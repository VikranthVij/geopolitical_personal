# Phase 1 — relationship and escalation verification

Date: 2026-10-30. Status: implementation verified in an isolated environment; not deployed to the live application. Historical data repair remains explicitly out of scope.

## A. Initial diagnosis

Inspected event_thread_resolution.py end-to-end, incident_resolution.py fingerprints/audits, claims.py attribution/polarity/epistemic extraction, collector.py stage/savepoint ordering, feature6.py assessment and material-change paths, main.py API readers, frontend/app/page.tsx consumers, SQL migrations 001–012, existing unit/API/integration suites and October 30 diagnostic artifacts. Git main/HEAD and local origin/main ref were both 53ac5604a947ec28e6c08a7f67458ebe2ae2d50e at entry. Existing dirty work was preserved; source hashes/backups were captured under /private/tmp/phase1-before, not added to Git.

### Executed relationship flow and defects

1. Collector extracts entities, claims and evidence, resolves document→incident, then calls resolve_incident_to_thread inside a savepoint. Failure audits preserve acquired intelligence. Feature 6 is a separate later stage.
2. Candidate retriever searches bounded indexed thread profiles by participants/actors/targets/locations/domains and occurrence/reporting windows; these are retrieval signals, not causal evidence.
3. Previously _relationship_cues recognized generic retaliation/response words. _candidate_signals promoted a cue to an explicit relationship whenever participants overlapped, without identifying its object. Separately, two shared participants/domain/near occurrence times could establish membership without an incident-specific reference.
4. Previously _select_related_member picked the latest member sharing a participant and reused the first relationship cue. It could therefore persist a response edge to a member never identified in the evidence. Multiple matching members were not checked.
5. Assignments and relationships were persisted, cached profiles/status refreshed, provisional empty thread cleanup performed by the normal resolver, and the audit cached by resolver version.

### Downstream flow and defects

Feature 6 does NOT directly consume relationship labels. The effect is indirect: resolver membership determines which incidents/claims/text are aggregated. _importance previously scored escalation from substrings such as retaliat/escalat and added incident-count contribution. Military material changes used the same raw keywords when aggregate importance rose. Thus a weak membership edge expanded the aggregate, and conditional planning vocabulary could label that aggregate as executed escalation. In addition, incident importance was incorrectly passed the whole thread's incident count, conflating incident and thread aggregation.

Contradiction/confidence algorithms, source quality rules and claim truth decisions are not changed here. The existing source-lineage support-count fix predated this task and was preserved.

## B. G20/Iran case: insufficiently grounded relationship; unsupported executed escalation

Live read-only evidence inspected for thread 3fd925a6-4395-489b-94dc-71d5f562635a; G20 incident addeff4c-850d-4d6d-966f-9e29f1ac1d38; Iran incident 871f0d0c-e3fd-4df1-98ed-5045b805022b; relationship 6548426e-6ed9-4e3a-9641-4dca69f1ae32.

Exact stored G20 excerpt:

> The G20 foreign ministers' meeting in Atlanta faces early divisions over Russia's participation, possible renewed US strikes on Iran and global trade tensions, with Washington struggling to build consensus on key international issues

Exact stored Iran excerpt, used unchanged in regression fixtures:

> Washington has urged regional partners to prepare for potential Iranian retaliation as President Donald Trump weighs renewed military action, while Vice President JD Vance reportedly proposes peace talks with Tehran

The persisted RESPONDED_TO evidence cites claim 1dd43036-3673-445d-a471-19703c478273 and the Iran excerpt. Signals are shared participant/target context, military domain, nearby publication dates with unknown occurrence time, and a generic retaliation cue. The excerpt does not identify the G20 meeting as its response target. It supports planning/possibility/consideration and a reported peace-talk proposal, not an executed strike. This does not prove the wider geopolitical developments are unrelated; it establishes that the specific directed edge is insufficiently grounded.

The live thread is CRITICAL/5, with escalation HIGH. Its MILITARY_ESCALATION record says importance rose MEDIUM→CRITICAL. The old resolver membership and raw keyword assessment explain the observed outcome. Whether a threat deserves high strategic importance is a separate question; no blanket downgrade of threats was introduced.

Corrected isolated behavior using these exact excerpts: retain separate assignments, REVIEW_REQUIRED with candidate/cue evidence, no edge, no MILITARY_ESCALATION, no change to the G20 thread's prior importance. The live historical edge and material-change record were NOT edited or reassessed.

