"""Deterministic, structured Incident → Event Thread resolution."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from .claim_semantics import assertion_semantics



RESOLVER_METHOD = "DETERMINISTIC_STRUCTURED_THREAD_V3"
RESOLVER_VERSION = "thread-v3"
MAX_CANDIDATES = 50
CONTINUITY_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class IncidentThreadContext:
    incident_id: UUID
    current_thread_id: UUID
    title: str
    actor_ids: frozenset[UUID] = frozenset()
    participant_ids: frozenset[UUID] = frozenset()
    target_ids: frozenset[UUID] = frozenset()
    location_ids: frozenset[UUID] = frozenset()
    domains: frozenset[str] = frozenset()
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    time_precision: str | None = None
    relationship_cues: tuple[dict, ...] = ()
    source_document_ids: tuple[UUID, ...] = ()
    multi_occurrence_review: bool = False
    report_published_at: datetime | None = None
    source_claims: tuple[dict, ...] = ()


@dataclass(frozen=True)
class EventThreadCandidate:
    event_thread_id: UUID
    title: str
    actor_ids: frozenset[UUID]
    participant_ids: frozenset[UUID]
    target_ids: frozenset[UUID]
    location_ids: frozenset[UUID]
    domains: frozenset[str]
    started_at: datetime | None
    latest_incident_at: datetime | None
    incident_count: int
    members: tuple[IncidentThreadContext, ...] = ()
    latest_reported_at: datetime | None = None
    members_complete: bool = True


@dataclass(frozen=True)
class ThreadResolution:
    state: str
    event_thread_id: UUID
    matched_signals: tuple[dict, ...] = ()
    conflicts: tuple[dict, ...] = ()
    candidates_considered: tuple[dict, ...] = ()
    relationship_ids: tuple[UUID, ...] = ()
    reason: str = ""


class EventThreadCandidateRetriever(Protocol):
    async def retrieve(self, conn, context: IncidentThreadContext) -> list[EventThreadCandidate]: ...


class EventThreadResolver(Protocol):
    def resolve(self, context: IncidentThreadContext, candidates: list[EventThreadCandidate]) -> ThreadResolution: ...


def _time_relation(context: IncidentThreadContext, candidate: EventThreadCandidate) -> str:
    if not context.event_time_start or not candidate.latest_incident_at:
        return "UNKNOWN"
    gap = abs(context.event_time_start - candidate.latest_incident_at)
    return "NEAR" if gap <= CONTINUITY_WINDOW else "DISTANT"


def _candidate_signals(context: IncidentThreadContext, candidate: EventThreadCandidate) -> tuple[list[dict], list[dict], bool, dict | None]:
    matches: list[dict] = []
    conflicts: list[dict] = []
    shared_participants = context.participant_ids & candidate.participant_ids
    shared_actors = context.actor_ids & candidate.actor_ids
    shared_targets = context.target_ids & candidate.target_ids
    shared_locations = context.location_ids & candidate.location_ids
    shared_domains = context.domains & candidate.domains
    relation = None
    if shared_actors:
        matches.append({"signal": "actor_continuity", "entity_ids": sorted(map(str, shared_actors))})
    if shared_participants:
        matches.append({"signal": "participant_continuity", "entity_ids": sorted(map(str, shared_participants))})
    if shared_targets:
        matches.append({"signal": "target_context_continuity", "entity_ids": sorted(map(str, shared_targets))})
    if shared_locations:
        matches.append({"signal": "geographic_continuity", "entity_ids": sorted(map(str, shared_locations))})
    if shared_domains:
        matches.append({"signal": "context_domain", "domains": sorted(shared_domains)})
    temporal = _time_relation(context, candidate)
    report_temporal = "UNKNOWN"
    if temporal == "UNKNOWN" and context.report_published_at and candidate.latest_reported_at:
        gap = abs(context.report_published_at - candidate.latest_reported_at)
        report_temporal = "NEAR" if gap <= CONTINUITY_WINDOW else "DISTANT"
        matches.append({"signal": "reporting_time_continuity", "relation": report_temporal,
                        "basis": "source publication dates; occurrence time remains unknown"})
    else:
        matches.append({"signal": "temporal_continuity", "relation": temporal,
                        "precision": context.time_precision or "UNKNOWN"})
    if context.domains and candidate.domains and not shared_domains:
        conflicts.append({"signal": "context_domain", "incident_domains": sorted(context.domains),
                          "thread_domains": sorted(candidate.domains)})
    elif temporal == "DISTANT" and context.event_time_start and candidate.latest_incident_at:
        conflicts.append({"signal": "temporal_gap", "days": round(abs(context.event_time_start - candidate.latest_incident_at).total_seconds() / 86400, 2)})

    # A cue is only a retrieval hint until its object identifies one member.
    grounded = _grounded_relationships(context, candidate.members) if candidate.members_complete else []
    if len(grounded) == 1:
        relation = grounded[0]
        matches.append({"signal": "explicit_incident_relationship", **relation,
                        "source_claim_id": relation.get("claim_id"),
                        "shared_entity_ids": sorted(map(str, shared_participants))})
    elif context.relationship_cues:
        conflicts.append({"signal": "relationship_target_unresolved",
                          "candidate_member_ids": [str(m.incident_id) for m in candidate.members],
                          "grounded_target_ids": [r["target_incident_id"] for r in grounded],
                          "members_complete": candidate.members_complete,
                          "source_cues": list(context.relationship_cues)})
    # Shared entities/domain/time retrieve plausible situations, but cannot prove
    # a relationship to a particular occurrence or proposition.
    eligible = relation is not None and bool(shared_participants) and (
        bool(shared_domains) or len(shared_participants) >= 2)
    return matches, conflicts, eligible, relation


class DeterministicEventThreadCandidateRetriever:
    limit = MAX_CANDIDATES

    async def retrieve(self, conn, context: IncidentThreadContext) -> list[EventThreadCandidate]:
        rows = await (await conn.execute(
            "SELECT p.event_thread_id,e.title,p.actor_entity_ids,p.participant_entity_ids,p.target_entity_ids,"
            "p.location_entity_ids,p.context_domains,p.started_at,p.latest_incident_at,p.incident_count,p.latest_reported_at "
            "FROM event_thread_profiles p JOIN event_threads e ON e.id=p.event_thread_id "
            "WHERE p.event_thread_id<>%s AND ("
            "p.actor_entity_ids && %s::uuid[] OR p.participant_entity_ids && %s::uuid[] OR "
            "p.target_entity_ids && %s::uuid[] OR p.location_entity_ids && %s::uuid[] OR "
            "p.context_domains && %s::text[] OR "
            "(%s::timestamptz IS NOT NULL AND p.latest_incident_at BETWEEN %s::timestamptz - interval '30 days' AND %s::timestamptz + interval '30 days') OR "
            "(%s::timestamptz IS NOT NULL AND p.latest_reported_at BETWEEN %s::timestamptz - interval '30 days' AND %s::timestamptz + interval '30 days')) "
            "ORDER BY COALESCE(p.latest_incident_at,p.latest_reported_at) DESC NULLS LAST,p.event_thread_id LIMIT %s",
            (context.current_thread_id, list(context.actor_ids), list(context.participant_ids), list(context.target_ids),
             list(context.location_ids), list(context.domains), context.event_time_start, context.event_time_start,
             context.event_time_start, context.report_published_at, context.report_published_at,
             context.report_published_at, self.limit),
        )).fetchall()
        result = []
        for row in rows:
            members, complete = await _relationship_members(conn, row["event_thread_id"])
            result.append(EventThreadCandidate(
                row["event_thread_id"], row["title"], frozenset(row["actor_entity_ids"] or []),
                frozenset(row["participant_entity_ids"] or []), frozenset(row["target_entity_ids"] or []),
                frozenset(row["location_entity_ids"] or []), frozenset(row["context_domains"] or []),
                row["started_at"], row["latest_incident_at"], row["incident_count"], members, row["latest_reported_at"], complete))
        return result


class DeterministicEventThreadResolver:
    def resolve(self, context: IncidentThreadContext, candidates: list[EventThreadCandidate]) -> ThreadResolution:
        evaluated = []
        for candidate in candidates:
            matches, conflicts, eligible, relation = _candidate_signals(context, candidate)
            evaluated.append((candidate, matches, conflicts, eligible, relation))
        candidate_audit = tuple({"event_thread_id": str(c.event_thread_id), "title": c.title,
            "signals": m, "conflicts": x, "eligible": ok, "related_incident_ids": [str(member.incident_id) for member in c.members]}
            for c, m, x, ok, _ in evaluated)
        eligible = [item for item in evaluated if item[3]]
        if len(eligible) > 1:
            return ThreadResolution("AMBIGUOUS", context.current_thread_id, candidates_considered=candidate_audit,
                reason="More than one existing Event Thread satisfies the deterministic continuity rules.")
        if len(eligible) == 1:
            candidate, matches, conflicts, _, relationship = eligible[0]
            return ThreadResolution("ASSIGNED_EXISTING_THREAD", candidate.event_thread_id, tuple(matches), tuple(conflicts),
                candidate_audit, reason="Multiple structured continuity signals support this existing Event Thread.")
        plausible = [item for item in evaluated if
            (context.participant_ids & item[0].participant_ids) and (context.domains & item[0].domains)]
        if len(plausible) > 1:
            return ThreadResolution("AMBIGUOUS", context.current_thread_id, candidates_considered=candidate_audit,
                reason="Several threads share participants and context, but none has sufficient continuity evidence.")
        if plausible:
            return ThreadResolution("REVIEW_REQUIRED", context.current_thread_id, candidates_considered=candidate_audit,
                reason="A related thread is plausible, but the structured continuity evidence is incomplete.")
        return ThreadResolution("NEW_THREAD", context.current_thread_id, candidates_considered=candidate_audit,
            reason="No existing Event Thread meets the structured continuity requirements.")


def _domain_for(action: str | None, statements: list[str], entity_types: set[str]) -> set[str]:
    domains = set()
    if action in {"launch", "strike", "deploy", "damage", "kill", "injure", "intercept", "withdraw", "explode", "respond"}:
        domains.add("MILITARY_SECURITY")
    joined = " ".join(statements).casefold()
    if re.search(r"\b(?:trade agreement|economic agreement|trade deal|tariff|trade pact)\b", joined):
        domains.add("ECONOMIC")
    if re.search(r"\b(?:diplomatic talks|ceasefire talks|peace negotiations|diplomatic agreement)\b", joined):
        domains.add("DIPLOMATIC")
    if "VESSEL" in entity_types and action in {"strike", "damage", "intercept", "deploy"}:
        domains.add("MARITIME_SECURITY")
    return domains


def _reference_text(text: str) -> str:
    # Exact proposition reference normalization, not similarity scoring.
    return " ".join(re.findall(r"\w+", text.casefold())).removeprefix("the ").removeprefix("a ")


def _relationship_cues(claims: list[dict]) -> tuple[dict, ...]:
    output = []
    patterns = (
        ("RESPONDED_TO", r"in response to|respond(?:ed|s|ing) to|in retaliation for|retaliated (?:against|for)"),
        ("CAUSED_BY", r"caused by|because of"),
        ("ESCALATED_FROM", r"escalat\w+ (?:after|following|from)|(?:a|one|\d+) days? after"),
        ("INFLUENCED_BY", r"influenced by|in support of|to support"),
        ("RESPONDED_TO", r"retaliat\w*"),
    )
    for claim in claims:
        statement = claim.get("statement") or ""
        for relation, expression in patterns:
            match = re.search(r"\b(?:" + expression + r")\b", statement, re.I)
            if not match:
                continue
            # Keep the actual complement, not the entire surrounding article.
            end = re.search(r"[.;!?]|,|\b(?:while|whereas|although)\b", statement[match.end():], re.I)
            stop = match.end() + end.start() if end else len(statement)
            raw_target = statement[match.end():stop]
            target = raw_target.strip(" :\"'“”")
            start = match.end() + len(raw_target) - len(raw_target.lstrip(" :\"'“”"))
            remainder = statement[stop:]
            multiple_targets = bool(remainder.startswith(",") and re.search(
                r"^,\s*(?:the|a|an|another|and|or)\b|\b(?:and|or|both|either)\b",
                remainder.split(".")[0], re.I))
            output.append({"relation": relation, "claim_id": str(claim["id"]),
                           "source_text": statement, "cue": match.group(),
                           "cue_start": match.start(), "cue_end": match.end(),
                           "target_text": target, "target_start": start, "target_end": start + len(target),
                           "multiple_targets_possible": multiple_targets,
                           "semantics": assertion_semantics(claim),
                           "epistemic_status": claim.get("epistemic_status"),
                           "polarity": claim.get("polarity", "AFFIRMED"),
                           "attribution": claim.get("attribution") or {},
                           "source_spans": claim.get("source_spans", [])})
            break
    return tuple(output)


def _grounded_relationships(context: IncidentThreadContext, members) -> list[dict]:
    targets = {}
    for cue in context.relationship_cues:
        if cue.get("semantics") not in {"ACTUAL_OCCURRENCE", "REPORTED_OCCURRENCE", "DECISION"}:
            continue
        if cue.get("multiple_targets_possible"):
            continue
        reference = _reference_text(cue.get("target_text", ""))
        # Generic tensions/retaliation, pronouns and multiple target references
        # cannot identify a target. Exact multiword proposition references only.
        if len(reference.split()) < 3 or re.search(r"\b(?:and|or|either|both|tensions|developments|concerns|there|previous|earlier)\b", reference):
            continue
        for member in members:
            # A candidate claim may itself refer to some other incident. Match
            # its asserted subject, never a reference in its context/object.
            subjects = []
            for claim in member.source_claims:
                subject = re.split(r"\b(?:in response to|responded to|in retaliation for|because of|caused by|amid|alongside|during|following|after)\b",
                                   claim.get("statement", ""), maxsplit=1, flags=re.I)[0]
                if assertion_semantics({**claim, "statement": subject}) in {"ACTUAL_OCCURRENCE", "REPORTED_OCCURRENCE", "DECISION"}:
                    subjects.append(_reference_text(subject))
            if reference == _reference_text(member.title) or any(
                    (" " + reference + " ") in (" " + subject + " ") for subject in subjects):
                targets.setdefault((str(member.incident_id), cue["relation"]), {**cue, "target_incident_id": str(member.incident_id),
                    "subject_incident_id": str(context.incident_id),
                    "source_document_ids": list(map(str, context.source_document_ids)),
                    "target_basis": "Exact explicit occurrence/proposition reference in a candidate member"})
    return list(targets.values())


async def build_incident_context(conn, incident_id: UUID) -> IncidentThreadContext:
    incident = await (await conn.execute(
        "SELECT i.id,i.event_thread_id,i.title,fp.primary_actor_id,fp.target_entity_id,fp.location_entity_id,"
        "fp.supporting_entities,fp.event_time_start,fp.event_time_end,fp.time_precision,fp.action_predicate "
        "FROM incidents i LEFT JOIN incident_fingerprints fp ON fp.incident_id=i.id WHERE i.id=%s", (incident_id,)
    )).fetchone()
    if not incident:
        raise ValueError(f"incident {incident_id} does not exist")
    rows = await (await conn.execute(
        "SELECT DISTINCT e.id,e.type,ie.role FROM incident_entities ie JOIN entities e ON e.id=ie.entity_id WHERE ie.incident_id=%s",
        (incident_id,))).fetchall()
    claims = await (await conn.execute(
        "SELECT c.id,c.statement,c.normalized_representation,c.type,c.polarity,c.status,c.epistemic_status,c.intent_label,         COALESCE((SELECT jsonb_agg(jsonb_build_object('document_id',sp.document_id,'text_field',sp.text_field,         'character_start',sp.character_start,'character_end',sp.character_end,'source_text',sp.source_text))         FROM claim_source_spans sp WHERE sp.claim_id=c.id),'[]'::jsonb) source_spans         FROM claims c WHERE c.incident_id=%s ORDER BY c.created_at,c.id", (incident_id,))).fetchall()
    documents = await (await conn.execute(
        "SELECT DISTINCT document_id FROM claim_sources WHERE claim_id IN (SELECT id FROM claims WHERE incident_id=%s)",
        (incident_id,))).fetchall()
    report_date = await (await conn.execute(
        "SELECT max(published_at) latest_published_at FROM documents WHERE incident_id=%s", (incident_id,))).fetchone()
    actor_ids = {r["id"] for r in rows if r["role"] == "ACTOR"}
    target_ids = {r["id"] for r in rows if r["role"] == "TARGET"}
    location_ids = {r["id"] for r in rows if r["role"] == "LOCATION"}
    if incident["primary_actor_id"]:
        actor_ids.add(incident["primary_actor_id"])
    if incident["target_entity_id"]:
        target_ids.add(incident["target_entity_id"])
    if incident["location_entity_id"]:
        location_ids.add(incident["location_entity_id"])
    country_or_org = {r["id"] for r in rows if r["type"] in {"COUNTRY", "ORGANIZATION", "MILITARY_UNIT", "VESSEL", "INFRASTRUCTURE"}}
    participants = actor_ids | target_ids | country_or_org
    entity_types = {r["type"] for r in rows}
    statements = [r["statement"] for r in claims]
    action = incident["action_predicate"]
    if not action:
        action = next(((c["normalized_representation"] or {}).get("action") for c in claims
                       if (c["normalized_representation"] or {}).get("action")), None)
    domains = _domain_for(action, statements, entity_types)
    cues = _relationship_cues(claims)
    # Feature 4's AMBIGUOUS state means document-to-incident identity is uncertain;
    # it does not mean that the article contains multiple occurrences. Only the
    # explicit decomposition limitation should block incident-to-thread resolution.
    review = await (await conn.execute(
        "SELECT 1 FROM documents d JOIN document_incident_resolutions r ON r.document_id=d.id "
        "WHERE d.incident_id=%s AND ("
        "starts_with(r.limitation,'Multiple distinct occurrence predicates were detected') OR "
        "COALESCE((SELECT (fp.source_metadata->>'multi_occurrence_possible')::boolean "
        "FROM incident_fingerprints fp WHERE fp.incident_id=d.incident_id),false)) LIMIT 1",
        (incident_id,))).fetchone()
    return IncidentThreadContext(incident["id"], incident["event_thread_id"], incident["title"],
        frozenset(actor_ids), frozenset(participants), frozenset(target_ids), frozenset(location_ids),
        frozenset(domains), incident["event_time_start"], incident["event_time_end"], incident["time_precision"],
        cues, tuple(r["document_id"] for r in documents), bool(review), report_date["latest_published_at"], tuple(claims))


async def _load_entity_names(conn, entity_ids: set[UUID]) -> list[str]:
    if not entity_ids:
        return []
    rows = await (await conn.execute("SELECT canonical_name,type FROM entities WHERE id=ANY(%s::uuid[]) ORDER BY canonical_name", (list(entity_ids),))).fetchall()
    countries = [r["canonical_name"] for r in rows if r["type"] == "COUNTRY"]
    return countries or [r["canonical_name"] for r in rows if r["type"] in {"ORGANIZATION", "MILITARY_UNIT"}]


def _thread_title(names: list[str], domains: set[str], thread_id: UUID, source_title: str | None = None) -> str:
    candidate = " ".join((source_title or "").split())
    if candidate and len(candidate) <= 240 and not re.fullmatch(r"Event Thread [0-9a-f]{8}", candidate, re.I):
        return candidate
    if not names:
        return "Unclassified geopolitical event"
    participants = "–".join(names[:2])
    domain_title = {
        "MILITARY_SECURITY": "Military Escalation",
        "MARITIME_SECURITY": "Maritime Security Situation",
        "DIPLOMATIC": "Diplomatic Engagement",
        "ECONOMIC": "Economic Relations",
    }
    label = next((domain_title[d] for d in sorted(domains) if d in domain_title), "Geopolitical Situation")
    return f"{participants} {label}"


async def refresh_thread_profile(conn, event_thread_id: UUID, *, advance_activity: bool = True) -> None:
    summary = await (await conn.execute(
        "SELECT count(DISTINCT i.id) incident_count,min(COALESCE(ctx.event_time_start,i.occurred_at)) started_at,"
        "max(COALESCE(ctx.event_time_start,i.occurred_at)) latest_incident_at,"
        "max(i.occurred_at) latest_confirmed_occurrence_at,"
        "(SELECT max(d.published_at) FROM incidents ir JOIN documents d ON d.incident_id=ir.id WHERE ir.event_thread_id=%s) latest_reported_at "
        "FROM incidents i LEFT JOIN incident_thread_contexts ctx ON ctx.incident_id=i.id WHERE i.event_thread_id=%s",
        (event_thread_id, event_thread_id))).fetchone()
    arrays = {}
    for key, column, element_type in (
        ("actors", "actor_entity_ids", "uuid"), ("participants", "participant_entity_ids", "uuid"),
        ("targets", "target_entity_ids", "uuid"), ("locations", "location_entity_ids", "uuid"),
        ("domains", "context_domains", "text"),
    ):
        arrays[key] = await (await conn.execute(
            f"SELECT COALESCE(array_agg(DISTINCT value),ARRAY[]::{element_type}[]) values FROM incidents i "
            f"LEFT JOIN incident_thread_contexts ctx ON ctx.incident_id=i.id "
            f"CROSS JOIN LATERAL unnest(COALESCE(ctx.{column},ARRAY[]::{element_type}[])) AS u(value) "
            "WHERE i.event_thread_id=%s", (event_thread_id,))).fetchone()
    await conn.execute(
        "INSERT INTO event_thread_profiles(event_thread_id,actor_entity_ids,participant_entity_ids,target_entity_ids,location_entity_ids,context_domains,started_at,latest_incident_at,incident_count,latest_reported_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_thread_id) DO UPDATE SET actor_entity_ids=EXCLUDED.actor_entity_ids,"
        "participant_entity_ids=EXCLUDED.participant_entity_ids,target_entity_ids=EXCLUDED.target_entity_ids,location_entity_ids=EXCLUDED.location_entity_ids,"
        "context_domains=EXCLUDED.context_domains,started_at=EXCLUDED.started_at,latest_incident_at=EXCLUDED.latest_incident_at,incident_count=EXCLUDED.incident_count,latest_reported_at=EXCLUDED.latest_reported_at,updated_at=now()",
        (event_thread_id, arrays["actors"]["values"], arrays["participants"]["values"], arrays["targets"]["values"],
         arrays["locations"]["values"], arrays["domains"]["values"], summary["started_at"], summary["latest_incident_at"], summary["incident_count"], summary["latest_reported_at"]))
    await conn.execute(
        "UPDATE event_threads SET started_at=%s,latest_activity_at=CASE WHEN %s AND %s::timestamptz IS NOT NULL THEN GREATEST(COALESCE(latest_activity_at,'-infinity'::timestamptz),%s) ELSE latest_activity_at END,thread_status=CASE "
        "WHEN %s=1 AND thread_status IN ('UNKNOWN','DEVELOPING','DORMANT') THEN 'DEVELOPING' "
        "WHEN %s>1 AND thread_status IN ('UNKNOWN','DEVELOPING','DORMANT') THEN 'ONGOING' ELSE thread_status END,"
        "status=CASE WHEN status='DISCOVERED' THEN 'DEVELOPING'::event_status ELSE status END,updated_at=now() WHERE id=%s",
        (summary["started_at"], advance_activity, summary["latest_confirmed_occurrence_at"], summary["latest_confirmed_occurrence_at"], summary["incident_count"], summary["incident_count"], event_thread_id))


async def _persist_incident_context(conn, context: IncidentThreadContext) -> None:
    from psycopg.types.json import Jsonb
    await conn.execute(
        "INSERT INTO incident_thread_contexts(incident_id,actor_entity_ids,participant_entity_ids,target_entity_ids,location_entity_ids,context_domains,event_time_start,event_time_end,time_precision,relationship_cues,source_document_ids) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(incident_id) DO UPDATE SET actor_entity_ids=EXCLUDED.actor_entity_ids,"
        "participant_entity_ids=EXCLUDED.participant_entity_ids,target_entity_ids=EXCLUDED.target_entity_ids,location_entity_ids=EXCLUDED.location_entity_ids,"
        "context_domains=EXCLUDED.context_domains,event_time_start=EXCLUDED.event_time_start,event_time_end=EXCLUDED.event_time_end,"
        "time_precision=EXCLUDED.time_precision,relationship_cues=EXCLUDED.relationship_cues,source_document_ids=EXCLUDED.source_document_ids,updated_at=now()",
        (context.incident_id, list(context.actor_ids), list(context.participant_ids), list(context.target_ids), list(context.location_ids),
         sorted(context.domains), context.event_time_start, context.event_time_end, context.time_precision,
         Jsonb(list(context.relationship_cues)), list(context.source_document_ids)))


async def _relationship_members(conn, thread_id: UUID):
    # One bounded member query, not a full context rebuild per member/candidate.
    rows = await (await conn.execute(
        "SELECT i.id,i.title,COALESCE((SELECT jsonb_agg(jsonb_build_object('id',c.id,'statement',c.statement)) "
        "FROM claims c WHERE c.incident_id=i.id),'[]'::jsonb) source_claims "
        "FROM incidents i WHERE i.event_thread_id=%s ORDER BY i.id LIMIT 51", (thread_id,))).fetchall()
    return tuple(IncidentThreadContext(r["id"], thread_id, r["title"],
        source_claims=tuple(r["source_claims"])) for r in rows[:50]), len(rows) <= 50


async def _select_related_member(conn, context: IncidentThreadContext, thread_id: UUID) -> tuple[IncidentThreadContext | None, dict | None]:
    members, complete = await _relationship_members(conn, thread_id)
    grounded = _grounded_relationships(context, members) if complete else []
    if len(grounded) != 1:
        return None, None
    cue = grounded[0]
    return next(m for m in members if str(m.incident_id) == cue["target_incident_id"]), cue


async def _persist_audit(conn, incident_id, thread_id, state, matched, conflicts, candidates, relationship_ids, reason, attempt=1):
    from psycopg.types.json import Jsonb
    await conn.execute(
        "INSERT INTO event_thread_resolution_audits(incident_id,event_thread_id,state,resolver_method,resolver_version,attempt,matched_signals,conflicts,candidates_considered,relationship_ids,reason) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(incident_id,resolver_version,attempt) DO NOTHING",
        (incident_id, thread_id, state, RESOLVER_METHOD, RESOLVER_VERSION, attempt,
         Jsonb(list(matched)), Jsonb(list(conflicts)), Jsonb(list(candidates)), list(relationship_ids), reason))


async def record_thread_resolution_failure(conn, incident_id: UUID, error: Exception) -> None:
    incident = await (await conn.execute("SELECT event_thread_id FROM incidents WHERE id=%s", (incident_id,))).fetchone()
    if not incident:
        return
    attempt = await (await conn.execute("SELECT COALESCE(MAX(attempt),0)+1 n FROM event_thread_resolution_audits WHERE incident_id=%s AND resolver_version=%s",
                                      (incident_id, RESOLVER_VERSION))).fetchone()
    await _persist_audit(conn, incident_id, incident["event_thread_id"], "RESOLUTION_FAILED", [], [], [], [],
        f"{type(error).__name__}: incident and prior intelligence were retained; Event Thread resolution failed.", attempt["n"])


async def resolve_incident_to_thread(conn, incident_id: UUID, retriever: EventThreadCandidateRetriever | None = None,
                                     resolver: EventThreadResolver | None = None) -> ThreadResolution:
    from psycopg.types.json import Jsonb
    existing = await (await conn.execute(
        "SELECT a.state,a.event_thread_id,a.matched_signals,a.conflicts,a.candidates_considered,a.relationship_ids,a.reason "
        "FROM event_thread_resolution_audits a WHERE a.incident_id=%s AND a.resolver_version=%s AND a.state<>'RESOLUTION_FAILED' "
        "ORDER BY a.attempt DESC LIMIT 1", (incident_id, RESOLVER_VERSION))).fetchone()
    if existing:
        # Reprocessing can attach new documents and better structured context to an
        # already assigned incident. Refresh its profile without changing the audited
        # assignment or advancing activity for a source copy alone.
        context = await build_incident_context(conn, incident_id)
        await _persist_incident_context(conn, context)
        await refresh_thread_profile(conn, context.current_thread_id, advance_activity=False)
        names = await _load_entity_names(conn, set(context.participant_ids))
        await conn.execute(
            "UPDATE event_threads SET title=%s WHERE id=%s AND (title ~* '^Event Thread [0-9a-f]{8}$' OR title ~* '^(?:.+ )?(?:Military Escalation|Maritime Security Situation|Diplomatic Engagement|Economic Relations|Geopolitical Situation)$')",
            (_thread_title(names, set(context.domains), context.current_thread_id, context.title), context.current_thread_id))
        return ThreadResolution(existing["state"], existing["event_thread_id"], tuple(existing["matched_signals"] or []),
            tuple(existing["conflicts"] or []), tuple(existing["candidates_considered"] or []),
            tuple(existing["relationship_ids"] or []), existing["reason"])

    context = await build_incident_context(conn, incident_id)
    if context.multi_occurrence_review:
        result = ThreadResolution("REVIEW_REQUIRED", context.current_thread_id, reason="Feature 4 marked this incident for multi-occurrence review.")
        await _persist_incident_context(conn, context)
        names = await _load_entity_names(conn, set(context.participant_ids))
        await conn.execute("UPDATE event_threads SET title=%s,thread_status='UNKNOWN',updated_at=now() WHERE id=%s",
                           (_thread_title(names, set(context.domains), context.current_thread_id, context.title), context.current_thread_id))
        await refresh_thread_profile(conn, context.current_thread_id)
        await conn.execute("UPDATE event_threads SET thread_status='UNKNOWN' WHERE id=%s", (context.current_thread_id,))
        await _persist_audit(conn, incident_id, context.current_thread_id, result.state, [], [], [], [], result.reason)
        return result

    await _persist_incident_context(conn, context)
    candidates = await (retriever or DeterministicEventThreadCandidateRetriever()).retrieve(conn, context)
    result = (resolver or DeterministicEventThreadResolver()).resolve(context, candidates)
    target_thread_id = result.event_thread_id
    relationships = []
    if result.state == "ASSIGNED_EXISTING_THREAD":
        selected = next(candidate for candidate in candidates if candidate.event_thread_id == target_thread_id)
        related_member, cue = await _select_related_member(conn, context, selected.event_thread_id)
        if not related_member:
            # Revalidate at persistence: never choose the latest shared actor if
            # evidence became ambiguous, including a custom resolver result.
            result = ThreadResolution("REVIEW_REQUIRED", context.current_thread_id,
                candidates_considered=result.candidates_considered,
                reason="The selected relationship target could not be uniquely grounded at persistence.")
            await _persist_audit(conn, incident_id, context.current_thread_id, result.state,
                [], [], result.candidates_considered, [], result.reason)
            return result
        if related_member:
            relation_type = cue.get("relation", "RELATED_TO")
            evidence = {**cue, "source_claim_id": str(cue.get("claim_id")) if cue.get("claim_id") else None,
                        "source_text": cue.get("source_text"), "matched_signals": list(result.matched_signals),
                        "relationship_basis": cue.get("evidence") or "Explicit source language supports this incident relationship."}
            row = await (await conn.execute(
                "INSERT INTO event_thread_incident_relationships(event_thread_id,from_incident_id,to_incident_id,relation,resolver_method,evidence) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(from_incident_id,to_incident_id,relation) DO UPDATE SET evidence=event_thread_incident_relationships.evidence RETURNING id",
                (target_thread_id, incident_id, related_member.incident_id, relation_type, RESOLVER_METHOD, Jsonb(evidence)))).fetchone()
            relationships.append(row["id"])
        old_thread_id = context.current_thread_id
        if old_thread_id != target_thread_id:
            await conn.execute("UPDATE event_updates SET event_thread_id=%s WHERE incident_id=%s AND event_thread_id=%s",
                               (target_thread_id, incident_id, old_thread_id))
            await conn.execute("UPDATE incidents SET event_thread_id=%s,updated_at=now() WHERE id=%s", (target_thread_id, incident_id))
    else:
        names = await _load_entity_names(conn, set(context.participant_ids))
        await conn.execute("UPDATE event_threads SET title=%s WHERE id=%s AND (title ~* '^Event Thread [0-9a-f]{8}$' OR title ~* '^(?:.+ )?(?:Military Escalation|Maritime Security Situation|Diplomatic Engagement|Economic Relations|Geopolitical Situation)$')",
                           (_thread_title(names, set(context.domains), target_thread_id, context.title), target_thread_id))

    await refresh_thread_profile(conn, target_thread_id)
    old_thread = context.current_thread_id
    if old_thread != target_thread_id:
        old_remaining = await (await conn.execute("SELECT 1 FROM incidents WHERE event_thread_id=%s LIMIT 1", (old_thread,))).fetchone()
        if not old_remaining:
            await conn.execute("DELETE FROM event_threads e WHERE e.id=%s AND NOT EXISTS(SELECT 1 FROM watchlists w WHERE w.event_thread_id=e.id) "
                "AND NOT EXISTS(SELECT 1 FROM event_entities x WHERE x.event_id=e.id) "
                "AND NOT EXISTS(SELECT 1 FROM event_relationships r WHERE r.from_event_id=e.id OR r.to_event_id=e.id) "
                "AND NOT EXISTS(SELECT 1 FROM event_updates u WHERE u.event_thread_id=e.id)", (old_thread,))
    await _persist_audit(conn, incident_id, target_thread_id, result.state, result.matched_signals,
        result.conflicts, result.candidates_considered, relationships, result.reason)
    return ThreadResolution(result.state, target_thread_id, result.matched_signals, result.conflicts,
                            result.candidates_considered, tuple(relationships), result.reason)
