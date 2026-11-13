# Roadmap

Which phase MetricPulse is in, and what's actually left before the next one can be called done.
Not a calendar — paced by real availability alongside an active job search, not by a date. A
checkbox here only gets checked when its phase gate is actually, verifiably met (a real test
passing, a real command run against real output) — not when time budgeted for it runs out, and
not on the strength of a design that hasn't been run yet. See `docs/WORKING_CONVENTIONS.md` for
the full reasoning behind how this file is kept.

Phase 1–3 below are the direct implementation of `docs/scoping.md`'s Section 10 rollout plan —
this file tracks the same milestones (M0–M7) as living, checkable progress; `docs/scoping.md`
stays the design record and doesn't get re-edited as implementation proceeds.

---

## Phase 0 — Core Pipeline (done)

**Gate:** ingestion → dbt → detection → decomposition → narrative → alerting works end-to-end,
is tested, and is live.

- [x] Ingestion: S3 → Redshift, 451,535 rows across 7 tables (`ingestion/`)
- [x] dbt: 11 models, 37 tests, staging → marts → metrics (`dbt_project/`)
- [x] Detection: z-score anomaly flagging (`detection/`)
- [x] Decomposition: segment contribution analysis (`decomposition/`)
- [x] Narrative: Jinja2 → 4 output formats (`narrative/`)
- [x] Alerting: SNS email (`alerting/`)
- [x] Orchestration: single-entry-point pipeline (`orchestration/`)
- [x] Django REST API + SPA dashboard, live on Render (`dashboard_api/`, `templates/`)
- [x] CI (lint + test + dbt parse), CD to Render
- [x] 15 unit tests, all pure-function, no mocking

**Named gaps, not silently dropped** (full list: `docs/infrastructure_and_deployment.md`
Known Gaps, `docs/MetricPulse_resume_project_doc.md` §14):
- CD's `dbt run` step is a placeholder — transformations are run manually on data refresh.
- Contact form email sending is disabled (`send_mail` commented out).
- Lambda deploy scripts exist and work but aren't invoked by CD — manual only.
- The dashboard's drill-down "Details" toggle is dead code — shows/hides an empty `<div>`,
  nothing populates it. (Phase 1 below is expected to finally give this real data to show.)

---

## Phase 1 — Investigation Agent (`docs/scoping.md` §§2–4)

**Gate:** a real LangGraph agent, wired into `orchestration/run_pipeline.py` and
`/api/investigate/`, produces a grounded investigation summary for a real anomaly — every
citation in it validated against actual `decomposition_results`/`drill_down_results`, not
trusted on the model's word — and the existing 15 tests still pass unmodified.

- [x] **M0** — `investigation/` skeleton: state schema, 5 deterministic nodes + 3 routing
      functions, tool wrappers around unchanged `detection`/`decomposition`/`narrative` calls,
      the one new `fetch_detail_metrics()` in `decomposer.py`. `test_investigation_routing.py`,
      `test_ambiguity_rules.py` passing.
- [x] **M1** — `synthesize`: structured-output LLM call, `validate_citation`, bounded
      retry/fallback, Jinja rendering. `test_citation_validation.py` passing; Golden Case #1
      (`docs/scoping.md` §3.8) run for real, not just designed on paper.
- [x] **M2** — Integration: `run_pipeline(run_investigation=...)`, `/api/investigate/`,
      `PipelineView` extension, dashboard button, Lambda passthrough. Full existing test suite
      re-run and green — this milestone touches the most call sites.
- [x] **M3** — `investigation.eval` command formalized; Section 8.5's metrics (grounding pass
      rate, fallback rate, golden-driver match rate) recorded from a real run, not estimated.

**Deferred, and why** (see `docs/scoping.md` for the reasoning behind each): parallel fan-out
for multi-dimension decomposition, free-form ReAct-style tool selection, multi-level drill-down,
cross-run agent memory.

---

## Phase 2 — Dataset Onboarding Agent (`docs/scoping.md` §§5–7)

