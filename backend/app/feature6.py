"""Deterministic, source-grounded Feature 6 assessments."""
from __future__ import annotations

import hashlib
import json
import re

from psycopg.types.json import Jsonb

TYPES = {"OCCURRENCE", "ATTRIBUTION", "QUANTITATIVE", "LOCATION", "TIME", "INTENT", "STATUS", "CONSEQUENCE"}


def _norm(value):
    if isinstance(value, str):
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return value


def assess_pair(a: dict, b: dict) -> tuple[str, str, dict]:
    """Return state, allowed contradiction type, and auditable scope/reason."""
    ta, tb = a["type"], b["type"]
    kind = ta if ta == tb and ta in TYPES else "OCCURRENCE"
    na, nb = a.get("normalized_representation") or {}, b.get("normalized_representation") or {}
    scope = {"incident_id": str(a["incident_id"]), "claim_type_a": ta, "claim_type_b": tb,
             "actor_a": na.get("actor"), "actor_b": nb.get("actor"),
             "target_a": na.get("target"), "target_b": nb.get("target"),
             "location_a": na.get("location_text"), "location_b": nb.get("location_text")}
    if a["incident_id"] != b["incident_id"]:
        return "NOT_COMPARABLE", kind, {**scope, "reason": "Claims belong to different incidents."}
    if ta != tb or ta not in TYPES:
        return "NOT_COMPARABLE", kind, {**scope, "reason": "Claim types or predicates are not aligned for structured comparison."}
    if ta != "ATTRIBUTION":
        va, vb = _norm(na.get("actor")), _norm(nb.get("actor"))
        if va and vb and va != vb:
            return "NOT_COMPARABLE", kind, {**scope, "reason": "Different actor scope; no contradiction inferred."}
    vt_a, vt_b = _norm(na.get("target")), _norm(nb.get("target"))
    if vt_a and vt_b and vt_a != vt_b:
        return "NOT_COMPARABLE", kind, {**scope, "reason": "Different target scope; no contradiction inferred."}
    if ta == "QUANTITATIVE":
        qa, qb = na.get("quantity") or {}, nb.get("quantity") or {}
        va, vb = qa.get("value"), qb.get("value")
        unit_a, unit_b = _norm(qa.get("unit")), _norm(qb.get("unit"))
        if not va or not vb or (unit_a and unit_b and unit_a != unit_b):
            return "INCONCLUSIVE", kind, {**scope, "reason": "Quantity values or units do not establish comparable scopes."}
        def quantity_scope(statement, quantity):
            original = quantity.get("original") or ""
            return _norm(re.sub(re.escape(original), " ", statement or "", flags=re.I))
        scope_a, scope_b = quantity_scope(a.get("statement"), qa), quantity_scope(b.get("statement"), qb)
        if (scope_a or scope_b) and scope_a != scope_b:
            return "NOT_COMPARABLE", kind, {**scope, "reason": "The remaining quantity statement differs, so target, predicate, or quantity scope is not aligned."}
        op_a, op_b = qa.get("operator", "UNKNOWN"), qb.get("operator", "UNKNOWN")
        if op_a in {"GTE", "GT", "APPROX", "RANGE"} or op_b in {"GTE", "GT", "APPROX", "RANGE"}:
            return "COMPATIBLE", kind, {**scope, "reason": "At-least, approximate, or range quantities may overlap; preserved as compatible."}
        if op_a == op_b == "EQ":
            if str(va) != str(vb):
                return "CONTRADICTS", kind, {**scope, "reason": f"Both claims report exact {unit_a or 'quantities'} for the same incident scope ({va} vs {vb}); neither is reconciled."}
            return "COMPATIBLE", kind, {**scope, "reason": f"Both claims report the same exact {unit_a or 'quantity'} ({va}) for the same incident scope."}
        return "INCONCLUSIVE", kind, {**scope, "reason": "Quantity operators or temporal scope are insufficient for a safe comparison."}
    if ta == "LOCATION":
        va, vb = _norm(na.get("location_text")), _norm(nb.get("location_text"))
        if not va or not vb:
            return "INCONCLUSIVE", kind, {**scope, "reason": "Location scope is incomplete."}
        statement_a, statement_b = (a.get("statement") or "").casefold(), (b.get("statement") or "").casefold()
        role_a = "origin" if re.search(r"\b(origin|launched from|fired from|departed from)\b", statement_a) else "impact" if re.search(r"\b(impact|hit|struck|occurred in|at the site)\b", statement_a) else None
        role_b = "origin" if re.search(r"\b(origin|launched from|fired from|departed from)\b", statement_b) else "impact" if re.search(r"\b(impact|hit|struck|occurred in|at the site)\b", statement_b) else None
        if role_a and role_b and role_a != role_b:
            return "NOT_COMPARABLE", kind, {**scope, "reason": "Claims describe different location roles (origin versus impact)."}
        residual_a = _norm(re.sub(re.escape(na.get("location_text") or ""), " ", a.get("statement") or "", flags=re.I))
        residual_b = _norm(re.sub(re.escape(nb.get("location_text") or ""), " ", b.get("statement") or "", flags=re.I))
        if not residual_a or residual_a != residual_b:
            return "NOT_COMPARABLE", kind, {**scope, "reason": "The surrounding location claim differs; same location role and proposition are not established."}
        if va != vb:
            return "CONTRADICTS", kind, {**scope, "reason": "Claims identify incompatible locations for the same incident and location role."}
        return "COMPATIBLE", kind, {**scope, "reason": "Claims identify the same location for the same incident and location role."}
    if ta == "TIME":
        xa, xb = na.get("normalized"), nb.get("normalized")
        if not xa or not xb or na.get("precision") != nb.get("precision"):
            return "INCONCLUSIVE", kind, {**scope, "reason": "Temporal precision is missing or not comparable."}
        sa, sb = (a.get("statement") or "").casefold(), (b.get("statement") or "").casefold()
        role_a = "start" if re.search(r"\b(begin|began|start|started)\b", sa) else "end" if re.search(r"\b(end|ended|finish|finished)\b", sa) else "occurrence"
        role_b = "start" if re.search(r"\b(begin|began|start|started)\b", sb) else "end" if re.search(r"\b(end|ended|finish|finished)\b", sb) else "occurrence"
        if role_a != role_b:
            return "COMPATIBLE", kind, {**scope, "reason": "Claims describe different temporal roles (for example, start versus end)."}
        if xa != xb and na.get("precision") in {"MINUTE", "DAY"}:
            return "CONTRADICTS", kind, {**scope, "reason": "Claims give incompatible exact times at the same stated precision for the same occurrence."}
        return "COMPATIBLE", kind, {**scope, "reason": "Claims give the same normalized time at the same precision."}
    if ta in {"OCCURRENCE", "STATUS", "CONSEQUENCE"}:
        polar_a = a.get("polarity") or "AFFIRMED"
        polar_b = b.get("polarity") or "AFFIRMED"
        if polar_a != polar_b:
            predicate_a, predicate_b = _norm(na.get("predicate_surface")), _norm(nb.get("predicate_surface"))
            if not predicate_a or not predicate_b or predicate_a != predicate_b:
                return "INCONCLUSIVE", kind, {**scope, "reason": "Opposite polarity is present, but normalized predicates do not establish the same proposition."}
            return "CONTRADICTS", kind, {**scope, "reason": "Claims assert opposite polarities for the same incident and aligned predicate scope."}
        sa, sb = _norm(a.get("statement")), _norm(b.get("statement"))
        if sa == sb:
            return "COMPATIBLE", kind, {**scope, "reason": "Claims make the same normalized assertion."}
        if ta == "STATUS":
            raw_a, raw_b = (a.get("statement") or "").casefold(), (b.get("statement") or "").casefold()
            destroyed = lambda s: bool(re.search(r"\b(destroyed|demolished|obliterated)\b", s))
            operational = lambda s: bool(re.search(r"\b(remains? operational|fully operational|still functioning|fully functional)\b", s))
            if destroyed(raw_a) and operational(raw_b) or destroyed(raw_b) and operational(raw_a):
                return "CONTRADICTS", kind, {**scope, "reason": "One claim says the facility was destroyed while the other says it remains operational."}
        if ta == "CONSEQUENCE":
            raw_a, raw_b = (a.get("statement") or "").casefold(), (b.get("statement") or "").casefold()
            def casualty_scope(raw):
                return "civilian" if "civilian" in raw else "military" if re.search(r"\b(soldier|troop|military personnel)\b", raw) else "unspecified"
            if casualty_scope(raw_a) != casualty_scope(raw_b):
                return "NOT_COMPARABLE", kind, {**scope, "reason": "Consequence claims cover different civilian/military populations."}
    if ta == "ATTRIBUTION":
        aa, ab = _norm(na.get("actor")), _norm(nb.get("actor"))
        if aa and ab:
            if aa != ab:
                return "CONTRADICTS", kind, {**scope, "reason": "Claims assign the same incident to different actors; attribution remains unresolved."}
            return "COMPATIBLE", kind, {**scope, "reason": "Claims assign the same incident to the same actor."}
        return "INCONCLUSIVE", kind, {**scope, "reason": "Actor attribution fields are incomplete."}
    if ta == "INTENT":
        ia, ib = na.get("intent_expression"), nb.get("intent_expression")
        if (a.get("intent_label") == b.get("intent_label") == "REPORTED_INTENT" and ia and ib and _norm(ia) == _norm(ib)):
            if a.get("polarity") != b.get("polarity"):
                return "CONTRADICTS", kind, {**scope, "reason": "Reported claims affirm and deny the same explicitly stated intended objective; attribution is preserved and intent remains unresolved."}
            return "COMPATIBLE", kind, {**scope, "reason": "Reported claims affirm the same intended objective."}
        return "INCONCLUSIVE", kind, {**scope, "reason": "Intent claims are retained as interpretations; incompatibility is not established by the available structured fields."}
    return "INCONCLUSIVE", kind, {**scope, "reason": "Structured evidence does not establish material incompatibility."}