## C. Changes implemented

| File | Functions/behavior | Why |
|---|---|---|
| backend/app/claim_semantics.py (new) | assertion_semantics | Shared deterministic interpretation of actual/reported occurrence, threat, warning, plan, consideration, intention, decision, conditional possibility, denial, negation, speculation and unknown. Reads existing claim metadata; labels describe assertions, not truth. |
| backend/app/event_thread_resolution.py | _relationship_cues, _grounded_relationships, _candidate_signals | Extract exact cue/complement offsets and preserve source spans/attribution; require a specific multiword occurrence/proposition reference to one candidate member. Broad entity/time/domain continuity alone is review evidence. Denied/prospective/generic/multiple targets do not establish a confirmed edge. |
| same | _relationship_members, retriever, _select_related_member | Load bounded member propositions, verify the asserted subject rather than an earlier attack merely mentioned as context, and select the evidenced member rather than the latest shared actor. More than 50 members remains review-only; incomplete retrieval cannot hide ambiguity. |
| same | build_incident_context, resolve_incident_to_thread, audit version | Load existing claim metadata/spans, revalidate target at persistence, retain cue/subject/target/document/claim provenance in existing JSON evidence. Resolver becomes DETERMINISTIC_STRUCTURED_THREAD_V3 / thread-v3 so old decisions are not reused as current-rule audits. No historical backfill. |
| backend/app/feature6.py | _military_escalation_support, _importance | Executed escalation requires affirmative actual/reported offensive-action evidence; routine activities and unspecified military action are insufficient. Plans/threats/decisions remain significant context without claiming execution. Response targets do not transfer earlier attack execution onto a new diplomatic response. Assessment basis includes semantics and supporting claim provenance. |
| same | run_feature6 | Incident importance uses one incident; thread aggregation retains thread count. Military importance-rise changes require current-incident executed-action support. Other existing importance-rise consequence types also require actual/reported claim support. Supporting claims/spans are stored in existing new_state JSON; existing dedupe keys retained. |
| backend/tests/test_event_thread_resolution.py | existing fixtures | Positive tests now carry a real target proposition/member instead of a bare relationship enum; entity/time-only positive assumption becomes a negative review test required by this task. |
| backend/tests/test_event_thread_resolution_integration.py | five-incident fixture | Names each preceding target explicitly; retains original five-member/four-edge/idempotency assertions. |
| three new test files | test_relationship_grounding.py, test_escalation_semantics.py, test_relationship_escalation_integration.py | Target, semantic and persistence/downstream regression coverage. |

No schema/migration change. No top-level API contract change; JSON importance/evidence/new_state bases gain explanatory metadata using existing columns. Frontend reads dimensions/reason as before; no frontend source edit. Existing valid relationship enum values remain. Broad RELATED_TO fallback is no longer manufactured from contextual overlap. Original confidence/importance regression assertions were retained and pass, including unverified nuclear-action status reports. No LLM, embedding, source scoring or contradiction-engine redesign.

## D. Regression coverage

Positive: explicit response maps to a unique occurrence, supported prior statement maps to a response, indirect reference inside an asserted source proposition resolves, all existing causal relation labels retain target grounding, a specific older member is selected instead of a later shared-context member. Persistence verifies subject/target IDs, claim/document/source spans, cue offsets, audit and relationship idempotency.

Negative: country/leader/security-domain/time overlap, two shared participants with known nearby dates, generic tensions/developments/retaliation, multiple targets including comma-separated alternatives, unrelated diplomacy alongside an attack, denied/prospective relationship, candidate references to some earlier incident rather than its own subject, incomplete member retrieval. Multiple matching threads stay AMBIGUOUS; multiple member targets or relationship classifications remain review-only. No first/latest-candidate selection.

Semantics: actual attack, reported occurrence with attribution, threat, warning, consideration, plan, conditional possibility, confirmed decision, intention, denial, metadata polarity/uncertainty, significant threat retaining CRITICAL importance without execution, actual status report retaining high importance, diplomatic response not inheriting the earlier attack, routine exercises/deployments and unspecified military action not automatically implying escalation.

