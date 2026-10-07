"""Rollback-only PostgreSQL test covering multi-document assignment and lineage."""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claims import persist_document_claims
from app.entities import persist_document_mentions
from app.evidence import persist_document_evidence
from app.incident_resolution import resolve_document


class IncidentResolutionDatabaseTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("INCIDENT_TEST_DATABASE_URL"), "set INCIDENT_TEST_DATABASE_URL for PostgreSQL integration")
    async def test_reports_group_claims_stay_document_specific_and_repeat_is_idempotent(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["INCIDENT_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                source_ids = []
                for name in ("Reuters", "AP", "BBC"):
                    source = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"{name} resolution {token}",))).fetchone()
                    source_ids.append(source["id"])
                fixtures = [
                    ("Reuters", "Iran launched more than 20 ballistic missiles toward Israel at 18:30 UTC on 2026-10-07.", "Satellite image ID IMG-2026-A77 shows damage near Natanz."),
                    ("AP", "Iran fired around 25 ballistic missiles toward Israel at 18:32 UTC on 2026-10-07.", "Satellite image ID IMG-2026-A77 shows damage near Natanz."),
                    ("BBC", "Iran launched a second missile attack toward Israel at 03:00 UTC on 2026-10-08.", "Satellite image ID IMG-2026-A78 shows damage near Natanz."),
                ]
                records = []
                for idx, (publisher, title, excerpt) in enumerate(fixtures):
                    event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"resolution fixture {token}",))).fetchone()
                    incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id", (event["id"], title))).fetchone()
                    document = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,excerpt,incident_id,published_at) VALUES(%s,%s,%s,%s,%s,%s,now()) RETURNING id",
                        (source_ids[idx], f"https://example.invalid/{token}/{idx}", title, f"{token}-{idx}", excerpt, incident["id"]))).fetchone()
                    await persist_document_mentions(conn, document["id"], title, excerpt)
                    legacy = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) VALUES(%s,%s,'OCCURRENCE','REPORTED','UNVERIFIED','Reported in fixture.') RETURNING id", (incident["id"], title))).fetchone()
                    await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (legacy["id"], document["id"]))
                    await persist_document_claims(conn, document["id"])
                    await persist_document_evidence(conn, document["id"])
                    records.append((document["id"], incident["id"], event["id"]))
                results = []
                for doc_id, incident_id, event_id in records:
                    results.append(await resolve_document(conn, doc_id, incident_id, event_id))
                self.assertEqual(results[0].incident_id, results[1].incident_id)
                self.assertNotEqual(results[0].incident_id, results[2].incident_id)
                self.assertEqual(results[1].state, "MATCHED_EXISTING")
                before = await (await conn.execute("SELECT count(*) n FROM document_incident_resolutions WHERE document_id=ANY(%s)", ([r[0] for r in records],))).fetchone()
                repeated = await resolve_document(conn, records[1][0], records[1][1], records[1][2])
                after = await (await conn.execute("SELECT count(*) n FROM document_incident_resolutions WHERE document_id=ANY(%s)", ([r[0] for r in records],))).fetchone()
                self.assertEqual(repeated.incident_id, results[1].incident_id)
                self.assertEqual(before["n"], after["n"])
                claims = await (await conn.execute("SELECT cs.document_id,count(*) claim_count,count(DISTINCT c.id) claim_ids FROM claim_sources cs JOIN claims c ON c.id=cs.claim_id WHERE cs.document_id=ANY(%s) GROUP BY cs.document_id", ([r[0] for r in records],))).fetchall()
                self.assertEqual(len(claims), 3)
                self.assertTrue(all(r["claim_count"] > 1 for r in claims))
                separate_claims = await (await conn.execute("SELECT count(DISTINCT c.id) n FROM claims c JOIN claim_sources cs ON cs.claim_id=c.id WHERE cs.document_id=ANY(%s) AND c.extraction_method='DETERMINISTIC_RULES'", ([records[0][0], records[1][0]],))).fetchone()
                self.assertGreater(separate_claims["n"], 1)
                shared = await (await conn.execute("SELECT count(DISTINCT ed.document_id) documents,count(DISTINCT e.id) evidence FROM evidence_documents ed JOIN evidence e ON e.id=ed.evidence_id WHERE ed.document_id=ANY(%s) AND e.identity_key LIKE %s", ([records[0][0], records[1][0]], "%img-2026-a77%"))).fetchone()
                self.assertEqual(shared["documents"], 2)
                self.assertEqual(shared["evidence"], 1)
                assigned = await (await conn.execute("SELECT count(DISTINCT incident_id) n FROM documents WHERE id=ANY(%s)", ([r[0] for r in records],))).fetchone()
                self.assertEqual(assigned["n"], 2)
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("INCIDENT_TEST_DATABASE_URL"), "set INCIDENT_TEST_DATABASE_URL for PostgreSQL integration")
    async def test_multi_occurrence_article_is_held_for_review(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        async with await AsyncConnection.connect(os.environ["INCIDENT_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                source = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ("Multi occurrence " + token,))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", ("Multi occurrence " + token,))).fetchone()
                title = "Iran launched missiles toward Israel. Israel struck Natanz."
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,%s) RETURNING id", (event["id"], title))).fetchone()
                doc = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (source["id"], f"https://example.invalid/multi/{token}", title, token, incident["id"]))).fetchone()
                await persist_document_mentions(conn, doc["id"], title, "")
                claim = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) VALUES(%s,%s,'OCCURRENCE','REPORTED','UNVERIFIED','fixture') RETURNING id", (incident["id"], title))).fetchone()
                await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (claim["id"], doc["id"]))
                await persist_document_claims(conn, doc["id"])
                await persist_document_evidence(conn, doc["id"])
                result = await resolve_document(conn, doc["id"], incident["id"], event["id"])
                self.assertEqual(result.state, "REVIEW_REQUIRED")
                row = await (await conn.execute("SELECT limitation FROM document_incident_resolutions WHERE document_id=%s", (doc["id"],))).fetchone()
                self.assertIn("Multiple distinct occurrence predicates", row["limitation"])
            finally:
                await conn.rollback()


if __name__ == "__main__":
    unittest.main()