async def _refresh_claims(conn, incident_id):
    claims = await (await conn.execute(
        "SELECT c.id,c.confidence,c.statement,"
        "(SELECT count(DISTINCT COALESCE(e.independence_key,"
        "(SELECT l.related_evidence_id::text FROM evidence_lineage l WHERE l.evidence_id=e.id AND l.relation IN ('SAME_UNDERLYING_EVIDENCE','CITES','DERIVED_FROM') LIMIT 1),"
        "ce.independence_group,e.origin_source_id::text)) FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id WHERE ce.claim_id=c.id AND ce.relation IN ('SUPPORTS','PARTIALLY_SUPPORTS') AND COALESCE(e.independence_key,ce.independence_group,e.origin_source_id::text) IS NOT NULL) support_groups,"
        "(SELECT count(DISTINCT e.id) FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id WHERE ce.claim_id=c.id AND ce.relation IN ('SUPPORTS','PARTIALLY_SUPPORTS')) support_items,"
        "(SELECT bool_or(e.directness='DIRECT') FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id WHERE ce.claim_id=c.id AND ce.relation IN ('SUPPORTS','PARTIALLY_SUPPORTS')) has_direct,"
        "(SELECT array_agg(DISTINCT e.strength) FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id WHERE ce.claim_id=c.id AND ce.relation IN ('SUPPORTS','PARTIALLY_SUPPORTS')) evidence_strengths,"
        "(SELECT array_agg(DISTINCT e.directness) FROM claim_evidence ce JOIN evidence e ON e.id=ce.evidence_id WHERE ce.claim_id=c.id AND ce.relation IN ('SUPPORTS','PARTIALLY_SUPPORTS')) evidence_directness,"
        "(SELECT min(s.tier) FROM claim_sources cs JOIN documents d ON d.id=cs.document_id JOIN sources s ON s.id=d.source_id WHERE cs.claim_id=c.id) source_quality_tier,"
        "(SELECT max(d.published_at) FROM claim_sources cs JOIN documents d ON d.id=cs.document_id WHERE cs.claim_id=c.id) latest_source_date,"
        "(SELECT count(*) FROM contradictions x WHERE x.status='CONTRADICTS' AND (x.claim_a=c.id OR x.claim_b=c.id)) conflicts "
        "FROM claims c WHERE c.incident_id=%s", (incident_id,))).fetchall()
    for row in claims:
        groups, support_items = row["support_groups"] or 0, row["support_items"] or 0
        direct, conflicts = bool(row["has_direct"]), row["conflicts"] or 0
        strengths = row["evidence_strengths"] or []
        strong = any(strength and str(strength).upper() in {"HIGH", "STRONG"} for strength in strengths)
        if conflicts:
            level, basis = "CONTESTED", ["A structured contradiction is recorded; claims are preserved without reconciliation."]
        elif groups >= 2 and direct and strong:
            level, basis = "HIGH", ["At least two distinct evidence provenance groups", "Direct evidence is linked", "At least one linked evidence item is marked strong", "No contradiction currently recorded"]
        elif groups >= 2:
            level, basis = "MEDIUM", ["At least two distinct provenance groups are identified", "Evidence directness or strength does not meet the HIGH threshold", "No contradiction currently recorded"]
        elif support_items:
            level, basis = "LOW", ["Supporting evidence is linked", "Independent corroboration is absent or provenance is unknown"]
        else:
            level, basis = "UNVERIFIED", ["No supporting evidence is linked"]
        latest = row["latest_source_date"].isoformat() if row["latest_source_date"] else None
        # Publisher tier and recency are exposed as context, never treated as truth.
        await conn.execute("UPDATE claims SET confidence=%s,confidence_explanation=%s,confidence_basis=%s,updated_at=now() WHERE id=%s",
                           (level, "; ".join(basis), Jsonb({"level": level, "basis": basis, "evidence_groups": groups,
                            "supporting_evidence_items": support_items, "evidence_strengths": strengths,
                            "evidence_directness": row["evidence_directness"] or [], "direct_evidence": direct,
                            "contradictions": conflicts, "source_quality_tier_context": row["source_quality_tier"],
                            "latest_source_published_at": latest,
                            "method": "PROVENANCE_RULES_V1"}), row["id"]))


