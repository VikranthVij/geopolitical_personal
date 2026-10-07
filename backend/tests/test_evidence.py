import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evidence import DeterministicEvidenceExtractor


class EvidenceExtractionTest(unittest.TestCase):
    def setUp(self):
        self.extractor = DeterministicEvidenceExtractor()

    def extract_one(self, text, evidence_type):
        return next(item for item in self.extractor.extract(text, "") if item.type == evidence_type)

    def test_fixture_covers_evidence_types_directness_and_provenance(self):
        text = (Path(__file__).parent / "fixtures" / "evidence_references.txt").read_text()
        items = self.extractor.extract(text, None)
        kinds = {item.type for item in items}
        self.assertTrue({"SATELLITE_IMAGERY", "OFFICIAL_STATEMENT", "VIDEO", "FLIGHT_TRACKING",
                         "EYEWITNESS", "OPEN_SOURCE_ANALYSIS", "GEOSPATIAL_DATA", "DOCUMENT",
                         "PHYSICAL_EVIDENCE"}.issubset(kinds))
        images = [item for item in items if item.type == "SATELLITE_IMAGERY"]
        self.assertEqual(images[0].identity_key, images[1].identity_key)
        self.assertNotEqual(images[0].identity_key, images[3].identity_key)
        self.assertEqual(images[0].directness, "REPORTED")
        self.assertEqual(images[0].external_reference, "IMG-2026-77")
        self.assertEqual(images[0].provider, None)
        direct = self.extract_one("AP independently reviewed satellite imagery showing damage.", "SATELLITE_IMAGERY")
        self.assertEqual(direct.directness, "DIRECT")
        self.assertEqual(self.extract_one("Satellite imagery shows damage.", "SATELLITE_IMAGERY").directness, "UNKNOWN")

    def test_adversarial_attribution_negation_and_relation_cues(self):
        reported = self.extract_one("Satellite imagery reportedly shows damage.", "SATELLITE_IMAGERY")
        self.assertEqual(reported.directness, "REPORTED")
        attributed = self.extract_one("According to officials, satellite imagery shows damage.", "SATELLITE_IMAGERY")
        self.assertEqual(attributed.attribution["speaker_text"], "officials")
        chain = self.extract_one("Reuters reported that officials said satellite imagery showed damage.", "SATELLITE_IMAGERY")
        self.assertEqual(chain.directness, "REPORTED")
        self.assertEqual(chain.attribution["speaker_text"], "officials")
        speculative = self.extract_one("Analysts believe satellite imagery may indicate damage.", "SATELLITE_IMAGERY")
        self.assertEqual(speculative.directness, "DERIVED")
        absent = self.extract_one("No satellite imagery has confirmed the damage.", "SATELLITE_IMAGERY")
        self.assertTrue(absent.negated)
        self.assertEqual(absent.claim_relation, "INCONCLUSIVE")
        self.assertEqual(self.extract_one("Satellite imagery partially supports the reported damage.", "SATELLITE_IMAGERY").claim_relation, "PARTIALLY_SUPPORTS")
        self.assertEqual(self.extract_one("Satellite imagery contradicts the damage claim.", "SATELLITE_IMAGERY").claim_relation, "CONTRADICTS")
        cited = self.extract_one("Reuters cited a video originally published by source X.", "VIDEO")
        self.assertEqual(cited.document_relation, "CITES")
        verified_video = self.extract_one("Video footage verified by Reuters shows damage.", "VIDEO")
        self.assertEqual(verified_video.document_relation, "REFERENCES")

    def test_spans_are_exact_for_title_excerpt_unicode_and_multiple_items(self):
        title = "Reuters reviewed Maxar satellite imagery; video footage verified by Reuters shows damage."
        excerpt = "The debris—photographed at the site—was examined. Radar data showed activity."
        items = self.extractor.extract(title, excerpt)
        for item in items:
            source = title if item.span.text_field == "TITLE" else excerpt
            self.assertEqual(source[item.span.character_start:item.span.character_end], item.span.source_text)
        self.assertEqual(len([item for item in items if item.type in {"SATELLITE_IMAGERY", "VIDEO"}]), 2)
        self.assertEqual(len([item for item in items if item.type == "RADAR_DATA"]), 1)

    def test_empty_malformed_long_and_unknown_origin(self):
        self.assertEqual(self.extractor.extract(None, ""), [])
        self.assertEqual(self.extractor.extract("\x00\ud800 Satellite imagery shows damage.", None)[0].origin_reference, None)
        long_items = self.extractor.extract("Satellite imagery shows damage. " * 2500, None)
        self.assertEqual(len(long_items), 2500)


if __name__ == "__main__":
    unittest.main()
