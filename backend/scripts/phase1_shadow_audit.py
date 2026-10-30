"""SELECT-only Phase 1 shadow audit. Emits a report payload; never applies decisions.

Run inside an existing-dependency analysis container with this source mounted read-only:
python scripts/phase1_shadow_audit.py --expected-database geopolitics
DATABASE_URL must be provided explicitly. No application lifespan/collector is started.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg.rows import dict_row
from app.claim_semantics import assertion_semantics
from app.event_thread_resolution import (build_incident_context, _relationship_cues,
    _grounded_relationships, _candidate_signals, EventThreadCandidate,
    DeterministicEventThreadCandidateRetriever, DeterministicEventThreadResolver, RESOLVER_VERSION)
from app.feature6 import _importance, _military_escalation_support

PRIMARY_THREAD = '3fd925a6-4395-489b-94dc-71d5f562635a'
PRIMARY_SOURCE = '871f0d0c-e3fd-4df1-98ed-5045b805022b'
PRIMARY_TARGET = 'addeff4c-850d-4d6d-966f-9e29f1ac1d38'
TABLES = ('documents','claims','evidence','incidents','event_threads',
    'event_thread_incident_relationships','material_changes','contradictions',
    'document_incident_resolutions','event_thread_resolution_audits','schema_migrations','collection_runs')


class SelectOnly:
    def __init__(self, connection):
        self.connection = connection
        self.queries = 0

    async def execute(self, sql, params=()):
        # Application read helpers must pass this gate as well as server read-only
        # enforcement. Fail closed on multiple statements/locks/SELECT INTO.
        if not isinstance(sql, str) or not re.match(r'^\s*SELECT\b', sql, re.I):
            raise ValueError('Shadow audit permits SELECT statements only')
        if ';' in sql or re.search(r'\bINTO\b|\bFOR\s+(?:UPDATE|SHARE)\b', sql, re.I):
            raise ValueError('Unsafe SELECT form rejected')
        self.queries += 1
        return await self.connection.execute(sql, params)


async def connect(expected):
    c = await psycopg.AsyncConnection.connect(os.environ['DATABASE_URL'],
        options='-c default_transaction_read_only=on', row_factory=dict_row)
    await c.set_isolation_level(psycopg.IsolationLevel.REPEATABLE_READ)
    q = SelectOnly(c)
    identity = await (await q.execute("SELECT current_database() database,current_user role,inet_server_addr() server,inet_server_port() port,current_setting('transaction_read_only') read_only,current_setting('transaction_isolation') isolation")).fetchone()
    if identity['database'] != expected or identity['read_only'] != 'on':
        await c.close()
        raise RuntimeError('Connection identity/read-only validation failed')
    return c, q, identity


async def snapshot(q):
    return {
        'counts': {t:(await (await q.execute('SELECT count(*) n FROM '+t)).fetchone())['n'] for t in TABLES},
        'documents': await (await q.execute('SELECT id,incident_id FROM documents ORDER BY id')).fetchall(),
        'incidents': await (await q.execute('SELECT id,event_thread_id FROM incidents ORDER BY id')).fetchall(),
        'relationships': await (await q.execute('SELECT * FROM event_thread_incident_relationships ORDER BY id')).fetchall(),
        'changes': await (await q.execute('SELECT * FROM material_changes ORDER BY id')).fetchall(),
        'primary_thread': await (await q.execute('SELECT * FROM event_threads WHERE id=%s',(PRIMARY_THREAD,))).fetchone(),
        'primary_incidents': await (await q.execute('SELECT * FROM incidents WHERE id=ANY(%s::uuid[]) ORDER BY id',([PRIMARY_SOURCE,PRIMARY_TARGET],))).fetchall(),
        'primary_documents': await (await q.execute('SELECT * FROM documents WHERE incident_id=ANY(%s::uuid[]) ORDER BY id',([PRIMARY_SOURCE,PRIMARY_TARGET],))).fetchall(),
        'primary_claims': await (await q.execute('SELECT * FROM claims WHERE incident_id=ANY(%s::uuid[]) ORDER BY id',([PRIMARY_SOURCE,PRIMARY_TARGET],))).fetchall(),
        'primary_spans': await (await q.execute('SELECT * FROM claim_source_spans WHERE claim_id IN (SELECT id FROM claims WHERE incident_id=ANY(%s::uuid[])) ORDER BY id',([PRIMARY_SOURCE,PRIMARY_TARGET],))).fetchall(),
    }


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def run(expected):
    c, q, identity = await connect(expected)
    output = {'timestamp_utc':datetime.now(timezone.utc).isoformat(), 'identity':identity,
              'evaluated_resolver':RESOLVER_VERSION}
    try:
        before = await snapshot(q)
        output['baseline'] = before['counts']
        output['migrations'] = await (await q.execute('SELECT version,applied_at FROM schema_migrations ORDER BY version')).fetchall()
        output['resolver_versions'] = await (await q.execute('SELECT resolver_version,state,count(*) FROM event_thread_resolution_audits GROUP BY resolver_version,state ORDER BY resolver_version,state')).fetchall()
        incidents = await (await q.execute('SELECT * FROM incidents ORDER BY id')).fetchall()
        threads = await (await q.execute('SELECT * FROM event_threads ORDER BY id')).fetchall()
        claims = await (await q.execute("SELECT c.*,COALESCE((SELECT jsonb_agg(jsonb_build_object('document_id',sp.document_id,'text_field',sp.text_field,'character_start',sp.character_start,'character_end',sp.character_end,'source_text',sp.source_text)) FROM claim_source_spans sp WHERE sp.claim_id=c.id),'[]'::jsonb) source_spans FROM claims c ORDER BY c.created_at,c.id")).fetchall()
        by_incident, by_thread = defaultdict(list), defaultdict(list)
        incident_map = {str(i['id']):i for i in incidents}
        for claim in claims:
            by_incident[str(claim['incident_id'])].append(claim)
            by_thread[str(incident_map[str(claim['incident_id'])]['event_thread_id'])].append(claim)
        reviews = []
        for edge in before['relationships']:
            source = await build_incident_context(q, edge['from_incident_id'])
            target = await build_incident_context(q, edge['to_incident_id'])
            member_ids = [i['id'] for i in incidents if i['event_thread_id'] == edge['event_thread_id'] and i['id'] != source.incident_id]
            members = tuple([await build_incident_context(q, i) for i in member_ids])
            # Counterfactual excludes the subject already joined by the old rules.
            candidate = EventThreadCandidate(edge['event_thread_id'], '',
                frozenset().union(*(m.actor_ids for m in members)),
                frozenset().union(*(m.participant_ids for m in members)),
                frozenset().union(*(m.target_ids for m in members)),
                frozenset().union(*(m.location_ids for m in members)),
                frozenset().union(*(m.domains for m in members)),None,None,len(members),members)
            hypothetical = replace(source,current_thread_id=source.incident_id)
            result = DeterministicEventThreadResolver().resolve(hypothetical,[candidate])
            grounded = _grounded_relationships(source, members)
            supported = [g for g in grounded if g['target_incident_id']==str(target.incident_id) and g['relation']==edge['relation']]
            if not source.source_claims or not members:
                classification = 'NOT_REEVALUATED'
            elif len(grounded)>1:
                classification = 'AMBIGUOUS'
            elif supported and result.state=='ASSIGNED_EXISTING_THREAD':
                classification = 'SUPPORTED'
            elif any(g['target_incident_id']!=str(target.incident_id) for g in grounded):
                classification = 'NOT_SUPPORTED'
            else:
                classification = 'INSUFFICIENT_EVIDENCE'
            documents = await (await q.execute('SELECT id,title,canonical_url,excerpt,published_at,collected_at,incident_id FROM documents WHERE incident_id=ANY(%s::uuid[]) ORDER BY id',([source.incident_id,target.incident_id],))).fetchall()
            stored_audits = await (await q.execute('SELECT * FROM event_thread_resolution_audits WHERE incident_id=%s ORDER BY created_at',(source.incident_id,))).fetchall()
            evaluations = {}
            for label, text, group, n in [
                ('source_alone',incident_map[str(source.incident_id)]['title']+' '+(incident_map[str(source.incident_id)]['summary'] or ''),by_incident[str(source.incident_id)],1),
                ('target_alone',incident_map[str(target.incident_id)]['title']+' '+(incident_map[str(target.incident_id)]['summary'] or ''),by_incident[str(target.incident_id)],1),
                ('existing_membership_retained',' '.join(i['title']+' '+(i['summary'] or '') for i in incidents if i['event_thread_id']==edge['event_thread_id']),by_thread[str(edge['event_thread_id'])],len(members)+1)]:
                level,score,basis = _importance(text,n,group)
                evaluations[label]={'category':level,'score':score,'basis':basis}
            reviews.append({'stored_edge':edge,'classification':classification,'stored_audits':stored_audits,
                'source_claims':list(source.source_claims),'target_claims':list(target.source_claims),
                'documents':documents,'new_resolution':result.__dict__,'grounded':grounded,
                'importance':evaluations,'source_escalation_support':_military_escalation_support(by_incident[str(source.incident_id)]),
                'stored_changes':[m for m in before['changes'] if m['event_thread_id']==edge['event_thread_id']]})
        output['relationships']=reviews
        output['relationship_classifications']=dict(Counter(r['classification'] for r in reviews))
        # Evaluate every matching military claim; retain a bounded stratified set
        # for human review, plus every previously HIGH escalation incident.
        pattern = re.compile(r'\b(?:military|retaliat\w*|air\s*strikes?|missile\w*|attack\w*|deployment\w*|contingency|escalat\w*)\b',re.I)
        military=[cl for cl in claims if pattern.search(cl['statement'])]
        output['military_claim_count']=len(military)
        output['semantics_counts']=dict(Counter(assertion_semantics(cl) for cl in military))
        output['supported_offensive_claim_count']=sum(bool(_military_escalation_support([cl])) for cl in military)
        samples=[]
        for semantic in sorted(output['semantics_counts']):
            group=[cl for cl in military if assertion_semantics(cl)==semantic]
            for cl in group[:2]:
                samples.append({'claim_id':cl['id'],'incident_id':cl['incident_id'],'statement':cl['statement'],
                    'type':cl['type'],'epistemic_status':cl['epistemic_status'],'attribution':cl['attribution'],
                    'source_spans':cl['source_spans'],'semantics':semantic,
                    'new_offensive_support':bool(_military_escalation_support([cl]))})
        output['semantic_samples']=samples
        comparisons=[]
        for i in incidents:
            group=by_incident[str(i['id'])]
            if (i['importance'] or {}).get('dimensions',{}).get('escalation')=='HIGH':
                level,score,basis=_importance(i['title']+' '+(i['summary'] or ''),1,group)
                comparisons.append({'incident_id':i['id'],'title':i['title'],'old_category':i['importance_level'],
                    'new_category':level,'new_score':score,'new_escalation':basis['dimensions']['escalation'],
                    'claim_semantics':basis['assertion_semantics'],
                    'support_claim_ids':[s['claim_id'] for s in basis['military_escalation_support']],
                    'supporting_claims':basis['military_escalation_support']})
        output['stored_high_escalation_incidents']=comparisons
        output['escalation_reassessment_counts']=dict(Counter(v['new_escalation'] for v in comparisons))
        output['query_count']=q.queries
    finally:
        await c.rollback()
        await c.close()
    # New server-enforced read-only transaction, not a repeatable-read self-check.
    final, fq, final_identity=await connect(expected)
    try:
        after=await snapshot(fq)
        comparisons={}
        for key in ['documents','incidents','relationships','changes','primary_incidents',
                    'primary_documents','primary_claims','primary_spans']:
            old={str(r['id']):r for r in before[key]};new={str(r['id']):r for r in after[key]}
            comparisons[key]={'existing_unchanged':all(new.get(i)==r for i,r in old.items()),
                              'added':len(new.keys()-old.keys()),'removed':len(old.keys()-new.keys()),
                              'before_sha256':fingerprint(before[key]),
                              'after_existing_sha256':fingerprint([new.get(str(r['id'])) for r in before[key]])}
        output['preservation']={'final_identity':final_identity,'records':comparisons,
            'primary_thread_unchanged':before['primary_thread']==after['primary_thread'],
            'count_deltas':{t:after['counts'][t]-before['counts'][t] for t in TABLES}}
    finally:
        await final.rollback()
        await final.close()
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-database',required=True)
    args=parser.parse_args()
    print(json.dumps(asyncio.run(run(args.expected_database)),default=str,indent=2))
