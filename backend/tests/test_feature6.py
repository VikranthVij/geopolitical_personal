from app.feature6 import assess_pair, candidate_pairs, _importance


def claim(kind, statement, incident="i1", normalized=None, polarity="AFFIRMED"):
    return {"id": statement, "incident_id": incident, "type": kind, "statement": statement,
            "normalized_representation": normalized or {}, "polarity": polarity}


# --- 1. QUANTITATIVE ---
def test_exact_quantities_conflict_but_lower_bound_is_compatible():
    a = claim("QUANTITATIVE", "20 missiles were launched", normalized={"quantity": {"operator": "EQ", "value": 20, "unit": "missiles", "original": "20 missiles"}})
    b = claim("QUANTITATIVE", "30 missiles were launched", normalized={"quantity": {"operator": "EQ", "value": 30, "unit": "missiles", "original": "30 missiles"}})
    assert assess_pair(a, b)[0] == "CONTRADICTS"
    b["normalized_representation"]["quantity"]["operator"] = "GTE"
    assert assess_pair(a, b)[0] == "COMPATIBLE"


def test_quantity_same_exact_value_is_compatible():
    a = claim("QUANTITATIVE", "20 missiles were launched", normalized={"quantity": {"operator": "EQ", "value": 20, "unit": "missiles", "original": "20 missiles"}})
    b = claim("QUANTITATIVE", "20 missiles were launched", normalized={"quantity": {"operator": "EQ", "value": 20, "unit": "missiles", "original": "20 missiles"}})
    assert assess_pair(a, b)[0] == "COMPATIBLE"


def test_quantity_conflict_requires_matching_target_and_predicate_scope():
    a = claim("QUANTITATIVE", "10 missiles hit Facility A", normalized={"quantity": {"operator": "EQ", "value": 10, "unit": "missiles", "original": "10 missiles"}})
    b = claim("QUANTITATIVE", "30 missiles were launched overall", normalized={"quantity": {"operator": "EQ", "value": 30, "unit": "missiles", "original": "30 missiles"}})
    assert assess_pair(a, b)[0] == "NOT_COMPARABLE"


def test_quantity_unit_mismatch_is_inconclusive():
    a = claim("QUANTITATIVE", "10 missiles were launched", normalized={"quantity": {"operator": "EQ", "value": 10, "unit": "missiles", "original": "10 missiles"}})
    b = claim("QUANTITATIVE", "10 drones were launched", normalized={"quantity": {"operator": "EQ", "value": 10, "unit": "drones", "original": "10 drones"}})
    assert assess_pair(a, b)[0] == "INCONCLUSIVE"


# --- 2. OCCURRENCE ---
def test_different_incidents_and_unknown_scope_are_not_forced_into_conflicts():
    a = claim("OCCURRENCE", "Explosion occurred", normalized={"predicate_surface": "explosion"})
    b = claim("OCCURRENCE", "No explosion occurred", incident="i2", normalized={"predicate_surface": "explosion"}, polarity="NEGATED")
    assert assess_pair(a, b)[0] == "NOT_COMPARABLE"
    b["incident_id"] = "i1"
    assert assess_pair(a, b)[0] == "CONTRADICTS"


def test_occurrence_same_assertion_is_compatible():
    a = claim("OCCURRENCE", "Strike occurred at the base", normalized={"predicate_surface": "strike occurred"})
    b = claim("OCCURRENCE", "Strike occurred at the base", normalized={"predicate_surface": "strike occurred"})
    assert assess_pair(a, b)[0] == "COMPATIBLE"


def test_occurrence_different_predicates_opposite_polarity_is_inconclusive():
    a = claim("OCCURRENCE", "Airstrike carried out", normalized={"predicate_surface": "airstrike"})
    b = claim("OCCURRENCE", "No naval activity observed", normalized={"predicate_surface": "naval activity"}, polarity="NEGATED")
    assert assess_pair(a, b)[0] == "INCONCLUSIVE"


# --- 3. LOCATION ---
def test_different_location_roles_are_not_guessed():
    a = claim("LOCATION", "Impact in Tehran", normalized={"location_text": "Tehran", "role": "impact"})
    b = claim("LOCATION", "Origin in Isfahan", normalized={"location_text": "Isfahan", "role": "origin"})
    assert assess_pair(a, b)[0] == "NOT_COMPARABLE"


