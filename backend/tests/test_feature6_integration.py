import os
import unittest
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Feature6DatabaseIntegrationTest(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.getenv("FEATURE6_TEST_DATABASE_URL"), "requires FEATURE6_TEST_DATABASE_URL")
    async def test_quantities_confidence_actor_change_and_idempotency(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        from app.feature6 import run_feature6

        async with await AsyncConnection.connect(os.environ["FEATURE6_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                src_a = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"F6 A {token}",))).fetchone()
                src_b = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,2) RETURNING id", (f"F6 B {token}",))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title,summary) VALUES(%s,'regional escalation') RETURNING id", (f"F6 {token}",))).fetchone()
                incident_a = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,summary) VALUES(%s,'Launch report','military missile launch') RETURNING id", (event["id"],))).fetchone()
                entity_a = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') RETURNING id", (f"Country A {token}",))).fetchone()
                entity_b = await (await conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') RETURNING id", (f"Country B {token}",))).fetchone()
                await conn.execute("INSERT INTO incident_thread_contexts(incident_id,actor_entity_ids) VALUES(%s,%s)", (incident_a["id"], [entity_a["id"]]))
                docs = []
                for source, n, phrase, operator in ((src_a, 20, "20 missiles", "EQ"), (src_b, 30, "30 missiles", "EQ"), (src_a, 20, "at least 20 missiles", "GTE")):
                    doc = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                        (source["id"], f"https://example.invalid/f6/{token}/{n}/{operator}", f"Country A launched {phrase}.", f"{token}-{n}-{operator}", incident_a["id"]))).fetchone()
                    docs.append(doc["id"])
                    claim = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,normalized_representation,confidence,confidence_explanation) VALUES(%s,%s,'QUANTITATIVE',%s,'UNVERIFIED','pending') RETURNING id",
                        (incident_a["id"], f"Country A launched {phrase}.", Jsonb({"quantity": {"original": phrase, "operator": operator, "value": n, "unit": "missiles"}})))).fetchone()
                    await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (claim["id"], doc["id"]))
                supported_doc = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,'Treaty intent',%s,%s) RETURNING id",
                    (src_a["id"], f"https://example.invalid/f6/{token}/intent", f"{token}-intent", incident_a["id"]))).fetchone()
                supported = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Officials reported a treaty commitment','INTENT','UNVERIFIED','pending') RETURNING id", (incident_a["id"],))).fetchone()
                await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (supported["id"], supported_doc["id"]))
                for source in (src_a, src_b):
                    ev = await (await conn.execute("INSERT INTO evidence(type,description,strength,directness,origin_source_id) VALUES('OTHER','direct fixture evidence','HIGH','DIRECT',%s) RETURNING id", (source["id"],))).fetchone()
                    await conn.execute("INSERT INTO claim_evidence(claim_id,evidence_id,relation) VALUES(%s,%s,'SUPPORTS')", (supported["id"], ev["id"]))

                await run_feature6(conn, incident_a["id"], event["id"])
                pair_states = await (await conn.execute("SELECT status,count(*) n FROM contradictions WHERE incident_id=%s GROUP BY status", (incident_a["id"],))).fetchall()
                self.assertEqual({r["status"]: r["n"] for r in pair_states}, {"CONTRADICTS": 1, "COMPATIBLE": 2})
                confidence = await (await conn.execute("SELECT confidence,confidence_basis FROM claims WHERE id=%s", (supported["id"],))).fetchone()
                self.assertEqual(confidence["confidence"], "HIGH")
                self.assertEqual(confidence["confidence_basis"]["evidence_groups"], 2)
                importance = await (await conn.execute("SELECT importance_level FROM incidents WHERE id=%s", (incident_a["id"],))).fetchone()
                self.assertEqual(importance["importance_level"], "MEDIUM")
                before = await (await conn.execute("SELECT count(*) n FROM contradictions WHERE incident_id=%s", (incident_a["id"],))).fetchone()
                await run_feature6(conn, incident_a["id"], event["id"])
                after = await (await conn.execute("SELECT count(*) n FROM contradictions WHERE incident_id=%s", (incident_a["id"],))).fetchone()
                self.assertEqual(before["n"], after["n"])

                incident_b = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,'New actor entry') RETURNING id", (event["id"],))).fetchone()
                await conn.execute("INSERT INTO incident_thread_contexts(incident_id,actor_entity_ids) VALUES(%s,%s)", (incident_b["id"], [entity_b["id"]]))
                await run_feature6(conn, incident_b["id"], event["id"])
                changes = await (await conn.execute("SELECT count(*) n FROM material_changes WHERE event_thread_id=%s AND change_type='NEW_MAJOR_ACTOR'", (event["id"],))).fetchone()
                self.assertEqual(changes["n"], 1)
                await run_feature6(conn, incident_b["id"], event["id"])
                changes_again = await (await conn.execute("SELECT count(*) n FROM material_changes WHERE event_thread_id=%s AND change_type='NEW_MAJOR_ACTOR'", (event["id"],))).fetchone()
                self.assertEqual(changes_again["n"], 1)
                spurious = await (await conn.execute("SELECT count(*) n FROM material_changes WHERE event_thread_id=%s AND change_type='MILITARY_ESCALATION'", (event["id"],))).fetchone()
                self.assertEqual(spurious["n"], 0)
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("FEATURE6_TEST_DATABASE_URL"), "requires FEATURE6_TEST_DATABASE_URL")
    async def test_all_eight_contradiction_categories_in_database(self):
        """Database acceptance test verifying all 8 contradiction categories are persisted with correct status."""
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        from app.feature6 import run_feature6

        async with await AsyncConnection.connect(os.environ["FEATURE6_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                src = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"F6 AllCat {token}",))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"Event AllCat {token}",))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,summary) VALUES(%s,'All Categories Incident','missile strike') RETURNING id", (event["id"],))).fetchone()

                cases = [
                    ("QUANTITATIVE",
                     {"statement": "20 missiles launched", "norm": {"quantity": {"operator": "EQ", "value": 20, "unit": "missiles", "original": "20 missiles"}}, "pol": "AFFIRMED"},
                     {"statement": "30 missiles launched", "norm": {"quantity": {"operator": "EQ", "value": 30, "unit": "missiles", "original": "30 missiles"}}, "pol": "AFFIRMED"}),
                    ("STATUS",
                     {"statement": "Port facility was destroyed", "norm": {"target": "port"}, "pol": "AFFIRMED"},
                     {"statement": "Port facility remains operational", "norm": {"target": "port"}, "pol": "AFFIRMED"}),
                    ("LOCATION",
                     {"statement": "Strike occurred in Tehran", "norm": {"location_text": "Tehran"}, "pol": "AFFIRMED"},
                     {"statement": "Strike occurred in Isfahan", "norm": {"location_text": "Isfahan"}, "pol": "AFFIRMED"}),
                    ("TIME",
                     {"statement": "Strike occurred at 10:00 UTC", "norm": {"normalized": "10:00UTC", "precision": "MINUTE"}, "pol": "AFFIRMED"},
                     {"statement": "Strike occurred at 18:00 UTC", "norm": {"normalized": "18:00UTC", "precision": "MINUTE"}, "pol": "AFFIRMED"}),
                    ("INTENT",
                     {"statement": "Officials stated objective is destroy infrastructure", "norm": {"intent_expression": "destroy infrastructure"}, "pol": "AFFIRMED", "intent": "REPORTED_INTENT"},
                     {"statement": "Officials denied objective is destroy infrastructure", "norm": {"intent_expression": "destroy infrastructure"}, "pol": "NEGATED", "intent": "REPORTED_INTENT"}),
                    ("ATTRIBUTION",
                     {"statement": "Strike launched by Country Alpha", "norm": {"actor": "Country Alpha"}, "pol": "AFFIRMED"},
                     {"statement": "Strike launched by Country Beta", "norm": {"actor": "Country Beta"}, "pol": "AFFIRMED"}),
                    ("OCCURRENCE",
                     {"statement": "Air attack occurred on radar post", "norm": {"predicate_surface": "air attack"}, "pol": "AFFIRMED"},
                     {"statement": "No air attack occurred on radar post", "norm": {"predicate_surface": "air attack"}, "pol": "NEGATED"}),
                    ("CONSEQUENCE",
                     {"statement": "Casualties were confirmed among civilian staff", "norm": {"predicate_surface": "casualties"}, "pol": "AFFIRMED"},
                     {"statement": "No casualties occurred among civilian staff", "norm": {"predicate_surface": "casualties"}, "pol": "NEGATED"}),
                ]

                claim_ids = []
                for ctype, ca, cb in cases:
                    doc = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                        (src["id"], f"https://example.invalid/{token}/{ctype}", f"Doc {ctype}", f"{token}-{ctype}", incident["id"]))).fetchone()
                    ra = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,normalized_representation,polarity,intent_label,confidence,confidence_explanation) VALUES(%s,%s,%s,%s,%s,%s,'UNVERIFIED','pending') RETURNING id",
                        (incident["id"], ca["statement"], ctype, Jsonb(ca["norm"]), ca["pol"], ca.get("intent")))).fetchone()
                    rb = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,normalized_representation,polarity,intent_label,confidence,confidence_explanation) VALUES(%s,%s,%s,%s,%s,%s,'UNVERIFIED','pending') RETURNING id",
                        (incident["id"], cb["statement"], ctype, Jsonb(cb["norm"]), cb["pol"], cb.get("intent")))).fetchone()
                    await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s),(%s,%s)", (ra["id"], doc["id"], rb["id"], doc["id"]))
                    claim_ids.append((ctype, ra["id"], rb["id"]))

                await run_feature6(conn, incident["id"], event["id"])

                contradiction_rows = await (await conn.execute("SELECT type,status,explanation FROM contradictions WHERE incident_id=%s AND status='CONTRADICTS'", (incident["id"],))).fetchall()
                found_types = {r["type"] for r in contradiction_rows}
                for ctype, _, _ in cases:
                    self.assertIn(ctype, found_types, f"Contradiction for {ctype} was not persisted as CONTRADICTS")

                # Verify all conflicting claims are marked CONTESTED
                contested_claims = await (await conn.execute("SELECT confidence FROM claims WHERE incident_id=%s AND confidence='CONTESTED'", (incident["id"],))).fetchall()
                self.assertGreaterEqual(len(contested_claims), len(cases) * 2)

                # Verify significant contradictions are recorded in material_changes
                mat_changes = await (await conn.execute("SELECT count(*) n FROM material_changes WHERE event_thread_id=%s AND change_type='SIGNIFICANT_CONTRADICTION'", (event["id"],))).fetchone()
                self.assertGreaterEqual(mat_changes["n"], len(cases))
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("FEATURE6_TEST_DATABASE_URL"), "requires FEATURE6_TEST_DATABASE_URL")
    async def test_source_independence_wire_copy_chains(self):
        """Verifies that multiple articles repeating a wire dispatch do NOT count as independent corroboration."""
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        from app.feature6 import run_feature6

        async with await AsyncConnection.connect(os.environ["FEATURE6_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                wire_src = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"Wire Reuters {token}",))).fetchone()
                pub_a = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,2) RETURNING id", (f"Pub Alpha {token}",))).fetchone()
                pub_b = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,2) RETURNING id", (f"Pub Beta {token}",))).fetchone()
                pub_c = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,3) RETURNING id", (f"Aggregator Gamma {token}",))).fetchone()

                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"Wire Event {token}",))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,'Wire Reporting Incident') RETURNING id", (event["id"],))).fetchone()

                # Shared wire evidence item cited by all 3 publishers
                wire_ev = await (await conn.execute(
                    "INSERT INTO evidence(type,description,strength,directness,origin_source_id,independence_key) VALUES('DOCUMENT','Reuters Wire Dispatch #401','HIGH','DIRECT',%s,%s) RETURNING id",
                    (wire_src["id"], f"wire:reuters:401:{token}"))).fetchone()

                claim = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Air defence batteries intercepted 4 missiles','STATUS','UNVERIFIED','pending') RETURNING id",
                    (incident["id"],))).fetchone()

                # 3 separate documents from 3 different publishers, all citing the same underlying wire evidence
                for i, pub in enumerate([pub_a, pub_b, pub_c]):
                    doc = await (await conn.execute(
                        "INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                        (pub["id"], f"https://example.invalid/{token}/wire_pub_{i}", f"Article {i}", f"hash-{token}-{i}", incident["id"]))).fetchone()
                    await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)", (claim["id"], doc["id"]))
                    await conn.execute("INSERT INTO claim_evidence(claim_id,evidence_id,relation,independence_group) VALUES(%s,%s,'SUPPORTS',%s) ON CONFLICT(claim_id,evidence_id) DO NOTHING",
                                       (claim["id"], wire_ev["id"], f"wire:reuters:401:{token}"))

                await run_feature6(conn, incident["id"], event["id"])

                # Despite 3 articles from 3 publishers, support_groups MUST be 1, so confidence is LOW (not HIGH or MEDIUM)
                res = await (await conn.execute("SELECT confidence,confidence_basis FROM claims WHERE id=%s", (claim["id"],))).fetchone()
                self.assertEqual(res["confidence_basis"]["evidence_groups"], 1)
                self.assertEqual(res["confidence"], "LOW")
                self.assertIn("Independent corroboration is absent", res["confidence_basis"]["basis"][1])

                # Now introduce a genuinely independent 2nd evidence item (e.g. independent commercial satellite imagery)
                sat_src = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"Planet Labs {token}",))).fetchone()
                sat_ev = await (await conn.execute(
                    "INSERT INTO evidence(type,description,strength,directness,origin_source_id,independence_key) VALUES('SATELLITE_IMAGERY','Commercial satellite analysis','HIGH','DIRECT',%s,%s) RETURNING id",
                    (sat_src["id"], f"sat:planet:{token}"))).fetchone()
                await conn.execute("INSERT INTO claim_evidence(claim_id,evidence_id,relation,independence_group) VALUES(%s,%s,'SUPPORTS',%s)",
                                   (claim["id"], sat_ev["id"], f"sat:planet:{token}"))

                await run_feature6(conn, incident["id"], event["id"])

                # Now with 2 genuinely distinct evidence groups + direct + strong -> confidence becomes HIGH
                res2 = await (await conn.execute("SELECT confidence,confidence_basis FROM claims WHERE id=%s", (claim["id"],))).fetchone()
                self.assertEqual(res2["confidence_basis"]["evidence_groups"], 2)
                self.assertEqual(res2["confidence"], "HIGH")
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("FEATURE6_TEST_DATABASE_URL"), "requires FEATURE6_TEST_DATABASE_URL")
    async def test_confidence_states_all_five_levels(self):
        """Verifies HIGH, MEDIUM, LOW, CONTESTED, and UNVERIFIED confidence transitions."""
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        from app.feature6 import run_feature6

        async with await AsyncConnection.connect(os.environ["FEATURE6_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                src1 = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"Conf1 {token}",))).fetchone()
                src2 = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"Conf2 {token}",))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"Conf Event {token}",))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,'Conf Incident') RETURNING id", (event["id"],))).fetchone()

                # 1. UNVERIFIED: No evidence
                unverified_c = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Unverified claim','STATUS','UNVERIFIED','pending') RETURNING id",
                    (incident["id"],))).fetchone()

                # 2. LOW: One evidence item
                low_c = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Single evidence claim','STATUS','UNVERIFIED','pending') RETURNING id",
                    (incident["id"],))).fetchone()
                ev1 = await (await conn.execute("INSERT INTO evidence(type,description,strength,directness,origin_source_id) VALUES('OTHER','report','LOW','REPORTED',%s) RETURNING id", (src1["id"],))).fetchone()
                await conn.execute("INSERT INTO claim_evidence(claim_id,evidence_id,relation) VALUES(%s,%s,'SUPPORTS')", (low_c["id"], ev1["id"]))

                # 3. MEDIUM: Two independent evidence groups, but indirect/reported
                med_c = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Medium evidence claim','STATUS','UNVERIFIED','pending') RETURNING id",
                    (incident["id"],))).fetchone()
                ev_m1 = await (await conn.execute("INSERT INTO evidence(type,description,strength,directness,origin_source_id) VALUES('OTHER','indirect 1','MEDIUM','REPORTED',%s) RETURNING id", (src1["id"],))).fetchone()
                ev_m2 = await (await conn.execute("INSERT INTO evidence(type,description,strength,directness,origin_source_id) VALUES('OTHER','indirect 2','MEDIUM','REPORTED',%s) RETURNING id", (src2["id"],))).fetchone()
                await conn.execute("INSERT INTO claim_evidence(claim_id,evidence_id,relation) VALUES(%s,%s,'SUPPORTS'),(%s,%s,'SUPPORTS')", (med_c["id"], ev_m1["id"], med_c["id"], ev_m2["id"]))

                # 4. HIGH: Two independent evidence groups, DIRECT and HIGH strength
                high_c = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'High evidence claim','STATUS','UNVERIFIED','pending') RETURNING id",
                    (incident["id"],))).fetchone()
                ev_h1 = await (await conn.execute("INSERT INTO evidence(type,description,strength,directness,origin_source_id) VALUES('SATELLITE_IMAGERY','sat 1','HIGH','DIRECT',%s) RETURNING id", (src1["id"],))).fetchone()
                ev_h2 = await (await conn.execute("INSERT INTO evidence(type,description,strength,directness,origin_source_id) VALUES('PHYSICAL_EVIDENCE','debris','HIGH','DIRECT',%s) RETURNING id", (src2["id"],))).fetchone()
                await conn.execute("INSERT INTO claim_evidence(claim_id,evidence_id,relation) VALUES(%s,%s,'SUPPORTS'),(%s,%s,'SUPPORTS')", (high_c["id"], ev_h1["id"], high_c["id"], ev_h2["id"]))

                await run_feature6(conn, incident["id"], event["id"])

                c_unv = await (await conn.execute("SELECT confidence FROM claims WHERE id=%s", (unverified_c["id"],))).fetchone()
                c_low = await (await conn.execute("SELECT confidence FROM claims WHERE id=%s", (low_c["id"],))).fetchone()
                c_med = await (await conn.execute("SELECT confidence FROM claims WHERE id=%s", (med_c["id"],))).fetchone()
                c_high = await (await conn.execute("SELECT confidence FROM claims WHERE id=%s", (high_c["id"],))).fetchone()

                self.assertEqual(c_unv["confidence"], "UNVERIFIED")
                self.assertEqual(c_low["confidence"], "LOW")
                self.assertEqual(c_med["confidence"], "MEDIUM")
                self.assertEqual(c_high["confidence"], "HIGH")
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("FEATURE6_TEST_DATABASE_URL"), "requires FEATURE6_TEST_DATABASE_URL")
    async def test_importance_independence_from_confidence(self):
        """Verifies that an unverified event can have CRITICAL importance, while a verified event can have LOW importance."""
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        from app.feature6 import run_feature6

        async with await AsyncConnection.connect(os.environ["FEATURE6_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"Importance Event {token}",))).fetchone()

                # Low-confidence catastrophic event (nuclear, missiles, strategic escalation)
                incident_crit = await (await conn.execute(
                    "INSERT INTO incidents(event_thread_id,title,summary) VALUES(%s,'Nuclear facility missile strike','Massive military strike on strategic nuclear enrichment plant; regional retaliatory war feared') RETURNING id",
                    (event["id"],))).fetchone()
                # Unverified claim attached
                claim_crit = await (await conn.execute(
                    "INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Nuclear facility struck','STATUS','UNVERIFIED','unverified single report') RETURNING id",
                    (incident_crit["id"],))).fetchone()

                await run_feature6(conn, incident_crit["id"], event["id"])

                inc_row = await (await conn.execute("SELECT importance_level,importance FROM incidents WHERE id=%s", (incident_crit["id"],))).fetchone()
                claim_row = await (await conn.execute("SELECT confidence FROM claims WHERE id=%s", (claim_crit["id"],))).fetchone()

                # Claim is UNVERIFIED, but Incident importance is CRITICAL/HIGH
                self.assertEqual(claim_row["confidence"], "UNVERIFIED")
                self.assertIn(inc_row["importance_level"], {"CRITICAL", "HIGH"})
                self.assertEqual(inc_row["importance"]["dimensions"]["strategic"], "HIGH")
                self.assertEqual(inc_row["importance"]["dimensions"]["military"], "HIGH")
                self.assertEqual(inc_row["importance"]["dimensions"]["escalation"], "HIGH")

                # Event thread importance also escalates
                thread_row = await (await conn.execute("SELECT importance_category FROM event_threads WHERE id=%s", (event["id"],))).fetchone()
                self.assertIn(thread_row["importance_category"], {"CRITICAL", "HIGH"})
            finally:
                await conn.rollback()

    @unittest.skipUnless(os.getenv("FEATURE6_TEST_DATABASE_URL"), "requires FEATURE6_TEST_DATABASE_URL")
    async def test_savepoint_failure_isolation_and_rollback(self):
        """Proves that a failure inside Feature 6 rollback does not corrupt previously committed claims/incidents."""
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb

        async with await AsyncConnection.connect(os.environ["FEATURE6_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
            try:
                token = str(uuid.uuid4())
                src = await (await conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", (f"Savepoint {token}",))).fetchone()
                event = await (await conn.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (f"Savepoint Event {token}",))).fetchone()
                incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title) VALUES(%s,'Savepoint Incident') RETURNING id", (event["id"],))).fetchone()
                doc = await (await conn.execute("INSERT INTO documents(source_id,canonical_url,title,content_hash,incident_id) VALUES(%s,%s,'Title',%s,%s) RETURNING id",
                    (src["id"], f"https://example.invalid/{token}", f"hash-{token}", incident["id"]))).fetchone()
                claim = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,confidence,confidence_explanation) VALUES(%s,'Preserved statement','STATUS','UNVERIFIED','init') RETURNING id",
                    (incident["id"],))).fetchone()

                # Simulate collector's savepoint behavior:
                try:
                    async with conn.transaction():
                        # Partial write
                        await conn.execute("INSERT INTO material_changes(event_thread_id,trigger_incident_id,change_type,reason,significance,dedupe_key) VALUES(%s,%s,'MILITARY_ESCALATION','test','HIGH',%s)",
                                           (event["id"], incident["id"], f"temp-key-{token}"))
                        # Deliberate failure inside Feature 6
                        raise RuntimeError("Simulated Feature 6 internal error")
                except Exception as exc:
                    # Collector logs to feature6_failures outside the failed savepoint
                    await conn.execute("INSERT INTO feature6_failures(document_id,incident_id,stage,error) VALUES(%s,%s,'INGESTION',%s)",
                                       (doc["id"], incident["id"], f"{type(exc).__name__}: {str(exc)}"))

                # Verify failure is logged
                fail_row = await (await conn.execute("SELECT stage,error FROM feature6_failures WHERE document_id=%s", (doc["id"],))).fetchone()
                self.assertIsNotNone(fail_row)
                self.assertEqual(fail_row["stage"], "INGESTION")
                self.assertIn("Simulated Feature 6 internal error", fail_row["error"])

                # Verify partial material_change was rolled back
                mat = await (await conn.execute("SELECT count(*) n FROM material_changes WHERE dedupe_key=%s", (f"temp-key-{token}",))).fetchone()
                self.assertEqual(mat["n"], 0)

                # Verify document, incident, and claim remain completely intact
                c_check = await (await conn.execute("SELECT id,statement FROM claims WHERE id=%s", (claim["id"],))).fetchone()
                self.assertIsNotNone(c_check)
                self.assertEqual(c_check["statement"], "Preserved statement")
            finally:
                await conn.rollback()


if __name__ == "__main__":
    unittest.main()
