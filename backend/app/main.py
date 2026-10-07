from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .collector import collect_once, collection_loop
from .providers import get_provider

ROOT = Path(__file__).resolve().parents[1]
pool = AsyncConnectionPool(os.getenv("DATABASE_URL", "postgresql://geopolitics:change-me-locally@localhost:5432/geopolitics"), min_size=1, max_size=8, open=False, kwargs={"row_factory": dict_row})
worker: asyncio.Task | None = None


async def migrate() -> None:
    async with pool.connection() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(891042771)")
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            version = path.name
            already = await (await conn.execute("SELECT 1 FROM schema_migrations WHERE version=%s", (version,))).fetchone()
            if already:
                continue
            await conn.execute(path.read_text())
            await conn.execute("INSERT INTO schema_migrations(version) VALUES(%s)", (version,))


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker
    await pool.open()
    await pool.wait()
    await migrate()
    worker = asyncio.create_task(collection_loop(pool))
    yield
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:
        pass
    await pool.close()


app = FastAPI(title="Geopolitical OSINT Intelligence Dashboard", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1200)


class IndiaPathRequest(BaseModel):
    edge_id: UUID
    pathway_note: str = Field(min_length=8, max_length=2000)
    relevance_level: int = Field(ge=0, le=4)


async def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    async with pool.connection() as conn:
        return await (await conn.execute(sql, params)).fetchall()


@app.get("/health")
async def health():
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute("SELECT now() AS database_time")).fetchone()
        return {"status": "ok", "database": "connected", "database_time": row["database_time"]}
    except Exception as exc:
        raise HTTPException(503, detail=f"database unavailable: {type(exc).__name__}")


@app.get("/documents/{document_id}/entities")
async def document_entities(document_id: UUID):
    rows = await fetch_all(
        "SELECT m.id mention_id,m.surface_text,m.text_field,m.character_start,m.character_end,m.entity_type,"
        "m.extraction_method,m.resolution_confidence,e.id entity_id,e.canonical_name,e.type canonical_type,e.country_code "
        "FROM documents d LEFT JOIN document_entity_mentions m ON m.document_id=d.id "
        "LEFT JOIN entities e ON e.id=m.entity_id WHERE d.id=%s "
        "ORDER BY m.text_field,m.character_start", (document_id,)
    )
    if not rows:
        raise HTTPException(404, "document not found")
    return {"document_id": document_id, "mentions": [r for r in rows if r["mention_id"] is not None]}


@app.get("/documents/{document_id}/claims")
async def document_claims(document_id: UUID):
    document = await fetch_all("SELECT id,source_id,published_at FROM documents WHERE id=%s", (document_id,))
    if not document:
        raise HTTPException(404, "document not found")
    claims = await fetch_all(
        "SELECT c.id,c.type,c.statement,c.status,c.confidence,c.confidence_explanation,c.intent_label,"
        "c.normalized_representation,c.polarity,c.epistemic_status,c.attribution_type,c.attribution,"
        "c.extraction_method,c.extraction_confidence,c.created_at "
        "FROM claims c JOIN claim_sources cs ON cs.claim_id=c.id WHERE cs.document_id=%s ORDER BY c.created_at,c.id",
        (document_id,),
    )
    claim_ids = [c["id"] for c in claims]
    spans = await fetch_all(
        "SELECT claim_id,text_field,character_start,character_end,source_text FROM claim_source_spans "
        "WHERE document_id=%s ORDER BY character_start", (document_id,),
    ) if claim_ids else []
    entities = await fetch_all(
        "SELECT ce.claim_id,ce.role,e.id entity_id,e.canonical_name,e.type entity_type "
        "FROM claim_entities ce JOIN entities e ON e.id=ce.entity_id "
        "JOIN claim_sources cs ON cs.claim_id=ce.claim_id WHERE cs.document_id=%s ORDER BY e.canonical_name",
        (document_id,),
    ) if claim_ids else []
    spans_by_claim = {}
    entities_by_claim = {}
    for span in spans:
        spans_by_claim.setdefault(span["claim_id"], []).append({k: v for k, v in span.items() if k != "claim_id"})
    for entity in entities:
        entities_by_claim.setdefault(entity["claim_id"], []).append({k: v for k, v in entity.items() if k != "claim_id"})
    for claim in claims:
        claim["source_spans"] = spans_by_claim.get(claim["id"], [])
        claim["entities"] = entities_by_claim.get(claim["id"], [])
    return {"document_id": document_id, "source_id": document[0]["source_id"], "published_at": document[0]["published_at"], "claims": claims}


