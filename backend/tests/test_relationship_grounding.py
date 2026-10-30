"""Target-specific relationships: controlled fixtures plus the exact live excerpt."""
import sys
import unittest
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.event_thread_resolution import (IncidentThreadContext, EventThreadCandidate,
    DeterministicEventThreadResolver, _relationship_cues, _grounded_relationships)

IRAN = uuid4()
G20_TITLE = 'G20 gathering in Atlanta clouded by Russia row, Iran tensions and trade disputes'
G20_TEXT = "The G20 foreign ministers' meeting in Atlanta faces early divisions over Russia's participation, possible renewed US strikes on Iran and global trade tensions, with Washington struggling to build consensus on key international issues"
IRAN_TEXT = 'Washington has urged regional partners to prepare for potential Iranian retaliation as President Donald Trump weighs renewed military action, while Vice President JD Vance reportedly proposes peace talks with Tehran'


def context(title, statement=None, **metadata):
    claims = ({'id': str(uuid4()), 'statement': statement or title, **metadata},)
    return IncidentThreadContext(uuid4(), uuid4(), title, participant_ids=frozenset([IRAN]),
        domains=frozenset(['MILITARY_SECURITY']), relationship_cues=_relationship_cues(claims),
        source_claims=claims, source_document_ids=(uuid4(),))


def candidate(*members):
    return EventThreadCandidate(uuid4(), 'fixture situation', frozenset(), frozenset([IRAN]),
        frozenset(), frozenset(), frozenset(['MILITARY_SECURITY']), None, None, len(members), members)


