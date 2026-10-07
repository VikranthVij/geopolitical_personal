"""Live API contract checks for Feature 5; fixture rows are removed after each test."""
import os
import sys
import unittest
import uuid
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None


class EventThreadResolutionApiTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("EVENT_THREAD_API_TEST_DATABASE_URL") and httpx, "requires EVENT_THREAD_API_TEST_DATABASE_URL and httpx")
    async def test_incident_thread_detail_timeline_and_relationship_routes(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVENT_THREAD_API_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            token = str(uuid.uuid4())
            thread = incident = other = None
            try:
                thread = await (await conn.execute("INSERT INTO event_threads(title,thread_status) VALUES(%s,'ONGOING') RETURNING id", ("Feature 5 API " + token,))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,occurred_at) VALUES(%s,%s,now()) RETURNING id", (thread["id"], "Feature 5 API incident " + token))).fetchone()
                other = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,occurred_at) VALUES(%s,%s,now()) RETURNING id", (thread["id"], "Feature 5 API related " + token))).fetchone()
                await conn.execute("INSERT INTO event_thread_profiles(event_thread_id,incident_count) VALUES(%s,2)", (thread["id"],))
                await conn.execute("INSERT INTO event_thread_incident_relationships(event_thread_id,from_incident_id,to_incident_id,relation,resolver_method,evidence) VALUES(%s,%s,%s,'RESPONDED_TO','TEST',%s)", (thread["id"], incident["id"], other["id"], '{"fixture":true}'))
                await conn.execute("INSERT INTO event_thread_resolution_audits(incident_id,event_thread_id,state,resolver_method,resolver_version,reason) VALUES(%s,%s,'ASSIGNED_EXISTING_THREAD','TEST','test-v1','API fixture')", (incident["id"], thread["id"]))
                await conn.commit()
                async with httpx.AsyncClient(base_url=os.getenv("EVENT_THREAD_API_BASE_URL", "http://127.0.0.1:8000"), timeout=10) as client:
                    assigned = await client.get(f"/incidents/{incident['id']}/event-thread")
                    detail = await client.get(f"/event-threads/{thread['id']}")
                    timeline = await client.get(f"/event-threads/{thread['id']}/timeline")
                    relationships = await client.get(f"/event-threads/{thread['id']}/relationships")
                for response in (assigned, detail, timeline, relationships):
                    self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(assigned.json()["assignment_state"], "ASSIGNED_EXISTING_THREAD")
                self.assertEqual(len(detail.json()["incidents"]), 2)
                self.assertEqual(len(timeline.json()), 2)
                self.assertEqual(relationships.json()[0]["relation"], "RESPONDED_TO")
            finally:
                if thread:
                    await conn.execute("DELETE FROM event_threads WHERE id=%s", (thread["id"],))
                await conn.commit()


if __name__ == "__main__":
    unittest.main()
