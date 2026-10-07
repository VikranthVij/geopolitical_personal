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

## Feature 2 — Structured claim extraction (2026-10-07)

### Implementation

- Added a replaceable `ClaimExtractor` protocol with a deterministic rule implementation. No LLM, cloud service, embedding, or new runtime dependency is used.
- The collector persists extracted claims after entity mention persistence and incident assignment. Exact-content duplicate documents reuse the existing incident while receiving document-specific claim source links/spans.
- Migration `005_structured_claims.sql` extends existing claims and adds `claim_source_spans` and `claim_entities`; it does not create a parallel claims table.
- `GET /documents/{document_id}/claims` exposes claim type, exact statement, status, unverified truth confidence, extraction confidence/method, epistemic status, attribution, normalized fields, exact source spans, and entity links.
- Supported deterministic rules cover the nine project claim types. Negation and explicit denials stay distinct from affirmed occurrence claims; reported/attributed assertions remain labelled; quantities retain operators and qualitative wording; time expressions are never given a date without source precision.
- Within a document, only candidates with identical normalized predicate, polarity, epistemic/intent, and attribution signatures collapse. The original spans are retained. Lexical paraphrases remain separate rather than being semantically merged.

### Pass 1 — Automated

- 26 host unit/regression tests passed. The DB integration test was skipped in the host environment because it has no database URL; it was run separately in the API container and passed.
- Python compilation, `docker compose config -q`, and `git diff --check` passed.
- Migrations 001–005 applied to the current database and a separate empty temporary database. The temporary database was dropped after validation.

### Pass 2 — Integration and database inspection

- A rollback-only PostgreSQL integration test created a document, persisted Feature 1 entities/mentions, extracted claims, source spans, and entity links, then processed the same document again. Claim and span counts stayed unchanged; negated claims remained negated.
- A separate temporary fixture was committed, read through `GET /documents/{id}/claims`, inspected directly in PostgreSQL, and removed. The API returned 8 structured claims for the fixture: occurrence, attribution, quantitative, time, and denial/response records. Actor/object/target links pointed at canonical entities. Direct inspection found 8 source spans and zero duplicate span keys. The fixture source/document/event were confirmed absent after cleanup.
- The rebuilt API started successfully and migration 005 is present in `schema_migrations`.

### Pass 3 — Adversarial

- Tests cover negated occurrence/response/status, mixed-predicate negation scope, denials, “no evidence” language, direct vs attributed assertions, Reuters reporting chains, possible/uncertain language, reported and speculative intent, exact/approximate/ranged/qualitative quantities, exact/low-precision temporal expressions, passive voice, multiple predicates, repeated exact claims, lexical paraphrases, and “at least” false-location prevention.
- Bugs found and fixed during this pass: noun “strike” produced a false event predicate; “at least” could be misread as a location; a modal/negated status could be recorded as affirmed; distinct “launched” and “fired” predicates collapsed; qualitative quantities lost their unit; passive subjects could be assigned as actors; and an outer Reuters attribution was initially flattened. Regression tests now cover these cases.

### Performance and limitations

- CPU-only extraction for the checked-in multi-sentence fixture took 0.193 s / 100 documents (1.929 ms per document), 0.892 s / 500 (1.785 ms/doc), and 1.759 s / 1,000 (1.759 ms/doc). These figures exclude database writes, feeds, and API serialization. Peak transient memory was small in this fixture run; timings are host-specific.
- This is bounded rule-based extraction, not general language understanding. It may miss unlisted predicates, entities, complex coreference, cross-sentence argument links, and intricate reporting grammar. Temporal normalization deliberately leaves weekday/relative expressions unresolved without a safe reference date. It does not merge semantic paraphrases. Extraction confidence is not claim truth confidence; the latter remains `UNVERIFIED`.
- At the Feature 2 milestone, evidence extraction had not yet been implemented; Feature 3's evidence/provenance foundation is recorded below. Contradiction detection, truth confidence, importance, incident/event resolution, historical/India analysis, retrieval, and LLM evidence analysis remain unimplemented.

## Feature 3 — Evidence extraction and provenance foundation (2026-10-07)