def _importance(text: str, incident_count: int = 1) -> tuple[str, int, dict]:
    t = text.casefold()
    dimensions = {
        "military": "HIGH" if any(x in t for x in ("strike", "missile", "attack", "troops", "military", "war", "armed forces")) else "LOW",
        "economic": "HIGH" if any(x in t for x in ("oil", "shipping", "sanction", "trade", "energy", "market")) else "LOW",
        "diplomatic": "HIGH" if any(x in t for x in ("ceasefire", "treaty", "talks", "diplomatic", "ambassador")) else "LOW",
        "strategic": "HIGH" if any(x in t for x in ("strategic", "nuclear", "national security", "alliance", "sovereignty")) else "LOW",
        "humanitarian": "HIGH" if any(x in t for x in ("killed", "casualt", "civilian", "displaced", "humanitarian")) else "LOW",
        "geographic_scope": "REGIONAL" if any(x in t for x in ("regional", "across", "multiple countries", "strait")) else "LOCAL",
        "escalation": "HIGH" if any(x in t for x in ("retaliat", "escalat", "widen", "new front", "direct conflict")) else "LOW",
        "duration": "ONGOING" if incident_count > 1 else "SINGLE_REPORT",
        "novelty": "ELEVATED" if any(x in t for x in ("first time", "unprecedented", "first direct")) else "UNKNOWN",
    }
    high_count = sum(v == "HIGH" for k, v in dimensions.items() if k not in {"duration", "novelty"})
    score = high_count + min(max(incident_count - 1, 0), 2)
    level = "CRITICAL" if high_count >= 4 else "HIGH" if score >= 3 else "MEDIUM" if score >= 1 else "LOW"
    explanation = f"{high_count} of the assessed impact dimensions are elevated; aggregation also considers {incident_count} linked incident(s)."
    return level, min(score, 5), {"level": level, "dimensions": dimensions, "reason": explanation, "method": "RULES_V1"}