@app.get("/documents/{document_id}/evidence")
async def document_evidence(document_id: UUID):
    document = await fetch_all(
        "SELECT d.id,d.source_id,d.title,d.published_at,s.name source_name FROM documents d "
        "JOIN sources s ON s.id=d.source_id WHERE d.id=%s", (document_id,),
    )
    if not document:
        raise HTTPException(404, "document not found")
    records = await fetch_all(
        "SELECT e.id,e.type,e.description,e.canonical_url,e.provenance,e.observed_at,e.directness,e.independence_key,"
        "e.metadata,e.extraction_method,e.extraction_confidence,e.identity_key,e.origin_reference,e.origin_source_id,"
        "e.created_at,e.updated_at,ed.relation document_relation,ed.directness document_directness,"
        "ed.attribution document_attribution,ed.metadata document_metadata,ed.referenced_document_id,"
        "rd.title referenced_document_title,rd.canonical_url referenced_document_url,rs.name referenced_document_source "
        "FROM evidence_documents ed JOIN evidence e ON e.id=ed.evidence_id "
        "LEFT JOIN documents rd ON rd.id=ed.referenced_document_id LEFT JOIN sources rs ON rs.id=rd.source_id "
        "WHERE ed.document_id=%s "
        "ORDER BY e.created_at,e.id", (document_id,),
    )
    ids = [row["id"] for row in records]
    spans = await fetch_all(
        "SELECT evidence_id,text_field,character_start,character_end,source_text FROM evidence_source_spans "
        "WHERE document_id=%s ORDER BY text_field,character_start", (document_id,),
    ) if ids else []
    sources = await fetch_all(
        "SELECT es.evidence_id,es.relation,es.reference_text,s.id source_id,s.name source_name "
        "FROM evidence_sources es JOIN sources s ON s.id=es.source_id WHERE es.evidence_id=ANY(%s) "
        "ORDER BY s.name", (ids,),
    ) if ids else []
    lineage = await fetch_all(
        "SELECT l.evidence_id,l.related_evidence_id,l.relation,l.reference_text,"
        "child.type child_type,child.description child_description,parent.type parent_type,parent.description parent_description "
        "FROM evidence_lineage l JOIN evidence child ON child.id=l.evidence_id JOIN evidence parent ON parent.id=l.related_evidence_id "
        "WHERE l.evidence_id=ANY(%s) OR l.related_evidence_id=ANY(%s) ORDER BY l.created_at", (ids, ids),
    ) if ids else []
    claims = await fetch_all(
        "SELECT ces.evidence_id,ces.relation,c.id claim_id,c.type claim_type,c.statement "
        "FROM claim_evidence_sources ces JOIN claims c ON c.id=ces.claim_id "
        "WHERE ces.document_id=%s ORDER BY c.created_at,c.id", (document_id,),
    )
    spans_by, sources_by, lineage_by, claims_by = {}, {}, {}, {}
    for row in spans:
        spans_by.setdefault(row["evidence_id"], []).append({k: v for k, v in row.items() if k != "evidence_id"})
    for row in sources:
        sources_by.setdefault(row["evidence_id"], []).append({k: v for k, v in row.items() if k != "evidence_id"})
    for row in lineage:
        if row["evidence_id"] in ids:
            lineage_by.setdefault(row["evidence_id"], []).append({
                "direction": "DERIVED_OR_CITES", "evidence_id": row["related_evidence_id"],
                "type": row["parent_type"], "description": row["parent_description"],
                "relation": row["relation"], "reference_text": row["reference_text"],
            })
        if row["related_evidence_id"] in ids:
            lineage_by.setdefault(row["related_evidence_id"], []).append({
                "direction": "USED_BY_OR_CITED_BY", "evidence_id": row["evidence_id"],
                "type": row["child_type"], "description": row["child_description"],
                "relation": row["relation"], "reference_text": row["reference_text"],
            })
    for row in claims:
        claims_by.setdefault(row["evidence_id"], []).append({k: v for k, v in row.items() if k != "evidence_id"})
    evidence_by_id = {}
    for row in records:
        item = evidence_by_id.setdefault(row["id"], {k: v for k, v in row.items() if k not in {"document_relation", "document_directness", "document_attribution", "document_metadata", "referenced_document_id", "referenced_document_title", "referenced_document_url", "referenced_document_source"}})
        item.setdefault("document_links", []).append({
            "relation": row["document_relation"], "directness": row["document_directness"],
            "attribution": row["document_attribution"], "metadata": row["document_metadata"],
            "referenced_document_id": row["referenced_document_id"],
            "referenced_document_title": row["referenced_document_title"],
            "referenced_document_url": row["referenced_document_url"],
            "referenced_document_source": row["referenced_document_source"],
        })
    for evidence_id, item in evidence_by_id.items():
        item["source_spans"] = spans_by.get(evidence_id, [])
        item["sources"] = sources_by.get(evidence_id, [])
        item["lineage"] = lineage_by.get(evidence_id, [])
        item["claims"] = claims_by.get(evidence_id, [])
    return {"document_id": document_id, "source_id": document[0]["source_id"],
            "source_name": document[0]["source_name"], "published_at": document[0]["published_at"],
            "evidence": list(evidence_by_id.values())}