### Implementation

- Extended the existing `evidence` and `claim_evidence` schema; migration `006_evidence_provenance.sql` adds explicit evidence/document links, exact evidence spans, evidence/source provenance, evidence-to-evidence lineage, source-specific claim/evidence relationships, identity keys, extraction metadata, and indexes.
- Evidence types reuse the existing project enum, including official statements, satellite imagery, geospatial data, video, photographs, documents, flight/ship/radar tracking, eyewitness reports, physical evidence, OSINT analysis, and OTHER.
- The deterministic extractor recognizes only explicit bounded evidence references. It preserves source spans, provider/reference IDs when present, directness (`DIRECT`, `REPORTED`, `DERIVED`, `UNKNOWN`), attribution, publication context, and relationship cues. Negative/no-confirmation references stay `INCONCLUSIVE`.
- Exact explicit evidence IDs are reused across reports. Reuters/AP/BBC fixture documents with `IMG-2026-A77` point to one evidence row; `IMG-2026-A78` stays separate. Two generic “satellite imagery” descriptions without identifiers do not merge. A cited publisher is linked to a particular document only when the exact evidence identity matches; otherwise the publisher citation remains without a guessed article target.
- OSINT analysis linked to geospatial evidence in a sentence is stored as derived from that evidence. `GET /documents/{document_id}/evidence` returns evidence metadata, source text spans, document relationships, directness, attribution, origin/cited sources, lineage, and claim/evidence relations.

### Verification

- Full host suite: 30 passed, 3 database/API integration tests skipped because host Python has no configured database URL or `httpx`. The 3 skipped tests were run successfully in the API container against the live PostgreSQL service and HTTP API, including Feature 2 claim persistence regression.
- Migration 006 applied to the existing database, and migrations 001–006 applied in sequence to a disposable clean database. The seven expected evidence/provenance tables are present; the temporary database was dropped.
- Database-backed checks verified exact span slicing, shared explicit identity across three documents, separate distinct identity, non-merging of unreferenced generic descriptions, all four persisted claim/evidence relations, source-specific claim relationships, CITES document resolution for a matching identity, DERIVED_FROM lineage, and idempotent reprocessing. The temporary HTTP API document/source/evidence fixture was deleted and direct SQL confirmed no fixture document, source, or evidence remained.
- Python compilation, Compose configuration, and `git diff --check` passed. API health returned `ok`; OpenAPI contains `GET /documents/{document_id}/evidence`; the dashboard returned HTTP 200 after a frontend build.
- Extractor-only timings on the checked-in fixture: 100 documents 0.0439 s (0.439 ms/doc), 500 documents 0.2188 s (0.438 ms/doc), and 1,000 documents 0.4336 s (0.434 ms/doc). These exclude database, network, and API costs.

### Boundaries and limitations

- Evidence extraction is deterministic and bounded; it can miss evidence forms outside its rule set. A report's source is not automatically treated as its evidence.
- Evidence identity is conservative and requires an explicit identifier or URL. Similar descriptions, different URLs, or different publishers alone do not establish identity or independence.
- Provenance/lineage is an independence foundation, not a final independence score. Unknown origins and unresolved citations remain explicit/unknown.
- Claim/evidence relationship cues are bounded; ambiguous multi-evidence or multi-claim sentences remain `INCONCLUSIVE`. An official statement never automatically supports the underlying event claim.
- At the Feature 3 verification point, incident/event resolution, truth confidence, contradiction detection, embeddings, and LLM analysis were not implemented. Feature 5 below subsequently added incident-to-event-thread resolution.

## Feature 4 — Structured document-to-incident resolution (2026-10-07)

### Implementation and boundaries

