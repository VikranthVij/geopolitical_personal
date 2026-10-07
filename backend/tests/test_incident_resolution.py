import sys
import unittest
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.incident_resolution import (
    CandidateIncident, DeterministicIncidentCandidateRetriever, DeterministicIncidentResolver,
    IncidentFingerprint, compare_fingerprints,
)


def fp(*, time="2026-10-07T18:30:00+00:00", quantity=None, evidence=("IMG-2026-A77",),
       actor="iran", action="launch", target="israel", location="natanz", object="missile", precision="MINUTE"):
    start = datetime.fromisoformat(time) if time else None
    return IncidentFingerprint(actor=actor, action=action, target=target, object=object, location=location,
        event_time_start=start, event_time_end=start, time_precision=precision if start else None,
        quantity=quantity or {}, evidence=frozenset(evidence))


class IncidentResolutionTest(unittest.TestCase):
    def test_cross_source_quantity_and_two_minute_difference_merge(self):
        incoming = fp(time="2026-10-07T18:32:00+00:00", quantity={"value": 25, "operator": "APPROX"})
        prior = fp(quantity={"value": 20, "operator": "GT"})
        result = DeterministicIncidentResolver().resolve(incoming, [CandidateIncident(uuid4(), prior)])
        self.assertEqual(result.state, "MATCHED_EXISTING")
        self.assertTrue(any(c["signal"] == "quantity_differs" for c in result.conflicts))
        self.assertTrue(any(m["signal"] == "evidence_identity" for m in result.matched_signals))

    def test_same_actor_action_target_location_different_exact_times_do_not_merge(self):
        prior = fp(time="2026-10-07T10:00:00+00:00", evidence=())
        incoming = fp(time="2026-10-07T18:00:00+00:00", evidence=())
        result = DeterministicIncidentResolver().resolve(incoming, [CandidateIncident(uuid4(), prior)])
        self.assertEqual(result.state, "NEW_INCIDENT")
        self.assertTrue(any(c["signal"] == "event_time" for c in result.candidates_considered[0]["conflicts"]))

    def test_next_day_attack_is_separate(self):
        result = DeterministicIncidentResolver().resolve(fp(time="2026-10-08T03:00:00+00:00", evidence=()),
            [CandidateIncident(uuid4(), fp(time="2026-10-07T18:30:00+00:00", evidence=()))])
        self.assertEqual(result.state, "NEW_INCIDENT")

    def test_actor_action_target_without_time_or_evidence_is_not_enough(self):
        prior = fp(time=None, evidence=(), location=None, object=None)
        incoming = fp(time=None, evidence=(), location=None, object=None)
        self.assertEqual(DeterministicIncidentResolver().resolve(incoming, [CandidateIncident(uuid4(), prior)]).state, "NEW_INCIDENT")

    def test_same_time_but_different_target_does_not_merge(self):
        result = DeterministicIncidentResolver().resolve(fp(target="saudi arabia"), [CandidateIncident(uuid4(), fp())])
        self.assertEqual(result.state, "NEW_INCIDENT")

    def test_same_target_but_different_actor_does_not_merge(self):
        result = DeterministicIncidentResolver().resolve(fp(actor="israel"), [CandidateIncident(uuid4(), fp())])
        self.assertEqual(result.state, "NEW_INCIDENT")

    def test_evidence_identity_alone_does_not_merge(self):
        incoming = fp(actor=None, action=None, target=None, location=None, object=None, time=None)
        prior = fp(actor=None, action=None, target=None, location=None, object=None, time=None)
        self.assertEqual(DeterministicIncidentResolver().resolve(incoming, [CandidateIncident(uuid4(), prior)]).state, "NEW_INCIDENT")

    def test_different_evidence_identity_is_a_conflict_not_an_absolute_rejection(self):
        incoming = fp(evidence=("IMG-B",))
        prior = fp(evidence=("IMG-A",))
        _, conflicts, _ = compare_fingerprints(incoming, prior)
        self.assertTrue(any(c["signal"] == "evidence_identity" for c in conflicts))

    def test_ambiguous_equal_candidates_are_not_force_merged(self):
        candidates = [CandidateIncident(uuid4(), fp()), CandidateIncident(uuid4(), fp())]
        result = DeterministicIncidentResolver().resolve(fp(time="2026-10-07T18:31:00+00:00"), candidates)
        self.assertEqual(result.state, "AMBIGUOUS")
        self.assertIsNone(result.incident_id)

    def test_partial_unknowns_are_retained_and_not_guessed(self):
        incoming = fp(actor=None, time=None, evidence=(), target=None, location="natanz", object=None)
        prior = fp(actor="iran", time=None, evidence=(), target=None, location="natanz", object=None)
        _, conflicts, support = compare_fingerprints(incoming, prior)
        self.assertFalse(any(c["signal"] == "actor" for c in conflicts))
        self.assertEqual(support, 1)

    def test_partial_explosion_and_strike_reports_can_match_on_time_and_location(self):
        incoming = fp(actor=None, action="explode", target=None, object=None, time="2026-10-07T18:30:00+00:00",
                      evidence=(), location="natanz")
        prior = fp(actor="israel", action="strike", target=None, object=None, time="2026-10-07T18:31:00+00:00",
                   evidence=(), location="natanz")
        result = DeterministicIncidentResolver().resolve(incoming, [CandidateIncident(uuid4(), prior)])
        self.assertEqual(result.state, "MATCHED_EXISTING")

    def test_low_precision_same_day_is_compatible(self):
        day = fp(time="2026-10-07T00:00:00+00:00", precision="DAY", evidence=())
        exact = fp(time="2026-10-07T18:30:00+00:00", precision="MINUTE", evidence=())
        event_time = next(m for m in compare_fingerprints(day, exact)[0] if m["signal"] == "event_time")
        self.assertEqual(event_time["relation"], "SAME_DAY")

    def test_retriever_is_bounded_structured_interface(self):
        self.assertEqual(DeterministicIncidentCandidateRetriever.limit, 50)

    def test_controlled_50_report_scenario_clusters_five_events(self):
        groups = [
            fp(time=f"2026-10-07T{hour:02d}:30:00+00:00", evidence=(f"img-a-{i}",), location="israel")
            for i, hour in enumerate((2, 6, 10, 14, 18))
        ]
        # Three events share actor, action, country, and target but occur hours apart.
        groups[0] = fp(time="2026-10-07T10:30:00+00:00", evidence=("incident-0",), location="israel")
        groups[1] = fp(time="2026-10-07T13:30:00+00:00", evidence=("incident-1",), location="israel")
        groups[2] = fp(time="2026-10-07T18:30:00+00:00", evidence=("incident-2",), location="israel")
        groups[3] = fp(time="2026-10-08T08:30:00+00:00", evidence=("incident-3",), actor="russia", target="ukraine", location="kyiv")
        groups[4] = fp(time="2026-10-08T12:30:00+00:00", evidence=("incident-4",), actor="china", target="taiwan", location="taiwan")
        sizes = (10, 8, 12, 9, 11)
        references = [CandidateIncident(uuid4(), group) for group in groups]
        started = time.perf_counter()
        resolved = []
        for group_index, count in enumerate(sizes):
            for report_index in range(count):
                base = groups[group_index]
                delta = report_index % 5 - 2
                candidate = IncidentFingerprint(**{**base.__dict__,
                    "event_time_start": base.event_time_start.replace(minute=30 + delta),
                    "event_time_end": base.event_time_end.replace(minute=30 + delta),
                    "quantity": {"value": 20 + report_index, "operator": "APPROX"}})
                outcome = DeterministicIncidentResolver().resolve(candidate, references)
                self.assertEqual(outcome.state, "MATCHED_EXISTING")
                self.assertEqual(outcome.incident_id, references[group_index].incident_id)
                resolved.append(outcome.incident_id)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(resolved), 50)
        self.assertEqual(len(set(resolved)), 5)
        self.assertLess(elapsed, 1.0)
        print(f"50-report resolver scenario: {elapsed:.6f}s CPU-only")


if __name__ == "__main__":
    unittest.main()
