"""Rollback-only acceptance and bounded-retrieval checks for Feature 5."""
import os
import sys
import time
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.event_thread_resolution import (
    DeterministicEventThreadCandidateRetriever,
    resolve_incident_to_thread,
)


class EventThreadResolutionDatabaseTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("EVENT_THREAD_TEST_DATABASE_URL"), "set EVENT_THREAD_TEST_DATABASE_URL for PostgreSQL acceptance tests")
    async def test_five_incident_thread_relationships_false_merge_and_idempotence(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVENT_THREAD_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                israel = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') ON CONFLICT(canonical_name,type) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING id", (f"Israel {token}",))).fetchone()
                iran = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') ON CONFLICT(canonical_name,type) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING id", (f"Iran {token}",))).fetchone()
                india = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') ON CONFLICT(canonical_name,type) DO UPDATE SET canonical_name=EXCLUDED.canonical_name RETURNING id", (f"India {token}",))).fetchone()
                location = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'LOCATION') RETURNING id", (f"Theatre {token}",))).fetchone()
                participants = [israel["id"], iran["id"]]
                incidents = []
                base = datetime(2026, 10, 1, tzinfo=timezone.utc)
                for index in range(5):
                    thread = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"provisional {token} {index}",))).fetchone()
                    incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,occurred_at) VALUES(%s,%s,%s) RETURNING id", (thread["id"], f"incident {token} {index}", base + timedelta(hours=index * 5)))).fetchone()
                    for entity_id in participants:
                        await conn.execute("INSERT INTO incident_entities(incident_id,entity_id,role) VALUES(%s,%s,'MENTIONED')", (incident["id"], entity_id))
                    await conn.execute("INSERT INTO incident_fingerprints(incident_id,primary_actor_id,action_predicate,event_time_start,time_precision) VALUES(%s,%s,%s,%s,'EXACT')", (incident["id"], participants[index % 2], "strike" if index % 2 == 0 else "launch", base + timedelta(hours=index * 5)))
                    if index:
                        claim = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) VALUES(%s,%s,'RESPONSE','REPORTED','UNVERIFIED','fixture') RETURNING id", (incident["id"], "Iran retaliated in response to the previous Israeli strike."))).fetchone()
                    incidents.append((incident["id"], thread["id"]))

                results = []
                for incident_id, _ in incidents:
                    results.append(await resolve_incident_to_thread(conn, incident_id))
                self.assertEqual(results[0].state, "NEW_THREAD")
                self.assertTrue(all(r.state == "ASSIGNED_EXISTING_THREAD" for r in results[1:]))
                root_thread = results[0].event_thread_id
                assigned = await (await conn.execute("SELECT count(*) n FROM incidents WHERE id=ANY(%s::uuid[]) AND event_thread_id=%s", ([i for i, _ in incidents], root_thread))).fetchone()
                self.assertEqual(assigned["n"], 5)
                edge_count = await (await conn.execute("SELECT count(*) n FROM event_thread_incident_relationships WHERE event_thread_id=%s AND relation='RESPONDED_TO'", (root_thread,))).fetchone()
                self.assertEqual(edge_count["n"], 4)
                audit_count = await (await conn.execute("SELECT count(*) n FROM event_thread_resolution_audits WHERE incident_id=%s", (incidents[1][0],))).fetchone()
                repeated = await resolve_incident_to_thread(conn, incidents[1][0])
                after = await (await conn.execute("SELECT count(*) n FROM event_thread_resolution_audits WHERE incident_id=%s", (incidents[1][0],))).fetchone()
                self.assertEqual(repeated.event_thread_id, root_thread)
                self.assertEqual(after["n"], audit_count["n"])

                # Shared place and close time alone do not merge an unrelated incident.
                other_thread = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"separate provisional {token}",))).fetchone()
                other = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,occurred_at) VALUES(%s,%s,%s) RETURNING id", (other_thread["id"], f"unrelated {token}", base + timedelta(hours=1)))).fetchone()
                await conn.execute("INSERT INTO incident_entities(incident_id,entity_id,role) VALUES(%s,%s,'LOCATION')", (other["id"], location["id"]))
                await conn.execute("INSERT INTO incident_entities(incident_id,entity_id,role) VALUES(%s,%s,'ACTOR')", (other["id"], india["id"]))
                await conn.execute("INSERT INTO incident_fingerprints(incident_id,primary_actor_id,action_predicate,event_time_start,time_precision,location_entity_id) VALUES(%s,%s,'launch',%s,'EXACT',%s)", (other["id"], india["id"], base + timedelta(hours=1), location["id"]))
                unrelated = await resolve_incident_to_thread(conn, other["id"])
                self.assertEqual(unrelated.state, "NEW_THREAD")
                self.assertNotEqual(unrelated.event_thread_id, root_thread)
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("EVENT_THREAD_TEST_DATABASE_URL"), "set EVENT_THREAD_TEST_DATABASE_URL for PostgreSQL acceptance tests")
    async def test_candidate_retrieval_is_bounded_at_100_500_1000_profiles(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from app.event_thread_resolution import IncidentThreadContext

        async with await AsyncConnection.connect(os.environ["EVENT_THREAD_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                actor = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') RETURNING id", (f"Load actor {token}",))).fetchone()
                current = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"load current {token}",))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id", (current["id"], f"load incident {token}"))).fetchone()
                context = IncidentThreadContext(incident["id"], current["id"], "load", frozenset({actor["id"]}), frozenset({actor["id"]}), domains=frozenset({"MILITARY_SECURITY"}))
                times = []
                for size in (100, 500, 1000):
                    await conn.execute("INSERT INTO event_threads(id,title) SELECT gen_random_uuid(),%s FROM generate_series(1,%s)", (f"load candidate {token}", size))
                    await conn.execute("INSERT INTO event_thread_profiles(event_thread_id,actor_entity_ids,participant_entity_ids,context_domains) SELECT id,%s::uuid[],%s::uuid[],ARRAY['MILITARY_SECURITY']::text[] FROM event_threads WHERE title=%s", ([actor["id"]], [actor["id"]], f"load candidate {token}"))
                    started = time.perf_counter()
                    candidates = await DeterministicEventThreadCandidateRetriever().retrieve(conn, context)
                    times.append(time.perf_counter() - started)
                    self.assertLessEqual(len(candidates), 50)
                    await conn.execute("DELETE FROM event_threads WHERE title=%s", (f"load candidate {token}",))
                print(f"Feature 5 indexed candidate retrieval (100/500/1000): {[round(t, 4) for t in times]} seconds; limit=50")
            finally:
                await conn.rollback()


if __name__ == "__main__":
    unittest.main()