- Migration `007_incident_resolution.sql` adds normalized actor/action/target/object/location/time/quantity/consequence/response fields, supporting entity IDs, explicit evidence identity links, candidate retrieval indexes, and `document_incident_resolutions` audit rows.
- `backend/app/incident_resolution.py` exposes `IncidentCandidateRetriever` / `IncidentResolver` interfaces and deterministic implementations. Candidate retrieval is capped at 50 and filters on indexed canonical entity roles, action, event time, explicit evidence identity, and linked entities. Resolution uses structured claim roles and exact evidence identities; it contains no text-similarity, embeddings, vector search, or LLM.
- Matching requires multiple structured signals and time compatibility or evidence identity plus other signals. Actor/target conflict and major exact-time conflicts prevent matching. Shared evidence alone does not merge. Quantity discrepancies remain visible in the audit without becoming a split rule. Equal candidate matches remain `AMBIGUOUS`; multi-occurrence documents are `REVIEW_REQUIRED`.
- New reports stage entities, claims and evidence before resolution. Claims receive a document-scoped canonical key, so different reports attached to one incident retain independent claims and spans. Evidence identity can be shared while document/source provenance remains linked. Resolver failures preserve the provisional incident and Feature 1–3 data with a `RESOLUTION_FAILED` audit state.
- `GET /documents/{document_id}/resolution` and `GET /incidents/{incident_id}` expose the incident fingerprint, attached documents, candidates considered, match reasons, conflicts, status, evidence and method. A controlled dry-run/apply command is provided at `backend/app/backfill_incident_fingerprints.py`; it indexes existing structured claims/evidence without merging or reassigning legacy records.
- At the Feature 4 verification point, incident-to-event-thread relationships were not yet implemented. Feature 5 below subsequently added that layer. Truth confidence, contradiction, importance, India relevance, embeddings, vector retrieval, RAG, and LLM analysis remain outside Feature 4. The current schema assigns one incident per article; articles with multiple distinct occurrence predicates are explicitly held for review rather than decomposed.

### Verification results

- Host regression suite: 44 passed and six DB/API tests skipped when no database URL is configured. The complete 50-test suite then passed inside Docker, including six PostgreSQL/API integration tests. Feature 1–3 extraction and persistence suites passed in the same run.
- Database fixture verified Reuters + AP reports at 18:30/18:32 with quantities >20/around 25 and shared explicit image ID join the same incident; the 03:00 UTC next-day report remains a separate incident. Database inspection confirmed two incident IDs, three document resolution records, separate extracted claims per report, and two source-document links to one shared evidence identity. Reprocessing a resolved document returned its prior assignment without adding incident/resolution records.
- Adversarial tests cover same actor/action/target at different exact times, time/target/actor mismatch, quantity discrepancy, evidence match/conflict/alone, low precision time, partial unknown actors, partial explosion/strike reports, candidate ambiguity, and potential multi-occurrence review.
- Controlled 50-report scenario: five known incident groups (10, 8, 12, 9 and 11 reports) resolved to exactly five expected incidents. Three groups deliberately shared actor/action/target/location but had attack times hours apart; no false cross-merge occurred. Wording is represented through the distinct structured fingerprints passed to the resolver; this is a deterministic resolver acceptance test, not an evaluation of general-language extraction.
- False-merge: same actor/action/target/location at 10:00 and 18:00 UTC produced separate incidents. False-split: same actor/target/location/evidence with quantities 20+ vs ~25 and times two minutes apart matched one incident.
- CPU resolver-only 50-report timing measured 0.001498 seconds in the final run; the automated test asserts the resolver stays below 1.0 second. This excludes SQL retrieval and network. Migration 007 applied; the full 001–007 chain passed in a temporary clean PostgreSQL database, then the temporary database was dropped. Live API restarted, health/OpenAPI routes were checked, `docker compose config -q`, Python compilation and `git diff --check` passed.
- Existing development records were not re-resolved. The explicit dry run counted 14 prior documents; the index-only `--apply` then populated 14 incident fingerprints and zero resolution audits, without changing any document assignment. New ingestion writes its own audit row.

## Feature 5 — Incident-to-Event Thread resolution (2026-10-07)

### Implementation and boundaries

