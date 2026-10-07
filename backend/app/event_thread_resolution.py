"""Deterministic, structured Incident → Event Thread resolution."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID



RESOLVER_METHOD = "DETERMINISTIC_STRUCTURED_THREAD_V1"
RESOLVER_VERSION = "thread-v1"
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
    matches.append({"signal": "temporal_continuity", "relation": temporal,
                    "precision": context.time_precision or "UNKNOWN"})
    if context.domains and candidate.domains and not shared_domains:
        conflicts.append({"signal": "context_domain", "incident_domains": sorted(context.domains),
                          "thread_domains": sorted(candidate.domains)})
    elif temporal == "DISTANT":
        conflicts.append({"signal": "temporal_gap", "days": round(abs(context.event_time_start - candidate.latest_incident_at).total_seconds() / 86400, 2)})

    # Relationship cues are explicit source language, not inferred causality.
    for cue in context.relationship_cues:
        cue_relation = cue.get("relation")
        if cue_relation not in {"CAUSED_BY", "RESPONDED_TO", "ESCALATED_FROM", "INFLUENCED_BY"}:
            continue
        if shared_participants:
            relation = cue
            matches.append({"signal": "explicit_incident_relationship", "relation": cue_relation,
                            "source_claim_id": str(cue.get("claim_id")) if cue.get("claim_id") else None,
                            "shared_entity_ids": sorted(map(str, shared_participants))})
            break

    explicit = relation is not None
    # Two involved canonical entities plus a shared structured context and near temporal placement
    # establish situation continuity. Geography and time by themselves are never sufficient.
    contextual = len(shared_participants) >= 2 and bool(shared_domains) and temporal == "NEAR"
    # One shared participant can connect a new entrant only when source claims explicitly say it
    # supports, responds to, or is influenced by this existing situation.
    explicit_contextual = explicit and bool(shared_domains) and bool(shared_participants)
    eligible = explicit_contextual or contextual
    if explicit and not shared_domains:
        # Explicit response can cross topical domains, but require more than a bare common actor.
        eligible = len(shared_participants) >= 2
    return matches, conflicts, eligible, relation


class DeterministicEventThreadCandidateRetriever:
    limit = MAX_CANDIDATES

    async def retrieve(self, conn, context: IncidentThreadContext) -> list[EventThreadCandidate]:
        rows = await (await conn.execute(
            "SELECT p.event_thread_id,e.title,p.actor_entity_ids,p.participant_entity_ids,p.target_entity_ids,"
            "p.location_entity_ids,p.context_domains,p.started_at,p.latest_incident_at,p.incident_count "
            "FROM event_thread_profiles p JOIN event_threads e ON e.id=p.event_thread_id "
            "WHERE p.event_thread_id<>%s AND ("
            "p.actor_entity_ids && %s::uuid[] OR p.participant_entity_ids && %s::uuid[] OR "
            "p.target_entity_ids && %s::uuid[] OR p.location_entity_ids && %s::uuid[] OR "
            "p.context_domains && %s::text[] OR "
            "(%s::timestamptz IS NOT NULL AND p.latest_incident_at BETWEEN %s::timestamptz - interval '30 days' AND %s::timestamptz + interval '30 days')) "
            "ORDER BY p.latest_incident_at DESC NULLS LAST LIMIT %s",
            (context.current_thread_id, list(context.actor_ids), list(context.participant_ids), list(context.target_ids),
             list(context.location_ids), list(context.domains), context.event_time_start, context.event_time_start,
             context.event_time_start, self.limit),
        )).fetchall()
        result = []
        for row in rows:
            result.append(EventThreadCandidate(
                row["event_thread_id"], row["title"], frozenset(row["actor_entity_ids"] or []),
                frozenset(row["participant_entity_ids"] or []), frozenset(row["target_entity_ids"] or []),
                frozenset(row["location_entity_ids"] or []), frozenset(row["context_domains"] or []),
                row["started_at"], row["latest_incident_at"], row["incident_count"], ()))
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


def _relationship_cues(claims: list[dict]) -> tuple[dict, ...]:
    output = []
    patterns = (
        ("RESPONDED_TO", re.compile(r"\b(?:in response to|respond(?:ed|s|ing) to|retaliat\w*(?:\s+in response)?(?:\s+to)?|in retaliation for)\b", re.I)),
        ("CAUSED_BY", re.compile(r"\b(?:caused by|because of)\b", re.I)),
        ("ESCALATED_FROM", re.compile(r"\b(?:escalat\w+ (?:after|following|from))\b", re.I)),
        ("INFLUENCED_BY", re.compile(r"\b(?:influenced by|to support|in support of)\b", re.I)),
    )
    for claim in claims:
        statement = claim["statement"] or ""
        for relation, pattern in patterns:
            match = pattern.search(statement)
            if match:
                output.append({"relation": relation, "claim_id": str(claim["id"]), "source_text": statement[:500]})
                break
    return tuple(output)


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
        "SELECT DISTINCT c.id,c.statement,c.normalized_representation FROM claims c WHERE c.incident_id=%s", (incident_id,))).fetchall()
    documents = await (await conn.execute(
        "SELECT DISTINCT document_id FROM claim_sources WHERE claim_id IN (SELECT id FROM claims WHERE incident_id=%s)",
        (incident_id,))).fetchall()
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
    review = await (await conn.execute(
        "SELECT 1 FROM documents d JOIN document_incident_resolutions r ON r.document_id=d.id "
        "WHERE d.incident_id=%s AND r.state IN ('REVIEW_REQUIRED','AMBIGUOUS') LIMIT 1", (incident_id,))).fetchone()
    return IncidentThreadContext(incident["id"], incident["event_thread_id"], incident["title"],
        frozenset(actor_ids), frozenset(participants), frozenset(target_ids), frozenset(location_ids),
        frozenset(domains), incident["event_time_start"], incident["event_time_end"], incident["time_precision"],
        cues, tuple(r["document_id"] for r in documents), bool(review))


async def _load_entity_names(conn, entity_ids: set[UUID]) -> list[str]:
    if not entity_ids:
        return []
    rows = await (await conn.execute("SELECT canonical_name,type FROM entities WHERE id=ANY(%s::uuid[]) ORDER BY canonical_name", (list(entity_ids),))).fetchall()
    countries = [r["canonical_name"] for r in rows if r["type"] == "COUNTRY"]
    return countries or [r["canonical_name"] for r in rows if r["type"] in {"ORGANIZATION", "MILITARY_UNIT"}]


def _thread_title(names: list[str], domains: set[str], thread_id: UUID) -> str:
    if not names:
        return f"Event Thread {str(thread_id)[:8].upper()}"
    participants = "–".join(names[:2])
    domain_title = {
        "MILITARY_SECURITY": "Military Escalation",
        "MARITIME_SECURITY": "Maritime Security Situation",
        "DIPLOMATIC": "Diplomatic Engagement",
        "ECONOMIC": "Economic Relations",
    }
    label = next((domain_title[d] for d in sorted(domains) if d in domain_title), "Geopolitical Situation")
    return f"{participants} {label}"


async def refresh_thread_profile(conn, event_thread_id: UUID) -> None:
    summary = await (await conn.execute(
        "SELECT count(*) incident_count,min(COALESCE(ctx.event_time_start,i.occurred_at)) started_at,"
        "max(COALESCE(ctx.event_time_start,i.occurred_at)) latest_incident_at FROM incidents i "
        "LEFT JOIN incident_thread_contexts ctx ON ctx.incident_id=i.id WHERE i.event_thread_id=%s",
        (event_thread_id,))).fetchone()
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
        "INSERT INTO event_thread_profiles(event_thread_id,actor_entity_ids,participant_entity_ids,target_entity_ids,location_entity_ids,context_domains,started_at,latest_incident_at,incident_count) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_thread_id) DO UPDATE SET actor_entity_ids=EXCLUDED.actor_entity_ids,"
        "participant_entity_ids=EXCLUDED.participant_entity_ids,target_entity_ids=EXCLUDED.target_entity_ids,location_entity_ids=EXCLUDED.location_entity_ids,"
        "context_domains=EXCLUDED.context_domains,started_at=EXCLUDED.started_at,latest_incident_at=EXCLUDED.latest_incident_at,incident_count=EXCLUDED.incident_count,updated_at=now()",
        (event_thread_id, arrays["actors"]["values"], arrays["participants"]["values"], arrays["targets"]["values"],
         arrays["locations"]["values"], arrays["domains"]["values"], summary["started_at"], summary["latest_incident_at"], summary["incident_count"]))
    await conn.execute(
        "UPDATE event_threads SET started_at=%s,latest_activity_at=now(),thread_status=CASE "
        "WHEN %s=1 AND thread_status IN ('UNKNOWN','DEVELOPING','DORMANT') THEN 'DEVELOPING' "
        "WHEN %s>1 AND thread_status IN ('UNKNOWN','DEVELOPING','DORMANT') THEN 'ONGOING' ELSE thread_status END,"
        "status=CASE WHEN status='DISCOVERED' THEN 'DEVELOPING'::event_status ELSE status END,updated_at=now() WHERE id=%s",
        (summary["started_at"], summary["incident_count"], summary["incident_count"], event_thread_id))


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


async def _select_related_member(conn, context: IncidentThreadContext, thread_id: UUID) -> tuple[IncidentThreadContext | None, dict | None]:
    row = await (await conn.execute(
        "SELECT i.id FROM incidents i JOIN incident_thread_contexts ctx ON ctx.incident_id=i.id "
        "WHERE i.event_thread_id=%s AND ctx.participant_entity_ids && %s::uuid[] "
        "ORDER BY ctx.event_time_start DESC NULLS LAST,i.created_at DESC LIMIT 1",
        (thread_id, list(context.participant_ids)))).fetchone()
    if not row:
        return None, None
    related = await build_incident_context(conn, row["id"])
    relation = next((cue for cue in context.relationship_cues if cue.get("relation") in
                     {"CAUSED_BY", "RESPONDED_TO", "ESCALATED_FROM", "INFLUENCED_BY"}), None)
    if relation:
        return related, relation
    return related, {"relation": "RELATED_TO", "evidence": "Shared participants, context domain, and temporal continuity supported thread membership."}


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
        return ThreadResolution(existing["state"], existing["event_thread_id"], tuple(existing["matched_signals"] or []),
            tuple(existing["conflicts"] or []), tuple(existing["candidates_considered"] or []),
            tuple(existing["relationship_ids"] or []), existing["reason"])

    context = await build_incident_context(conn, incident_id)
    if context.multi_occurrence_review:
        result = ThreadResolution("REVIEW_REQUIRED", context.current_thread_id, reason="Feature 4 marked this incident for multi-occurrence review.")
        await _persist_incident_context(conn, context)
        names = await _load_entity_names(conn, set(context.participant_ids))
        await conn.execute("UPDATE event_threads SET title=%s,thread_status='UNKNOWN',latest_activity_at=now(),updated_at=now() WHERE id=%s",
                           (_thread_title(names, set(context.domains), context.current_thread_id), context.current_thread_id))
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
        if related_member:
            relation_type = cue.get("relation", "RELATED_TO")
            evidence = {"source_claim_id": str(cue.get("claim_id")) if cue.get("claim_id") else None,
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
        await conn.execute("UPDATE event_threads SET title=%s WHERE id=%s",
                           (_thread_title(names, set(context.domains), target_thread_id), target_thread_id))

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
