# Implementation Notes

## Delivery status

This is the first runnable foundation of V1. It includes a Compose stack, versioned PostgreSQL/pgvector schema, FastAPI event/watch/collection surfaces, an incremental RSS collector with per-feed audit records and URL/exact-content deduplication, provenance-bearing reported claims, a provider boundary for Ollama, citation-validated event Q&A, and a Next.js event desk with India, history, changes, contradiction, related-event, and watch-indicator sections.

Feature 1 now adds deterministic structured entity extraction to every newly inserted document, including exact-content duplicate documents. `backend/app/entities.py` applies curated canonical names and aliases to title and excerpt text without an LLM; it stores exact character offsets separately for each field. Canonical records are reused by `(canonical_name,type)`, aliases are persisted in `entity_aliases`, and occurrences are persisted in `document_entity_mentions`. `GET /documents/{document_id}/entities` exposes the stored resolution and original mention text. Reprocessing replaces a document's mention rows transactionally and reuses existing canonical rows.

The initial dictionary covers a deliberately bounded set of countries, organizations, military units, weapons/systems, aircraft, vessels, locations, facilities, and economic entities. `Washington` and generic force phrases such as `Iranian forces` remain explicitly unresolved. This is surface-form extraction, not general NER: it misses names outside the curated alias list, does not infer actor/target roles, and does not turn plain generic references such as “regional allies” into entities. It also does not establish whether any reported statement is true.

Verification for Feature 1: 14 backend unit/regression tests pass; Python compile and `git diff --check` pass; `docker compose config -q` passes. Migration 004 applied to the current PostgreSQL volume; health is green; a temporary persisted fixture was inspected through the new API, processed twice, and removed. Direct database inspection found 3 canonical entities, 11 aliases, 0 remaining fixture mentions, and no duplicate mention keys. CPU-only extraction of a representative 2-field document fixture took 0.032 s / 100 documents, 0.152 s / 500, and 0.302 s / 1,000 on this host; these timings exclude database writes and network/feed collection.

## Deliberate constraints

- Newly ingested documents currently create a distinct event thread and incident. This is conservative and avoids false merges, but cross-document incident/event resolution is not yet implemented. Do not interpret the current collector as satisfying deduplication across differently titled coverage.
- Current extraction records a document headline as an unverified reported occurrence claim. It does not yet perform robust entity/claim/evidence extraction, nor does it automatically create contradictions or confidence assessments.
- `candidate_score`, `claims_incompatible`, and `confidence_summary` are deterministic building blocks only; they are not yet connected to persistence workflows.
- Historical tables and India exposure tables are present, but historical research/reuse and causal impact investigation are not implemented yet. No history or economic observations are seeded.
- Vector storage is provisioned, but embeddings are not currently generated or queried. No vector threshold is used for identity.
- Material updates currently represent new document discoveries. Watch toggling is implemented; selective material-change notifications are not.
- Collection is in-process and starts immediately with the API. On-demand/periodic failures are isolated per feed; there is no separate worker process or backoff queue.
- Initial feed URLs are configuration examples and may be unavailable or change. Individual errors appear at `/collection/runs`.

## Manual steps for the user

1. Install/start Docker Desktop, copy `.env.example` to `.env`, and set a local password before first launch.
2. Optionally install and run Ollama and pull the configured model to enable event Q&A.
3. Review feed availability, source terms, and excerpt retention before adding/depending on sources.
4. Authorize Tailscale on the user's devices if private remote access is wanted; the app does not configure account access.

## Next implementation milestones

Complete structured event resolution and entity extraction; evidence independence and contradiction persistence; explainable claim confidence and event importance; canonical historical retrieval; pathway-backed India impact/hypotheses; local embeddings and task-specific retrieval; realistic fixtures and integration tests; and robust catch-up/material-change regression verification.