class RelationshipGroundingTests(unittest.TestCase):
    def setUp(self):
        self.prior = context('Missile strike on Natanz on October 1')
        self.response = context('Iran response', 'Iran responded in response to the missile strike on Natanz on October 1.')

    def test_explicit_target_and_source_evidence(self):
        c = candidate(self.prior)
        result = DeterministicEventThreadResolver().resolve(self.response, [c])
        self.assertEqual(result.state, 'ASSIGNED_EXISTING_THREAD')
        cue = _grounded_relationships(self.response, c.members)[0]
        self.assertEqual(cue['target_incident_id'], str(self.prior.incident_id))
        self.assertEqual(cue['subject_incident_id'], str(self.response.incident_id))
        self.assertEqual(cue['source_document_ids'], list(map(str, self.response.source_document_ids)))
        self.assertEqual(cue['source_text'], self.response.source_claims[0]['statement'])
        self.assertEqual(cue['source_text'][cue['cue_start']:cue['cue_end']], cue['cue'])
        self.assertEqual(cue['source_text'][cue['target_start']:cue['target_end']], cue['target_text'])

    def test_context_is_not_identity(self):
        for statement in ['Iran announced trade talks.', 'The leader announced a tax decision.',
                          'Military forces discussed security.', 'Iran responded amid rising tensions.',
                          'Iran retaliated.', 'Iran responded in response to regional developments.',
                          'Iran responded in response to tensions.',
                          'Iran responded in response to missile strike on Natanz on October 1 and diplomatic talks.',
                          'Iran responded in response to missile strike on Natanz on October 1, the port attack.']:
            with self.subTest(statement=statement):
                incoming = context('different incident', statement)
                result = DeterministicEventThreadResolver().resolve(incoming, [candidate(self.prior)])
                self.assertNotEqual(result.state, 'ASSIGNED_EXISTING_THREAD')

    def test_multiple_matching_incidents_in_same_thread_stay_unresolved(self):
        c = candidate(self.prior, replace(self.prior, incident_id=uuid4()))
        result = DeterministicEventThreadResolver().resolve(self.response, [c])
        self.assertEqual(result.state, 'REVIEW_REQUIRED')
        self.assertTrue(result.candidates_considered[0]['conflicts'])

    def test_multiple_matching_threads_are_ambiguous(self):
        r = DeterministicEventThreadResolver().resolve(self.response, [candidate(self.prior), candidate(self.prior)])
        self.assertEqual(r.state, 'AMBIGUOUS')

    def test_statement_can_be_target_without_physical_action(self):
        prior = context('Government statement rejecting the ceasefire proposal')
        current = context('Response', 'Iran responded in response to the government statement rejecting the ceasefire proposal.')
        self.assertEqual(DeterministicEventThreadResolver().resolve(current, [candidate(prior)]).state,
                         'ASSIGNED_EXISTING_THREAD')

    def test_exact_reference_inside_source_claim_resolves_indirect_target(self):
        prior = context('October facility incident', 'Israel launched the missile strike on Natanz on October 1.')
        self.assertEqual(DeterministicEventThreadResolver().resolve(self.response, [candidate(prior)]).state,
                         'ASSIGNED_EXISTING_THREAD')

    def test_denied_or_prospective_relationship_not_confirmed(self):
        for text in ['Iran denied responding in response to the missile strike on Natanz on October 1.',
                     'Iran may respond in response to the missile strike on Natanz on October 1.',
                     'Iran did not respond in response to the missile strike on Natanz on October 1.']:
            current = context('response', text)
            self.assertNotEqual(DeterministicEventThreadResolver().resolve(current, [candidate(self.prior)]).state,
                                'ASSIGNED_EXISTING_THREAD')

    def test_g20_iran_exact_live_excerpt_has_no_grounded_response_target(self):
        prior = context(G20_TITLE, G20_TEXT)
        current = context('Iran strike planning', IRAN_TEXT, type='INTENT', epistemic_status='REPORTED')
        result = DeterministicEventThreadResolver().resolve(current, [candidate(prior)])
        self.assertNotEqual(result.state, 'ASSIGNED_EXISTING_THREAD')
        self.assertFalse(_grounded_relationships(current, [prior]))
        self.assertTrue(result.candidates_considered[0]['conflicts'][0]['source_cues'])

    def test_member_bound_cannot_hide_ambiguity(self):
        c = replace(candidate(self.prior), members_complete=False)
        self.assertNotEqual(DeterministicEventThreadResolver().resolve(self.response, [c]).state,
                            'ASSIGNED_EXISTING_THREAD')

    def test_existing_relation_types_keep_target_grounding(self):
        for text,relation in [
            ('Iran retaliated in response to the missile strike on Natanz on October 1.', 'RESPONDED_TO'),
            ('Iran launched an attack because of the missile strike on Natanz on October 1.', 'CAUSED_BY'),
            ('Iran escalated following the missile strike on Natanz on October 1.', 'ESCALATED_FROM'),
            ('Iran announced aid in support of the missile strike on Natanz on October 1.', 'INFLUENCED_BY')]:
            with self.subTest(relation=relation):
                c=context('Response',text)
                matches=_grounded_relationships(c,[self.prior])
                self.assertEqual(len(matches),1)
                self.assertEqual(matches[0]['relation'],relation)

    def test_two_shared_entities_near_time_do_not_substitute_for_reference(self):
        from datetime import datetime, timezone
        shared=frozenset([IRAN, uuid4()]); now=datetime(2026,10,30,tzinfo=timezone.utc)
        prior=replace(candidate(self.prior),participant_ids=shared,latest_incident_at=now,latest_reported_at=now)
        current=replace(context('Unrelated meeting','Government announced trade talks.'),
                        participant_ids=shared,event_time_start=now,report_published_at=now)
        self.assertNotEqual(DeterministicEventThreadResolver().resolve(current,[prior]).state,
                            'ASSIGNED_EXISTING_THREAD')

    def test_earlier_attack_mentioned_only_as_context_is_not_candidate_identity(self):
        for title,text in [
            ('Minister announcement', 'Officials announced talks in response to the missile strike on Natanz on October 1.'),
            ('Diplomatic meeting amid missile strike on Natanz on October 1',
             'Officials announced talks amid missile strike on Natanz on October 1.')]:
            prior=context(title,text)
            self.assertFalse(_grounded_relationships(self.response,[prior]))

    def test_conflicting_relation_classifications_are_not_overwritten(self):
        second = context('Action', 'Iran launched an attack because of the missile strike on Natanz on October 1.')
        current = replace(self.response, relationship_cues=self.response.relationship_cues + second.relationship_cues)
        self.assertNotEqual(DeterministicEventThreadResolver().resolve(current,[candidate(self.prior)]).state,
                            'ASSIGNED_EXISTING_THREAD')