def test_locations_conflict_only_for_the_same_residual_proposition():
    a = claim("LOCATION", "Strike occurred in Tehran", normalized={"location_text": "Tehran"})
    b = claim("LOCATION", "Strike occurred in Isfahan", normalized={"location_text": "Isfahan"})
    assert assess_pair(a, b)[0] == "CONTRADICTS"
    b["statement"] = "Missile launched from Isfahan"
    b["normalized_representation"]["location_text"] = "Isfahan"
    assert assess_pair(a, b)[0] == "NOT_COMPARABLE"


def test_locations_same_location_is_compatible():
    a = claim("LOCATION", "Strike occurred in Tehran", normalized={"location_text": "Tehran"})
    b = claim("LOCATION", "Strike occurred in Tehran", normalized={"location_text": "Tehran"})
    assert assess_pair(a, b)[0] == "COMPATIBLE"


# --- 4. TIME ---
def test_time_values_and_start_end_roles():
    a = claim("TIME", "Attack occurred at 10:00 UTC", normalized={"normalized": "10:00UTC", "precision": "MINUTE"})
    b = claim("TIME", "Attack occurred at 18:00 UTC", normalized={"normalized": "18:00UTC", "precision": "MINUTE"})
    assert assess_pair(a, b)[0] == "CONTRADICTS"
    b["statement"] = "Attack ended at 18:00 UTC"
    assert assess_pair(a, b)[0] == "COMPATIBLE"


def test_time_same_normalized_value_is_compatible():
    a = claim("TIME", "Attack began at 10:00 UTC", normalized={"normalized": "10:00UTC", "precision": "MINUTE"})
    b = claim("TIME", "Attack began at 10:00 UTC", normalized={"normalized": "10:00UTC", "precision": "MINUTE"})
    assert assess_pair(a, b)[0] == "COMPATIBLE"


def test_time_precision_mismatch_is_inconclusive():
    a = claim("TIME", "Attack occurred at 10:00 UTC", normalized={"normalized": "10:00UTC", "precision": "MINUTE"})
    b = claim("TIME", "Attack occurred on Tuesday", normalized={"normalized": "Tuesday", "precision": "DAY"})
    assert assess_pair(a, b)[0] == "INCONCLUSIVE"


# --- 5. STATUS ---
def test_status_destroyed_vs_operational_but_not_damaged_subset():
    a = claim("STATUS", "Facility was destroyed")
    b = claim("STATUS", "Facility remains operational")
    assert assess_pair(a, b)[0] == "CONTRADICTS"
    a["statement"] = "Facility was damaged"
    assert assess_pair(a, b)[0] == "INCONCLUSIVE"


def test_status_same_assertion_is_compatible():
    a = claim("STATUS", "Facility remains fully operational")
    b = claim("STATUS", "Facility remains fully operational")
    assert assess_pair(a, b)[0] == "COMPATIBLE"


# --- 6. INTENT ---
def test_reported_intent_only_conflicts_when_same_objective_is_explicitly_denied():
    a = claim("INTENT", "Officials said objective is destroy infrastructure", normalized={"intent_expression": "destroy infrastructure"})
    a["intent_label"] = "REPORTED_INTENT"
    b = claim("INTENT", "Officials denied objective is destroy infrastructure", normalized={"intent_expression": "destroy infrastructure"}, polarity="NEGATED")
    b["intent_label"] = "REPORTED_INTENT"
    assert assess_pair(a, b)[0] == "CONTRADICTS"
    b["normalized_representation"]["intent_expression"] = "send political message"
    assert assess_pair(a, b)[0] == "INCONCLUSIVE"


def test_reported_intent_same_objective_is_compatible():
    a = claim("INTENT", "Officials said objective is deterrence", normalized={"intent_expression": "deterrence"})
    a["intent_label"] = "REPORTED_INTENT"
    b = claim("INTENT", "Spokesperson stated goal is deterrence", normalized={"intent_expression": "deterrence"})
    b["intent_label"] = "REPORTED_INTENT"
    assert assess_pair(a, b)[0] == "COMPATIBLE"


