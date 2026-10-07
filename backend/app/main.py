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
