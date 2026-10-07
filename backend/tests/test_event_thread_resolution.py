import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.event_thread_resolution import (
    DeterministicEventThreadResolver, EventThreadCandidate, IncidentThreadContext,
    _thread_title,
)


NOW = datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)
IRAN, ISRAEL, CHINA, RUSSIA, UKRAINE, NATANZ = [uuid4() for _ in range(6)]


def incident(*, actor=IRAN, participants=(IRAN, ISRAEL), targets=(ISRAEL,), locations=(NATANZ,),
             domains=("MILITARY_SECURITY",), when=NOW, cues=(), current=None):
    return IncidentThreadContext(uuid4(), current or uuid4(), "fixture", frozenset((actor,)) if actor else frozenset(),
        frozenset(participants), frozenset(targets), frozenset(locations), frozenset(domains),
        when, when, "MINUTE" if when else None, tuple(cues))


def thread(*, participants=(IRAN, ISRAEL), actors=(ISRAEL,), targets=(IRAN,), locations=(NATANZ,),
           domains=("MILITARY_SECURITY",), when=NOW, members=(), thread_id=None):
    return EventThreadCandidate(thread_id or uuid4(), "Israel–Iran Military Escalation", frozenset(actors),
        frozenset(participants), frozenset(targets), frozenset(locations), frozenset(domains), when, when, len(members) or 1,
        tuple(members))


class EventThreadResolutionTest(unittest.TestCase):
    def test_incident_without_candidates_creates_new_thread(self):
        current = incident()
        result = DeterministicEventThreadResolver().resolve(current, [])
        self.assertEqual(result.state, "NEW_THREAD")
        self.assertEqual(result.event_thread_id, current.current_thread_id)

    def test_related_military_incident_continues_thread(self):
        prior = thread()
        result = DeterministicEventThreadResolver().resolve(incident(when=NOW.replace(hour=11)), [prior])
        self.assertEqual(result.state, "ASSIGNED_EXISTING_THREAD")
        self.assertEqual(result.event_thread_id, prior.event_thread_id)
        self.assertTrue(any(s["signal"] == "context_domain" for s in result.matched_signals))

    def test_explicit_retaliation_is_strong_cross_actor_relationship_evidence(self):
        prior = thread(participants=(IRAN, ISRAEL), actors=(ISRAEL,), targets=(IRAN,))
        new = incident(actor=IRAN, participants=(IRAN, ISRAEL), cues=({"relation": "RESPONDED_TO", "claim_id": uuid4()},),
                       when=NOW.replace(hour=22))
        result = DeterministicEventThreadResolver().resolve(new, [prior])
        self.assertEqual(result.state, "ASSIGNED_EXISTING_THREAD")
        self.assertTrue(any(s.get("relation") == "RESPONDED_TO" for s in result.matched_signals))

    def test_same_actor_in_different_domain_starts_a_new_thread(self):
        military = thread(participants=(IRAN, ISRAEL), domains=("MILITARY_SECURITY",))
        economic = incident(actor=IRAN, participants=(IRAN, CHINA), targets=(CHINA,), domains=("ECONOMIC",))
        result = DeterministicEventThreadResolver().resolve(economic, [military])
        self.assertEqual(result.state, "NEW_THREAD")
        self.assertTrue(result.candidates_considered[0]["conflicts"])

    def test_same_location_only_does_not_merge_unrelated_incident(self):
        prior = thread(participants=(), actors=(), targets=(), domains=("MILITARY_SECURITY",), locations=(NATANZ,))
        new = incident(actor=None, participants=(), targets=(), domains=("MILITARY_SECURITY",), locations=(NATANZ,))
        self.assertEqual(DeterministicEventThreadResolver().resolve(new, [prior]).state, "NEW_THREAD")

    def test_temporal_proximity_alone_does_not_merge(self):
        prior = thread(participants=(), actors=(), targets=(), locations=(), domains=())
        new = incident(actor=None, participants=(), targets=(), locations=(), domains=(), when=NOW.replace(minute=1))
        self.assertEqual(DeterministicEventThreadResolver().resolve(new, [prior]).state, "NEW_THREAD")

    def test_long_gap_needs_explicit_continuity(self):
        prior = thread()
        without_cue = incident(when=NOW.replace(year=2027, month=1))
        self.assertNotEqual(DeterministicEventThreadResolver().resolve(without_cue, [prior]).state, "ASSIGNED_EXISTING_THREAD")
        with_cue = incident(when=NOW.replace(year=2027, month=1), cues=({"relation": "RESPONDED_TO"},))
        self.assertEqual(DeterministicEventThreadResolver().resolve(with_cue, [prior]).state, "ASSIGNED_EXISTING_THREAD")

    def test_unknown_time_is_not_invented_and_requires_explicit_relationship(self):
        prior = thread(when=None)
        new = incident(when=None)
        self.assertNotEqual(DeterministicEventThreadResolver().resolve(new, [prior]).state, "ASSIGNED_EXISTING_THREAD")
        explicit = incident(when=None, cues=({"relation": "RESPONDED_TO"},))
        self.assertEqual(DeterministicEventThreadResolver().resolve(explicit, [prior]).state, "ASSIGNED_EXISTING_THREAD")

    def test_multiple_eligible_threads_are_ambiguous(self):
        current = incident()
        result = DeterministicEventThreadResolver().resolve(current, [thread(), thread()])
        self.assertEqual(result.state, "AMBIGUOUS")
        self.assertEqual(result.event_thread_id, current.current_thread_id)

    def test_plausible_but_incomplete_continuity_requires_review(self):
        prior = thread(participants=(IRAN,), actors=(IRAN,), targets=(), domains=("MILITARY_SECURITY",), when=None)
        new = incident(participants=(IRAN,), targets=(), domains=("MILITARY_SECURITY",), when=None)
        self.assertEqual(DeterministicEventThreadResolver().resolve(new, [prior]).state, "REVIEW_REQUIRED")

    def test_deterministic_title_uses_structured_names_and_domain(self):
        self.assertEqual(_thread_title(["Iran", "Israel"], {"MILITARY_SECURITY"}, uuid4()),
                         "Iran–Israel Military Escalation")
        self.assertTrue(_thread_title([], set(), uuid4()).startswith("Event Thread "))


if __name__ == "__main__":
    unittest.main()