@app.get("/documents/{document_id}/resolution")
async def document_resolution(document_id: UUID):
    rows = await fetch_all(
        "SELECT d.id document_id,d.title document_title,d.source_id,d.incident_id,i.title incident_title,i.event_thread_id,"
        "r.state,r.resolution_method,r.match_strength,r.matched_signals,r.conflicts,r.candidates_considered,r.limitation,r.updated_at "
        "FROM documents d LEFT JOIN incidents i ON i.id=d.incident_id LEFT JOIN document_incident_resolutions r ON r.document_id=d.id "
        "WHERE d.id=%s", (document_id,))
    if not rows:
        raise HTTPException(404, "document not found")
    result = rows[0]
    result["fingerprint"] = await fetch_all(
        "SELECT fp.primary_actor_id,ea.canonical_name primary_actor,fp.action_predicate,fp.target_entity_id,et.canonical_name target,"
        "fp.object_entity_id,eo.canonical_name object,fp.location_entity_id,el.canonical_name location,fp.event_time_start,"
        "fp.event_time_end,fp.event_time_expression,fp.time_precision,fp.quantity,fp.consequence,fp.response,fp.supporting_entities,fp.source_metadata "
        "FROM incident_fingerprints fp LEFT JOIN entities ea ON ea.id=fp.primary_actor_id LEFT JOIN entities et ON et.id=fp.target_entity_id "
        "LEFT JOIN entities eo ON eo.id=fp.object_entity_id LEFT JOIN entities el ON el.id=fp.location_entity_id WHERE fp.incident_id=%s",
        (result["incident_id"],)) if result["incident_id"] else []
    result["documents"] = await fetch_all(
        "SELECT d.id,d.title,d.canonical_url,d.published_at,s.name source_name FROM documents d JOIN sources s ON s.id=d.source_id "
        "WHERE d.incident_id=%s ORDER BY d.published_at NULLS LAST,d.created_at", (result["incident_id"],)) if result["incident_id"] else []
    return result


