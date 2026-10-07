# Implementation Notes

## Delivery status

This is the first runnable foundation of V1. It includes a Compose stack, versioned PostgreSQL/pgvector schema, FastAPI event/watch/collection surfaces, an incremental RSS collector with per-feed audit records and URL/exact-content deduplication, provenance-bearing reported claims, a provider boundary for Ollama, citation-validated event Q&A, and a Next.js event desk with India, history, changes, contradiction, related-event, and watch-indicator sections.

Feature 1 now adds deterministic structured entity extraction to every newly inserted document, including exact-content duplicate documents. `backend/app/entities.py` applies curated canonical names and aliases to title and excerpt text without an LLM; it stores exact character offsets separately for each field. Canonical records are reused by `(canonical_name,type)`, aliases are persisted in `entity_aliases`, and occurrences are persisted in `document_entity_mentions`. `GET /documents/{document_id}/entities` exposes the stored resolution and original mention text. Reprocessing replaces a document's mention rows transactionally and reuses existing canonical rows.

The initial dictionary covers a deliberately bounded set of countries, organizations, military units, weapons/systems, aircraft, vessels, locations, facilities, and economic entities. `Washington` and generic force phrases such as `Iranian forces` remain explicitly unresolved. This is surface-form extraction, not general NER: it misses names outside the curated alias list, does not infer actor/target roles, and does not turn plain generic references such as “regional allies” into entities. It also does not establish whether any reported statement is true.

Verification for Feature 1: 14 backend unit/regression tests pass; Python compile and `git diff --check` pass; `docker compose config -q` passes. Migration 004 applied to the current PostgreSQL volume; health is green; a temporary persisted fixture was inspected through the new API, processed twice, and removed. Direct database inspection found 3 canonical entities, 11 aliases, 0 remaining fixture mentions, and no duplicate mention keys. CPU-only extraction of a representative 2-field document fixture took 0.032 s / 100 documents, 0.152 s / 500, and 0.302 s / 1,000 on this host; these timings exclude database writes and network/feed collection.

Feature 2 adds a replaceable `ClaimExtractor` interface and a bounded `DeterministicClaimExtractor` in `backend/app/claims.py`. The collector invokes it after entity mentions are persisted and an incident is available; it also processes exact-content duplicate documents attached to an existing incident. It recognizes the project's nine claim types using sentence, predicate, attribution, negation, quantity, time, and location rules. It stores the original statement, normalized JSON attributes, affirmed/negated polarity, epistemic status, attribution chain, intent label, extraction method/confidence, document/source provenance, exact title/excerpt spans, and canonical entity links. The new `GET /documents/{document_id}/claims` route exposes these fields. Claim truth confidence remains `UNVERIFIED` and is distinct from extraction confidence.

Duplicate collapse is intentionally conservative: candidates collapse only when their deterministic normalized predicate, polarity, epistemic status, intent, and attribution signatures match. Each distinct source span is retained. Fire/launch wording and other lexical paraphrases remain separate unless the signatures match; there is no embedding or semantic merge. Weekday and relative time expressions are retained without an invented date. Explicit ISO dates, full month dates, and UTC clock expressions are normalized only to their expressed precision. Qualitative quantities such as “dozens” retain an unknown numeric value.

Feature 2 verification: 25 host tests pass; the PostgreSQL integration test is skipped by default without a test DB URL and passed separately inside the API container. The complete migration chain 001–005 passed on the live DB and a disposable empty database. A temporary document was persisted, inspected through the live claims API and direct SQL, then removed. It produced 8 extracted claims, exact source spans, and actor/object/target entity links; no duplicate span keys were found. The rollback-only integration test verified repeated extraction reuses claims/spans and links entities. CPU-only extraction of a representative title/excerpt fixture took 0.193 s / 100 docs (1.929 ms/doc), 0.892 s / 500 (1.785 ms/doc), and 1.759 s / 1,000 (1.759 ms/doc), excluding database writes and feed collection.

## Deliberate constraints

- Newly ingested documents currently create a distinct event thread and incident. This is conservative and avoids false merges, but cross-document incident/event resolution is not yet implemented. Do not interpret the current collector as satisfying deduplication across differently titled coverage.
- Current extraction records a document headline as an unverified reported occurrence claim and adds bounded entity/claim extraction. It does not extract evidence, resolve contradictions, or assess claim truth/confidence.
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

Complete evidence independence and provenance; contradiction persistence; explainable claim confidence and event importance; structured incident/event resolution; canonical historical retrieval; pathway-backed India impact/hypotheses; local embeddings and task-specific retrieval; broader linguistic coverage and robust catch-up/material-change regression verification.
