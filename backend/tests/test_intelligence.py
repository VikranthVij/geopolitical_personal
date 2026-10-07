import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intelligence import candidate_score, canonicalize_url, claims_incompatible, confidence_summary, content_hash, event_fingerprint


class IntelligenceRulesTest(unittest.TestCase):
    def test_urls_drop_tracking_parameters_and_normalize_host(self):
        self.assertEqual(canonicalize_url("https://www.example.com/news/item/?utm_source=x"), "https://example.com/news/item")

    def test_duplicate_content_hash_is_stable_across_whitespace(self):
        self.assertEqual(content_hash("A report", "one   two"), content_hash("a REPORT", "one two"))

    def test_fingerprint_retrieval_explains_structured_matches(self):
        a = event_fingerprint("India", "intercepts", "aircraft", "Arabian Sea", "P-8I")
        b = event_fingerprint("India", "intercepts", "aircraft", "Arabian Sea", "P-8I")
        self.assertEqual(candidate_score(a, b), (5, ["actor", "action", "target", "location", "object"]))

    def test_quantities_same_scope_conflict_and_subset_scope_does_not(self):
        conflict, reason = claims_incompatible("QUANTITATIVE", "12 ships were damaged", "QUANTITATIVE", "15 ships were damaged")
        self.assertTrue(conflict)
        self.assertIn("unresolved", reason)
        subset, _ = claims_incompatible("QUANTITATIVE", "12 ships were damaged", "QUANTITATIVE", "15 ships were damaged overall")
        self.assertFalse(subset)

    def test_confidence_remains_contested_and_separate_from_importance(self):
        level, explanation = confidence_summary(4, 1, True)
        self.assertEqual(level, "CONTESTED")
        self.assertIn("contradictory", explanation)


if __name__ == "__main__":
    unittest.main()
