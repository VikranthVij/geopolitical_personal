import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.entities import extract_mentions, normalize_name


class EntityExtractionTest(unittest.TestCase):
    def mentions(self, text):
        return extract_mentions(text, "")

    def test_canonical_and_country_aliases(self):
        for spelling in ("Iran", "India", "Israel", "US", "U.S.", "U.S", "USA", "United States"):
            with self.subTest(spelling=spelling):
                found = self.mentions(spelling)
                self.assertTrue(found)
        us = [m for m in extract_mentions("US, U.S., USA, United States", "")]
        self.assertEqual({m.entity_name for m in us}, {"United States"})
        self.assertEqual(len(us), 4)

    def test_country_organization_and_government_are_distinct(self):
        found = self.mentions("Iran, IRGC, Iranian government, Iranian forces")
        self.assertEqual([(m.surface, m.entity_name, m.entity_type, m.confidence) for m in found], [
            ("Iran", "Iran", "COUNTRY", "HIGH"),
            ("IRGC", "Islamic Revolutionary Guard Corps", "ORGANIZATION", "HIGH"),
            ("Iranian government", "Government of Iran", "ORGANIZATION", "HIGH"),
            ("Iranian forces", None, "ORGANIZATION", "UNRESOLVED"),
        ])

    def test_person_and_organization_are_distinct(self):
        found = self.mentions("Narendra Modi met the Indian Navy.")
        by_name = {m.entity_name: m.entity_type for m in found}
        self.assertEqual(by_name["Narendra Modi"], "PERSON")
        self.assertEqual(by_name["Indian Navy"], "ORGANIZATION")

    def test_multiple_repeated_mentions_reuse_identity(self):
        found = self.mentions("Iran said Iran would respond; Iran repeated it.")
        self.assertEqual(len(found), 3)
        self.assertEqual({m.entity_name for m in found}, {"Iran"})

    def test_realistic_multi_type_text_and_offsets(self):
        title = "Iranian forces launched ballistic missiles toward Israel"
        excerpt = "The United States deployed additional aircraft near the Strait of Hormuz. The Pentagon confirmed the move."
        found = extract_mentions(title, excerpt)
        actual = {(m.entity_name, m.entity_type) for m in found}
        self.assertIn((None, "ORGANIZATION"), actual)
        for item in (("Ballistic missile", "WEAPON_SYSTEM"), ("Israel", "COUNTRY"),
                     ("United States", "COUNTRY"), ("Aircraft", "AIRCRAFT"),
                     ("Strait of Hormuz", "LOCATION"),
                     ("United States Department of Defense", "ORGANIZATION")):
            self.assertIn(item, actual)
        for m in found:
            source = title if m.field == "TITLE" else excerpt
            self.assertEqual(source[m.start:m.end], m.surface)

    def test_ambiguous_names_are_not_forced(self):
        self.assertEqual(self.mentions("Washington")[0].confidence, "UNRESOLVED")
        self.assertIsNone(self.mentions("Washington")[0].entity_name)

    def test_unicode_punctuation_normalization_and_noise(self):
        self.assertEqual(normalize_name("  U.S. — UNITED  States! "), "u s united states")
        self.assertEqual(self.mentions("")[0:] , [])
        self.assertEqual(self.mentions("us are here"), [])
        self.assertEqual(self.mentions("The F-35 and Shahed‑136 were discussed.")[0].entity_name, "F-35")

    def test_malformed_and_long_input(self):
        text = "<b>Iran</b> " + ("ordinary text " * 5000) + " IRGC"
        found = self.mentions(text)
        self.assertEqual([m.entity_name for m in found], ["Iran", "Islamic Revolutionary Guard Corps"])
        self.assertEqual(self.mentions("\x00\ud800 Iran" )[-1].entity_name, "Iran")


if __name__ == "__main__":
    unittest.main()