@app.get("/incidents/{incident_id}")
async def incident_detail(incident_id: UUID):
    row = await fetch_all("SELECT i.*,fp.primary_actor_id,ea.canonical_name primary_actor,fp.action_predicate,fp.target_entity_id,et.canonical_name target,"
        "fp.object_entity_id,eo.canonical_name object,fp.location_entity_id,el.canonical_name location,fp.event_time_start,fp.event_time_end,"
        "fp.event_time_expression,fp.time_precision,fp.quantity,fp.consequence,fp.response,fp.supporting_entities "
        "FROM incidents i LEFT JOIN incident_fingerprints fp ON fp.incident_id=i.id LEFT JOIN entities ea ON ea.id=fp.primary_actor_id "
        "LEFT JOIN entities et ON et.id=fp.target_entity_id LEFT JOIN entities eo ON eo.id=fp.object_entity_id "
        "LEFT JOIN entities el ON el.id=fp.location_entity_id WHERE i.id=%s", (incident_id,))
    if not row:
        raise HTTPException(404, "incident not found")
    result = row[0]
    result["documents"] = await fetch_all("SELECT d.id,d.title,d.canonical_url,d.published_at,s.name source_name FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.incident_id=%s ORDER BY d.published_at NULLS LAST,d.created_at", (incident_id,))
    result["resolutions"] = await fetch_all("SELECT document_id,state,resolution_method,match_strength,matched_signals,conflicts,candidates_considered,updated_at FROM document_incident_resolutions WHERE incident_id=%s ORDER BY created_at", (incident_id,))
    result["evidence"] = await fetch_all("SELECT DISTINCT e.id,e.type,e.description,e.identity_key FROM incident_fingerprint_evidence ie JOIN evidence e ON e.id=ie.evidence_id WHERE ie.incident_id=%s ORDER BY e.id", (incident_id,))
    return result


