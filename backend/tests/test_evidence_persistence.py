import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claims import persist_document_claims
from app.entities import persist_document_mentions
from app.evidence import persist_document_evidence


class EvidencePersistenceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("EVIDENCE_TEST_DATABASE_URL"), "set EVIDENCE_TEST_DATABASE_URL to run PostgreSQL integration test")
    async def test_shared_lineage_independence_spans_links_and_idempotency(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVIDENCE_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                docs = []
                for publisher, title, excerpt in (
                    ("Reuters", "Reuters reviews imagery", "Reuters reviewed satellite imagery ID IMG-2026-A77 that confirms damage."),
                    ("AP", "AP cites the imagery", "AP cited the same satellite imagery ID IMG-2026-A77 that confirms damage."),
                    ("BBC", "BBC reports Reuters imagery assessment", "BBC reported Reuters' assessment of satellite imagery ID IMG-2026-A77 that confirms damage."),
                    ("Reuters", "Separate imagery", "Reuters independently reviewed satellite imagery ID IMG-2026-A78 showing damage at Natanz."),
                    ("Ministry Test", "Government missile announcement", "The Iranian government released an official statement saying Iran launched 12 missiles."),
                    ("OSINT Analysis", "Open source review", "OSINT analysts identified a new deployment using geospatial analysis."),
                    ("Reuters", "Unidentified imagery A", "Satellite imagery shows damage to a facility."),
                    ("AP", "Unidentified imagery B", "Satellite imagery shows damage to a facility."),
                    ("Reuters", "Contrary tracking", "Radar data contradicts Iran launched missiles."),
                    ("AP", "Partial imagery", "Satellite imagery partially supports facility damage."),
                    ("BBC", "Unclear flight record", "Flight tracking data does not confirm aircraft were deployed."),
                ):
                    source = await (await conn.execute(
                        "INSERT INTO sources(name,tier) VALUES(%s,1) ON CONFLICT(name) DO UPDATE SET tier=EXCLUDED.tier RETURNING id", (publisher,),
                    )).fetchone()
                    event = await (await conn.execute(
                        "INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"evidence test {token}",),
                    )).fetchone()
                    incident = await (await conn.execute(
                        "INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id",
                        (event["id"], f"evidence test {token}"),
                    )).fetchone()
                    doc = await (await conn.execute(
                        "INSERT INTO documents(source_id,canonical_url,title,content_hash,excerpt,incident_id,published_at) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (source["id"], f"https://example.invalid/evidence/{token}/{len(docs)}", title,
                         f"evidence-{token}-{len(docs)}", excerpt, incident["id"], datetime.now(timezone.utc)),
                    )).fetchone()
                    await persist_document_mentions(conn, doc["id"], title, excerpt)
                    await persist_document_claims(conn, doc["id"])
                    await persist_document_evidence(conn, doc["id"])
                    docs.append(doc["id"])

                shared = await (await conn.execute(
                    "SELECT id FROM evidence WHERE identity_key='SATELLITE_IMAGERY:img-2026-a77'",
                )).fetchone()
                self.assertIsNotNone(shared)
                refs = await (await conn.execute(
                    "SELECT count(DISTINCT document_id) n FROM evidence_documents WHERE evidence_id=%s", (shared["id"],),
                )).fetchone()
                self.assertEqual(refs["n"], 3)
                citation = await (await conn.execute(
                    "SELECT referenced_document_id FROM evidence_documents WHERE evidence_id=%s AND document_id=%s AND relation='CITES'",
                    (shared["id"], docs[1]),
                )).fetchone()
                self.assertEqual(citation["referenced_document_id"], docs[0])
                separate = await (await conn.execute(
                    "SELECT id FROM evidence WHERE identity_key='SATELLITE_IMAGERY:img-2026-a78'",
                )).fetchone()
                self.assertIsNotNone(separate)
                self.assertNotEqual(shared["id"], separate["id"])
                official = await (await conn.execute(
                    "SELECT id,type,directness FROM evidence WHERE type='OFFICIAL_STATEMENT' AND extraction_method='DETERMINISTIC_RULES' "
                    "AND id IN (SELECT evidence_id FROM evidence_documents WHERE document_id=%s)", (docs[4],),
                )).fetchone()
                self.assertIsNotNone(official)
                self.assertNotEqual(official["id"], shared["id"])
                self.assertEqual(official["directness"], "DIRECT")
                official_relations = await (await conn.execute(
                    "SELECT relation FROM claim_evidence_sources WHERE evidence_id=%s AND document_id=%s",
                    (official["id"], docs[4]),
                )).fetchall()
                self.assertTrue(official_relations)
                self.assertEqual({row["relation"] for row in official_relations}, {"INCONCLUSIVE"})

                derived = await (await conn.execute(
                    "SELECT child.type child_type,parent.type parent_type,l.relation FROM evidence_lineage l "
                    "JOIN evidence child ON child.id=l.evidence_id JOIN evidence parent ON parent.id=l.related_evidence_id "
                    "WHERE l.relation='DERIVED_FROM' AND EXISTS (SELECT 1 FROM evidence_documents ed WHERE ed.evidence_id=child.id AND ed.document_id=%s)",
                    (docs[5],),
                )).fetchone()
                self.assertEqual((derived["child_type"], derived["parent_type"], derived["relation"]),
                                 ("OPEN_SOURCE_ANALYSIS", "GEOSPATIAL_DATA", "DERIVED_FROM"))
                unidentified = await (await conn.execute(
                    "SELECT DISTINCT es.evidence_id FROM evidence_source_spans es WHERE es.document_id IN (%s,%s)",
                    (docs[6], docs[7]),
                )).fetchall()
                self.assertEqual(len(unidentified), 2)
                self.assertNotEqual(unidentified[0]["evidence_id"], unidentified[1]["evidence_id"])
                stored_relations = {}
                for doc_id in docs[8:11]:
                    row = await (await conn.execute(
                        "SELECT DISTINCT relation FROM claim_evidence_sources WHERE document_id=%s", (doc_id,),
                    )).fetchall()
                    stored_relations[doc_id] = {entry["relation"] for entry in row}
                self.assertEqual(stored_relations[docs[8]], {"CONTRADICTS"})
                self.assertEqual(stored_relations[docs[9]], {"PARTIALLY_SUPPORTS"})
                self.assertEqual(stored_relations[docs[10]], {"INCONCLUSIVE"})

                span_rows = await (await conn.execute(
                    "SELECT es.document_id,es.text_field,es.character_start,es.character_end,es.source_text,d.title,d.excerpt "
                    "FROM evidence_source_spans es JOIN documents d ON d.id=es.document_id WHERE es.evidence_id=%s", (shared["id"],),
                )).fetchall()
                self.assertEqual(len(span_rows), 3)
                for row in span_rows:
                    source_text = row["title"] if row["text_field"] == "TITLE" else row["excerpt"]
                    self.assertEqual(source_text[row["character_start"]:row["character_end"]], row["source_text"])
                relations = await (await conn.execute(
                    "SELECT relation FROM claim_evidence_sources WHERE evidence_id=%s", (shared["id"],),
                )).fetchall()
                self.assertTrue(relations)
                self.assertIn("SUPPORTS", {row["relation"] for row in relations})

                before = await (await conn.execute(
                    "SELECT (SELECT count(*) FROM evidence_source_spans WHERE document_id=%s) spans, "
                    "(SELECT count(*) FROM claim_evidence_sources WHERE document_id=%s) links, "
                    "(SELECT count(*) FROM evidence_documents WHERE document_id=%s) docs",
                    (docs[0], docs[0], docs[0]),
                )).fetchone()
                await persist_document_evidence(conn, docs[0])
                after = await (await conn.execute(
                    "SELECT (SELECT count(*) FROM evidence_source_spans WHERE document_id=%s) spans, "
                    "(SELECT count(*) FROM claim_evidence_sources WHERE document_id=%s) links, "
                    "(SELECT count(*) FROM evidence_documents WHERE document_id=%s) docs",
                    (docs[0], docs[0], docs[0]),
                )).fetchone()
                self.assertEqual(before, after)
            finally:
                await conn.rollback()


if __name__ == "__main__":
    unittest.main()