# --- 7. ATTRIBUTION ---
def test_attribution_different_actors_conflict():
    a = claim("ATTRIBUTION", "Strike launched by Country A", normalized={"actor": "Country A"})
    b = claim("ATTRIBUTION", "Strike launched by Country B", normalized={"actor": "Country B"})
    assert assess_pair(a, b)[0] == "CONTRADICTS"


def test_attribution_same_actor_is_compatible():
    a = claim("ATTRIBUTION", "Strike launched by Country A", normalized={"actor": "Country A"})
    b = claim("ATTRIBUTION", "Strike launched by Country A", normalized={"actor": "Country A"})
    assert assess_pair(a, b)[0] == "COMPATIBLE"


def test_attribution_missing_actor_is_inconclusive():
    a = claim("ATTRIBUTION", "Strike launched by Country A", normalized={"actor": "Country A"})
    b = claim("ATTRIBUTION", "Strike launched by unknown forces", normalized={})
    assert assess_pair(a, b)[0] == "INCONCLUSIVE"


# --- 8. CONSEQUENCE ---
def test_consequence_different_casualty_scopes_not_comparable():
    a = claim("CONSEQUENCE", "10 civilians were killed", normalized={"predicate_surface": "casualties"})
    b = claim("CONSEQUENCE", "5 soldiers were killed", normalized={"predicate_surface": "casualties"})
    assert assess_pair(a, b)[0] == "NOT_COMPARABLE"


def test_consequence_opposite_polarities_conflict():
    a = claim("CONSEQUENCE", "Civilian casualties were confirmed", normalized={"predicate_surface": "civilian casualties"})
    b = claim("CONSEQUENCE", "No civilian casualties were reported", normalized={"predicate_surface": "civilian casualties"}, polarity="NEGATED")
    assert assess_pair(a, b)[0] == "CONTRADICTS"


def test_consequence_same_assertion_is_compatible():
    a = claim("CONSEQUENCE", "Extensive structural damage reported", normalized={"predicate_surface": "damage"})
    b = claim("CONSEQUENCE", "Extensive structural damage reported", normalized={"predicate_surface": "damage"})
    assert assess_pair(a, b)[0] == "COMPATIBLE"


# --- 9. CANDIDATE RETRIEVAL & BOUNDS ---
def test_candidate_retrieval_is_bounded_and_never_crosses_incidents():
    claims = [claim("OCCURRENCE", f"Claim {i}", normalized={"predicate_surface": "attack"}) for i in range(100)]
    claims[-1]["incident_id"] = "different"
    pairs = candidate_pairs(claims, per_claim=3, total_limit=70)
    assert len(pairs) == 70
    assert all(a["incident_id"] == b["incident_id"] for a, b in pairs)


# --- 10. IMPORTANCE SCORING DIMENSIONS ---
def test_importance_calculation_and_independence_from_confidence():
    # Low confidence catastrophic strategic event: elevated importance
    level, score, basis = _importance("Unverified report of nuclear facility strike with regional escalation")
    assert level in {"CRITICAL", "HIGH"}
    assert basis["dimensions"]["strategic"] == "HIGH"
    assert basis["dimensions"]["military"] == "HIGH"
    assert basis["dimensions"]["escalation"] == "HIGH"

    # High confidence minor administrative event: low importance
    level, score, basis = _importance("Routine bilateral border flag meeting held in municipal office")
    assert level == "LOW"
    assert basis["dimensions"]["military"] == "LOW"
    assert basis["dimensions"]["economic"] == "LOW"

    # Economic consequence dimension
    _, _, basis = _importance("Oil tanker shipping disrupted in strait due to new trade sanctions")
    assert basis["dimensions"]["economic"] == "HIGH"

    # Humanitarian dimension
    _, _, basis = _importance("Over 200 civilians killed and displaced in humanitarian crisis")
    assert basis["dimensions"]["humanitarian"] == "HIGH"

    # Diplomatic dimension
    _, _, basis = _importance("Bilateral ceasefire agreement talks concluded by ambassador")
    assert basis["dimensions"]["diplomatic"] == "HIGH"
