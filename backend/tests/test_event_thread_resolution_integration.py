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
    refresh_thread_profile,
    resolve_incident_to_thread,
)


class EventThreadResolutionDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def _ambiguous_document_context(self, conn, *, multi_occurrence: bool):
        token = str(uuid.uuid4())
        source = await (await conn.execute(
            "INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ("Feature 4 ambiguity " + token,)
        )).fetchone()
        thread = await (await conn.execute(
            "INSERT INTO event_threads(title) VALUES(%s) RETURNING id", ("Ambiguous incident " + token,)
        )).fetchone()
        incident = await (await conn.execute(
            "INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id",
            (thread["id"], "Ambiguous incident " + token),
        )).fetchone()
        document = await (await conn.execute(
            "INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) "
            "VALUES(%s,%s,%s,%s,%s) RETURNING id",
            (source["id"], f"https://example.invalid/ambiguous/{token}", "One unresolved report", token, incident["id"]),
        )).fetchone()
        limitation = ("Multiple distinct occurrence predicates were detected; the article-level incident model cannot safely split them, so this document is held for review."
                     if multi_occurrence else
                     "Article-level single-incident assignment; multi-occurrence decomposition is not available in the current document schema.")
        await conn.execute(
            "INSERT INTO document_incident_resolutions(document_id,incident_id,state,resolution_method,match_strength,limitation) "
            "VALUES(%s,%s,'AMBIGUOUS','TEST','INSUFFICIENT',%s)",
            (document["id"], incident["id"], limitation),
        )
        if multi_occurrence:
            from psycopg.types.json import Jsonb
            await conn.execute(
                "INSERT INTO incident_fingerprints(incident_id,source_metadata) VALUES(%s,%s)",
                (incident["id"], Jsonb({"multi_occurrence_possible": True})),
            )
        return incident["id"]

    @unittest.skipUnless(os.getenv("EVENT_THREAD_TEST_DATABASE_URL"), "set EVENT_THREAD_TEST_DATABASE_URL for PostgreSQL acceptance tests")
    async def test_feature4_ambiguous_single_occurrence_does_not_block_thread_resolution(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVENT_THREAD_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                incident_id = await self._ambiguous_document_context(conn, multi_occurrence=False)
                result = await resolve_incident_to_thread(conn, incident_id)
                self.assertEqual(result.state, "NEW_THREAD")
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("EVENT_THREAD_TEST_DATABASE_URL"), "set EVENT_THREAD_TEST_DATABASE_URL for PostgreSQL acceptance tests")
    async def test_explicit_multi_occurrence_document_stays_held_for_review(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVENT_THREAD_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                incident_id = await self._ambiguous_document_context(conn, multi_occurrence=True)
                result = await resolve_incident_to_thread(conn, incident_id)
                self.assertEqual(result.state, "REVIEW_REQUIRED")
                self.assertIn("multi-occurrence review", result.reason)
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("EVENT_THREAD_TEST_DATABASE_URL"), "set EVENT_THREAD_TEST_DATABASE_URL for PostgreSQL acceptance tests")
    async def test_report_publication_does_not_advance_thread_event_activity(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["EVENT_THREAD_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                source = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ("Activity source " + token,))).fetchone()
                thread = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", ("Activity thread " + token,))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,occurred_at) VALUES(%s,%s,NULL) RETURNING id", (thread["id"], "Occurrence time unknown"))).fetchone()
                await conn.execute(
                    "INSERT INTO incident_thread_contexts(incident_id,event_time_start,time_precision) VALUES(%s,%s,'DAY')",
                    (incident["id"], datetime(2027, 4, 7, tzinfo=timezone.utc)),
                )
                published = datetime(2026, 10, 2, tzinfo=timezone.utc)
                await conn.execute(
                    "INSERT INTO documents(source_id,canonical_url,title,content_hash,published_at,incident_id) "
                    "VALUES(%s,%s,'Published report',%s,%s,%s)",
                    (source["id"], f"https://example.invalid/activity/{token}", token, published, incident["id"]),
                )
                await refresh_thread_profile(conn, thread["id"])
                activity = await (await conn.execute("SELECT latest_activity_at FROM event_threads WHERE id=%s", (thread["id"],))).fetchone()
                profile = await (await conn.execute("SELECT latest_reported_at FROM event_thread_profiles WHERE event_thread_id=%s", (thread["id"],))).fetchone()
                self.assertIsNone(activity["latest_activity_at"])
                self.assertEqual(profile["latest_reported_at"], published)
            finally:
                await conn.rollback()

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
                    incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,occurred_at) VALUES(%s,%s,%s) RETURNING id", (thread["id"], f"Military strike on Natanz wave {index} {token}", base + timedelta(hours=index * 5)))).fetchone()
                    for entity_id in participants:
                        await conn.execute("INSERT INTO incident_entities(incident_id,entity_id,role) VALUES(%s,%s,'MENTIONED')", (incident["id"], entity_id))
                    await conn.execute("INSERT INTO incident_fingerprints(incident_id,primary_actor_id,action_predicate,event_time_start,time_precision) VALUES(%s,%s,%s,%s,'EXACT')", (incident["id"], participants[index % 2], "strike" if index % 2 == 0 else "launch", base + timedelta(hours=index * 5)))
                    if index:
                        claim = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) VALUES(%s,%s,'RESPONSE','REPORTED','UNVERIFIED','fixture') RETURNING id", (incident["id"], f"Iran responded in response to the Military strike on Natanz wave {index - 1} {token}."))).fetchone()
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
