"""Structured, conservative document-to-incident resolution (no text similarity)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID



@dataclass(frozen=True)
class IncidentFingerprint:
    actor: str | None = None
    action: str | None = None
    target: str | None = None
    object: str | None = None
    location: str | None = None
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    time_precision: str | None = None
    time_expression: str | None = None
    quantity: dict = field(default_factory=dict)
    consequence: str | None = None
    response: str | None = None
    evidence: frozenset[str] = frozenset()
    entities: frozenset[str] = frozenset()
    source_metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateIncident:
    incident_id: UUID
    fingerprint: IncidentFingerprint


@dataclass(frozen=True)
class Resolution:
    state: str
    incident_id: UUID | None
    match_strength: str
    matched_signals: tuple[dict, ...] = ()
    conflicts: tuple[dict, ...] = ()
    candidates_considered: tuple[dict, ...] = ()


class IncidentCandidateRetriever(Protocol):
    async def retrieve(self, conn, fingerprint: IncidentFingerprint, exclude_incident_id: UUID | None = None) -> list[CandidateIncident]: ...


class IncidentResolver(Protocol):
    def resolve(self, fingerprint: IncidentFingerprint, candidates: list[CandidateIncident]) -> Resolution: ...


def _time_relation(a: IncidentFingerprint, b: IncidentFingerprint) -> str:
    if not a.event_time_start or not b.event_time_start:
        return "UNKNOWN"
    a_end = a.event_time_end or a.event_time_start
    b_end = b.event_time_end or b.event_time_start
    if a.event_time_start <= b_end and b.event_time_start <= a_end:
        return "EXACT_MATCH" if a.event_time_start == b.event_time_start else "CLOSE_MATCH"
    gap = max(a.event_time_start, b.event_time_start) - min(a_end, b_end)
    if gap <= timedelta(minutes=15):
        return "CLOSE_MATCH"
    exact_a = a.time_precision == "MINUTE"
    exact_b = b.time_precision == "MINUTE"
    if exact_a and exact_b:
        return "CONFLICTING"
    if a.event_time_start.date() == b.event_time_start.date():
        return "SAME_DAY"
    return "CONFLICTING"


def compare_fingerprints(incoming: IncidentFingerprint, prior: IncidentFingerprint) -> tuple[list[dict], list[dict], int]:
    """Return explicit positive/negative identity signals and conservative independent support count."""
    matches: list[dict] = []
    conflicts: list[dict] = []
    strong = 0
    for field_name in ("actor", "action", "target", "object", "location"):
        left, right = getattr(incoming, field_name), getattr(prior, field_name)
        if left and right and left == right:
            matches.append({"signal": field_name, "value": left})
            if field_name in {"actor", "target", "object", "location"}:
                strong += 1
        elif left and right:
            # Location precision can differ by hierarchy; differing canonical entities are reported as a conflict,
            # but are not treated as proof of distinct events.
            conflicts.append({"signal": field_name, "incoming": left, "candidate": right})
    if incoming.action and prior.action and incoming.action == prior.action:
        matches.append({"signal": "action", "value": incoming.action})
    temporal = _time_relation(incoming, prior)
    if temporal in {"EXACT_MATCH", "CLOSE_MATCH"}:
        matches.append({"signal": "event_time", "relation": temporal})
        strong += 1
    elif temporal == "SAME_DAY":
        matches.append({"signal": "event_time", "relation": temporal})
    elif temporal == "CONFLICTING":
        conflicts.append({"signal": "event_time", "relation": temporal,
                          "incoming": incoming.event_time_start.isoformat(),
                          "candidate": prior.event_time_start.isoformat()})
    if incoming.time_expression and prior.time_expression:
        if incoming.time_expression == prior.time_expression:
            matches.append({"signal": "event_time", "relation": "SAME_LOW_PRECISION_EXPRESSION"})
        else:
            conflicts.append({"signal": "event_time_expression", "incoming": incoming.time_expression,
                              "candidate": prior.time_expression})
    shared_evidence = sorted(incoming.evidence & prior.evidence)
    if shared_evidence:
        matches.append({"signal": "evidence_identity", "values": shared_evidence})
        strong += 1
    elif incoming.evidence and prior.evidence:
        conflicts.append({"signal": "evidence_identity", "incoming": sorted(incoming.evidence), "candidate": sorted(prior.evidence)})
    if incoming.quantity and prior.quantity and incoming.quantity != prior.quantity:
        conflicts.append({"signal": "quantity_differs", "incoming": incoming.quantity, "candidate": prior.quantity,
                          "note": "Quantity difference is retained for later claim analysis and does not alone split incidents."})
    if incoming.consequence and prior.consequence and incoming.consequence == prior.consequence:
        matches.append({"signal": "consequence", "value": incoming.consequence})
        strong += 1
    if incoming.response and prior.response and incoming.response == prior.response:
        matches.append({"signal": "response", "value": incoming.response})
        strong += 1
    return matches, conflicts, strong


class DeterministicIncidentCandidateRetriever:
    """Indexed structured retrieval; returned set is capped and never uses text or vectors."""
    limit = 50

    async def retrieve(self, conn, fingerprint: IncidentFingerprint, exclude_incident_id=None):
        rows = await (await conn.execute(
            "SELECT DISTINCT i.id,fp.primary_actor_id,fp.action_predicate,fp.target_entity_id,fp.object_entity_id,"
            "fp.location_entity_id,fp.event_time_start,fp.event_time_end,fp.time_precision,fp.event_time_expression,fp.quantity,fp.consequence,fp.response,"
            "fp.supporting_entities,fp.source_metadata,COALESCE((SELECT array_agg(ie.identity_key) FROM incident_fingerprint_evidence ie WHERE ie.incident_id=i.id AND ie.identity_key IS NOT NULL),'{}') AS evidence_keys FROM incident_fingerprints fp JOIN incidents i ON i.id=fp.incident_id "
            "WHERE (%s::uuid IS NULL OR i.id<>%s::uuid) AND ("
            "(%s::uuid IS NOT NULL AND fp.primary_actor_id=%s) OR (%s::uuid IS NOT NULL AND fp.target_entity_id=%s) OR "
            "(%s::uuid IS NOT NULL AND fp.object_entity_id=%s) OR (%s::uuid IS NOT NULL AND fp.location_entity_id=%s) OR "
            "(%s::text IS NOT NULL AND fp.action_predicate=%s) OR (%s::text IS NOT NULL AND fp.event_time_expression=%s) OR "
            "(%s::timestamptz IS NOT NULL AND fp.event_time_start BETWEEN %s::timestamptz - interval '1 day' AND %s::timestamptz + interval '1 day') OR "
            "EXISTS(SELECT 1 FROM incident_fingerprint_evidence ie WHERE ie.incident_id=i.id AND ie.identity_key=ANY(%s::text[])) OR "
            "EXISTS(SELECT 1 FROM incident_entities x WHERE x.incident_id=i.id AND x.entity_id=ANY(%s::uuid[]))) "
            "ORDER BY fp.event_time_start DESC NULLS LAST LIMIT %s",
            (exclude_incident_id, exclude_incident_id, fingerprint.actor, fingerprint.actor,
             fingerprint.target, fingerprint.target, fingerprint.object, fingerprint.object,
             fingerprint.location, fingerprint.location, fingerprint.action, fingerprint.action,
             fingerprint.time_expression, fingerprint.time_expression,
             fingerprint.event_time_start, fingerprint.event_time_start, fingerprint.event_time_start,
             list(fingerprint.evidence), list(fingerprint.entities), self.limit),
        )).fetchall()
        return [CandidateIncident(row["id"], _fingerprint_from_row(row)) for row in rows]


class DeterministicIncidentResolver:
    def resolve(self, fingerprint: IncidentFingerprint, candidates: list[CandidateIncident]) -> Resolution:
        evaluated = []
        for candidate in candidates:
            matches, conflicts, support = compare_fingerprints(fingerprint, candidate.fingerprint)
            time_conflict = any(c["signal"].startswith("event_time") for c in conflicts)
            target_conflict = any(c["signal"] in {"target", "actor"} for c in conflicts)
            # Require multiple independent signals. Time alone, shared evidence alone, or broad actor/action alone never merge.
            time_supported = any(m["signal"] == "event_time" for m in matches)
            evidence_supported = any(m["signal"] == "evidence_identity" for m in matches)
            eligible = support >= 2 and (time_supported or evidence_supported) and not time_conflict and not target_conflict
            evaluated.append((candidate, matches, conflicts, support, eligible))
        eligible = [row for row in evaluated if row[4]]
        candidate_audit = tuple({"incident_id": str(c.incident_id), "matched_signals": m, "conflicts": x,
                                 "supporting_signal_count": n, "eligible": ok}
                                for c, m, x, n, ok in evaluated)
        if not eligible:
            state = "AMBIGUOUS" if any(row[1] or row[2] for row in evaluated) and len(evaluated) > 1 else "NEW_INCIDENT"
            return Resolution(state, None, "INSUFFICIENT", candidates_considered=candidate_audit)
        eligible.sort(key=lambda row: (-row[3], str(row[0].incident_id)))
        best = eligible[0]
        if len(eligible) > 1 and eligible[1][3] == best[3]:
            return Resolution("AMBIGUOUS", None, "UNKNOWN", candidates_considered=candidate_audit)
        strength = "STRONG" if best[3] >= 3 else "SUPPORTED"
        return Resolution("MATCHED_EXISTING", best[0].incident_id, strength, tuple(best[1]), tuple(best[2]), candidate_audit)


def _fingerprint_from_row(row) -> IncidentFingerprint:
    return IncidentFingerprint(actor=str(row["primary_actor_id"]) if row.get("primary_actor_id") else None,
        action=row.get("action_predicate"), target=str(row["target_entity_id"]) if row.get("target_entity_id") else None,
        object=str(row["object_entity_id"]) if row.get("object_entity_id") else None,
        location=str(row["location_entity_id"]) if row.get("location_entity_id") else None,
        event_time_start=row.get("event_time_start"), event_time_end=row.get("event_time_end"),
        time_precision=row.get("time_precision"), time_expression=row.get("event_time_expression"), quantity=row.get("quantity") or {},
        consequence=row.get("consequence"), response=row.get("response"),
        evidence=frozenset(row.get("evidence_keys") or []),
        entities=frozenset(map(str, row.get("supporting_entities") or [])), source_metadata=row.get("source_metadata") or {})


async def build_document_fingerprint(conn, document_id) -> tuple[IncidentFingerprint, dict]:
    claims = await (await conn.execute(
        "SELECT c.type,c.normalized_representation,c.polarity,ce.role,e.id entity_id,e.canonical_name "
        "FROM claims c JOIN claim_sources cs ON cs.claim_id=c.id LEFT JOIN claim_entities ce ON ce.claim_id=c.id "
        "LEFT JOIN entities e ON e.id=ce.entity_id WHERE cs.document_id=%s ORDER BY c.created_at,c.id", (document_id,)
    )).fetchall()
    evidence = await (await conn.execute(
        "SELECT e.id,e.identity_key FROM evidence_documents ed JOIN evidence e ON e.id=ed.evidence_id WHERE ed.document_id=%s", (document_id,)
    )).fetchall()
    roles: dict[str, str] = {}
    entities: set[str] = set()
    actions: list[str] = []
    occurrence_claims: set[tuple[str, str]] = set()
    times: list[tuple[datetime, str]] = []
    time_expressions: list[str] = []
    quantities: list[dict] = []
    consequence = response = None
    for row in claims:
        normalized = row["normalized_representation"] or {}
        if row["polarity"] == "NEGATED":
            continue
        action = normalized.get("action")
        if action and row["type"] == "OCCURRENCE":
            actions.append(action)
            occurrence_claims.add((action, str(row.get("normalized_representation", {}).get("target") or "")))
        if row["type"] == "TIME":
            value = normalized.get("normalized")
            precision = normalized.get("precision", "UNKNOWN")
            if value:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
                    times.append((parsed.astimezone(timezone.utc), precision))
                except ValueError: pass
            elif normalized.get("original"):
                time_expressions.append(str(normalized["original"]).strip().casefold())
        if row["type"] == "QUANTITATIVE" and normalized.get("quantity"):
            quantities.append(normalized["quantity"])
        if row["type"] == "CONSEQUENCE": consequence = action or consequence
        if row["type"] == "RESPONSE": response = action or response
        if row["entity_id"]:
            entity = str(row["entity_id"])
            entities.add(entity)
            if row["role"] and row["role"] in {"ACTOR", "TARGET", "OBJECT", "LOCATION"}:
                roles.setdefault(row["role"].lower(), entity)
    # Existing location text can be a country, city, or named facility; only canonical links are used.
    start = min((t[0] for t in times), default=None)
    end = max((t[0] for t in times), default=None)
    precision = min((t[1] for t in times), key=lambda p: {"MINUTE": 0, "DAY": 1, "PERIOD": 2}.get(p, 3), default=None)
    identity = frozenset(row["identity_key"] for row in evidence if row["identity_key"])
    fp = IncidentFingerprint(actor=roles.get("actor"), action=actions[0] if actions else None, target=roles.get("target"),
                             object=roles.get("object"), location=roles.get("location"), event_time_start=start,
                             event_time_end=end, time_precision=precision,
                             time_expression=time_expressions[0] if time_expressions else None,
                             quantity=quantities[0] if quantities else {}, consequence=consequence, response=response,
                             evidence=identity, entities=frozenset(entities), source_metadata={
                                 "document_id": str(document_id),
                                 "multi_occurrence_possible": len(occurrence_claims) > 1,
                             })
    return fp, {"evidence_ids": [row["id"] for row in evidence], "entities": sorted(entities)}


async def persist_fingerprint(conn, incident_id, fingerprint: IncidentFingerprint, extras: dict) -> None:
    from psycopg.types.json import Jsonb
    values = {"actor": fingerprint.actor, "target": fingerprint.target, "object": fingerprint.object, "location": fingerprint.location}
    entity_ids = {role: await (await conn.execute("SELECT id FROM entities WHERE id=%s", (value,))).fetchone() for role, value in values.items() if value}
    def uid(role): return entity_ids.get(role)["id"] if entity_ids.get(role) else None
    await conn.execute(
        "INSERT INTO incident_fingerprints(incident_id,primary_actor_id,action_predicate,target_entity_id,object_entity_id,location_entity_id,event_time_start,event_time_end,time_precision,event_time_expression,quantity,consequence,response,supporting_entities,source_metadata) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(incident_id) DO UPDATE SET "
        "primary_actor_id=COALESCE(incident_fingerprints.primary_actor_id,EXCLUDED.primary_actor_id),action_predicate=COALESCE(incident_fingerprints.action_predicate,EXCLUDED.action_predicate),"
        "target_entity_id=COALESCE(incident_fingerprints.target_entity_id,EXCLUDED.target_entity_id),object_entity_id=COALESCE(incident_fingerprints.object_entity_id,EXCLUDED.object_entity_id),"
        "location_entity_id=COALESCE(incident_fingerprints.location_entity_id,EXCLUDED.location_entity_id),event_time_start=COALESCE(incident_fingerprints.event_time_start,EXCLUDED.event_time_start),"
        "event_time_end=COALESCE(incident_fingerprints.event_time_end,EXCLUDED.event_time_end),time_precision=COALESCE(incident_fingerprints.time_precision,EXCLUDED.time_precision),"
        "event_time_expression=COALESCE(incident_fingerprints.event_time_expression,EXCLUDED.event_time_expression),"
        "quantity=CASE WHEN incident_fingerprints.quantity='{}'::jsonb THEN EXCLUDED.quantity ELSE incident_fingerprints.quantity END,"
        "consequence=COALESCE(incident_fingerprints.consequence,EXCLUDED.consequence),response=COALESCE(incident_fingerprints.response,EXCLUDED.response),"
        "supporting_entities=(SELECT ARRAY(SELECT DISTINCT unnest(incident_fingerprints.supporting_entities || EXCLUDED.supporting_entities))),updated_at=now()",
        (incident_id, uid("actor"), fingerprint.action, uid("target"), uid("object"), uid("location"), fingerprint.event_time_start,
         fingerprint.event_time_end, fingerprint.time_precision, fingerprint.time_expression, Jsonb(fingerprint.quantity), fingerprint.consequence, fingerprint.response,
         list(fingerprint.entities), Jsonb(fingerprint.source_metadata)))
    for evidence_id in extras["evidence_ids"]:
        row = await (await conn.execute("SELECT identity_key FROM evidence WHERE id=%s", (evidence_id,))).fetchone()
        await conn.execute("INSERT INTO incident_fingerprint_evidence(incident_id,evidence_id,identity_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                           (incident_id, evidence_id, row["identity_key"] if row else None))
    for entity_id in fingerprint.entities:
        role = next((r.upper() for r, v in values.items() if v == entity_id), "MENTIONED")
        await conn.execute("INSERT INTO incident_entities(incident_id,entity_id,role) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (incident_id, entity_id, role))


async def resolve_document(conn, document_id, provisional_incident_id, event_thread_id) -> Resolution:
    from psycopg.types.json import Jsonb
    existing = await (await conn.execute(
        "SELECT incident_id,state,match_strength,matched_signals,conflicts,candidates_considered FROM document_incident_resolutions WHERE document_id=%s",
        (document_id,))).fetchone()
    if existing:
        return Resolution(existing["state"], existing["incident_id"], existing["match_strength"],
                          tuple(existing["matched_signals"] or []), tuple(existing["conflicts"] or []),
                          tuple(existing["candidates_considered"] or []))
    fp, extras = await build_document_fingerprint(conn, document_id)
    await persist_fingerprint(conn, provisional_incident_id, fp, extras)
    retriever = DeterministicIncidentCandidateRetriever()
    resolver = DeterministicIncidentResolver()
    candidates = [] if fp.source_metadata.get("multi_occurrence_possible") else await retriever.retrieve(conn, fp, exclude_incident_id=provisional_incident_id)
    resolution = (Resolution("REVIEW_REQUIRED", None, "UNKNOWN") if fp.source_metadata.get("multi_occurrence_possible")
                  else resolver.resolve(fp, candidates))
    target_id = resolution.incident_id or provisional_incident_id
    matched = resolution.matched_signals
    conflicts = resolution.conflicts
    if resolution.incident_id:
        await conn.execute("UPDATE documents SET incident_id=%s WHERE id=%s", (target_id, document_id))
        await conn.execute("UPDATE claims SET incident_id=%s WHERE incident_id=%s AND id IN (SELECT claim_id FROM claim_sources WHERE document_id=%s)",
                           (target_id, provisional_incident_id, document_id))
        await persist_fingerprint(conn, target_id, fp, extras)
        await conn.execute("DELETE FROM incidents WHERE id=%s", (provisional_incident_id,))
        await conn.execute("DELETE FROM event_threads et WHERE et.id=%s AND NOT EXISTS(SELECT 1 FROM incidents i WHERE i.event_thread_id=et.id)", (event_thread_id,))
    await conn.execute(
        "INSERT INTO document_incident_resolutions(document_id,incident_id,state,resolution_method,match_strength,matched_signals,conflicts,candidates_considered,limitation) "
        "VALUES(%s,%s,%s,'DETERMINISTIC_STRUCTURED_V1',%s,%s,%s,%s,%s) ON CONFLICT(document_id) DO UPDATE SET incident_id=EXCLUDED.incident_id,state=EXCLUDED.state,"
        "resolution_method=EXCLUDED.resolution_method,match_strength=EXCLUDED.match_strength,matched_signals=EXCLUDED.matched_signals,conflicts=EXCLUDED.conflicts,"
        "candidates_considered=EXCLUDED.candidates_considered,limitation=EXCLUDED.limitation,updated_at=now()",
        (document_id, target_id, resolution.state, resolution.match_strength, Jsonb(list(matched)), Jsonb(list(conflicts)), Jsonb(list(resolution.candidates_considered)),
         ("Multiple distinct occurrence predicates were detected; the article-level incident model cannot safely split them, so this document is held for review." if fp.source_metadata.get("multi_occurrence_possible")
          else "Article-level single-incident assignment; multi-occurrence decomposition is not available in the current document schema.")))
    return Resolution(resolution.state, target_id, resolution.match_strength, tuple(matched), tuple(conflicts), resolution.candidates_considered)
