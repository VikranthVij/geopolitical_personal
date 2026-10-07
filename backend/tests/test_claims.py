import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claims import extract_document_claims


class StructuredClaimExtractionTest(unittest.TestCase):
    def claims(self, text):
        return extract_document_claims(text, "")

    def test_realistic_fixture_covers_claim_taxonomy_and_roles(self):
        text = (Path(__file__).parent / "fixtures" / "claim_multitype.txt").read_text()
        claims = self.claims(text)
        types = {c.type for c in claims}
        self.assertEqual(types, {"OCCURRENCE", "ATTRIBUTION", "LOCATION", "TIME", "QUANTITATIVE", "INTENT", "STATUS", "RESPONSE", "CONSEQUENCE"})
        first_event = next(c for c in claims if c.type == "OCCURRENCE" and "more than 20" in c.statement)
        self.assertEqual(first_event.normalized["actor"], "Iran")
        self.assertEqual(first_event.normalized["target"], "Israel")
        self.assertEqual(first_event.normalized["quantity"]["operator"], "GT")
        self.assertEqual(first_event.epistemic_status, "REPORTED")

    def test_exact_and_approximate_quantities(self):
        exact = next(c for c in self.claims("Iran launched 20 missiles.") if c.type == "QUANTITATIVE")
        self.assertEqual(exact.normalized["quantity"], {"original": "20 missiles", "operator": "EQ", "value": 20, "unit": "missiles"})
        for phrase, operator, value in (("more than 20 missiles", "GT", 20), ("at least 20 missiles", "GTE", 20),
                                        ("fewer than 5 aircraft", "LT", 5), ("about 20 rockets", "APPROX", 20)):
            with self.subTest(phrase=phrase):
                item = next(c for c in self.claims(f"Iran deployed {phrase}.") if c.type == "QUANTITATIVE")
                self.assertEqual((item.normalized["quantity"]["operator"], item.normalized["quantity"]["value"]), (operator, value))
        self.assertFalse(any(c.type == "LOCATION" for c in self.claims("At least 50 people were killed.")))
        ranged = next(c for c in self.claims("Iran launched between 20 and 30 missiles.") if c.type == "QUANTITATIVE")
        self.assertEqual((ranged.normalized["quantity"]["min"], ranged.normalized["quantity"]["max"]), (20, 30))
        qualitative = next(c for c in self.claims("Dozens of missiles were launched.") if c.type == "QUANTITATIVE")
        self.assertEqual((qualitative.normalized["quantity"]["operator"], qualitative.normalized["quantity"]["value"], qualitative.normalized["quantity"]["unit"]), ("UNKNOWN", None, "missiles"))

    def test_negation_and_denial_never_become_affirmed_occurrences(self):
        negated = self.claims("Iran did not launch missiles.")
        occurrence = next(c for c in negated if c.type == "OCCURRENCE")
        self.assertEqual((occurrence.polarity, occurrence.status), ("NEGATED", "NEGATED"))
        denied = self.claims("Iran denied launching ballistic missiles.")
        self.assertEqual([c.type for c in denied], ["RESPONSE"])
        self.assertEqual(denied[0].status, "DENIED")
        self.assertEqual(denied[0].normalized["actor"], "Iran")
        no_evidence = self.claims("No evidence has emerged that Iran launched missiles.")
        self.assertFalse(any(c.type == "OCCURRENCE" for c in no_evidence))

    def test_attribution_chain_and_uncertainty_are_preserved(self):
        direct = next(c for c in self.claims("Iran launched missiles.") if c.type == "OCCURRENCE")
        attributed = next(c for c in self.claims("Israeli officials said Iran launched missiles.") if c.type == "OCCURRENCE")
        self.assertEqual(direct.attribution_type, "DIRECT_SOURCE_ASSERTION")
        self.assertEqual(attributed.attribution_type, "ATTRIBUTED_ASSERTION")
        self.assertEqual(attributed.attribution["speaker_text"], "Israeli officials")
        according = next(c for c in self.claims("According to Israeli officials, Iran launched missiles.") if c.type == "OCCURRENCE")
        self.assertEqual((according.attribution_type, according.attribution["speaker_text"]), ("ATTRIBUTED_ASSERTION", "Israeli officials"))
        possible = next(c for c in self.claims("Officials said Iran may have launched missiles.") if c.type == "OCCURRENCE")
        self.assertEqual(possible.epistemic_status, "POSSIBLE")
        reported = next(c for c in self.claims("Iran reportedly launched missiles.") if c.type == "OCCURRENCE")
        self.assertEqual(reported.epistemic_status, "REPORTED")
        chain = next(c for c in self.claims("Reuters reported that Israeli officials claimed Iran launched missiles.") if c.type == "OCCURRENCE")
        self.assertEqual(chain.attribution_type, "REPORTED_ASSERTION")
        self.assertEqual(chain.attribution["reported_by"], "Reuters")
        self.assertEqual(chain.attribution["speaker_text"], "Israeli officials")

    def test_attributed_denial_is_not_a_launch_confirmation(self):
        values = self.claims("Iran said it had not launched missiles.")
        occurrence = next(c for c in values if c.type == "OCCURRENCE")
        self.assertEqual((occurrence.polarity, occurrence.epistemic_status), ("NEGATED", "REPORTED"))
        self.assertEqual(occurrence.attribution["speaker_text"], "Iran")

    def test_negated_response_and_status_keep_polarity(self):
        response = next(c for c in self.claims("Israel did not respond with airstrikes.") if c.type == "RESPONSE")
        self.assertEqual(response.polarity, "NEGATED")
        state = next(c for c in self.claims("The ceasefire has not collapsed.") if c.type == "STATUS")
        self.assertEqual((state.polarity, state.status), ("NEGATED", "NEGATED"))

    def test_negation_is_scoped_to_each_predicate(self):
        values = self.claims("Iran did not launch missiles, but Israel responded with airstrikes.")
        occurrence = next(c for c in values if c.type == "OCCURRENCE")
        response = next(c for c in values if c.type == "RESPONSE")
        self.assertEqual((occurrence.polarity, occurrence.status), ("NEGATED", "NEGATED"))
        self.assertEqual((response.polarity, response.status), ("AFFIRMED", "ASSERTED"))

    def test_intent_labels_and_consequence_response_status(self):
        intent = next(c for c in self.claims("Iran said the attack was intended as retaliation.") if c.type == "INTENT")
        self.assertEqual(intent.intent_label, "REPORTED_INTENT")
        speculative = next(c for c in self.claims("Analysts believe the strike may have been intended to deter further attacks.") if c.type == "INTENT")
        self.assertEqual(speculative.intent_label, "SPECULATION")
        self.assertEqual(speculative.epistemic_status, "POSSIBLE")
        self.assertTrue(any(c.type == "RESPONSE" for c in self.claims("Israel responded with airstrikes.")))
        self.assertTrue(any(c.type == "CONSEQUENCE" for c in self.claims("The strike damaged a military facility.")))
        self.assertTrue(any(c.type == "STATUS" for c in self.claims("Negotiations remain ongoing.")))

    def test_time_precision_and_source_spans(self):
        title = "Iran launched missiles on Tuesday morning."
        excerpt = "A further strike occurred on 2026-09-15."
        claims = extract_document_claims(title, excerpt)
        time_claims = [c for c in claims if c.type == "TIME"]
        self.assertEqual(time_claims[0].normalized["original"], "Tuesday morning")
        self.assertIsNone(time_claims[0].normalized["normalized"])
        self.assertEqual(time_claims[1].normalized["normalized"], "2026-09-15")
        clock = next(c for c in self.claims("The launch happened at 14:30 UTC.") if c.type == "TIME")
        self.assertEqual((clock.normalized["normalized"], clock.normalized["precision"]), ("14:30UTC", "MINUTE"))
        for c in claims:
            for span in c.spans:
                source = title if span.text_field == "TITLE" else excerpt
                self.assertEqual(source[span.character_start:span.character_end], span.source_text)

    def test_repeat_claims_collapse_but_paraphrases_remain_conservative(self):
        claims = self.claims("Iran launched missiles. Iran launched missiles.")
        occurrences = [c for c in claims if c.type == "OCCURRENCE"]
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(len(occurrences[0].spans), 2)
        paraphrases = self.claims("Iran launched missiles. Iran fired a missile barrage.")
        self.assertGreaterEqual(len([c for c in paraphrases if c.type == "OCCURRENCE"]), 2)

    def test_passive_consequence_does_not_assign_object_as_actor_and_multiple_actions_survive(self):
        passive = next(c for c in self.claims("Ballistic missiles were launched toward Israel.") if c.type == "OCCURRENCE")
        self.assertNotIn("actor", passive.normalized)
        self.assertEqual(passive.normalized.get("object"), "Ballistic missile")
        mixed = self.claims("Iran launched missiles, and Israel responded with airstrikes.")
        self.assertIn("RESPONSE", {c.type for c in mixed})

    def test_empty_malformed_and_long_text(self):
        self.assertEqual(self.claims(""), [])
        self.assertEqual(self.claims("\x00\ud800 Iran launched missiles.")[0].spans[0].source_text, "\x00\ud800 Iran launched missiles.")
        self.assertLessEqual(len(self.claims("Iran launched missiles. " * 3000)), 1)


if __name__ == "__main__":
    unittest.main()