def _candidate_bucket(claim: dict) -> tuple:
    rep = claim.get("normalized_representation") or {}
    kind = claim["type"]
    statement = claim.get("statement") or ""
    inc_id = str(claim["incident_id"])
    if kind == "QUANTITATIVE":
        quantity = rep.get("quantity") or {}
        scope = _norm(re.sub(re.escape(quantity.get("original") or ""), " ", statement, flags=re.I))
        return (inc_id, kind, scope, _norm(quantity.get("unit")))
    if kind == "TIME":
        role = "start" if re.search(r"\b(begin|began|start|started)\b", statement, re.I) else "end" if re.search(r"\b(end|ended|finish|finished)\b", statement, re.I) else "occurrence"
        return (inc_id, kind, role)
    if kind == "LOCATION":
        role = "origin" if re.search(r"\b(origin|launched from|fired from|departed from)\b", statement, re.I) else "impact" if re.search(r"\b(impact|hit|struck|occurred in|at the site)\b", statement, re.I) else "unknown"
        location = rep.get("location_text") or ""
        scope = _norm(re.sub(re.escape(location), " ", statement, flags=re.I))
        return (inc_id, kind, role, scope)
    if kind == "STATUS":
        target = _norm(rep.get("target") or "")
        return (inc_id, kind, target)
    if kind == "ATTRIBUTION":
        target = _norm(rep.get("target") or "")
        return (inc_id, kind, target)
    if kind == "INTENT":
        intent_expr = _norm(rep.get("intent_expression") or "")
        return (inc_id, kind, intent_expr)
    if kind == "CONSEQUENCE":
        casualty = "civilian" if "civilian" in statement.casefold() else "military" if re.search(r"\b(soldier|troop|military personnel)\b", statement.casefold()) else "unspecified"
        return (inc_id, kind, casualty)
    predicate = _norm(rep.get("predicate_surface"))
    return (inc_id, kind, predicate or "general")


