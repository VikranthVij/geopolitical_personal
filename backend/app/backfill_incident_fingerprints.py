"""Controlled index-only backfill for incidents created before migration 007.

Run `python -m app.backfill_incident_fingerprints` to inspect the count, or add
`--apply` to index existing structured claims/evidence without merging incidents.
"""
from __future__ import annotations

import argparse
import asyncio
import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .incident_resolution import build_document_fingerprint, persist_fingerprint


async def run(apply: bool) -> int:
    pool = AsyncConnectionPool(os.getenv("DATABASE_URL", "postgresql://geopolitics:change-me-locally@localhost:5432/geopolitics"),
                               min_size=1, max_size=1, open=False, kwargs={"row_factory": dict_row})
    await pool.open()
    try:
        async with pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT d.id document_id,d.incident_id FROM documents d WHERE d.incident_id IS NOT NULL ORDER BY d.created_at,d.id")).fetchall()
            print(f"Existing documents to index: {len(rows)}")
            if not apply:
                print("Dry run only. Add --apply to persist fingerprints; no incidents will be merged or reassigned.")
                return len(rows)
            for row in rows:
                fp, extras = await build_document_fingerprint(conn, row["document_id"])
                await persist_fingerprint(conn, row["incident_id"], fp, extras)
            print(f"Indexed {len(rows)} documents. Incident assignments were not changed.")
            return len(rows)
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist structured fingerprints without reassigning documents")
    asyncio.run(run(parser.parse_args().apply))