- Migration `008_event_thread_resolution.sql` adds thread lifecycle/status and time fields, structured per-incident context, indexed aggregate profiles, incident-to-incident relationship edges, and per-assignment audit records.
- The collector invokes deterministic Feature 5 resolution only after Feature 4 document-to-incident resolution. Distinct incident rows are retained; one primary thread membership is stored on each incident. Exact-content duplicates remain attached to their existing incident.
- Candidate retrieval uses canonical entity IDs, context domains, and time with a hard cap of 50 thread profiles. Time/location alone do not merge. Shared participant and context-domain continuity plus a bounded 30-day window support ordinary continuation. Explicit response/cause language can support long-gap continuity. Multiple matches are `AMBIGUOUS`; plausible but incomplete continuity is `REVIEW_REQUIRED`.
- Response/causal relationships are separate rows with a unique incident-pair/relation key. Thread titles are deterministic from canonical structured names/domains. Inactivity does not imply conclusion. Resolver failures preserve the provisional incident and use an isolated savepoint plus `RESOLUTION_FAILED` audit.
- Debug APIs: `GET /incidents/{incident_id}/event-thread`, `GET /event-threads/{event_thread_id}`, `GET /event-threads/{event_thread_id}/timeline`, and `GET /event-threads/{event_thread_id}/relationships`. `python -m app.backfill_event_threads` previews in a rollback-only transaction; `--apply` is the explicit persistence mode.

### Verification results

- Host Python compilation and all 64 backend tests passed; nine database/API tests skip in the host-only run without their environment variables. The full 64-test suite also passed inside Docker with all PostgreSQL/API integration tests enabled, covering Features 1–5.
- Live PostgreSQL acceptance grouped five distinct related incidents into one Event Thread, persisted four `RESPONDED_TO` edges, retained a separate unrelated incident despite shared place/time, and verified repeated resolution added no audit or membership. All fixture rows were rolled back.
- Indexed candidate retrieval was exercised against 100, 500, and 1,000 profiles: 0.0010 s, 0.0006 s, and 0.0007 s in the final recorded run, returning no more than 50 candidates each time. The five-incident acceptance and API routes passed against the running Docker services.
- The default database backfill preview inspected 15 existing incidents and 15 provisional threads, proposed new-thread assignments for all 15, and rolled back. No existing records were changed by preview. The preview also showed that current legacy incidents lack enough structured relationship context to join one another.
- Migrations 001–008 applied in order to a disposable clean PostgreSQL database, which was dropped afterward. `npm run build` completed successfully for the frontend; the running API health returned `ok`, and the dashboard returned HTTP 200.

### Boundaries and limitations

- Thread context depends on persisted canonical entity roles, Feature 4 fingerprints, and bounded deterministic claim-language cues. Unsupported/unresolved entity mentions remain unknown; this is not general-language causal inference.
- The collector creates a new provisional thread for each new incident, then consolidates the incident into a selected existing thread only when deterministic rules support the match. Historical assignments remain unchanged unless the explicit backfill `--apply` mode is run.
- No thread is marked `CONCLUDED` from inactivity. The feature does not calculate truth confidence, contradiction, importance, India relevance, forecasting, or alert signals.

- At the Feature 4 verification point, differently worded coverage was not yet resolved into a shared Incident, and each new incident retained its own provisional Event Thread. Feature 5 above subsequently added cross-document incident resolution and conservative incident-to-thread consolidation.
- Source-independence scoring, logical contradiction persistence, explainable confidence calculations, importance calculations, and material-change resolution remain incomplete.
- Historical search/reuse/contextual interpretation and India exposure graph/hypothesis workflows have schema/API foundations only; no automatic graph relevance, causal investigation, or observations are currently produced.
- Ollama supports citation-validated event Q&A only. Embedding generation/retrieval, cache invalidation, grounded summaries, and what-to-watch generation remain incomplete.
- Broader 50-report separate-incidents/shared-thread, unrelated-semantic-events, source-copy independence, historical reuse, India causality, feed-failure, and startup catch-up end-to-end scenarios remain outside Feature 5 verification.

## Manual intervention

To enable model-backed Q&A, repair/update the installed Ollama runtime, start its local service, confirm `http://localhost:11434/api/tags` responds, and pull `qwen2.5:7b`. The Q&A path then uses the configured host URL from Docker. Feed availability and permitted excerpt retention should be reviewed before relying on any source.
