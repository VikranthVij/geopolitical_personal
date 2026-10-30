# Phase 1 live shadow audit — 2026-10-30

## A. Environment and audit boundary

Audit snapshot UTC: 2026-10-30T17:00:16.826529+00:00 (Asia/Kolkata is UTC+05:30).
Git branch main; pre-task HEAD and freshly fetched origin/main both 53ac5604a947ec28e6c08a7f67458ebe2ae2d50e, ahead0/behind0. Remote https://github.com/VikranthVij/geopolitical_personal.git. Working tree already contained the Phase1 implementation, earlier dashboard/extraction changes and untracked handover reports/migrations.

Database identity verified before evaluation: `geopolitics`, role `geopolitics`, port5432. Connection enforced PostgreSQL `default_transaction_read_only=on`; observed `transaction_read_only=on` and `transaction_isolation=repeatable read`. Every application-helper query also passed a SELECT-only wrapper rejecting non-SELECT SQL, multiple statements, SELECT INTO and row locking. Database read-only mode remains the final protection against hidden write functions. No application lifespan, migration runner, ingestion, collector or persistence function was invoked. Exactly 47 SELECT calls in the main consistent audit snapshot, then a separate read-only transaction for preservation comparison. The utility imports only read/pure helpers.

Audit utility: `backend/scripts/phase1_shadow_audit.py`. Run using existing image dependencies with local source mounted read-only, without starting the application:

```sh
docker compose run --rm --no-deps -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/backend:/app:ro" api \
  python scripts/phase1_shadow_audit.py --expected-database geopolitics
```

The container receives DATABASE_URL through existing Compose configuration; credentials are never printed. Both full local source and the exact staged candidate were audited; primary hypothetical importance outputs agree. Runtime API remains thread-v2, while evaluated source is thread-v3. The live collector remains running independently. No live container was restarted/rebuilt.

Live API image sha256:955ead168d7202636a68fbd5a275f48525ca112e43ce3d0bb18c9a5bddd201a3, started2026-10-30T15:29:32.358548338Z.
Live web image sha256:2b07854c1cd0dbb85a75d9d41bb6ffc4540706ec03d4d97efd8181abbce09843, started2026-10-30T15:28:11.021087217Z.
PostgreSQL container uses pgvector/pgvector:pg16 and the original development volume. API health reports ok/database connected and frontend HTTP200.

## B. Live baseline

| Table | Snapshot count |
|---|---:|
| `documents` | 1040 |
| `claims` | 1743 |
| `evidence` | 25 |
| `incidents` | 1041 |
| `event_threads` | 1040 |
| `event_thread_incident_relationships` | 1 |
| `material_changes` | 1 |
| `contradictions` | 120 |
| `document_incident_resolutions` | 1026 |
| `event_thread_resolution_audits` | 1026 |
| `schema_migrations` | 12 |
| `collection_runs` | 266 |

All migrations001–012 are applied in live schema_migrations. Stored resolver audits (attempts, not unique incidents):

| Version | State | Count |
|---|---|---:|
| thread-v1 | NEW_THREAD | 405 |
| thread-v1 | RESOLUTION_FAILED | 1 |
| thread-v1 | REVIEW_REQUIRED | 161 |
| thread-v2 | AMBIGUOUS | 18 |
| thread-v2 | ASSIGNED_EXISTING_THREAD | 1 |
| thread-v2 | NEW_THREAD | 419 |
| thread-v2 | REVIEW_REQUIRED | 21 |

## C. G20–Iran case analysis

- Thread: `3fd925a6-4395-489b-94dc-71d5f562635a` — G20 gathering in Atlanta clouded by Russia row, Iran tensions and trade disputes.
- Subject incident: `871f0d0c-e3fd-4df1-98ed-5045b805022b` — Iran strike-planning report.
- Stored target: `addeff4c-850d-4d6d-966f-9e29f1ac1d38` — G20 gathering.
- Relationship: `6548426e-6ed9-4e3a-9641-4dca69f1ae32`, `RESPONDED_TO`, stored thread-v2 audit `ASSIGNED_EXISTING_THREAD`.

### Actual stored documents and spans

