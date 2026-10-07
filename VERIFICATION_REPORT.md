# Verification Report

## Current result

The runnable foundation passes local checks and the Compose stack has now been exercised end to end. V1 is not complete and should not be treated as operational intelligence software yet.

## Pass 1 — Functional surface

- Compose configuration parses successfully.
- Backend imports with its pinned dependencies and publishes 17 OpenAPI paths, including health, event detail, timeline, evidence, history, India impact, changes, ask, watch, and collection.
- A clean PostgreSQL 16 + pgvector volume started; all three migrations applied and PostgreSQL reports 36 public tables.
- API `/health` returned `ok` with a connected database; event list/detail, timeline, evidence, history, India-impact, changes, contradictions, related-events, and watch-indicator routes responded for a collected record.
- Next.js production build succeeded in Docker; the dashboard returned HTTP 200.
- The reversible watch on/off flow worked. Q&A returned the safe unavailable-provider response because Ollama is not installed/running.

## Pass 2 — Adversarial deterministic rules

Six unit tests pass for URL canonicalization, whitespace-stable content hashes, structured fingerprint match reporting, explicit same-scope numeric conflicts vs differing-scope quantities, contested confidence behavior, and the IAEA relevance filter.

## Pass 3 — Regression and dependency checks

- Full implemented Python unit suite: 6 passed.
- Python compile check: passed.
- Frontend production build: passed.
- Frontend offline npm audit: 0 vulnerabilities.
- `docker compose config`: passed.
- `git diff --check`: passed.

## Collection verification

- First startup exposed an obsolete UN News URL (404), a wrong MEA URL, and irrelevant IAEA science headlines. The starter feeds were corrected: the dead UN News URL was retired, UN Geneva Press Releases became active, stale MEA/NATO feeds were disabled, and a subject filter was added to the broad IAEA feed.
- Current configured feeds (UN Geneva and IAEA) returned 25 feed entries on a fresh run; 3 were inserted and the rest were skipped by age/relevance/deduplication. Both feeds completed successfully with no errors. A subsequent catch-up run skipped the already processed entries and inserted no duplicates.
- The old failed run remains in audit history as evidence of feed failure handling; current enabled feeds are successful.
- Ollama's local API is not listening on port 11434. The installed `ollama list` CLI crashes during Metal/MLX initialization (`NSRangeException`, array index 0 on an empty array), so model-backed Q&A safely falls back to an unavailable-provider response.

## Feature 1 — Structured entity extraction (2026-10-07)

- Migration `004_structured_entities.sql` applied successfully to the existing database; API health stayed `ok`, and the document entity endpoint is present in OpenAPI.
- 14 backend tests pass, including entity aliases, type separation, repeated mentions, conservative ambiguous resolution, malformed/empty/long input, Unicode punctuation, and the original regression suite. Python compile, Compose config, and whitespace checks pass.
- A temporary document fixture was written, extracted twice, read through `GET /documents/{id}/entities`, and removed. The API returned exact title/excerpt offsets, one shared United States ID for `U.S.` and `United States`, and an unresolved Washington mention. Direct DB inspection showed no duplicate mentions; 3 canonical entities and 11 aliases remained from the fixture, with no fixture documents/mentions retained.
- CPU-only deterministic extraction: 100 docs 0.032 s; 500 docs 0.152 s; 1,000 docs 0.302 s for a representative title+excerpt pair. This excludes database writes and live feed ingestion.
- The complete migration chain (001–004) also passed against a separately created empty database; that temporary database was dropped afterward. A full automatic DB-backed test is not part of the unit suite yet.

## Acceptance gaps

- The collector stores one reported headline claim per new source document. Exact URL/content duplicates are reused, but differently worded coverage is not yet resolved into a shared Incident. New documents currently create separate Event Threads and Incidents.
- Structured entity/claim/evidence extraction, source-independence grouping, logical contradiction persistence, explainable confidence calculations, importance calculations, and material-change resolution remain incomplete.
- Historical search/reuse/contextual interpretation and India exposure graph/hypothesis workflows have schema/API foundations only; no automatic graph relevance, causal investigation, or observations are currently produced.
- Ollama supports citation-validated event Q&A only. Embedding generation/retrieval, cache invalidation, grounded summaries, and what-to-watch generation remain incomplete.
- The 50-report, separate-incidents/shared-thread, unrelated-semantic-events, source-copy independence, historical reuse, India causality, feed-failure, and startup catch-up end-to-end acceptance scenarios were not run.

## Manual intervention

To enable model-backed Q&A, repair/update the installed Ollama runtime, start its local service, confirm `http://localhost:11434/api/tags` responds, and pull `qwen2.5:7b`. The Q&A path then uses the configured host URL from Docker. Feed availability and permitted excerpt retention should be reviewed before relying on any source.
