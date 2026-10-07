import os
import sys
import unittest
import uuid
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evidence import persist_document_evidence


class EvidenceApiIntegrationTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("EVIDENCE_TEST_DATABASE_URL") and httpx, "requires EVIDENCE_TEST_DATABASE_URL and httpx")
    async def test_document_evidence_debug_response(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVIDENCE_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            token = str(uuid.uuid4())
            source = event = incident = document = None
            try:
                source = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ("Evidence API " + token,))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", ("Evidence API " + token,))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id", (event["id"], "Evidence API " + token))).fetchone()
                excerpt = "Satellite imagery reportedly shows damage at Natanz."
                document = await (await conn.execute(
                    "INSERT INTO documents(source_id,canonical_url,title,content_hash,excerpt,incident_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                    (source["id"], f"https://example.invalid/evidence-api/{token}", "Natanz assessment", token, excerpt, incident["id"]),
                )).fetchone()
                claim = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) "
                    "VALUES(%s,%s,'OCCURRENCE','REPORTED','UNVERIFIED','Not assessed.') RETURNING id",
                    (incident["id"], excerpt),
                )).fetchone()
                await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (claim["id"], document["id"]))
                await conn.execute(
                    "INSERT INTO claim_source_spans(claim_id,document_id,text_field,character_start,character_end,source_text) "
                    "VALUES(%s,%s,'EXCERPT',0,%s,%s)", (claim["id"], document["id"], len(excerpt), excerpt),
                )
                await persist_document_evidence(conn, document["id"])
                await conn.commit()

                base_url = os.getenv("EVIDENCE_API_BASE_URL", "http://127.0.0.1:8000")
                async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
                    response = await client.get(f"/documents/{document['id']}/evidence")
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual(payload["document_id"], str(document["id"]))
                item = next(entry for entry in payload["evidence"] if entry["type"] == "SATELLITE_IMAGERY")
                self.assertEqual(item["source_spans"][0]["source_text"], "Satellite imagery reportedly")
                self.assertEqual(item["document_links"][0]["directness"], "REPORTED")
                self.assertEqual(item["claims"][0]["relation"], "SUPPORTS")
                self.assertIn("identity_key", item)
            finally:
                if document:
                    await conn.execute("DELETE FROM documents WHERE id=%s", (document["id"],))
                if incident:
                    await conn.execute("DELETE FROM incidents WHERE id=%s", (incident["id"],))
                if event:
                    await conn.execute("DELETE FROM event_threads WHERE id=%s", (event["id"],))
                if source:
                    await conn.execute("DELETE FROM sources WHERE id=%s", (source["id"],))
                await conn.execute("DELETE FROM evidence WHERE provenance->>'reporting_source'=%s", ("Evidence API " + token,))
                await conn.commit()


if __name__ == "__main__":
    unittest.main()
