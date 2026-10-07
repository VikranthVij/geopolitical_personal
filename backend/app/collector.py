from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from psycopg_pool import AsyncConnectionPool
from psycopg.types.json import Jsonb

from .default_feeds import FEEDS, RETIRED_FEED_NAMES, is_relevant_iaea
from .intelligence import canonicalize_url, content_hash


async def ensure_feeds(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        for name in RETIRED_FEED_NAMES:
            await conn.execute("UPDATE source_feeds f SET enabled=false FROM sources s WHERE f.source_id=s.id AND s.name=%s", (name,))
            await conn.execute("UPDATE sources SET enabled=false WHERE name=%s", (name,))
        for name, url, tier, category in FEEDS:
            source = await conn.execute("INSERT INTO sources(name,base_url,tier,source_type) VALUES(%s,%s,%s,'PUBLISHER') ON CONFLICT(name) DO UPDATE SET base_url=EXCLUDED.base_url,enabled=true RETURNING id", (name, url, tier))
            source_id = (await source.fetchone())["id"]
            await conn.execute("INSERT INTO source_feeds(source_id,url,category) VALUES(%s,%s,%s) ON CONFLICT(url) DO UPDATE SET enabled=true", (source_id, url, category))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


async def collect_once(pool: AsyncConnectionPool) -> dict:
    await ensure_feeds(pool)
    async with pool.connection() as conn:
        feeds = await (await conn.execute("SELECT f.id,f.source_id,f.url,s.name,s.tier FROM source_feeds f JOIN sources s ON s.id=f.source_id WHERE f.enabled AND s.enabled ORDER BY s.tier,f.url")).fetchall()
    totals = {"feeds": len(feeds), "fetched": 0, "inserted": 0, "skipped": 0, "errors": []}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "GeopoliticalOSINTDashboard/1.0 (+local personal research)"}) as client:
        for feed in feeds:
            feed_id, source_id, feed_url, source_name = feed["id"], feed["source_id"], feed["url"], feed["name"]
            run_id = None
            try:
                async with pool.connection() as conn:
                    row = await (await conn.execute("INSERT INTO collection_runs(source_id) VALUES(%s) RETURNING id", (source_id,))).fetchone()
                    run_id = row["id"]
                response = await client.get(feed_url)
                response.raise_for_status()
                parsed = feedparser.parse(response.text)
                fetched = len(parsed.entries)
                inserted = skipped = 0
                totals["fetched"] += fetched
                for entry in parsed.entries:
                    link = canonicalize_url(entry.get("link", ""))
                    title = clean_text(entry.get("title", ""))
                    excerpt = clean_text(entry.get("summary", entry.get("description", "")))[:1200]
                    if source_name == "International Atomic Energy Agency" and not is_relevant_iaea(f"{title} {excerpt}"):
                        skipped += 1
                        continue
                    if not link or not title:
                        skipped += 1
                        continue
                    published = None
                    if entry.get("published_parsed"):
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    # RSS feeds often expose only a small rolling batch. Give first-run
                    # catch-up a wider window; hashes/URLs prevent repeat processing.
                    max_age = int(os.getenv("MAX_DOCUMENT_AGE_DAYS", "60"))
                    if published and published < datetime.now(timezone.utc) - timedelta(days=max_age):
                        skipped += 1
                        continue
                    digest = content_hash(title, excerpt)
                    async with pool.connection() as conn:
                        # Keep duplicate publisher records for provenance while attaching exact copies
                        # to their already stored occurrence rather than making another incident.
                        previous = await (await conn.execute("SELECT incident_id FROM documents WHERE content_hash=%s AND incident_id IS NOT NULL ORDER BY collected_at LIMIT 1", (digest,))).fetchone()
                        cursor = await conn.execute("INSERT INTO documents(source_id,canonical_url,title,author,language,published_at,content_hash,excerpt,incident_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(canonical_url) DO NOTHING RETURNING id", (source_id, link, title, entry.get("author"), entry.get("language"), published, digest, excerpt, previous["incident_id"] if previous else None))
                        doc = await cursor.fetchone()
                        if not doc:
                            skipped += 1
                            continue
                        if previous:
                            await conn.execute("INSERT INTO claim_sources(claim_id,document_id,provenance_note) SELECT c.id,%s,'Exact content hash match; same underlying report.' FROM claims c WHERE c.incident_id=%s ON CONFLICT DO NOTHING", (doc["id"], previous["incident_id"]))
                            skipped += 1
                            continue
                        inserted += 1
                        # Conservative initial event identity; separate documents are not assumed to be separate occurrences.
                        # Explicit operator review/structured event resolution can link these in later processing.
                        event = await (await conn.execute("INSERT INTO event_threads(title,summary,status) VALUES(%s,%s,'DISCOVERED') RETURNING id", (title, excerpt or title))).fetchone()
                        incident = await (await conn.execute("INSERT INTO incidents(event_thread_id,title,summary,fingerprint) VALUES(%s,%s,%s,%s) RETURNING id", (event["id"], title, excerpt or title, Jsonb({"headline": re.sub(r"[^a-z0-9 ]", "", title.lower())})))).fetchone()
                        await conn.execute("UPDATE documents SET incident_id=%s WHERE id=%s", (incident["id"], doc["id"]))
                        claim = await (await conn.execute("INSERT INTO claims(incident_id,statement,type,status,confidence,confidence_explanation) VALUES(%s,%s,'OCCURRENCE','REPORTED','UNVERIFIED','A source reported this; independent evidence has not been assessed.') RETURNING id", (incident["id"], title))).fetchone()
                        await conn.execute("INSERT INTO claim_sources(claim_id,document_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (claim["id"], doc["id"]))
                        await conn.execute("INSERT INTO event_updates(event_thread_id,incident_id,change_type,summary,material) VALUES(%s,%s,'DISCOVERY',%s,true)", (event["id"], incident["id"], title))
                totals["inserted"] += inserted
                totals["skipped"] += skipped
                async with pool.connection() as conn:
                    await conn.execute("UPDATE collection_runs SET ended_at=now(),status='SUCCEEDED',fetched_count=%s,inserted_count=%s,skipped_count=%s WHERE id=%s", (fetched, inserted, skipped, run_id))
                    await conn.execute("UPDATE source_feeds SET last_success_at=now() WHERE id=%s", (feed_id,))
            except Exception as exc:
                message = f"{source_name}: {type(exc).__name__}: {str(exc)[:300]}"
                totals["errors"].append(message)
                async with pool.connection() as conn:
                    if run_id:
                        await conn.execute("UPDATE collection_runs SET ended_at=now(),status='FAILED',errors=%s WHERE id=%s", (Jsonb([message]), run_id))
    return totals


async def collection_loop(pool: AsyncConnectionPool) -> None:
    interval = max(15, int(os.getenv("COLLECTION_INTERVAL_MINUTES", "60")) * 60)
    while True:
        try:
            await collect_once(pool)
        except Exception:
            # Keep the service alive; collection_runs records per-feed errors.
            pass
        await asyncio.sleep(interval)
