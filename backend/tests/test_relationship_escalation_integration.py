"""Disposable DB fixtures only; every test rolls back its data."""
import os
import sys
import unittest
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.event_thread_resolution import resolve_incident_to_thread
from app.feature6 import run_feature6
from test_relationship_grounding import G20_TITLE, G20_TEXT, IRAN_TEXT


@unittest.skipUnless(os.getenv('FEATURE6_TEST_DATABASE_URL'), 'requires isolated FEATURE6_TEST_DATABASE_URL')
class RelationshipEscalationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        self.conn = await AsyncConnection.connect(os.environ['FEATURE6_TEST_DATABASE_URL'], row_factory=dict_row)
        self.token = str(uuid4())
        self.source = await (await self.conn.execute("INSERT INTO sources(name,tier) VALUES(%s,1) RETURNING id", ('Phase1 '+self.token,))).fetchone()
        self.entity = await (await self.conn.execute("INSERT INTO entities(canonical_name,type) VALUES(%s,'COUNTRY') RETURNING id", ('Fixture country '+self.token,))).fetchone()

    async def asyncTearDown(self):
        await self.conn.rollback()
        await self.conn.close()

    async def incident(self, title, text, *, kind='OCCURRENCE', epistemic='ASSERTED'):
        from psycopg.types.json import Jsonb
        c = self.conn
        t = await (await c.execute("INSERT INTO event_threads(title) VALUES(%s) RETURNING id", (title,))).fetchone()
        i = await (await c.execute("INSERT INTO incidents(event_thread_id,title,summary) VALUES(%s,%s,%s) RETURNING id", (t['id'], title, text))).fetchone()
        d = await (await c.execute("INSERT INTO documents(source_id,canonical_url,title,excerpt,content_hash,incident_id) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id", (self.source['id'], 'https://example.invalid/'+str(uuid4()), title,text,str(uuid4()),i['id']))).fetchone()
        q = await (await c.execute("INSERT INTO claims(incident_id,statement,type,epistemic_status,attribution,normalized_representation) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id", (i['id'],text,kind,epistemic,Jsonb({'speaker_text':'Fixture source'}),Jsonb({'action':'strike'})))).fetchone()
        await c.execute('INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s)', (q['id'],d['id']))
        await c.execute("INSERT INTO claim_source_spans(claim_id,document_id,text_field,character_start,character_end,source_text) VALUES(%s,%s,'EXCERPT',0,%s,%s)", (q['id'],d['id'],len(text),text))
        await c.execute("INSERT INTO incident_entities(incident_id,entity_id,role) VALUES(%s,%s,'ACTOR')", (i['id'],self.entity['id']))
        await c.execute("INSERT INTO incident_fingerprints(incident_id,primary_actor_id,action_predicate) VALUES(%s,%s,'strike')", (i['id'],self.entity['id']))
        return i['id'],t['id'],q['id'],d['id']

    async def test_grounded_edge_provenance_and_actual_escalation_idempotence(self):
        a,thread,_,_=await self.incident('Missile strike on Natanz on October 1', 'Forces launched a missile strike on Natanz on October 1.')
        await resolve_incident_to_thread(self.conn,a)
        await run_feature6(self.conn,a,thread)
        text='Forces launched a nuclear military attack affecting oil trade and diplomatic talks in response to the missile strike on Natanz on October 1.'
        b,_,claim,doc=await self.incident('Retaliatory action',text)
        result=await resolve_incident_to_thread(self.conn,b)
        self.assertEqual(result.state,'ASSIGNED_EXISTING_THREAD')
        edge=await (await self.conn.execute('SELECT * FROM event_thread_incident_relationships WHERE from_incident_id=%s',(b,))).fetchone()
        self.assertEqual(edge['to_incident_id'],a)
        self.assertEqual(edge['evidence']['source_claim_id'],str(claim))
        self.assertEqual(edge['evidence']['source_spans'][0]['document_id'],str(doc))
        self.assertEqual(edge['evidence']['source_spans'][0]['source_text'],text)
        await run_feature6(self.conn,b,thread)
        await resolve_incident_to_thread(self.conn,b)
        await run_feature6(self.conn,b,thread)
        changes=await (await self.conn.execute("SELECT * FROM material_changes WHERE event_thread_id=%s AND change_type='MILITARY_ESCALATION'",(thread,))).fetchall()
        self.assertEqual(len(changes),1)
        self.assertEqual(changes[0]['new_state']['supporting_claims'][0]['claim_id'],str(claim))
        self.assertEqual(changes[0]['new_state']['supporting_claims'][0]['source_spans'][0]['source_text'],text)
        self.assertEqual((await (await self.conn.execute('SELECT count(*) n FROM event_thread_incident_relationships WHERE from_incident_id=%s',(b,))).fetchone())['n'],1)
        confidence=await (await self.conn.execute('SELECT confidence FROM claims WHERE id=%s',(claim,))).fetchone()
        self.assertEqual(confidence['confidence'],'UNVERIFIED')

    async def test_g20_iran_no_assignment_no_edge_no_escalation_or_prior_importance_change(self):
        a,thread,_,_=await self.incident(G20_TITLE,G20_TEXT)
        await resolve_incident_to_thread(self.conn,a)
        await run_feature6(self.conn,a,thread)
        before=await (await self.conn.execute('SELECT importance FROM event_threads WHERE id=%s',(thread,))).fetchone()
        b,own,_,_=await self.incident('Iran strike planning',IRAN_TEXT,kind='INTENT',epistemic='REPORTED')
        r=await resolve_incident_to_thread(self.conn,b)
        self.assertEqual(r.state,'REVIEW_REQUIRED')
        await run_feature6(self.conn,b,own)
        after=await (await self.conn.execute('SELECT importance FROM event_threads WHERE id=%s',(thread,))).fetchone()
        self.assertEqual(before,after)
        self.assertEqual((await (await self.conn.execute('SELECT count(*) n FROM event_thread_incident_relationships WHERE from_incident_id=%s',(b,))).fetchone())['n'],0)
        self.assertEqual((await (await self.conn.execute("SELECT count(*) n FROM material_changes WHERE trigger_incident_id=%s AND change_type='MILITARY_ESCALATION'",(b,))).fetchone())['n'],0)
        audit=await (await self.conn.execute('SELECT reason,candidates_considered FROM event_thread_resolution_audits WHERE incident_id=%s',(b,))).fetchone()
        self.assertTrue(audit['candidates_considered'])

    async def test_prospective_and_denied_actions_never_emit_executed_escalation(self):
        from psycopg.types.json import Jsonb
        for text in ['Government threatened nuclear military retaliation affecting oil trade and diplomatic talks.',
                     'President is considering nuclear military action affecting oil trade and diplomatic talks.',
                     'Officials are preparing contingency plans for a nuclear attack affecting oil trade and diplomatic talks.',
                     'Country may retaliate if attacked affecting nuclear oil trade and diplomatic talks.',
                     'Government confirmed a military decision about nuclear oil trade and diplomatic talks.',
                     'Officials denied reports of a nuclear attack affecting oil trade and diplomatic talks.',
                     'Government may impose new sanctions affecting nuclear military oil trade and diplomatic talks.']:
            with self.subTest(text=text):
                i,t,_,_=await self.incident(text,text)
                await self.conn.execute("UPDATE event_threads SET importance=%s WHERE id=%s", (Jsonb({'method':'RULES_V1'}),t))
                await run_feature6(self.conn,i,t)
                await run_feature6(self.conn,i,t)
                changes=await (await self.conn.execute("SELECT count(*) n FROM material_changes WHERE event_thread_id=%s",(t,))).fetchone()
                self.assertEqual(changes['n'],0)

    async def test_specific_older_member_selected_instead_of_latest_shared_member(self):
        from app.event_thread_resolution import refresh_thread_profile
        a,thread,_,_=await self.incident('Missile strike on Natanz on October 1', 'Forces launched a missile strike on Natanz on October 1.')
        await resolve_incident_to_thread(self.conn,a)
        other,_,_,_=await self.incident('Different military occurrence on October 2','Forces deployed elsewhere on October 2.')
        await self.conn.execute('UPDATE incidents SET event_thread_id=%s WHERE id=%s',(thread,other))
        await refresh_thread_profile(self.conn,thread)
        b,_,_,_=await self.incident('Response','Iran responded in response to the missile strike on Natanz on October 1.')
        result=await resolve_incident_to_thread(self.conn,b)
        self.assertEqual(result.state,'ASSIGNED_EXISTING_THREAD')
        edge=await (await self.conn.execute('SELECT to_incident_id FROM event_thread_incident_relationships WHERE from_incident_id=%s',(b,))).fetchone()
        self.assertEqual(edge['to_incident_id'],a)

    async def test_actual_economic_change_preserves_its_own_support(self):
        from psycopg.types.json import Jsonb
        text='Government imposed new sanctions on oil shipping.'
        i,t,claim,doc=await self.incident('Economic consequence',text)
        await self.conn.execute('UPDATE event_threads SET importance=%s WHERE id=%s',(Jsonb({'method':'RULES_V1'}),t))
        await run_feature6(self.conn,i,t)
        change=await (await self.conn.execute('SELECT change_type,new_state FROM material_changes WHERE event_thread_id=%s',(t,))).fetchone()
        self.assertEqual(change['change_type'],'ECONOMIC_CONSEQUENCE')
        self.assertEqual(change['new_state']['supporting_claims'][0]['claim_id'],str(claim))