@app.get("/events")
async def events(section: str = Query("all", pattern="^(all|india|global|other)$"), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    where = {"india": "india_relevance > 0", "global": "india_relevance = 0 AND importance_level >= 2", "other": "india_relevance = 0 AND importance_level < 2"}.get(section, "TRUE")
    return await fetch_all(f"SELECT id,title,summary,status,importance_level,india_relevance,created_at,updated_at FROM event_threads WHERE {where} ORDER BY updated_at DESC LIMIT %s OFFSET %s", (limit, offset))


@app.get("/events/{event_id}")
async def event_detail(event_id: UUID):
    rows = await fetch_all("SELECT * FROM event_threads WHERE id=%s", (event_id,))
    if not rows:
        raise HTTPException(404, "event not found")
    result = rows[0]
    result["incidents"] = await fetch_all("SELECT * FROM incidents WHERE event_thread_id=%s ORDER BY occurred_at NULLS LAST,created_at", (event_id,))
    return result


@app.get("/events/{event_id}/timeline")
async def timeline(event_id: UUID):
    return await fetch_all("SELECT i.id AS incident_id,i.title,i.summary,i.occurred_at,i.created_at FROM incidents i WHERE i.event_thread_id=%s ORDER BY i.occurred_at NULLS LAST,i.created_at", (event_id,))


@app.get("/events/{event_id}/evidence")
async def evidence(event_id: UUID):
    return await fetch_all("SELECT c.id claim_id,c.statement,c.type,c.confidence,c.confidence_explanation,d.title document_title,d.canonical_url,d.published_at,s.name source_name,s.tier source_tier,ce.relation evidence_relation,e.id evidence_id,e.type evidence_type,e.description evidence_description FROM incidents i JOIN claims c ON c.incident_id=i.id LEFT JOIN claim_sources cs ON cs.claim_id=c.id LEFT JOIN documents d ON d.id=cs.document_id LEFT JOIN sources s ON s.id=d.source_id LEFT JOIN claim_evidence ce ON ce.claim_id=c.id LEFT JOIN evidence e ON e.id=ce.evidence_id WHERE i.event_thread_id=%s ORDER BY c.created_at DESC", (event_id,))


@app.get("/events/{event_id}/history")
async def history(event_id: UUID):
    return await fetch_all("SELECT h.id,h.title,h.summary,h.started_at,h.ended_at,hi.interpretation,hi.labels FROM historical_interpretations hi JOIN historical_events h ON h.id=hi.historical_event_id WHERE hi.event_thread_id=%s ORDER BY h.started_at", (event_id,))


@app.get("/events/{event_id}/india-impact")
async def india_impact(event_id: UUID):
    event = await fetch_all("SELECT id,india_relevance FROM event_threads WHERE id=%s", (event_id,))
    if not event:
        raise HTTPException(404, "event not found")
    paths = await fetch_all("SELECT p.id,p.pathway_note,e.pathway,n1.name from_node,n1.domain from_domain,n2.name to_node,n2.domain to_domain FROM event_india_exposure_paths p JOIN india_exposure_edges e ON e.id=p.edge_id JOIN india_exposure_nodes n1 ON n1.id=e.from_node_id JOIN india_exposure_nodes n2 ON n2.id=e.to_node_id WHERE p.event_thread_id=%s ORDER BY p.created_at", (event_id,))
    return {"level": event[0]["india_relevance"], "hypotheses": await fetch_all("SELECT id,statement,label,causal_confidence,explanation,created_at FROM impact_hypotheses WHERE event_thread_id=%s ORDER BY created_at DESC", (event_id,)), "pathways": paths}


@app.post("/events/{event_id}/india-impact/pathways")
async def add_india_pathway(event_id: UUID, body: IndiaPathRequest):
    async with pool.connection() as conn:
        if not await (await conn.execute("SELECT 1 FROM event_threads WHERE id=%s", (event_id,))).fetchone():
            raise HTTPException(404, "event not found")
        edge = await (await conn.execute("SELECT id FROM india_exposure_edges WHERE id=%s", (body.edge_id,))).fetchone()
        if not edge:
            raise HTTPException(404, "India exposure edge not found")
        await conn.execute("INSERT INTO event_india_exposure_paths(event_thread_id,edge_id,pathway_note) VALUES(%s,%s,%s) ON CONFLICT(event_thread_id,edge_id) DO UPDATE SET pathway_note=EXCLUDED.pathway_note", (event_id,body.edge_id,body.pathway_note))
        await conn.execute("UPDATE event_threads SET india_relevance=GREATEST(india_relevance,%s),updated_at=now(),knowledge_version=knowledge_version+1 WHERE id=%s", (body.relevance_level,event_id))
        actual = await (await conn.execute("SELECT india_relevance FROM event_threads WHERE id=%s", (event_id,))).fetchone()
        return {"saved": True, "india_relevance": actual["india_relevance"]}


@app.get("/events/{event_id}/changes")
async def changes(event_id: UUID):
    return await fetch_all("SELECT id,incident_id,change_type,summary,material,created_at FROM event_updates WHERE event_thread_id=%s ORDER BY created_at DESC", (event_id,))


@app.get("/events/{event_id}/contradictions")
async def contradictions(event_id: UUID):
    return await fetch_all("SELECT x.id,x.type,x.explanation,x.status,a.id claim_a_id,a.statement claim_a,b.id claim_b_id,b.statement claim_b FROM incidents i JOIN claims a ON a.incident_id=i.id JOIN contradictions x ON x.claim_a=a.id OR x.claim_b=a.id JOIN claims b ON b.id=CASE WHEN x.claim_a=a.id THEN x.claim_b ELSE x.claim_a END WHERE i.event_thread_id=%s ORDER BY x.created_at DESC", (event_id,))


@app.get("/events/{event_id}/related")
async def related_events(event_id: UUID):
    return await fetch_all("SELECT r.relation,r.explanation,e.id,e.title,e.status,e.updated_at FROM event_relationships r JOIN event_threads e ON e.id=CASE WHEN r.from_event_id=%s THEN r.to_event_id ELSE r.from_event_id END WHERE r.from_event_id=%s OR r.to_event_id=%s ORDER BY e.updated_at DESC", (event_id,event_id,event_id))


@app.get("/events/{event_id}/watch-indicators")
async def watch_indicators(event_id: UUID):
    return await fetch_all("SELECT id,indicator,why_it_matters,created_at FROM event_watch_indicators WHERE event_thread_id=%s ORDER BY created_at", (event_id,))


@app.post("/events/{event_id}/ask")
async def ask(event_id: UUID, body: AskRequest):
    event = await fetch_all("SELECT id,title,summary,status FROM event_threads WHERE id=%s", (event_id,))
    if not event:
        raise HTTPException(404, "event not found")
    claims = await fetch_all("SELECT c.id,c.statement,c.type,c.confidence,c.confidence_explanation,d.canonical_url,s.name source_name FROM incidents i JOIN claims c ON c.incident_id=i.id LEFT JOIN claim_sources cs ON cs.claim_id=c.id LEFT JOIN documents d ON d.id=cs.document_id LEFT JOIN sources s ON s.id=d.source_id WHERE i.event_thread_id=%s ORDER BY c.created_at DESC LIMIT 40", (event_id,))
    if not claims:
        return {"answer": "UNKNOWN: The stored intelligence has no sourced claims for this event yet.", "sources": []}
    context = "\n".join(f"[claim:{c['id']}] {c['type']} / {c['confidence']}: {c['statement']} Source: {c['source_name'] or 'unknown'} {c['canonical_url'] or ''}" for c in claims)
    try:
        answer = await get_provider().generate(f"Answer using only the context. Cite each factual sentence with exact [claim:UUID] tokens from the context. Separate REPORTED_CLAIM, INFERENCE, ANALYSIS, SPECULATION, UNKNOWN. If unsupported, say UNKNOWN. Never invent facts or citations.\nQuestion: {body.question}\nContext:\n{context}")
        valid_ids = {str(c["id"]) for c in claims}
        import re
        citations = set(re.findall(r"\[claim:([0-9a-fA-F-]{36})\]", answer))
        if not citations or not citations.issubset(valid_ids):
            raise ValueError("response lacked valid stored claim citations")
        return {"answer": answer, "sources": [c for c in claims if str(c["id"]) in citations], "provider": "ollama"}
    except Exception:
        return {"answer": "The local model is unavailable or did not return verifiable claim citations. Stored context is provided without generated conclusions.", "sources": claims, "provider": "unavailable"}


@app.post("/events/{event_id}/watch")
async def watch(event_id: UUID):
    async with pool.connection() as conn:
        exists = await (await conn.execute("SELECT id FROM event_threads WHERE id=%s", (event_id,))).fetchone()
        if not exists:
            raise HTTPException(404, "event not found")
        row = await (await conn.execute("INSERT INTO watchlists(event_thread_id) VALUES(%s) ON CONFLICT(event_thread_id) DO NOTHING RETURNING id", (event_id,))).fetchone()
        if row:
            return {"watched": True}
        await conn.execute("DELETE FROM watchlists WHERE event_thread_id=%s", (event_id,))
        return {"watched": False}


@app.get("/watchlist")
async def watchlist():
    return await fetch_all("SELECT e.id,e.title,e.summary,e.status,e.india_relevance,w.created_at watched_at FROM watchlists w JOIN event_threads e ON e.id=w.event_thread_id ORDER BY w.created_at DESC")


@app.get("/collection/runs")
async def collection_runs(limit: int = Query(30, ge=1, le=200)):
    return await fetch_all("SELECT r.*,s.name source_name FROM collection_runs r LEFT JOIN sources s ON s.id=r.source_id ORDER BY started_at DESC LIMIT %s", (limit,))


@app.post("/collection/run")
async def run_collection():
    return await collect_once(pool)