def candidate_pairs(claims: list[dict], per_claim: int = 20, total_limit: int = 5000) -> list[tuple[dict, dict]]:
    """Indexed structural candidate generation with strict per-claim and total caps."""
    buckets: dict[tuple, list[dict]] = {}
    for claim in claims:
        buckets.setdefault(_candidate_bucket(claim), []).append(claim)
    pairs = []
    for group in buckets.values():
        for index, right in enumerate(group):
            for left in group[max(0, index - per_claim):index]:
                if len(pairs) >= total_limit:
                    return pairs
                pairs.append((left, right))
    return pairs


async def run_feature6(conn, incident_id, event_thread_id, document_id=None):
    """Recompute claim assessments, bounded same-thread candidate pairs and importance."""
    claims = await (await conn.execute(
        "SELECT c.id,c.incident_id,c.type,c.statement,c.normalized_representation,c.polarity,c.intent_label "
        "FROM claims c JOIN incidents i ON i.id=c.incident_id WHERE i.event_thread_id=%s ORDER BY c.created_at,c.id LIMIT 1000",
        (event_thread_id,))).fetchall()
    # Reassessment must withdraw earlier pairings that no longer meet current scope rules.
    await conn.execute("UPDATE contradictions SET status='NOT_COMPARABLE',explanation='Candidate scope is not aligned under the current structured rules.',updated_at=now() WHERE event_thread_id=%s AND method='STRUCTURED_RULES_V1'", (event_thread_id,))
    for a, b in candidate_pairs(claims):
        state, kind, details = assess_pair(a, b)
        if state not in {"CONTRADICTS", "COMPATIBLE", "INCONCLUSIVE"}:
            continue
        left, right = sorted((a["id"], b["id"]), key=str)
        await conn.execute("INSERT INTO contradictions(claim_a,claim_b,type,explanation,status,incident_id,event_thread_id,scope,method) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'STRUCTURED_RULES_V1') ON CONFLICT ((LEAST(claim_a,claim_b)),(GREATEST(claim_a,claim_b)),type) DO UPDATE SET explanation=EXCLUDED.explanation,status=EXCLUDED.status,scope=EXCLUDED.scope,method=EXCLUDED.method,updated_at=now()",
            (left, right, kind, details["reason"], state, a["incident_id"], event_thread_id, Jsonb(details)))
        if state == "CONTRADICTS":
            key = hashlib.sha256(f"{event_thread_id}:contradiction:{left}:{right}:{kind}".encode()).hexdigest()
            await conn.execute("INSERT INTO material_changes(event_thread_id,trigger_incident_id,change_type,previous_state,new_state,reason,significance,dedupe_key) "
                "VALUES(%s,%s,'SIGNIFICANT_CONTRADICTION',%s,%s,%s,'HIGH',%s) ON CONFLICT(dedupe_key) DO NOTHING",
                (event_thread_id, a["incident_id"], Jsonb({"claims": [str(left), str(right)], "status": "UNASSESSED"}),
                 Jsonb({"status": "CONTRADICTS", "type": kind}), details["reason"], key))
    await _refresh_claims(conn, incident_id)
    row = await (await conn.execute("SELECT title,summary,importance_level,importance FROM incidents WHERE id=%s", (incident_id,))).fetchone()
    n = await (await conn.execute("SELECT count(*) n FROM incidents WHERE event_thread_id=%s", (event_thread_id,))).fetchone()
    level, numeric, basis = _importance(f"{row['title']} {row['summary'] or ''}", n["n"])
    await conn.execute("UPDATE incidents SET importance=%s,importance_level=%s,updated_at=now() WHERE id=%s", (Jsonb(basis), level, incident_id))
    thread = await (await conn.execute("SELECT string_agg(coalesce(title,'')||' '||coalesce(summary,''),' ') text FROM incidents WHERE event_thread_id=%s", (event_thread_id,))).fetchone()
    thread_level, thread_numeric, thread_basis = _importance(thread["text"] or "", n["n"])
    prior_thread = await (await conn.execute("SELECT importance,importance_category FROM event_threads WHERE id=%s", (event_thread_id,))).fetchone()
    await conn.execute("UPDATE event_threads SET importance=%s,importance_category=%s,importance_level=%s,updated_at=now() WHERE id=%s",
                       (Jsonb(thread_basis), thread_level, thread_numeric, event_thread_id))
    ranks = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    if prior_thread and (prior_thread["importance"] or {}).get("method") == "RULES_V1" and ranks[thread_level] > ranks.get(prior_thread["importance_category"], 0):
        incident_text = f"{row['title']} {row['summary'] or ''}".casefold()
        triggers = (
            ("MILITARY_ESCALATION", ("escalat", "retaliat", "new front", "direct conflict", "widened the conflict")),
            ("ECONOMIC_CONSEQUENCE", ("shipping disruption", "strait closed", "oil supply disrupted", "new sanctions")),
            ("DIPLOMATIC_SHIFT", ("ceasefire collapsed", "talks suspended", "ambassador recalled", "treaty withdrawn")),
            ("HUMANITARIAN_CONSEQUENCE", ("mass displacement", "mass casualties", "humanitarian emergency")),
        )
        change_type = next((kind for kind, terms in triggers if any(term in incident_text for term in terms)), None)
        if change_type:
            key = hashlib.sha256(f"{event_thread_id}:importance-rise:{thread_level}:{change_type}".encode()).hexdigest()
            await conn.execute("INSERT INTO material_changes(event_thread_id,trigger_incident_id,change_type,previous_state,new_state,reason,significance,dedupe_key) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(dedupe_key) DO NOTHING",
                (event_thread_id, incident_id, change_type, Jsonb({"importance": prior_thread["importance_category"]}), Jsonb({"importance": thread_level}),
                 f"Event Thread importance rose from {prior_thread['importance_category']} to {thread_level} alongside an explicit {change_type.replace('_', ' ').lower()} signal.", thread_level, key))
    # A newly introduced country or organization actor in an existing thread is material.
    context = await (await conn.execute("SELECT actor_entity_ids,participant_entity_ids,location_entity_ids FROM incident_thread_contexts WHERE incident_id=%s", (incident_id,))).fetchone()
    if context and n["n"] > 1:
        current_ids = set(context["actor_entity_ids"] or []) | set(context["participant_entity_ids"] or [])
        prior = await (await conn.execute("SELECT coalesce(array_agg(DISTINCT x.id),'{}'::uuid[]) actor_ids FROM incidents i "
            "JOIN incident_thread_contexts c ON c.incident_id=i.id CROSS JOIN LATERAL unnest(c.actor_entity_ids||c.participant_entity_ids) x(id) "
            "WHERE i.event_thread_id=%s AND i.id<>%s", (event_thread_id, incident_id))).fetchone()
        introduced = current_ids - set(prior["actor_ids"] or [])
        if introduced:
            actors = await (await conn.execute("SELECT id,canonical_name FROM entities WHERE id=ANY(%s) AND type IN ('COUNTRY','ORGANIZATION') ORDER BY canonical_name", (list(introduced),))).fetchall()
            if actors:
                actor_ids = sorted(str(actor["id"]) for actor in actors)
                names = [actor["canonical_name"] for actor in actors]
                key = hashlib.sha256(f"{event_thread_id}:new-major-actor:{','.join(actor_ids)}".encode()).hexdigest()
                await conn.execute("INSERT INTO material_changes(event_thread_id,trigger_incident_id,change_type,previous_state,new_state,reason,significance,dedupe_key) "
                    "VALUES(%s,%s,'NEW_MAJOR_ACTOR',%s,%s,%s,'HIGH',%s) ON CONFLICT(dedupe_key) DO NOTHING",
                    (event_thread_id, incident_id, Jsonb({"actor_entity_ids": sorted(str(actor_id) for actor_id in set(prior["actor_ids"] or []))}), Jsonb({"actors": names}),
                     f"New country or organization actor(s) entered this existing Event Thread: {', '.join(names)}.", key))
        # Geographic expansion: location entity introduced in ongoing thread
        current_locs = set(context.get("location_entity_ids") or [])
        if current_locs:
            prior_loc_row = await (await conn.execute("SELECT coalesce(array_agg(DISTINCT x.id),'{}'::uuid[]) loc_ids FROM incidents i "
                "JOIN incident_thread_contexts c ON c.incident_id=i.id CROSS JOIN LATERAL unnest(c.location_entity_ids) x(id) "
                "WHERE i.event_thread_id=%s AND i.id<>%s", (event_thread_id, incident_id))).fetchone()
            new_loc_ids = current_locs - set(prior_loc_row["loc_ids"] or [])
            if new_loc_ids:
                loc_entities = await (await conn.execute("SELECT id,canonical_name FROM entities WHERE id=ANY(%s) ORDER BY canonical_name", (list(new_loc_ids),))).fetchall()
                if loc_entities:
                    loc_names = [l["canonical_name"] for l in loc_entities]
                    key = hashlib.sha256(f"{event_thread_id}:geographic-expansion:{','.join(sorted(str(l['id']) for l in loc_entities))}".encode()).hexdigest()
                    await conn.execute("INSERT INTO material_changes(event_thread_id,trigger_incident_id,change_type,previous_state,new_state,reason,significance,dedupe_key) "
                        "VALUES(%s,%s,'GEOGRAPHIC_EXPANSION',%s,%s,%s,'HIGH',%s) ON CONFLICT(dedupe_key) DO NOTHING",
                        (event_thread_id, incident_id, Jsonb({"prior_locations": []}), Jsonb({"new_locations": loc_names}),
                         f"Geographic expansion: new location(s) introduced in existing Event Thread: {', '.join(loc_names)}.", key))