Document `82ae7908-292a-44ca-897e-f8e43eed5f04`, incident `addeff4c-850d-4d6d-966f-9e29f1ac1d38`. [G20 gathering in Atlanta clouded by Russia row, Iran tensions and trade disputes](https://firstpost.com/world/g20-gathering-in-atlanta-clouded-by-russia-row-iran-tensions-and-trade-disputes-14056688.html). Published `2026-10-30 14:57:26+00:00`; collected `2026-10-30 15:24:08.718753+00:00`.

> The G20 foreign ministers' meeting in Atlanta faces early divisions over Russia's participation, possible renewed US strikes on Iran and global trade tensions, with Washington struggling to build consensus on key international issues

Document `c3bf3858-2b66-4a26-9ee7-22c95d7e3eb9`, incident `871f0d0c-e3fd-4df1-98ed-5045b805022b`. [Trump ready for fresh strikes on Iran? US tells allies to prepare for post-midterms attacks, says report](https://firstpost.com/world/trump-ready-for-fresh-strikes-on-iran-us-tells-allies-to-prepare-for-post-midterms-attacks-says-report-14056217.html). Published `2026-10-29 06:30:56+00:00`; collected `2026-10-30 15:24:09.165841+00:00`.

> Washington has urged regional partners to prepare for potential Iranian retaliation as President Donald Trump weighs renewed military action, while Vice President JD Vance reportedly proposes peace talks with Tehran

The response evidence cites claim `1dd43036-3673-445d-a471-19703c478273`, document `c3bf3858-2b66-4a26-9ee7-22c95d7e3eb9`, EXCERPT characters `[0,215)`. Its exact source span is the complete Iran excerpt above. Existing structured type INTENT, polarity AFFIRMED, epistemic status REPORTED. A second claim `34b373b9-bb40-45f8-bb49-7ed1b5c9496d` contains the title question with TITLE span `[0,38)`; the legacy headline claim `48d335f4-69d1-4d3e-a2a4-9d7ffbeba36e` has no source-span row. No missing span was fabricated.

The old relationship JSON contains shared participant/target context, military domain, nearby reporting dates (occurrence time unknown), and a generic retaliation cue. It does not identify the G20 meeting as the response object. The old persistence selector used the latest matching shared-participant member, not an identified response target.

### Classification and new outcome

**INSUFFICIENT_EVIDENCE**, not a finding that the wider developments are unrelated. The specific directed edge is not established. thread-v3 returns **REVIEW_REQUIRED**, zero grounded target relationships, retaining uncertainty. Generic retaliation remains available in candidate conflict evidence; it is not promoted into a confirmed response. No new audit row or assignment was persisted.

This is a leave-one-subject-out counterfactual of the stored target thread: remove the already-joined source from candidate members in memory, then apply the resolver against the remaining actual members. It tests this existing edge, not a production backfill or proposal to select an alternative canonical thread among every live candidate. No synthetic source text, dates or identity evidence is introduced.

The Iran evidence is CONDITIONAL_POSSIBILITY at statement level (potential retaliation), includes reported consideration of military action and peace-talk proposals; title questions are CONSIDERATION. These are source assertions, not verified truth. There is no affirmative execution claim supporting MILITARY_ESCALATION in either member's stored claim set.

### Importance and material-change counterfactuals

| Membership assumption | New category | Score | Escalation dimension |
|---|---|---:|---|
| source_alone | MEDIUM | 2 | LOW |
| target_alone | MEDIUM | 2 | LOW |
| existing_membership_retained | HIGH | 4 | LOW |

Stored thread importance is CRITICAL/5, escalation HIGH. Under new semantics, retaining the two incidents together hypothetically gives HIGH/4 and escalation LOW. If separately approved identity review separates them, source and target individually assess MEDIUM/2; this report does not choose/create a replacement thread ID. CRITICAL from the old combined assessment is not reproduced by the new heuristic. This is a model comparison, not a calibrated judgement that the developments have low real-world significance.

Stored material change `4b2040db-052f-45da-82cf-dd42d3cc933e` is MILITARY_ESCALATION, MEDIUM→CRITICAL, triggered by the Iran incident. Its dedupe key is `7bd31b7f5ea008baff1c7ec8055020cabfa97de6809a8228094bf7a9dd8e4e11`. New source escalation support is empty. Thus the required executed-action support gate fails, and the military-escalation record would not be emitted under the new rules. No persistent reassessment/deletion was performed. The new logic can still assign importance to planning/threats without claiming an executed action.

## D. All existing relationships

Exactly one existing event-thread incident relationship was examined; none were skipped.

| Relationship | Subject → target | Stored label / outcome | Explicit target? | New outcome | Classification |
|---|---|---|---|---|---|
| `6548426e-6ed9-4e3a-9641-4dca69f1ae32` | `871f0d0c-e3fd-4df1-98ed-5045b805022b` → `addeff4c-850d-4d6d-966f-9e29f1ac1d38` | RESPONDED_TO / ASSIGNED_EXISTING_THREAD | No; shared context and generic cue | REVIEW_REQUIRED | INSUFFICIENT_EVIDENCE |

Supporting document, claim and exact span are identified above. This is contextual overlap rather than an unambiguous target reference; no alternative target is established. Classification totals: SUPPORTED0, INSUFFICIENT_EVIDENCE1, AMBIGUOUS0, NOT_SUPPORTED0, NOT_REEVALUATED0. Full source evidence was available for this edge, so NOT_REEVALUATED is unnecessary.

## E. Broader escalation audit

Every stored claim matching military/retaliation/air-strike/missile/attack/deployment/contingency/escalation vocabulary was evaluated in memory. Counts are **claim rows**, including multiple extracted types for one sentence; they are not independent sources or occurrences. Unknown/mixed claims are not forced into an actual-escalation interpretation.

Matched claim rows: **370**. Rows eligible as offensive-action support: **44**.

| New assertion semantics | Claim rows |
|---|---:|
| ACTUAL_OCCURRENCE | 58 |
| CONDITIONAL_POSSIBILITY | 19 |
| CONSIDERATION | 7 |
| DENIAL | 5 |
| INTENTION | 5 |
| NEGATED | 2 |
| PLAN | 4 |
| REPORTED_OCCURRENCE | 55 |
| THREAT | 1 |
| UNKNOWN | 201 |
| WARNING | 13 |

### Stratified per-claim inspection

Two earliest stored examples per observed semantic class are shown below. All matched rows were classified computationally; this bounded sample is a human-review aid and is not a claim of independent factual verification of all reporting. A source type such as ATTRIBUTION is not independently counted as executed-action support.

| Claim ID | Semantics / type | Offensive support? | Exact stored statement |
|---|---|---|---|
| `5242485d-a73a-45b2-abbe-143ccb3f818e` | ACTUAL_OCCURRENCE / OCCURRENCE | True | Houthis say attacked Riyadh as loud explosions rock Saudi capital, India condemns strikes on airports |
| `ab808114-2b00-41d5-950a-cc522ccb408f` | ACTUAL_OCCURRENCE / OCCURRENCE | True | Houthis say attacked Riyadh as loud explosions rock Saudi capital, India condemns strikes on airports |
| `135d006a-5bfc-4dc0-a3ea-9e0f92b5b679` | CONDITIONAL_POSSIBILITY / OCCURRENCE | False | Iran readies harder retaliation if attacked as diplomacy faces long odds - Reuters |
| `7f0629bb-e8e8-4623-af84-efa56249c081` | CONDITIONAL_POSSIBILITY / INTENT | False | Iran readies harder retaliation if attacked as diplomacy faces long odds - Reuters |
| `c307473a-25cf-4f22-8384-8f95d2036ad5` | CONSIDERATION / OCCURRENCE | False | Has Emmanuel Macron lost control as student protests escalate in France? |
| `2a77f0c7-7499-409b-95d2-fccd1b4e87c0` | CONSIDERATION / OCCURRENCE | False | Gaza after three years of Hamas attack: What will it take to rebuild the territory? |
| `0552f780-ae0e-4027-9374-725b3501d30c` | DENIAL / RESPONSE | False | Move marks a shift from 2015, when parliament rejected joining the Saudi-led Yemen intervention, amid growing military influence over foreign policy under Asim Munir |
| `8d06063e-96c9-4fcf-8bd5-271398d7d23a` | DENIAL / RESPONSE | False | Moscow rejected Zelenskyy’s call for a 60-day ceasefire to allow Ukraine to hold presidential elections, but said Putin could order troops to halt attacks on polling day |
| `09c4c0be-2d47-45ec-9508-1832e70dbb0d` | INTENTION / INTENT | False | A Channel 12 report citing investigators said Omani co-pilot Hamam al-Hammami told interrogators he acted in retaliation for the Gaza war and wanted to die as a martyr |
| `2760e302-0452-4f92-b3d8-3d89d877e957` | INTENTION / INTENT | False | Taiwan aims to "deter war" by increasing its defence spending, the democratic island's leader said Saturday, as China uses military pressure to assert its territorial claims. |
| `03ce4c6f-d405-45a9-9410-622d0bf22def` | NEGATED / OCCURRENCE | False | Turkish Foreign Minister Hakan Fidan said Ankara’s role under the Mecca defence agreement would remain defensive and would not involve attacking another country. |
| `26af99be-c084-4636-9a51-6dbd17673473` | NEGATED / OCCURRENCE | False | As Munir's military takes on Gulf role, Pakistan's parliament is not involved - Reuters |
| `796e12df-b567-4f0f-aa61-2564cbda6009` | PLAN / TIME | False | Authorities allege Bryant communicated with shooter Jesse Van Rootselaar online, provided money, and technical assistance, and helped plan aspects of the February 10 attack |
| `80db7d2b-551a-479e-8e7c-ed4945773e60` | PLAN / OCCURRENCE | False | Co-pilot planned flydubai attack before joining airline, two Israeli officials say - Reuters |
| `08abfc2b-f150-400a-8efe-431bd9ed9d62` | REPORTED_OCCURRENCE / OCCURRENCE | True | Saudi authorities said three people were killed and 36 wounded in attacks on Riyadh's King Khalid International Airport and Abha International Airport, after Yemen's Houthis claimed to have fired on both, and the Saudi-led coalition said it struck 82 Houthi targets in response |
| `6e270f8e-010b-468a-b09b-abdbb497085e` | REPORTED_OCCURRENCE / ATTRIBUTION | False | Saudi authorities said three people were killed and 36 wounded in attacks on Riyadh's King Khalid International Airport and Abha International Airport, after Yemen's Houthis claimed to have fired on both, and the Saudi-led coalition said it struck 82 Houthi targets in response |
| `127feaa8-2553-4d11-8b0b-b6c8293992e4` | THREAT / OCCURRENCE | False | Houthis say Saudi Arabia attacked Sanaa as Yemen war escalates, threaten oil sites |
| `38adedcb-7179-473b-ad49-d9c19bfb212c` | UNKNOWN / OCCURRENCE | False | EXCLUSIVE: Attack aircraft, military vehicles visible at new China-Laos base, satellite images show - Reuters |
| `551a22e0-2476-4774-bbe2-70603b9e0378` | UNKNOWN / LOCATION | False | EXCLUSIVE: Attack aircraft, military vehicles visible at new China-Laos base, satellite images show - Reuters |
| `5ba74cbd-a7e3-4060-acfe-c1763f47b507` | WARNING / OCCURRENCE | False | Kremlin warns Lithuania that its move to lift a nuclear arms ban risks further escalation - Reuters |
| `80ebf8d8-5fd6-4932-af26-7fce6b525cd3` | WARNING / OCCURRENCE | False | Lithuania votes to lift nuclear weapons ban, Russia warns of ‘significant escalation’ |

### Every incident with previously HIGH escalation

All24 stored HIGH-escalation incident assessments were reevaluated using their complete stored claim sets and one incident per incident-level importance assessment. **21 become LOW;3 remain HIGH** for the escalation dimension. This is a hypothetical change in support classification, not an authorized update. Category changes can also reflect the incident/thread count correction.

| Incident ID | Title | Stored → hypothetical category | New escalation | New claim semantics |
|---|---|---|---|---|
| `057da5d9-eb46-4b84-8642-5e641152ecf0` | Attacks on Saudi airports kill three people, as fighting escalates in Yemen - Reuters | MEDIUM → MEDIUM | LOW | UNKNOWN |
| `07c23751-56cf-4837-a281-0e51e31a3d50` | Iran, don’t test Israel: Netanyahu’s warning to Tehran ahead of elections carries a bigger message | MEDIUM → MEDIUM | LOW | WARNING |
| `0a50fcc0-9faf-42b3-b03b-2fdaf930d544` | Houthis say Saudi Arabia attacked Sanaa as Yemen war escalates, threaten oil sites | HIGH → MEDIUM | LOW | THREAT |
| `1915b2a0-a7fe-460c-8bb6-2389200a19c3` | Trump says US 'may' join Saudi strikes against Houthis after missile attack on Riyadh airport | HIGH → HIGH | HIGH | ACTUAL_OCCURRENCE, CONDITIONAL_POSSIBILITY |
| `251bca29-64c6-4b86-8f01-8c006fcc88a1` | This Week in Explainers: Why France is witnessing its worst student protest in decades | MEDIUM → LOW | LOW | UNKNOWN |
| `303e80a4-e110-4214-8ff1-661b56d3ab4d` | ‘Already on the ground’: Pakistan confirms troops in Saudi Arabia amid Houthi escalation | MEDIUM → MEDIUM | LOW | UNKNOWN |
| `32974b78-dd10-4c65-81c6-fbd9f216abee` | ‘Stop!’ Mayor stands between riot police and student protesters in France \| Watch | MEDIUM → LOW | LOW | UNKNOWN |
| `358d3913-d76b-4350-a8c3-f4d7f9d8dd54` | Netanyahu clashes with Israel’s army chief over reported Iran strike plan days before election: Report | MEDIUM → MEDIUM | LOW | PLAN |
| `37c45ccd-4918-4b13-866e-c03720b614f7` | Lithuania votes to lift nuclear weapons ban, Russia warns of ‘significant escalation’ | HIGH → MEDIUM | LOW | WARNING |
| `3d1c467d-060f-4142-83d8-6c759d99551d` | Mecca Pact members to hold high-level talks with Iran amid escalating regional conflict | HIGH → MEDIUM | LOW | UNKNOWN |
| `55c0db91-49b2-4635-9d84-31e2d2260920` | Russian drone strike kills 13 at Ukraine’s Dnipro railway station, Zelenskyy calls for international action | CRITICAL → CRITICAL | HIGH | ACTUAL_OCCURRENCE, UNKNOWN |
| `7612362a-be92-42ae-95b4-31a301b482db` | Has Emmanuel Macron lost control as student protests escalate in France? | MEDIUM → LOW | LOW | CONSIDERATION, UNKNOWN |
| `7e5fdf00-0adb-4401-aa3b-b7e60b4db5e7` | Explosion heard in Riyadh as Saudi-Houthi war escalates | MEDIUM → MEDIUM | LOW | UNKNOWN |
| `871f0d0c-e3fd-4df1-98ed-5045b805022b` | Trump ready for fresh strikes on Iran? US tells allies to prepare for post-midterms attacks, says report | HIGH → MEDIUM | LOW | CONDITIONAL_POSSIBILITY, CONSIDERATION |
| `8cfa6758-4009-4f8f-b4ca-30e8eaddc404` | 270 killed in Yemen fighting as Saudi Arabia intercepts Houthi ballistic missile near Riyadh | CRITICAL → HIGH | LOW | ACTUAL_OCCURRENCE |
| `8f612087-5233-4db6-a2ec-186a088a5f06` | Trump shares Ukraine de-escalation proposals with Putin, Kremlin says | MEDIUM → LOW | LOW | UNKNOWN |
| `b7da3edc-609a-4cfc-9480-f68180c6a033` | Kremlin warns Lithuania that its move to lift a nuclear arms ban risks further escalation - Reuters | HIGH → MEDIUM | LOW | WARNING |
| `c1fd36ab-cb80-489f-b7e6-30d9e6a2e972` | Volvo Cars shares in record plunge on widening losses, job cuts - Reuters | MEDIUM → LOW | LOW | UNKNOWN |
| `c4213cc0-ba7c-4861-855c-ec676506775f` | India's central bank widens ambit of forex risk reserve requirement, tightens NDF rules - Reuters | MEDIUM → LOW | LOW | UNKNOWN |
| `cd45a5a7-8835-497a-b8f0-6a4966ca7b35` | Flydubai attack: Co-pilot wanted revenge for Gaza war, says report | MEDIUM → MEDIUM | LOW | INTENTION, UNKNOWN |
| `df06dcfd-1421-4338-81b4-db8a60091394` | Iran readies harder retaliation if attacked as diplomacy faces long odds - Reuters | MEDIUM → MEDIUM | LOW | CONDITIONAL_POSSIBILITY |
| `e42b7588-a263-4c45-b8bb-bb2c5a6a601c` | Riyadh airport evacuated after reported attack as Houthi threats escalate | MEDIUM → MEDIUM | LOW | UNKNOWN |
| `eae9d4e8-a15e-4406-ae0e-561e497842e3` | Houthis claim strikes on Saudi Defence Ministry, Ras Tanura refinery as regional tensions escalate | HIGH → HIGH | HIGH | REPORTED_OCCURRENCE, UNKNOWN |
| `fc65721f-035b-4156-a4c7-3cac60cbcd44` | Plane billows smoke at Riyadh airport as Houthis escalate attacks - Reuters | MEDIUM → MEDIUM | LOW | UNKNOWN |

### Affirmative reporting retained

Incident `1915b2a0-a7fe-460c-8bb6-2389200a19c3` — Trump says US 'may' join Saudi strikes against Houthis after missile attack on Riyadh airport. The headline alone is not the decision input. Supporting stored claim rows:

- Claim `08433f8b-3e38-4bab-9fd9-e21db398635a` (ACTUAL_OCCURRENCE), document `8fd0d2e5-5e13-4fbe-bfee-ca20047af739` EXCERPT [0,249): The airport in Saudi Arabia's capital, Riyadh, was attacked again Saturday and evacuated, just days after three Saudi citizens, including a pilot, were killed as the kingdom faces an extraordinary series of assaults in the new front in the Iran war.
- Claim `6a053f77-9487-4000-8efd-c79aebee8c44` (ACTUAL_OCCURRENCE), document `8fd0d2e5-5e13-4fbe-bfee-ca20047af739` EXCERPT [0,249): The airport in Saudi Arabia's capital, Riyadh, was attacked again Saturday and evacuated, just days after three Saudi citizens, including a pilot, were killed as the kingdom faces an extraordinary series of assaults in the new front in the Iran war.

Incident `55c0db91-49b2-4635-9d84-31e2d2260920` — Russian drone strike kills 13 at Ukraine’s Dnipro railway station, Zelenskyy calls for international action. The headline alone is not the decision input. Supporting stored claim rows:

- Claim `9a5fb768-8e90-4192-85f1-7669a3c5506f` (ACTUAL_OCCURRENCE), document `67e9d8db-58db-4c98-9b6a-a8d156a7c10a` EXCERPT [0,206): At least 13 people were killed when a Russian drone hit a crowded railway platform in Dnipro, as Zelenskyy urged the US and Europe to maintain sanctions on Moscow and respond to Russia’s escalating attacks.
- Claim `a54ac900-ef07-4bdc-9af3-3ca3da140b16` (ACTUAL_OCCURRENCE), document `67e9d8db-58db-4c98-9b6a-a8d156a7c10a` EXCERPT [0,206): At least 13 people were killed when a Russian drone hit a crowded railway platform in Dnipro, as Zelenskyy urged the US and Europe to maintain sanctions on Moscow and respond to Russia’s escalating attacks.

Incident `eae9d4e8-a15e-4406-ae0e-561e497842e3` — Houthis claim strikes on Saudi Defence Ministry, Ras Tanura refinery as regional tensions escalate. The headline alone is not the decision input. Supporting stored claim rows:

- Claim `aabea71d-22a8-4fbb-b95f-d937183129a1` (REPORTED_OCCURRENCE), document `23b41519-abd1-4ecb-a711-bb8c7ad9fa8c` EXCERPT [0,221): Yemen’s Houthi rebels on Tuesday claimed to have struck Saudi Arabia’s Defence Ministry in Riyadh and the country’s largest oil refinery at Ras Tanura, escalating hostilities between the Iran-aligned group and the kingdom

Attribution is preserved: e.g. Houthi claimed strikes remain reported actions, not verified truth. The speculative US-joining headline is separated from its source claims reporting an airport attack. Repeated source text in different claim rows is not independent corroboration.

### Code-review corrections discovered by this audit

The prior PLAN regex `plan\w*` also matched **plant** and **plane**. Exact stored evidence about a damaged pharmaceutical plant was mislabeled as planning, and an aircraft headline was mislabeled PLAN. The pattern now enumerates planning/preparation words. A narrow offensive/action morphology omission also lost affirmative “attacked” and some reported casualty consequences; attack/strike/missile inflections and executed “killed” support were added with regressions. No confidence/source credibility/contradiction rules were expanded.

Regression fixtures use the exact plant excerpt, plane headline and Riyadh headline inspected here, alongside synthetic boundary cases explicitly labelled as fixtures. A source sentence can still contain both an actual attack and a prospective threat; statement-level semantics can conservatively retain the threat/uncertainty and miss a separable actual clause. This limitation is visible, not reclassified as evidence that an attack did not happen.

## F. Hypothetical correction review list — no changes applied

If separately authorized, review rather than blindly delete:

1. Relationship6548426e-6ed9-4e3a-9641-4dca69f1ae32 and its source thread-v2 audit: retain original provenance and append an auditable superseding decision if a correction is approved.
2. Incident871f0d0c-e3fd-4df1-98ed-5045b805022b membership, thread3fd925a6-4395-489b-94dc-71d5f562635a aggregate/profile/status and linked event updates. No replacement canonical thread ID has been chosen. Preserve G20 and Iran incident identities.
3. Incident-level importance for each member and thread-level importance/explanation under the approved membership; do not conflate a source statement about planning with executed escalation.
4. Material change4b2040db-052f-45da-82cf-dd42d3cc933e: review an auditable supersession/withdrawal mechanism. No deletion, rewrite or replacement was performed here.
5. The24 HIGH-escalation incident rows above need claim-scope review before any bulk historical reassessment. Unknown/mixed cases and missing spans must remain explicit. Do not convert all21 hypothetical LOW cases into historical corrections automatically.

## G. Preservation and uncertainty

- All document→incident assignment pairs: existing unchanged=True, added=0, removed=0; before `84e828ae8f832241f0b4d4c8258f91d05f591d4e9c21ced1a1dfb9bf2d2e33ce` = after-existing `84e828ae8f832241f0b4d4c8258f91d05f591d4e9c21ced1a1dfb9bf2d2e33ce`.
- All incident→thread assignment pairs: existing unchanged=True, added=0, removed=0; before `205cf28837635cf07f7c322b53dc5b1d2c14ea9f6c9ccc9f6519966e2c97d0ab` = after-existing `205cf28837635cf07f7c322b53dc5b1d2c14ea9f6c9ccc9f6519966e2c97d0ab`.
- Full relationship rows: existing unchanged=True, added=0, removed=0; before `ab93dfe1b10893c169b92d14defb2aed457c97194a59c048b9fce651676721c4` = after-existing `ab93dfe1b10893c169b92d14defb2aed457c97194a59c048b9fce651676721c4`.
- Full material-change rows: existing unchanged=True, added=0, removed=0; before `0d22322d1f565006d148b0a521626275c5da33d7c45693472618543ee061b680` = after-existing `0d22322d1f565006d148b0a521626275c5da33d7c45693472618543ee061b680`.
- Full primary incident rows: existing unchanged=True, added=0, removed=0; before `7592a0c2bff50044f267c0a926ac6539015849d290cdb971063b1bb299d323dc` = after-existing `7592a0c2bff50044f267c0a926ac6539015849d290cdb971063b1bb299d323dc`.
- Full primary document rows: existing unchanged=True, added=0, removed=0; before `fd34f95c603a8c0991c21d331435c1b978b08dae2ab30ecdb31b9a39d86ef46a` = after-existing `fd34f95c603a8c0991c21d331435c1b978b08dae2ab30ecdb31b9a39d86ef46a`.
- Full primary claim rows: existing unchanged=True, added=0, removed=0; before `ee6d575ceb4c16da61a23cbdc07c69b19302ced6aa7fe1f9b7d42c1fbc9499f1` = after-existing `ee6d575ceb4c16da61a23cbdc07c69b19302ced6aa7fe1f9b7d42c1fbc9499f1`.
- Full primary source-span rows: existing unchanged=True, added=0, removed=0; before `7ea1ac6e5c6d9fcd487ca9b64ff0a27892945587522be32ae13f5239d98a40b0` = after-existing `7ea1ac6e5c6d9fcd487ca9b64ff0a27892945587522be32ae13f5239d98a40b0`.

Primary thread snapshot unchanged: True. All relevant count deltas during the final audit window are zero. Snapshots use a second read-only transaction for comparison, rather than comparing a repeatable-read transaction to itself. The collector remained active, but no independent collection run or ingestion was observed inside this short audit window. A later collector cycle can legitimately add records; that must not be attributed to the audit.

Limitations: no full-article retrieval or external fact verification; audit uses stored RSS excerpts/claims/spans. The relationship comparison is against existing members, not a global remapping proposal. Exact proposition matching can miss paraphrases/coreference. Unknown nominal headlines, rejected-proposal metadata and mixed tense/polarity require human review; a LOW support result does not prove no escalation. Importance remains an existing lexical heuristic (including substring matching), not a calibrated measure. Target evidence quality and claim truth are separate. These findings do not authorize live rollout or data repair.

## H. Deployment recommendation

**Ready for deployment review, with documented conservative limitations; not deployed or approved for automatic historical repair.** The unsafe G20 directed edge and executed-escalation interpretation are not reproduced. Genuine reported actions remain detectable, and audit-discovered planning/morphology omissions were corrected and tested. Review mixed-clause false negatives, the separate unresolved dashboard presentation issues, and a controlled rollout/data-supersession plan before any deployment. Do not begin contradiction-engine changes or new intelligence features as a substitute for this review.

## I. Verification of code and commit scope

- Full local tree:110 unittest tests plus25 standalone Feature6 functions;135 discovered/executed/passed,0 failures,0 errors,0 skips,0 blocked.
- Exact staged candidate tree:105 unittest tests plus25 standalone functions;130 discovered/executed/passed,0 failures,0 errors,0 skips,0 blocked.
- Counts differ because five pre-existing extraction/dashboard tests and their unrelated changes stay local. Candidate tests were run against the actual exported Git index, not assumed equivalent to the dirty workspace.
- Fresh tmpfs PostgreSQL cluster applied migrations001–012 for candidate validation; all database/API integrations used explicit isolated DB URLs and localhost inside an isolated API process with collection disabled. No development fixtures, live migrations, installs, downloads or restarts.
- Frontend production build and TypeScript noEmit checks passed in isolated containers. Python syntax, Compose config and working/index diff checks passed. Audit SQL-gate tests cover mutation/multistatement/SELECT INTO/locking rejection and parameterized SELECT delegation. Server read-only mode was independently observed in live audit output.
- One intermediate run failed because the new audit test imported from a path inconsistent with the mounted test directory; the import was corrected and all suites rerun. No failing test or skip is represented as passed.

The pre-existing migration010 adds latest_reported_at referenced by the resolver;011/012 supply the already-verified meaningful-activity safeguards. They are checked in as existing resolver prerequisites, not newly authored migrations or live changes. Earlier resolver title/report-time/ambiguity safeguards are retained with this self-contained module. The unrelated pre-existing Feature6 lineage hunk is excluded from the index and remains local, along with frontend, collector, entity/claim extraction, general handover/verification docs and .DS_Store files. No generated JSON payloads, private logs, temporary runners, database dumps or build artifacts are included.

## J. Git workflow and authorization

Repository policy is in docs/GIT_WORKFLOW.md and referenced by README.md and the new AGENTS.md. All future completed/tested/accepted logical changes must be scoped, committed, pushed and checked against the actual remote SHA, except when explicit instructions, failures, safety or history/authentication blockers prohibit pushing. A dirty tree is preserved and selectively staged; it is not cleaned by deletion/reset. Deployment/data repair remain separate authorizations.

This report records the pre-commit audit and verification evidence. Commit SHA/push result are reported after synchronization in the task response; no self-referential commit SHA is fabricated inside its own content.