Database/downstream: exact G20/Iran text produces no assignment/edge/escalation/prior-thread importance increase. Actual uniquely grounded military action raises importance and produces exactly one MILITARY_ESCALATION after repeated runs, with supporting source spans. Claim remains UNVERIFIED independently of importance. Prospective/denied military and economic statements produce no importance-rise material changes. Actual sanctions still produce ECONOMIC_CONSEQUENCE with its own claim support. Existing Feature6 contradiction, confidence, independence, failure isolation and material-change regression suite also passes.

## E. Verification results

Final full result:

| Suite | Discovered | Executed | Passed | Failed/errors | Skipped/blocked |
|---|---:|---:|---:|---:|---:|
| unittest classes, including DB/API integrations | 106 | 106 | 106 | 0 | 0 |
| Standalone test_feature6.py functions | 25 | 25 | 25 | 0 | 0 |
| Combined | 131 | 131 | 131 | 0 | 0 |

The above total is the final run after all source changes; intermediate runs found four old bare-cue/contextual fixture expectations and actual-status/nominal-report handling. Fixtures were made evidence-specific, and status/nominal reported actions were supported without changing confidence or importance assertions. Subsequent regressions caught the earlier-action-as-context boundary and preserve it explicitly. No test failures were hidden or skipped.

### Isolated environment and commands

Used the already installed pgvector/pgvector:pg16 image (`--pull=never`), separate container geopolitical-phase1-db-20261030, database phase1/user phase1, project network for connectivity, no published DB port, tmpfs `/var/lib/postgresql/data`, no development volume. Test password is a disposable fixture value only. API test process uses localhost:8000 inside a separate container with no host port; collection_loop replaced with an idle coroutine before startup. All seven DB test variables and three API base URL variables were pointed at this isolated environment. A runner asserts the DB hostname/database before starting. App/test/migration mounts read-only; bytecode disabled. The live API/web were not rebuilt/restarted or mounted to changed source.

Commands executed (from repository root):

```sh
docker run -d --rm --pull=never --name geopolitical-phase1-db-20261030 \
  --network geopolitical_personal_default --tmpfs /var/lib/postgresql/data:rw \
  -e POSTGRES_USER=phase1 -e POSTGRES_PASSWORD=phase1-test-only \
  -e POSTGRES_DB=phase1 pgvector/pgvector:pg16

docker compose run --rm --no-deps -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL=postgresql://phase1:phase1-test-only@geopolitical-phase1-db-20261030:5432/phase1 \
  -v "$PWD/backend:/app:ro" -v "$PWD/backend/tests:/tests:ro" \
  -v /private/tmp/phase1_full_suite.py:/tmp/phase1_full_suite.py:ro \
  api python /tmp/phase1_full_suite.py

docker compose run --rm --no-deps web sh -lc \
  'npm run build && ./node_modules/.bin/tsc --noEmit --incremental false'
docker compose config -q
git diff --check
```

Temporary runner uses unittest.defaultTestLoader.discover('/tests', pattern='test_*.py'), executes every standalone test_* function in test_feature6 using inspect.getmembers, fails on any failure/error, and prints discovered/executed/pass/skip counts separately. It configures CLAIM_TEST_DATABASE_URL, EVIDENCE_TEST_DATABASE_URL, INCIDENT_TEST_DATABASE_URL, INCIDENT_API_TEST_DATABASE_URL, EVENT_THREAD_TEST_DATABASE_URL, EVENT_THREAD_API_TEST_DATABASE_URL, FEATURE6_TEST_DATABASE_URL; EVIDENCE_API_BASE_URL, INCIDENT_API_BASE_URL and EVENT_THREAD_API_BASE_URL. It starts isolated uvicorn only after disabling collection and waits for health before API tests. Outputs remain temporary under /private/tmp; no generated logs/test data/secrets were added to the repository.

A fresh isolated cluster applied all migrations 001_initial.sql through 012_confirmed_event_activity.sql. The full suite ran again after the clean-chain pass. No migration added, so no new upgrade path required. Indexed retrieval at100/500/1000 profiles remains bounded to50. This is a synthetic performance check, not a production load benchmark.

Python in-memory compilation of app/tests passed without source writes. Next production build and explicit TypeScript noEmit check both exited0 in a separate container with existing dependencies, leaving live assets unchanged. Compose config and diff whitespace checks passed. Existing DB-backed API tests verify list/detail/timeline/importance/provenance response compatibility. No new live browser rollout claim is made: corrected backend code is not deployed to live services by design.

