import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.claim_semantics import assertion_semantics
from app.feature6 import _importance, _military_escalation_support
from test_relationship_grounding import IRAN_TEXT


class EscalationSemanticsTests(unittest.TestCase):
    def test_required_semantic_categories(self):
        cases = [('Forces launched an attack.', 'ACTUAL_OCCURRENCE'),
                 ('Government threatened retaliation.', 'THREAT'),
                 ('President is considering military action.', 'CONSIDERATION'),
                 ('Officials are preparing contingency plans.', 'PLAN'),
                 ('Country may retaliate if attacked.', 'CONDITIONAL_POSSIBILITY'),
                 ('Government confirmed a military decision.', 'DECISION'),
                 ('Officials denied reports of an attack.', 'DENIAL'),
                 ('Military action reportedly occurred.', 'REPORTED_OCCURRENCE'),
                 ('Government announced an intention to deploy forces.', 'INTENTION'),
                 ('Officials warned of military retaliation.', 'WARNING')]
        for text, expected in cases:
            with self.subTest(text=text):
                c = {'statement': text, 'type': 'OCCURRENCE', 'attribution': {'speaker_text': 'source'}}
                self.assertEqual(assertion_semantics(c), expected)
                _, _, basis = _importance(text, claims=[c])
                self.assertEqual(basis['dimensions']['escalation'] == 'HIGH',
                                 text == 'Forces launched an attack.')

    def test_threat_keeps_importance_without_executed_escalation(self):
        text = 'Government threatened nuclear military retaliation affecting oil trade and diplomatic talks.'
        level, _, b = _importance(text)
        self.assertEqual(level, 'CRITICAL')
        self.assertEqual(b['dimensions']['escalation'], 'LOW')
        self.assertIn('THREAT', b['assertion_semantics'])

    def test_metadata_denial_or_uncertainty_overrides_action_words(self):
        for metadata in [{'polarity': 'NEGATED'}, {'epistemic_status': 'DENIED'},
                         {'epistemic_status': 'POSSIBLE'}, {'intent_label': 'SPECULATION'}]:
            self.assertFalse(_military_escalation_support([{'statement': 'Forces launched an attack.', **metadata}]))

    def test_source_attribution_preserved_for_reported_actual_action(self):
        c = {'id': 'fixture', 'statement': 'Officials reported that forces launched an attack.',
             'type': 'OCCURRENCE', 'epistemic_status': 'REPORTED',
             'attribution': {'speaker_text': 'Officials'}, 'source_spans': [{'document_id': 'fixture-doc'}]}
        support = _military_escalation_support([c])[0]
        self.assertEqual(support['attribution'], c['attribution'])
        self.assertEqual(support['source_spans'], c['source_spans'])

    def test_exact_g20_iran_planning_text_does_not_establish_executed_escalation(self):
        level, _, b = _importance(IRAN_TEXT)
        self.assertNotEqual(level, 'LOW')
        self.assertEqual(b['dimensions']['escalation'], 'LOW')
        self.assertFalse(b['military_escalation_support'])

    def test_diplomatic_response_does_not_inherit_earlier_attack_execution(self):
        c = {'type': 'RESPONSE', 'statement': 'Officials announced peace talks in response to reports of a nuclear missile strike.'}
        self.assertFalse(_military_escalation_support([c]))

    def test_unverified_reported_status_action_still_has_importance(self):
        c = {'type': 'STATUS', 'statement': 'Nuclear facility struck', 'confidence': 'UNVERIFIED'}
        level, _, b = _importance('Nuclear facility missile strike with strategic impact', claims=[c])
        self.assertIn(level, {'HIGH', 'CRITICAL'})
        self.assertEqual(b['dimensions']['escalation'], 'HIGH')

    def test_routine_executed_military_activity_is_not_escalation(self):
        for text in ['Forces launched a military training exercise.',
                     'Troops deployed for routine duties.',
                     'Military action reportedly occurred.']:
            with self.subTest(text=text):
                self.assertFalse(_military_escalation_support([{'type': 'OCCURRENCE', 'statement': text}]))

    def test_plant_and_plane_are_not_planning_words(self):
        # Exact stored excerpts/headlines inspected during the live shadow audit.
        plant = 'An Indian-run pharmaceutical plant in Ukraine’s Sumy region has been badly damaged in a Russian drone attack, with one person killed and several others injured'
        plane = 'Plane billows smoke at Riyadh airport as Houthis escalate attacks - Reuters'
        self.assertEqual(assertion_semantics({'statement': plant}), 'ACTUAL_OCCURRENCE')
        self.assertNotEqual(assertion_semantics({'statement': plane}), 'PLAN')
        self.assertTrue(_military_escalation_support([{'type': 'CONSEQUENCE', 'statement': plant}]))

    def test_affirmative_attacked_predicate_is_not_lost(self):
        for text in ['Forces attacked a military base.',
                     'Houthis say attacked Riyadh as loud explosions rock Saudi capital, India condemns strikes on airports']:
            self.assertTrue(_military_escalation_support([{'type': 'OCCURRENCE', 'statement': text}]))
        self.assertFalse(_military_escalation_support([{'type': 'OCCURRENCE',
            'statement': 'Forces may attack a military base.'}]))
