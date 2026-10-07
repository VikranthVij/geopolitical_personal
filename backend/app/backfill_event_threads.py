"""Controlled Feature 5 backfill. Defaults to a rollback-only dry run."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .event_thread_resolution import resolve_incident_to_thread, record_thread_resolution_failure


async def run(apply: bool) -> dict:
    pool = AsyncConnectionPool(os.getenv("DATABASE_URL", "postgresql://geopolitics:change-me-locally@localhost:5432/geopolitics"),
                               min_size=1, max_size=1, open=False, kwargs={"row_factory": dict_row})
    await pool.open()
    report = Counter()
    try:
        async with pool.connection() as conn:
            incidents = await (await conn.execute("SELECT id,event_thread_id FROM incidents ORDER BY occurred_at NULLS LAST,created_at,id")).fetchall()
            report["incidents_examined"] = len(incidents)
            report["existing_event_threads"] = len({row["event_thread_id"] for row in incidents})
            report["already_audited"] = (await (await conn.execute("SELECT count(DISTINCT incident_id) n FROM event_thread_resolution_audits WHERE state<>'RESOLUTION_FAILED'")).fetchone())["n"]
            for row in incidents:
                try:
                    async with conn.transaction():
                        resolution = await resolve_incident_to_thread(conn, row["id"])
                    report[resolution.state.lower()] += 1
                    report["relationship_candidates"] += len(resolution.candidates_considered)
                    report["relationships_created"] += len(resolution.relationship_ids)
                    if resolution.state == "NEW_THREAD":
                        report["new_threads_created"] += 1
                except Exception as exc:
                    report["resolution_failed"] += 1
                    if apply:
                        await record_thread_resolution_failure(conn, row["id"], exc)
            if not apply:
                # The dry run executes the same resolver against sequential hypothetical state,
                # then discards memberships, profiles, relationships, titles and audits.
                await conn.rollback()
    finally:
        await pool.close()
    report["mode"] = "APPLY" if apply else "DRY_RUN"
    report["assignments_changed"] = bool(apply)
    return dict(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist Event Thread assignments; omit for rollback-only dry run")
    result = asyncio.run(run(parser.parse_args().apply))
    print(json.dumps(result, indent=2, sort_keys=True))
