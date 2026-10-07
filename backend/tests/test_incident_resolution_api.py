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


class IncidentResolutionApiTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("INCIDENT_API_TEST_DATABASE_URL") and httpx, "requires INCIDENT_API_TEST_DATABASE_URL and httpx")
    async def test_resolution_and_incident_debug_routes(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["INCIDENT_API_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            token = str(uuid.uuid4())
            source = event = incident = document = None
            try:
                source = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ("Resolution API " + token,))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", ("Resolution API " + token,))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id", (event["id"], "Iran missile occurrence"))).fetchone()
                await conn.execute("INSERT INTO incident_fingerprints(incident_id,action_predicate,source_metadata) VALUES(%s,'launch','{}')", (incident["id"],))
                document = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,'Iran launches missiles',%s,%s) RETURNING id",
                    (source["id"], f"https://example.invalid/resolution-api/{token}", token, incident["id"]))).fetchone()
                await conn.execute("INSERT INTO document_incident_resolutions(document_id,incident_id,state,resolution_method,match_strength,matched_signals) VALUES(%s,%s,'NEW_INCIDENT','DETERMINISTIC_STRUCTURED_V1','INSUFFICIENT','[{\"signal\":\"actor\",\"value\":\"Iran\"}]'::jsonb)",
                    (document["id"], incident["id"]))
                await conn.commit()
                async with httpx.AsyncClient(base_url=os.getenv("INCIDENT_API_BASE_URL", "http://127.0.0.1:8000"), timeout=10) as client:
                    resolution = await client.get(f"/documents/{document['id']}/resolution")
                    detail = await client.get(f"/incidents/{incident['id']}")
                self.assertEqual(resolution.status_code, 200, resolution.text)
                self.assertEqual(resolution.json()["state"], "NEW_INCIDENT")
                self.assertEqual(resolution.json()["fingerprint"][0]["action_predicate"], "launch")
                self.assertEqual(len(resolution.json()["documents"]), 1)
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(len(detail.json()["resolutions"]), 1)
            finally:
                if document:
                    await conn.execute("DELETE FROM documents WHERE id=%s", (document["id"],))
                if incident:
                    await conn.execute("DELETE FROM incidents WHERE id=%s", (incident["id"],))
                if event:
                    await conn.execute("DELETE FROM event_threads WHERE id=%s", (event["id"],))
                if source:
                    await conn.execute("DELETE FROM sources WHERE id=%s", (source["id"],))
                await conn.commit()


if __name__ == "__main__":
    unittest.main()