## F. Remaining limitations

- Target grounding is deliberately narrow and deterministic: exact normalized multiword proposition reference to a member title or asserted claim subject. It does not solve paraphrases, multilingual references, coreference such as 'that earlier attack', alias equivalence inside propositions, or complex event-time disambiguation. Those remain review-only rather than guessed.
- Candidate retrieval remains bounded to50 profiles and50 members per profile. Oversized member sets are not automatically resolved. Relevant candidates outside retrieval bounds can be missed; this is an existing retrieval limitation, not authority for arbitrary target selection.
- Semantic scope is conservative at statement level; mixed clauses may be held even where an analyst can separate a plan and an actual event. These labels are source assertions, not verified truth. No parser or LLM was introduced.
- Importance remains the existing broad dimensional heuristic. This task fixes execution/relationship propagation; it does not claim calibrated strategic significance or verify publisher claims. New-actor and geographic-expansion detectors remain separate membership/context heuristics, not executed-military-action evidence.
- Existing legacy relationships, importance and material changes remain in live data. Reprocessing/deployment and any historical correction require a separate reviewed plan. thread-v3 prevents cache reuse only for future invocations; it is not a historical repair job.
- Earlier dashboard status/watch/filter/evidence-display defects remain outside this implementation scope.

## G. Database and Git safety

Live DB was queried only with read-only transactions. No live writes, fixture insertion, backfill, reassignment, merge, edge deletion, material-change regeneration or manual reassessment was issued. The existing live collector continues independently on its old image. The exact case snapshot is identical before/after, and every pre-existing keyword-candidate document retains its incident/thread assignment. An intermediate snapshot had identical table counts. The final snapshot caught the independently running live collector completing its next hourly cycle:44 new documents/incidents/threads,52 new claims and4 collection-run rows. Final counts:1040 documents,1041 incidents,1040 threads,1743 claims;120 contradictions,1 material change,1 incident relationship and12 migrations remain unchanged. Keyword candidates grew from33 to35 through newly collected reporting; comparing the existing IDs individually confirms no reassignment. This normal background ingestion ran the old live image; it was not triggered by a test or live restart. Therefore the live database was not globally frozen: it changed through its own authorized running collector, while this task issued no live mutation commands and preserved the inspected historical records.

The disposable tmpfs test container was stopped after verification; no persistent test volume was created and the original development volume was never altered by test commands. Live API/web were not restarted or rebuilt. No migrations added/edited. No installs/downloads, branch switches, staging, commit, push or unrelated cleanup. Pre-existing dirty source/docs, untracked migrations010–012, verification artifacts and .DS_Store files preserved.

Task changes:4 existing files (two app modules, two resolver test modules);4 new Python files (shared semantics and three test modules);this report. Existing unrelated modifications listed by git status remain pre-existing. Generated test logs/scripts stay outside repository. The prior source/config hash manifest shows no changes outside these intended paths.

## H. Recommended next stage

Review this implementation and approve a separate rollout/data-correction plan. First run a read-only shadow audit of the specific legacy relationship and affected importance/material change with target-grounding evidence and before/after IDs; decide how to preserve an audit trail if a correction is authorized. Do not silently delete/reassign history. Then deploy the reviewed image and verify affected list/detail consumers. Historical four-group reconciliation remains unresolved and should use these stricter rules; no new intelligence milestone is recommended before correctness and auditability are accepted.


## Subsequent shadow-audit review — 2026-10-30

The original131-test result above is historical for the Phase1 local tree. The later master-task live shadow audit found and corrected a PLAN-pattern false match on plant/plane and narrow affirmative-action morphology omissions; added regressions and SELECT-only audit-gate tests now pass. Full local tree135 tests passed; selectively staged self-contained candidate130 passed, including all isolated DB/API integrations and25 standalone functions in each total. Five unrelated local extraction/dashboard tests are intentionally outside the commit. See PHASE_1_LIVE_SHADOW_AUDIT_2026-10-30.md for exact scope, evidence, safety and deployment limitations.

Existing migrations010–012 are included as resolver reporting/activity prerequisites so a clean clone can execute the committed resolver. No new migration was authored or applied to live data. The prior unrelated source-lineage support-count edit remains preserved locally and excluded from the Phase1 commit. Live services remain on their existing image; Git synchronization is not deployment.
