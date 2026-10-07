import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claims import persist_document_claims
from app.entities import persist_document_mentions


class ClaimPersistenceIntegrationTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("CLAIM_TEST_DATABASE_URL"), "set CLAIM_TEST_DATABASE_URL to run PostgreSQL integration test")
    async def test_document_to_claims_spans_entities_and_reprocessing(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["CLAIM_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                source = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ("Claim integration " + token,))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", ("Claim integration " + token,))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id", (event["id"], "Claim integration " + token))).fetchone()
                title = "Iran launches 20 missiles toward Israel on Tuesday."
                excerpt = "Israeli officials said Iran launched 20 missiles toward Israel on Tuesday. Iran did not launch an attack."
                document = await (await conn.execute(
                    "INSERT INTO documents(source_id,canonical_url,title,content_hash,excerpt,incident_id) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                    (source["id"], "https://example.invalid/claim-test/" + token, title, "claim-test-" + token, excerpt, incident["id"]),
                )).fetchone()
                await persist_document_mentions(conn, document["id"], title, excerpt)
                legacy = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) VALUES(%s,%s,'OCCURRENCE','REPORTED','UNVERIFIED','Legacy headline report.') RETURNING id",
                    (incident["id"], title),
                )).fetchone()
                await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (legacy["id"], document["id"]))
                await persist_document_claims(conn, document["id"])
                initial = await (await conn.execute("SELECT count(*) n FROM claim_sources WHERE document_id=%s", (document["id"],))).fetchone()
                claim_rows = await (await conn.execute(
                    "SELECT c.id,c.type,c.polarity FROM claims c JOIN claim_sources cs ON cs.claim_id=c.id WHERE cs.document_id=%s AND c.extraction_method='DETERMINISTIC_RULES'",
                    (document["id"],),
                )).fetchall()
                self.assertGreaterEqual(initial["n"], 4)
                self.assertTrue(await (await conn.execute("SELECT 1 FROM claims WHERE id=%s AND extraction_method='DETERMINISTIC_RULES' AND canonical_key IS NOT NULL", (legacy["id"],))).fetchone())
                self.assertTrue(any(c["type"] == "OCCURRENCE" and c["polarity"] == "NEGATED" for c in claim_rows))
                spans = await (await conn.execute("SELECT count(*) n FROM claim_source_spans WHERE document_id=%s", (document["id"],))).fetchone()
                source_spans = await (await conn.execute("SELECT text_field,character_start,character_end,source_text FROM claim_source_spans WHERE document_id=%s", (document["id"],))).fetchall()
                for source_span in source_spans:
                    source_text = title if source_span["text_field"] == "TITLE" else excerpt
                    self.assertEqual(source_text[source_span["character_start"]:source_span["character_end"]], source_span["source_text"])
                links = await (await conn.execute("SELECT count(*) n FROM claim_entities ce JOIN claim_sources cs ON cs.claim_id=ce.claim_id WHERE cs.document_id=%s", (document["id"],))).fetchone()
                self.assertGreater(spans["n"], 0)
                self.assertGreater(links["n"], 0)
                self.assertTrue(await (await conn.execute("SELECT 1 FROM claim_entities ce JOIN claim_sources cs ON cs.claim_id=ce.claim_id WHERE cs.document_id=%s AND ce.role='ACTOR'", (document["id"],))).fetchone())
                self.assertTrue(await (await conn.execute("SELECT 1 FROM claim_entities ce JOIN claim_sources cs ON cs.claim_id=ce.claim_id WHERE cs.document_id=%s AND ce.role='TARGET'", (document["id"],))).fetchone())

                await persist_document_claims(conn, document["id"])
                final = await (await conn.execute("SELECT count(*) n FROM claim_sources WHERE document_id=%s", (document["id"],))).fetchone()
                final_spans = await (await conn.execute("SELECT count(*) n FROM claim_source_spans WHERE document_id=%s", (document["id"],))).fetchone()
                self.assertEqual(final["n"], initial["n"])
                self.assertEqual(final_spans["n"], spans["n"])
            finally:
                await conn.rollback()


if __name__ == "__main__":
    unittest.main()
