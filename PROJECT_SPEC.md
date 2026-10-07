# Geopolitical OSINT Intelligence Dashboard V1

## Purpose

Build a local-first intelligence system that turns public source material into traceable geopolitical intelligence. Articles are evidence-bearing documents, not the product's primary identity. The canonical chain is source → document → claim → evidence → incident → event thread, connected to canonical entities, reusable historical records, and explicit India-impact pathways.

## Locked architecture

- Modular monolith: PostgreSQL with pgvector, Python/FastAPI, an in-process background worker/scheduler, Ollama/local model behind a provider interface, and Next.js/React/TypeScript.
- Docker Compose runs PostgreSQL, API/worker, and web UI. No Kubernetes, Kafka, Redis cluster, or unnecessary services.
- PostgreSQL is the system of record. Vectors retrieve candidates; structured evidence and reasoning determine identity and confidence.
- Event thread is a persistent geopolitical situation; incident is a discrete occurrence. Articles are never incidents. Temporal proximity and embedding similarity alone never merge events.
- Preserve source lineage and evidence independence. Contradictions stay visible; confidence and importance remain separate.
- LLM outputs are grounded and labelled FACT, REPORTED_CLAIM, INFERENCE, ANALYSIS, SPECULATION, or UNKNOWN. The model cannot decide truth, credibility, final event identity, contradiction, confidence, or canonical history identity.
- India relevance has explicit causal pathways. Correlation/anomaly alone does not establish causation.
- Historical records are canonical/reusable; event-specific interpretations are separate and never mutate history.
- Incremental collection, hashes, and material-change detection prevent rebuilds and duplicate alerts.

## Intelligence models

- Sources and documents retain tier, URL, lineage, author/language/type, publication/collection times, hash, and excerpts subject to source terms.
- Claims use OCCURRENCE, ATTRIBUTION, LOCATION, TIME, QUANTITATIVE, INTENT, STATUS, RESPONSE, CONSEQUENCE; intent labels are REPORTED_INTENT, INFERENCE, SPECULATION, UNKNOWN.
- Evidence types include official statements, imagery, geospatial, video/photo/document, flight/ship/radar tracking, eyewitness, physical evidence, OSINT analysis, and OTHER. Relations are SUPPORTS, CONTRADICTS, PARTIALLY_SUPPORTS, INCONCLUSIVE.
- Contradiction types include occurrence, attribution, quantitative, location, intent, status, consequence. Scope/time-window/subset differences are not contradictions.
- Claim confidence levels: HIGH, MEDIUM, LOW, CONTESTED, UNVERIFIED, with a human-readable basis and dimensions for evidence strength, source quality/independence, corroboration, contradiction, directness, and recency.
- Importance has military, economic, diplomatic, strategic, humanitarian, geographic scope, escalation, duration, novelty dimensions at incident and event levels.
- Entities are canonical and aliased; entity/event/incident roles and relationships support retrieval and India exposure.
- India exposure levels 0–4, domains ENERGY, MARITIME, TRADE, SUPPLY_CHAINS, DEFENCE, STRATEGIC_INTERESTS, with pathway and known/inferred/speculative labels. Observations and competing hypotheses remain distinct.

## Required application surfaces

- API event list/detail/timeline/evidence/history/India-impact/changes/ask/watch, health, and collection diagnostics.
- Dashboard sections: India Relevant, Global Strategic Events, Other Intelligence. Event detail shows summary/change, timeline, supporting/contradicting/unverified claims, evidence, India impact, history, related events, watch indicators, grounded Q&A, and watch state.
- Source collectors are configurable, start with modest RSS/official feeds, record run status/counts/errors, and never bypass terms or licensing.
- Startup serves existing data immediately and catches up incrementally in the background.

## Implementation checklist

- [x] Read full supplied V1 specification and record architecture/product constraints here.
- [x] Milestone 1: Compose, PostgreSQL/pgvector schema and reproducible migrations, health checks, environment example.
- [x] Milestone 2 foundation: configurable RSS feed list, repeat-safe document ingestion, collection-run audit and URL/exact-content deduplication. Structured normalization/resolution is still outstanding.
- [x] Milestone 3: entity/claim/evidence models and deterministic extraction/provenance (entity aliases/mentions, structured claims/spans/entity links, evidence/source spans, claim/evidence relations, and document debugging APIs implemented; identity reuse is explicit-reference only and independence is a provenance foundation).
- [ ] Milestone 4: structured fingerprint candidate retrieval and incident/event resolution; no vector-only merges.
- [ ] Milestone 5: contradiction, confidence, importance, and material-update rules.
- [ ] Milestone 6: shared canonical history and contextual interpretations.
- [ ] Milestone 7: India exposure graph, observations, hypotheses, explicit causality labels.
- [ ] Milestone 8: retrieval/context builder, provider abstraction, Ollama graceful degradation.
- [x] Milestone 9 foundation: FastAPI health, event, timeline, evidence, history, India-impact, changes, related, contradictions, watch, Q&A, and collection endpoints; periodic in-process collector.
- [x] Milestone 10 foundation: Next.js event desk with India/global/other feeds and event drill-down sections.
- [ ] Milestone 11: watchlist and material changes.
- [ ] Milestone 12: adversarial, end-to-end, clean migration, startup catch-up, and regression verification.

## Engineering decisions where the specification leaves implementation open

- Use SQL migrations checked into `backend/migrations`, applied once at API/worker startup under a PostgreSQL advisory lock; all schema changes remain reviewable SQL.
- Keep source collection adapters behind a small Python protocol and seed only a short configurable RSS set. Collector runs can continue when individual feeds fail.
- Initial ingestion records a source-reported headline claim and runs bounded deterministic entity, claim, and evidence extraction. Evidence remains distinct from its reporting source/document; explicit external evidence IDs may be reused across documents, while unresolved references stay separate. Exact source spans, directness, attribution, and lineage remain queryable; extraction does not assess truth. Event Q&A uses Ollama behind the provider boundary and rejects answers without valid stored-claim citations.
- Preserve source excerpts conservatively and store URLs/metadata/hashes by default; adapters may retain only the excerpt needed for analysis.
- Run API and periodic collection in one container process for V1, with separate Compose service commands so API availability does not depend on an Ollama call.

## Manual setup points

1. Docker Desktop must be installed and running to launch the stack.
2. Ollama and a selected local model are optional for deterministic collection/API operation. On the current host, Ollama's local API is not listening and the installed CLI crashes during Metal/MLX startup; repair/update the local runtime before pulling the configured model for generated analyses.
3. RSS availability and publisher terms vary. Review and configure `backend/app/default_feeds.py` for the user's preferred sources and permitted retention.
4. Private remote access requires the user's Tailscale account/device authorization; it is intentionally not enabled automatically.