**Gate:** a genuinely new, real (not synthetic) dataset — never referenced anywhere in this
repo before — goes from a raw CSV to a working `detect → decompose → narrate` cycle via
`onboarding/`, with a human confirming the schema classification along the way, and the
Phase 1 investigation agent runs against it *unmodified*.

- [x] **M4** — `onboarding/profiling.py` (Stage A) + `onboarding/classification.py` (Stage B +
      validation). `test_profiling.py`, `test_classification_validation.py` passing; Golden
      Case #2 (`docs/scoping.md` §5.6, the SaaS fixture) run for real.
- [x] **M5** — `onboarding/codegen.py`, the two additive parameters on `decomposer.py`/
      `anomaly_detector.py`, the CLI confirmation flow, the schema-fingerprint cache.
      `test_codegen.py`, `test_reconciliation.py`, `test_schema_fingerprint.py` passing — **plus**
      a full re-run of the pre-existing suite, since this milestone edits already-tested files.
- [x] **M6** — End-to-end run against a real, freshly-picked dataset (not the SaaS fixture).
      This is the actual proof of "MetricPulse works on more than one dataset" — a synthetic
      golden case can't substitute for it. Run for real against "Sample Superstore Sales"
      (8,399 rows, real public retail data, never referenced in this repo before): raw CSV →
      profiling → classification → human confirmation → codegen → a real `detect → decompose →
      narrate` cycle → the Phase 1 investigation agent, genuinely unmodified. Found and fixed six
      real bugs no synthetic fixture had exposed (see `docs/project/SESSION_LOG.md`'s 2026-08-17
      entry and `investigation/README.md`/`onboarding/README.md`'s M6 sections for the details),
      including a hardcoded Olist-only `Literal` on `EvidenceCitation.dimension` that had made
      "the Phase 1 agent runs unmodified" not actually true until fixed. **Phase 2's overall gate
      is met.**

**Deferred, and why:** real dbt/Redshift codegen (targets a local DuckDB file for v1 instead —
`docs/scoping.md` §6.1), a `dim_*` business-taxonomy remapping layer for onboarded data (§6.4),
a dashboard-based onboarding wizard (CLI only for v1 — §7.3).

---

## Phase 3 — Portfolio Close-Out (`docs/scoping.md` §9–10)

**Gate:** resume bullets and interview talking points are filled in with real, measured numbers
— not the placeholders drafted in `docs/scoping.md` §9.4. **Met.**

- [x] **M7** — Section 9.3/9.4 claims updated with real numbers from M3 and M6's actual runs.
      §9.3's unlock table now marks all four claims unlocked with their real evidence; §9.4's
      resume bullets replaced every bracketed placeholder with real measured numbers
      (`grounding_pass_rate=1.00` across 5 real M3 runs) and gained two new bullets §9.4 didn't
      have before — the real M6 cross-dataset proof (six bugs found/fixed) and the "agent runs
      unmodified against a second, independently-onboarded dataset" claim, since M6 is the actual
      proof of Goal G2 (`docs/scoping.md` §10.4), not just Phase 1/2 shipping in the abstract.
- [x] Optional: recorded demo of the M6 live onboarding run (`docs/scoping.md` §9.6) — not
      required for the phase gate, done anyway. A real, unedited `asciinema` recording of one
      live execution — profiling, classification, human confirmation, codegen, detect/decompose/
      narrate, and the unmodified Phase 1 investigation agent — against a fresh copy of the M6
      dataset (`superstore_sales_demo`, same real data, new dataset_id so the fingerprint cache
      didn't shortcut the first-time flow). Saved at
      `docs/project/demos/m6_onboarding_demo.cast` (replay: `asciinema play <path>`); a formatted
      transcript is also published as an artifact for easy reading/sharing.

---

## Initiative Status: Complete

Phase 0 (core pipeline, done pre-initiative) → Phase 1 (investigation agent, M0–M3) → Phase 2
(dataset onboarding agent, M4–M6) → Phase 3 (portfolio close-out, M7) — all four phases' gates
are met as of M7 (2026-08-19). The agentic-layer initiative described in `docs/scoping.md` is
fully implemented, tested, and documented; nothing on this roadmap remains except the one named-
optional M6 demo recording. Future work on this project either starts a new, separately-scoped
initiative (a new `docs/scoping.md`-style design doc, per `CLAUDE.md`'s "Working on the
Agentic-Layer Initiative" section) or addresses one of the honestly-named deferred items listed
under Phase 1/Phase 2 above — neither is required for this initiative to be considered done.

---

## Action Agent (`docs/action-agent-scope.md`)

A new, separately-scoped initiative (scoped 2026-10-26, revised 2026-11-01): turn a validated
investigation into a proposed action from a fixed catalog, gate it on deterministic policy and
human approval, execute it idempotently, and log it append-only. Local-only (§11 D9). Milestones
are A1–A7 to avoid colliding with the agentic-layer initiative's M0–M7 above. Per §11 D7, A1–A3
are built in this pass, then work stops for review before A4.

**Gate (minimum slice, A1–A3):** a real local run proposes an action, `policy_check` gates it,
a T1 action is approved via the CLI and survives a restart while pending, and the action log
records it — with the 20b live-test result recorded in the scope doc's decision log, and that
run's full trace (every node and LLM call, with token/cost/latency) visible in LangSmith and
reachable from its action-log row.

- [x] **A1** — Action catalog, Pydantic schemas, `policy_check`, dry-run payload builder, tests.
      `action_agent/` (see its README). 81 new test cases (`test_action_policy.py`,
      `test_action_dry_run.py`), suite 162 passing. Verified live against the real onboarded
      `superstore_sales` evidence: T1 → `needs_approval` with a full dry-run payload, T0 →
      `auto_execute`, a 30-day suppression and an ungrounded segment both rejected with reasons.
- [x] **A2** — LangSmith tracing (scope §13.1–13.2), SQLite checkpointer, `interrupt()` approval
      flow, CLI approver, `actions.db` with append-only `action_log` (trigger-enforced) carrying
      trace/thread ids, idempotency keys, approver decisions as LangSmith feedback, decision-replay
      test (§13.6).
      **LangSmith half verified live 2026-11-02** (AWS US region + workspace id; see
      `observability/README.md`): a traced `propose` → `approve` in two processes put both root
      runs (`action_agent.start`, `action_agent.approve`) in LangSmith with the same trace ids as
      the `action_log` rows, thread = proposal id, git SHA and tags in metadata; the approval
      landed as feedback (`approval`/`approve`, score 1.0, the approver's reason) on the propose
      trace. That run found and fixed a bug: feedback had been silently dropped (`project_id`
      rejected by the SDK). Plan: free Developer, 5k traces/month, 14-day retention.
      **Earlier (first key rejected):** Everything else is verified live against
      `superstore_sales` across separate processes: propose → pause → `pending` after restart →
      approve → executed, a re-approve refused, a second run for the same anomaly skipped (D1),
      replay matching, a raw `DELETE` on `action_log` refused, and the run completing with tracing
      on while LangSmith rejected every upload (fail-open, N5). 28 new tests, suite at 190.
- [x] **A3** — Live-test `gpt-oss-20b`; `propose_action` node, citation validation, 20b→120b
      escalation, fallback, token budget; shared LLM telemetry wrapper (§13.3) on all three
      agents' LLM calls.
      **Verified live 2026-11-02:** 20b alone grounded 12/12 real Olist + Superstore anomalies
      (12/12 pass policy, median 2,615 tokens, $0.0042 total). Every D2 path run live:
      escalation (a real 404 → 120b grounded), full fallback, budget skip. CLI `propose` with
      tracing on: `proposed` row names the model and attempt trail; the `llm.propose_action`
      LangSmith run carries tokens/cost/latency and the same trace id as `logs/llm_calls.jsonl`.
      Phase 1 `synthesize` and Phase 2 `classify` recorded live through the same wrapper (the
      onboarding eval still passes). Found and fixed: LangSmith metadata added after the run had
      closed. 26 new tests, suite at 247. **Per D7, stop here for review before A4.**
- [x] **A4** — GitHub Issue and notifier executors, `suppress_alerts` and `create_control`
      evaluation, undo.
      **Verified live 2026-11-02** (scratch DBs, real Olist warehouse and pipeline): D3 —
      `run_pipeline --force-alert` sent → suppressed after a CLI-approved `suppress_alerts` → sent
      again after `undo`. D4 — a watch (Credit Card `order_count` below 5, real value 0) alerted
      Payments Team once and logged `control_breached`; the second run `already_sent_today`.
      `notify_owner` via `propose --dataset-id olist` wrote the owner's outbox message.
      `open_incident --live` opened issue #1 in the private `nkousik18/metricpulse-incidents`,
      a replayed execution reused it (no duplicate), and `undo --live` closed it. 33 new tests,
      suite at 280. Bug found: a non-decomposable Olist metric crashed `propose` (BUG_LOG A4-1).
- [x] **A5** — Golden (15, labeled by Kousik) and adversarial (10) eval suite as LangSmith
      datasets/experiments; committed eval ledger + baseline report (§7.2, §13.5).
      **Built 2026-11-02; not checked — waiting on Kousik's golden labels** (`evals/action/golden.yaml`,
      15 real anomalies; check with `python -m action_agent.golden --check`). Adversarial + safety run
      live: first run found `annotate_anomaly` (T0) auto-applied from injected text in 5/10 cases →
      Kousik made it T1 → re-run `injection_bypasses = 0` (0/10), 10/10 held, `unauthorized_exec_count
      = 0` (4 probes). Also found and fixed: 20b's `functions.ProposalDraft` tool name (escalation
      7/10 → 2/10), and two onboarding confirm/edit bugs. LangSmith experiments recorded; ledger at
      `evals/ledger.jsonl`. Remaining for the gate: the golden run (`action_match_rate` ≥ 0.8,
      idempotency 0) and `--set-baseline`.
      **Golden run 2026-11-03 (Kousik's labels): `action_match_rate` 0.47 (7/15) — gate FAILED.**
      Safety and grounding all pass. 7 of 8 misses are known-cause anomalies (holidays, Monday
      rebounds) labelled annotate/suppress, where the model proposes `notify_owner`: the proposer
      sees no calendar context. No baseline accepted; next step is Kousik's decision (scope A7 log).
      **2026-11-04: scope §14 built (trusted calendar in the evidence + `calendar_event` policy
      check). Re-run: `action_match_rate` 0.67 (10/15), gate still FAILED;** safety, idempotency and
      grounding all pass. No baseline. Next is Kousik's decision (scope §14.7).
      **Done 2026-11-06. Gate PASSED on a clean tree (`de23866`): `action_match_rate` 1.00 (15/15),
      idempotency 0,** unauthorized executions 0/20, injection bypasses 0/10, 10/10 held, fake-holiday
      probe rejected, grounding 15/15 and 10/10, fallback 0, escalation 2/15, ~$0.0005/run. Built on
      §14.8 (share-adjusted `driver_check`) and §15 (data freshness), plus Kousik's g01 relabel to
      `data_issue` (disclosed as likely to raise the score). Baseline accepted from that run's ledger
      row (`evals/baselines/action.json`).
- [x] **A6** — `/actions/*` API endpoints, SPA "Pending actions" tab, DRF throttling.
      **Done 2026-11-03.** `dashboard_api/action_views.py`: pending, approve / edit / reject, log,
      undo (F5) over the same `ActionAgent` as the CLI; approver identity is a bearer secret,
      `ACTION_APPROVER_TOKEN` (D8, 503 when unset); scoped throttles on the actions, investigate
      and pipeline endpoints, checked before the token so guesses are counted (N4). Undo now
      records a LangSmith trace id. Verified live on `runserver` with scratch databases: 401s, the
      tab's approve and reject, 409 on a second decision and on undoing `notify_owner`, a policy
      error from an edit shown on the card, and 429s from both throttles. 16 new tests, suite 300.
- [x] **A7** — Detection eval (≥20 labeled dates), investigation golden set ≥10 and onboarding
      ≥3 (§7.1), scheduled drift run against stored baselines.
      **Built 2026-11-03; not checked — waiting on Kousik's labels** (design: scope §7.3, choices
      in the A7 decision log). `python -m detection.eval` (replays the production decision; 28
      candidate dates in `evals/detection/labels.yaml`), `python -m investigation.golden` (9 real
      frozen cases + Golden Case #1 = 10, in `evals/investigation/golden.yaml`), `python -m
      onboarding.eval` (3 datasets × 2 runs), `python -m observability.drift` (runs what's ready,
      regressions first; `--print-launchd` for the weekly job Kousik installs). Shared plumbing in
      `observability/evals.py`. Found and fixed: BUG_LOG A7-1 (the action eval compared adversarial
      escalation the wrong way) and A7-2 (onboarding accepted a non-existent rejected column).
      **2026-11-03:** labels in; baselines set for detection, investigation and onboarding (action's
      waits on A5). The runs found BUG_LOG A7-3 (dirty check), A7-4 (a Phase 1 prompt bug making real
      Olist investigations fall back) and A7-5 (unpaced evals faking regressions), all fixed.
      **Remaining for the gate: one clean full drift run**; today's hit Groq's 120b daily cap
      (200k tokens/day) and was correctly reported as invalid, not as regressions.
      **2026-11-06, data-freshness check (scope §15, approved; built, under A7 where the gap was
      found):** `detection/freshness.py` flags a day whose record volume is under 25% of the previous
      28 rows' median (off below 50 records/day). The pipeline alerts on a stale day even when the
      z-score doesn't; the Action Agent's rule 3 annotates it as `data_issue`. Detection eval with it:
      recall 12/12, precision 12/13, F1 0.96 (z-score alone 0.92); the threshold stays 2.0.
      **2026-11-12, gate passed:** a clean full `python -m observability.drift` on main `06a58bf` ran
      all four evals with 0 API errors and **0 regressions**: detection F1 0.92 (0.96 with freshness),
      onboarding unchanged, investigation up (grounding 0.77→0.83, golden match 0.57→0.73, fallback
      0.07→0), action 15/15 with every safety metric 0.

---

## Local Stack (`docs/local-stack-scope.md`)

The AWS free trial ended and every AWS resource was deleted (2026-11-02), so the Olist pipeline
can't run. This work brings it back locally and for free (a DuckDB warehouse, dbt-duckdb, a local
alert outbox), **keeping every line of AWS code** as an archived, switchable backend (scope §3
R1–R5). It is prioritized ahead of Action Agent A3 (scope §9).

**Gate:** from a fresh clone plus `data/raw/`, `load_local` → `dbt build --target local` →
`run_pipeline --dry-run` runs end to end with no cloud account, and no AWS file has been deleted.

- [x] **L1** — `WAREHOUSE` switch in `config/db.py`, `ingestion/load_local.py`, `dbt-duckdb` +
      committed `dbt_project/profiles.yml`, the 3 Redshift→portable SQL fixes. Row total 451,535;
      dbt build passes; Django dashboard serves Olist from DuckDB.
      **Verified live 2026-11-02:** `load_local` loaded 451,535 rows in ~2s (matches Phase 0);
      `dbt build` gave PASS=47 WARN=1 ERROR=0 (the WARN is a real 2016 data gap);
      `run_pipeline --dry-run --no-metrics` completed in 0.28s; `/api/health|metrics|anomalies|
      decomposition|narrative` and `/` returned 200 with Olist data; the result was cross-checked
      independently from the raw CSVs with pandas (−90.56%, exact match). 12 new tests, suite
      at 202. The Redshift connection code is byte-identical (diffed).
- [x] **L2** — `alerting/notifier.py` (local outbox, SNS kept as a channel), `run_pipeline` alert
      wiring, Action Agent scope text aligned (`notify_owner` via notifier).
      **Verified live 2026-11-02:** `run_pipeline --force-alert` → `alert.status = sent`,
      `channel = outbox`, 0.32s, a readable Markdown file with the real narrative and one
      `index.jsonl` line; `python -m alerting.notifier --test` works; the `ALERT_CHANNEL=sns`
      dispatch is tested and runs the unchanged `sns_publisher` without a network call. 13 new
      tests, suite at 215. Added `CLOUDWATCH_METRICS` (off locally). **Finding:** the SNS topic
      and AWS credentials still work (one real message was published by a test during the build;
      fixed). See the scope's L2 decision log.
- [x] **L3** — Committed Olist sample + real `dbt-build-local` CI job (the old `dbt-check` can't
      fail); `cd.yml` to manual trigger (it has failed on every merge since 2026-08); docs pass.
      **Verified 2026-11-02 on PR #31:** `dbt-build-local` passed (32,749 sample rows, `PASS=48`),
      then **failed** on a deliberately broken `stg_customers` in a throwaway commit while
      `dbt-check` still passed; the break was reverted. Sample is deterministic (diffed), CC
      BY-NC-SA 4.0 confirmed and attributed. `cd.yml` now has only a `workflow_dispatch` trigger.
      5 new tests, suite at 220.

---

## Hosting (`docs/hosting-scope.md`)

Nothing is clickable: the Render deployment is gone and AWS was deleted. A static GitHub Pages site
replays **real recorded outputs** (primary link), and the real app runs on a new Render free account
in demo mode (no outside effects, capped LLM spend). **Scope approved 2026-11-12** (both proposed
decisions accepted). **H1 built 2026-11-12** (recorder, builder, replay shim, Pages workflow;
checked in a browser locally); its box waits for the live Pages URL.

- [ ] **H1** — Static replay site: `demo/record.py` (real views via the test client), `demo/build.py`
      + `replay.js`, Pages workflow, README link. Gate: every tab loads from recordings on the Pages
      URL, checked in a browser.
- [ ] **H2** — Render demo-mode app: 2.1 MB staging snapshot, `DEMO_MODE` (live effects off
      server-side, daily LLM cap, dry-run pipeline), `requirements-web.txt`, `render.yaml`. Kousik
      creates the Render account. Gate: scope §7 Q3–Q5 and a real investigation on the live URL.
- [ ] **H3** — Docs point at the real URLs (the 8 "live on Render" mentions, README). Gate: Q6.

---

## UI redesign (`docs/ui-redesign-scope.md`)

The site looked AI-generated (Inter, indigo→violet, template landing page) and its breakdown bars
misdrew values over 100%. Rebuilt as the category standard at Linear / Stripe craft, for a
hiring manager's 30-second visit. Brief in `PRODUCT.md`. The Pages deploy waits for U4.

- [x] **U1** — Foundation: tokens (light + dark), base CSS, top bar and tabs, About. Gate: no
      detector findings from scope §1 in U1's files; no overflow at 375 and 1440 px. (Tailwind and
      Font Awesome come out in U3.)
- [ ] **U2** — Investigate: intro, flagged days, anomaly panel, diverging contribution chart,
      cited investigation, eval scorecard. Gate: first-screen numbers all trace to recordings.
      (Built 2026-11-12, waiting on Kousik's review. The intro's 451,535 rows comes from the
      ingestion run, not a recording.)
- [ ] **U3** — Approvals and How it's built. Gate: the recorded walk-through replays end to end.
- [ ] **U4** — Finish review, `DESIGN.md`, re-record on `main`, enable Pages. Gate: verdict,
      `DESIGN.md`, live URL checked in a browser (also H1's gate).

---

## Retrospectives

`docs/project/retrospectives/` is a named convention (end-of-phase reflection, heavier than a
session log entry). Phase 1 (M0–M3) closed on 2026-08-10 — see
[`phase-1-investigation-agent.md`](project/retrospectives/phase-1-investigation-agent.md) for its
retrospective, the first one actually written under this convention.
