# MetricPulse Action Agent — Scope

**Status:** Approved for A1–A3 · **Owner:** Kousik Nandury · **Date:** 2026-10-26 (revised 2026-11-01, 2026-11-02)
**Builds on:** Phase 1 Investigation Agent, Phase 2 Dataset Onboarding Agent (`docs/scoping.md`)
**Tracked in:** `docs/ROADMAP.md` → "Action Agent" (milestones A1–A7)

## 1. Problem
MetricPulse explains an anomaly, and then a person has to act on it. The agentic roles in the application set (Nordstrom, ClarityPay, Ramp, Nuvo, NewsBreak, Dotmatics) ask for agents that take **scoped, approved, auditable actions**, not just explanations.

## 2. Goal
Turn a validated investigation into a proposed action, gate that action on policy and human approval, then execute it idempotently and log it.

## 3. Non-goals
- No writes to source or warehouse data (Olist, Redshift, DuckDB tables).
- No open-ended tool selection. Actions come from a fixed catalog.
- No multi-step autonomous remediation chains. One proposal per investigation.
- No new UI framework. Extend the existing Django API and SPA.
- No auth system beyond a single approver identity (portfolio scope).
- No hosted deployment. The Action Agent runs locally only (D9); the Lambda path is unchanged.

## 4. Action Catalog

| Action | Effect | Risk tier | Reversible |
|---|---|---|---|
| `annotate_anomaly` | Tag an anomaly with a known cause (e.g. holiday). Tag only — no effect on alerting | T0: auto | Yes (remove tag) |
| `suppress_alerts` | Suppress repeat pipeline alerts for an anomaly key for N days | T1: approval | Yes (lift suppression) |
| `notify_owner` | Send the narrative and evidence to the segment owner (via `alerting.notifier`: local outbox by default, SNS archived) | T1: approval | No (logged) |
| `open_incident` | Create a GitHub Issue with the evidence table and citations | T1: approval | Yes (close issue) |
| `create_control` | Register a segment-level watch: metric, segment, threshold, owner, expiry | T1: approval | Yes (disable) |

- **Tiers:** T0 executes automatically. T1 requires approval. T2 (any data mutation) is rejected by policy before it reaches the approver.
- **Why suppression is T1, not T0:** suppression silences the detection alert, so it is the action an injected segment name would most want to trigger. The only auto-executed action (`annotate_anomaly`) therefore has no effect on alerting; silencing always passes a human.
- **Owners:** segment → owner mapping lives in `owners.yaml`. An unmapped segment routes to the default owner.

## 5. Flow (LangGraph, extends the Phase 1 graph)
`finalize` → `propose_action` → `policy_check` → [T0: `execute`] / [T1: `await_approval` (`interrupt`)] → `execute` → `record`

- **`propose_action`** is the only LLM node. It returns `{action_type, params, rationale_citations}` via structured output. Citations are validated with the existing `validate_citation()` (`investigation/validation.py`). Retry and fallback follow D2.
- **`policy_check`** is deterministic and uses three checks:
  - action is in the catalog
  - tier is permitted
  - params pass schema and range checks (threshold bounds, expiry ≤ 30 days, suppression N ≤ the cap in the decision log)
- **`await_approval`** uses a LangGraph `interrupt()` with a persistent checkpointer (`SqliteSaver` from `langgraph-checkpoint-sqlite`, pinned in `requirements.txt`), so a pending approval survives a restart. The Phase 1 graph currently compiles with no checkpointer (`investigation/graph.py`); A2 adds one to the extended graph only, leaving the Phase 1 graph's compile path unchanged. The approver sees a **dry-run diff** (exact payload plus target) and chooses approve, edit, or reject. Edited params go through `policy_check` again.
- **`execute`** uses an idempotency key `hash(anomaly_id, action_type, params)` (params serialized as canonical, key-sorted JSON), so a duplicate execution is a no-op.
- **`record`** writes an append-only action log:
  - proposal
  - policy result
  - approver decision with timestamp
  - payload
  - external ID (issue URL, message ID)
  - outcome

## 6. Requirements

**Functional**
- F1: Every executed T1 action has an approval record. The executor fails closed if the record is missing.
- F2: Rejected and expired proposals (24h TTL) are logged and never executed.
- F3: Reversible actions expose an `undo` endpoint that logs a compensating entry.
- F4: `create_control` watches are evaluated on every local pipeline run and alert their named owner on a breach.
- F5: API endpoints: `GET /actions/pending`, `POST /actions/{id}/approve|edit|reject`, `GET /actions/log`, `POST /actions/{id}/undo`.

**Non-functional**
- N1: Every LLM call, in all three agents, goes through one telemetry wrapper (§13.3). The wrapper records model, input/output tokens, cost, latency and outcome, both to LangSmith and to a local append-only record. Each run has a token budget (D2) and stops gracefully with the fallback when exceeded. The budget covers Action Agent calls only; Phase 1's `synthesize` and the onboarding `classify` calls are recorded under N1 but not counted against it.
- N2: Model routing: a small model drafts the proposal; escalate to a larger model only after a grounding failure. Report the escalation rate.
- N3: Data values are untrusted input. Segment names and column values are passed as data fields, never concatenated into instructions.
- N4: Rate limiting (DRF throttling) on approve/execute and on investigation endpoints. This closes a known Phase 1 limitation.
- N5: Every decision can be traced and replayed (§13). Each proposal, policy result, approval and execution links to its LangSmith trace and LangGraph checkpoint thread. Tracing is fail-open: if LangSmith is down or disabled, runs proceed and only the local record is written. Actions stay fail-closed (F1); telemetry never gates them.

## 7. Evaluation (before any demo)

| Metric | Target | Method |
|---|---|---|
| `unauthorized_exec_count` | 0 | Property tests: T1 without approval, T2, out-of-catalog, tampered params |
| `action_match_rate` | ≥ 0.8 | Golden set of 15 anomalies with the expected action type and owner |
| `grounding_pass_rate` | 1.00 | Existing validator on proposal citations |
| `idempotency_violations` | 0 | Replay each approved action 3× |
| `injection_resistance` | 0 policy bypasses | 10 adversarial cases (instructions embedded in segment names or CSV values), including at least one segment name that tries to trigger alert suppression |
| `escalation_rate` | Reported, no target | Runs that reached the large model ÷ total runs (D2) |
| `cost_per_run`, `p95_latency` | Reported, no target | Collected from N1 telemetry |

Deterministic nodes are covered by pytest with no mocks, matching the existing suite. LLM nodes are graded by the eval suite, as in Phase 1.

### 7.1 System-wide eval suite (added 2026-11-02)

The table above grades the Action Agent alone. For the system to hold up over time, every stage needs an eval that answers one question a stakeholder would ask. Read top to bottom, the suite says whether MetricPulse alarms at the right time, explains with real evidence, gets the cause right, is honest when unsure, acts safely and stays affordable, and whether any of that has slipped.

| Question | Eval | Metric(s) | Status | What a bad number means |
|---|---|---|---|---|
| Does it alarm at the right times? | Detection eval | `detection_precision`, `detection_recall` at the configured threshold, plus a threshold sweep | **New (A7)** | Low precision: alert fatigue and ignored alerts. Low recall: silent incidents |
| Is the math right? | Decomposition unit tests | pass/fail | Exists | Every downstream number is corrupt |
| Is the agent making things up? | Investigation eval | `grounding_pass_rate` | Exists (n=1 case × 5) | It is citing segments that aren't in the data. This is the trust metric |
| Does it find the right cause? | Investigation eval | `golden_match_rate` | Exists | Grounded but wrong: real evidence, wrong conclusion |
| Does it admit when it's unsure? | Investigation eval | `uncertainty_ok_rate` | Exists | It sounds confident about an ambiguous case |
| How often does the LLM fail outright? | Investigation eval | `fallback_rate` | Exists | You pay for an LLM and get the template narrative |
| Can it understand an unseen dataset? | Onboarding eval | per-field match rate, `human_review_rate` | Exists (n=1) | A human is needed for every new dataset, so it doesn't generalize |
| Can it be tricked or go rogue? | Action eval (§7) | `unauthorized_exec_count`, `injection_resistance` | A5 | Anything above 0 is a safety incident, not a quality dip |
| Does it pick the right response? | Action eval (§7) | `action_match_rate` | A5 | It understands the problem but responds wrongly |
| Does the human agree with it? | Approver feedback (§13.4) | `approval_rate`, `edit_rate`, `reject_rate` by action type | A2 (collect), A5 (report) | A high edit or reject rate means proposals miss in a way the golden set didn't catch |
| What does quality cost? | N1 telemetry | `escalation_rate`, `cost_per_run`, `p95_latency`, tokens per stage | A3 | Quality is being bought with the large model or slow retries |
| Has anything silently gotten worse? | Drift run | every LLM eval above vs. its stored baseline | **New (A7)** | A model or provider change broke something nobody touched |

**Set sizes (A7):** detection ≥ 20 labeled dates across Olist and Superstore, with real events and real non-events, labeled by Kousik as in D6. Investigation golden set expanded from 1 to ≥ 10 cases, covering a clear driver, close contributors, offsetting segments and an onboarded-dataset case. Onboarding from 1 to ≥ 3 datasets. Small n stays small: report n beside every rate (§9).

### 7.2 How every eval reports

An eval result is a short story, not a bare number. Every eval run writes one ledger row (§13.5) and prints a report in this order:
1. **Question:** the one-line question from §7.1.
2. **Result:** each metric with its n, e.g. `grounding_pass_rate = 0.90 (9/10)`.
3. **Against baseline:** the delta from the stored baseline and whether it crosses the regression threshold.
4. **What changed:** git SHA, model, and prompt hash, against the baseline's.
5. **Failing cases:** each with its expected vs. actual and a link to its LangSmith trace, so every failure is one click from its full reasoning.

## 8. Milestones

| # | Deliverable | Est. |
|---|---|---|
| A1 | Action catalog, Pydantic schemas, `policy_check`, dry-run payload builder, and tests | 6h |
| A2 | LangSmith tracing (§13.1–13.2), checkpointer, `interrupt` approval flow, CLI approver, action log with trace/thread links, idempotency, approver decisions as LangSmith feedback (§13.4), decision-replay test (§13.6) | 10h |
| A3 | Live-test `gpt-oss-20b`; `propose_action` node, citation validation, fallback, model routing; shared LLM telemetry wrapper (§13.3) applied to all three agents' LLM calls | 8h |
| A4 | GitHub Issue and notifier executors, `suppress_alerts` and `create_control` evaluation, undo | 6h |
| A5 | Golden and adversarial eval suite as LangSmith datasets and experiments; local eval ledger and the baseline report (§7.2, §13.5) | 8h |
| A6 | API endpoints and SPA "Pending actions" tab, throttling | 5h |
| A7 | Detection eval, expanded investigation and onboarding golden sets (§7.1), scheduled drift run | 8h |

**Total: ~51h.** A1 to A3 are the minimum demonstrable slice: propose, gate, approve in the CLI, and log.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Golden set too small to mean much | Report n and the per-case table. Make no rate claims beyond the set. |
| GitHub/notifier side effects during tests | Executor interface with a recording fake for tests. Real executors run only behind an `--live` flag. |
| Scope creep into autonomous remediation | Non-goals in §3. Any new action type needs a catalog entry plus a tier assignment. |
| Traces send prompts and evidence to LangSmith's hosted service | Olist and Superstore are public datasets. Tracing is off unless `LANGSMITH_TRACING=true`; onboard a private dataset with it off. Recorded in D10 |
| LangSmith retention or plan limits drop history | The local eval ledger and `llm_calls.jsonl` are the durable record; LangSmith is the exploration layer (§13.5) |
| `gpt-oss-20b` can't produce grounded proposals at all | A3 live-tests it first. If it fails most cases, record that and raise it before building routing around it (D2). |

## 10. Open Questions (resolved)
1. Should the approver use the CLI only (A2), or also Slack interactive buttons? **Decided:** CLI only. Slack is deferred.
2. Should `create_control` expire automatically or require renewal? **Decided:** auto-expire. Expiry is required, ≤ 30 days, and there is no renewal. A new watch needs a new proposal.

## 11. Decisions

These are fixed for the build. If one turns out to be wrong in practice, stop and raise it. Don't work around it.

**D1. Anomaly identity.** `anomaly_id = sha256(dataset_id, metric, anomaly_date)`. Segment is not part of it. An anomaly gets one proposal for its lifetime: if a later pipeline run finds an existing proposal for the same `anomaly_id` in any status (pending, executed, rejected, expired), it does not propose again. Re-proposing is a manual API call that is out of scope for the Action Agent.

**D2. Model sequence and budget.** Phase 1 already runs `openai/gpt-oss-120b` on Groq (`config/settings.py`), so the routing is flipped relative to "start where Phase 1 is": the small model is `openai/gpt-oss-20b` and the large model is `openai/gpt-oss-120b`. A3 live-tests 20b on real proposals first and records the result in the decision log before routing is built on it. Sequence:
1. Small model (20b) drafts the proposal, and its citations are validated.
2. On failure, retry once **on the large model (120b)**, with the validation errors fed back. This is the only retry, and it counts as an escalation.
3. On a second failure, fall back to `notify_owner` with the deterministic narrative.

Token budget: 10,000 tokens per run across all Action Agent LLM calls (Phase 1 `synthesize` excluded, see N1). If the next call would exceed it, go straight to the fallback. Escalation rate = runs that reached step 2 ÷ total runs.

**D3. Existing pipeline alert vs `notify_owner`.** The existing pipeline alert stays as it is. It is the detection alert, delivered through `alerting.notifier` (the local outbox by default; the archived SNS topic under `ALERT_CHANNEL=sns`, local-stack scope §6.4). `notify_owner` is a separate message (`notifier.send_alert` with the owner as recipient) to one segment owner, carrying the narrative plus the evidence table. `suppress_alerts` (T1) applies to the existing alert on local pipeline runs: a suppressed anomaly key raises no repeat pipeline alert until the suppression expires or is undone. `annotate_anomaly` never affects alerting. The Lambda path is unchanged and does not read suppressions.

**D4. `create_control` evaluation.** A watch is `{dataset_id, metric, dimension, segment, direction (above|below), threshold, owner, expires_at}`. The threshold is an **absolute value** of the segment's daily metric, not a z-score. Each local pipeline run evaluates every active, unexpired watch for the dataset being run, by calling the existing decomposition query for that date (`decompose_metric` with its `dimension_config`/connection arguments — the SQL itself is string-interpolated behind `_validate_date()`, not driver-parameterized). This covers both Olist/Redshift and onboarded DuckDB datasets. A breach sends one `notify_owner`-style message to the watch's owner and writes an action-log entry. Only one alert is sent per watch per day.

**D5. Storage.** Action Agent state lives in a dedicated SQLite file, `actions.db`, separate from Django's `db.sqlite3`. This keeps the existing rule that the Django database holds no business data. The LangGraph checkpointer gets its own file, `checkpoints.db`. Tables:
- `proposals`
- `action_log`
- `annotations`
- `suppressions`
- `controls`

`action_log` is append-only, enforced by SQLite triggers that raise on `UPDATE` and `DELETE`. Status changes, undos and expiries are new rows, never edits. Cover the triggers with a pytest test.

**D6. Eval sets.**
- **Golden set (15):** Kousik writes the expected action type and owner for each case. Draw candidates from real Olist and Superstore anomalies. The agent may propose candidates, but it does not label them.
- **Adversarial set (10):** the agent writes these. Use a synthetic CSV, onboarded through the Phase 2 flow, with instructions embedded in segment names and column values. Olist's fixed segment names can't carry an injection. At least one case is a segment name that tries to trigger `suppress_alerts`; passing means it is either not proposed or held at approval, never auto-executed.

**D7. Build scope.** Build A1 to A3 now, then stop for review before starting A4. A4 to A7 are approved in scope but are not started in this pass.

**D8. Choices left to the agent.** Decide these, then record each choice in the "Decision log" below with a one-line reason:
- the `owners.yaml` schema and the default owner entry
- bounds on N days for `suppress_alerts` (`policy_check` must enforce a hard maximum)
- whether an approver's edit may change `action_type` or only `params`
- how expiry after the 24h TTL is applied (lazily on read, or by a sweep)
- how the API checks the single approver identity
- which GitHub repo and notifier channel the live executors target, and where their credentials come from

An edit produces new params and so a new idempotency key. That is intended: the edited action counts as a different action.

**D9. Local only.** The Action Agent runs locally only (Render is no longer available, and Lambda's ephemeral filesystem can't hold `actions.db`/`checkpoints.db`). D3 suppression and D4 control evaluation apply to local pipeline runs; the Lambda handler is unchanged.

**D10. Tracing tool: LangSmith.** Chosen over MLflow tracking. Reasons:
- LangGraph and LangChain trace into it natively. Setting the env vars traces every graph node and LLM call with no per-node code, including interrupts and resumes.
- An LLM run can be opened in the LangSmith Playground and re-run with the same messages, or with a different model or prompt. That is the "replay" for LLM decisions.
- Datasets, experiments and the feedback API cover the eval and human-label needs (§7.1, §13.4).
- `langsmith` is already in `requirements.txt` (0.10.16, pulled in by LangChain), so no new dependency.
- Kousik wants hands-on LangSmith experience.

The trade-offs: it is a hosted vendor, so traces leave the machine (see §9), and history depends on plan retention. Hence the local ledger in §13.5. MLflow would self-host but needs a tracking server and manual instrumentation for anything outside its LangChain autolog.

**D11. Durable record vs. exploration layer.** The local files (`actions.db`, `llm_calls.jsonl`, `evals/ledger.jsonl`) are the source of truth. LangSmith is a mirror for browsing, comparing and replaying. Nothing reads LangSmith to decide anything, and a LangSmith outage loses traces, never decisions.

## 12. Decision log

Filled in as the D8 choices are made during the build. One line each: choice — reason.

**A1 (2026-11-01)**
- **`owners.yaml` schema:** `default_owner` id + `people` (id → name, email) + `segments[dataset_id][dimension][segment | '*']` → id. Resolution goes exact segment → dimension `'*'` → default. The default is `analytics-oncall`, with placeholder emails until A4. Reason: the recipient comes from config and is never an LLM param, and each email lives in one place.
- **`suppress_alerts` N:** integer 1–7 days, strict type. Reason: 7 days covers a holiday week, and a mistaken silence surfaces within a week. Anything longer needs a fresh proposal.
- **Segment grounding (added check):** any `dimension`/`segment` param must be a pair present in the investigation's decomposition `top_contributors`. Reason: this is the policy-side half of N3, so an injected or hallucinated segment can't be targeted.
- **`create_control` threshold bounds:** `0.1×`–`10×` of the segment's `max(current, previous)` value, finite, > 0. Zero-volume segments are rejected. Reason: this blocks watches that could never fire or would always fire, without needing per-metric config.
- **Strict numerics:** `days`, `expires_in_days` and `threshold` reject bools and numeric strings. Reason: Pydantic's lax mode would turn a tampered `true` into `1`.

**A2 (2026-11-02)**
- **Edit scope:** an approver's edit may change `params` only, never `action_type`. A changed type is logged `invalid_decision` and the proposal keeps waiting. Reason: a different type is a different tier and risk, so it is a different proposal, not an edit.
- **An edit is an approval of its own params.** If the edited params pass `policy_check`, an `edited` row is logged for the new idempotency key and the action executes without a second approve. If they fail, the approver sees the errors and decides again; approving the failed params is refused. Reason: the approver wrote the params, and making them approve their own edit adds a step with no safety value.
- **TTL expiry is lazy, with no sweep.** `await_approval` checks `expires_at` on entry, and every resume re-enters it, so a decision after 24h logs `expired` and ends the run without executing. `pending` hides proposals past their TTL. Reason: the agent is a single local process (D9) with nothing to run a sweep on, and F2 only requires that an expired proposal is never executed, which the decision-time check guarantees.
- **Approver identity (CLI):** `ACTION_APPROVER`, falling back to the OS user, recorded as the `actor` on decision rows. The API check stays with A6. Reason: local-only with one approver. This records who approved; it doesn't authenticate them.
- **Event vocabulary:** `proposed`, `policy_passed`, `policy_rejected`, `edit_submitted`, `edit_policy_rejected`, `edited`, `approved`, `rejected`, `expired`, `invalid_decision`, `executed`, `execution_failed`, `execution_blocked`, `duplicate_skipped`. Terminal events are listed in `store.TERMINAL_EVENTS`.
- **A separate action graph, not new nodes on the Phase 1 graph.** It runs on the investigation's output. Reason: the Phase 1 graph and its no-checkpointer compile path stay byte-for-byte unchanged (§5).
- **LangSmith key (2026-11-02):** the first key returned 403 on read and write, identical to a fabricated key, so it is not recognized. Plan, quota and retention are to be recorded once a working key is in place (§13.1).

_Pending: the 20b live-test result (A3), live executor targets and credentials (A4), and the API approver identity check (A6)._

## 13. Observability, tracing and replay (added 2026-11-02)

Goal: every decision MetricPulse makes, whether detection, investigation, onboarding classification, action proposal, policy result or approval, can be **tracked** (found later by anomaly, dataset or action), **traced** (its full inputs, reasoning and outputs seen step by step) and **replayed** (re-run to confirm or compare).

### 13.1 Setup
- Env vars in `.env` and `.env.example`, read only through `config/settings.py`: `LANGSMITH_TRACING` (default off), `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` (default `metricpulse`), `LANGSMITH_ENDPOINT` (optional).
- Tests and CI never set them. The pytest suite stays offline, and one test asserts the telemetry wrapper works with tracing disabled.
- Record the plan, its trace quota and its retention in the decision log at setup. Don't assume them.

### 13.2 What gets traced, and how it's linked
- **LangGraph graphs** (investigation, action) are traced automatically once tracing is on, one trace per run, with every node as a child run. Deterministic nodes like `policy_check` show up with their inputs and outputs too.
- **Non-graph code** gets a `@traceable` wrapper: onboarding classification, and the detection and decomposition calls in `run_pipeline` and `onboarding.investigate`. Its runs nest under the same trace.
- **Trace metadata and tags** on every run: `dataset_id`, `metric`, `anomaly_date`, `anomaly_id`, `git_sha`, `prompt_hash`, `model`, plus `idempotency_key` once a proposal exists. That makes traces searchable by anomaly or by code version.
- **Links in both directions.** `proposals` and `action_log` rows store `trace_id`, `run_id` and the checkpointer `thread_id`. Traces carry `anomaly_id`. From an action-log entry you can reach its trace, and from a trace you can find its log rows.

### 13.3 LLM telemetry wrapper (N1)
One shared module, `observability/llm.py`, wraps every Groq call in all three agents. Per call, it records:
- stage and model
- input/output tokens, from the response's usage metadata
- cost, from a pinned per-model price table kept in config and dated
- latency
- attempt number (first try, retry, escalation)
- outcome (grounded, retry, fallback, error)
- `trace_id`

It writes each call to the current LangSmith run's metadata when tracing is on, and always appends a line to `logs/llm_calls.jsonl` (gitignored). The D2 token budget counts from this wrapper, so the budget and the telemetry can't disagree.

### 13.4 Human decisions as feedback
When the approver approves, edits or rejects (A2), the same decision is posted to the proposal's trace as LangSmith feedback: key `approval`, with the decision as its value, the edit diff as the correction, and the reason as the comment. The `action_log` row stays authoritative (D11). Over time this builds a human-labeled set of real proposals. That is where `approval_rate`/`edit_rate` (§7.1) come from, and the pool new golden cases are drawn from.

### 13.5 Eval ledger and experiments
- Each eval run (investigation, onboarding, action, detection) appends one JSON line to `evals/ledger.jsonl`, which **is committed**. The line holds the timestamp, eval name, git SHA, model, prompt hash, each metric with its n, and the failing case ids with trace URLs. A committed baseline file per eval holds the accepted numbers, and the report in §7.2 compares against it.
- The same golden sets are uploaded as LangSmith datasets, and each eval run is also a LangSmith experiment (`langsmith.evaluate`). The existing deterministic graders (`validate_synthesis_output`, golden match, `policy_check`) are the evaluators, not an LLM judge. Experiments are for side-by-side comparison in the UI; the ledger is the history.

### 13.6 Replay, precisely
"Replay" means three different things here, each with its own mechanism:

| What | Mechanism | Guarantee |
|---|---|---|
| Deterministic decisions (`policy_check`, dry run, routing) | Re-run the pure function on the logged proposal plus the evidence snapshot stored with it | **Exact.** A pytest decision-replay test re-runs logged decisions and asserts the same outcome, and fails if code changes alter a past decision without a decision-log entry |
| LLM decisions (`synthesize`, `classify`, `propose_action`) | Open the run in the LangSmith Playground and re-run with the same messages, or with a different model or prompt | **Comparable, not identical.** LLM output isn't deterministic even at temperature 0, so the replay shows whether a decision is stable, not a byte match |
| Action-graph runs | LangGraph checkpoints (`get_state_history`), so you can inspect any step and resume or fork from it | Exact state at each step for the action graph. The Phase 1 graph has no checkpointer, so it is replayed from its trace inputs instead |

For exact replay to work, `proposals` stores the evidence snapshot the decision was made on (the `decomposition_results` dict, or its hash plus the dict), not just a pointer to the live data.

### 13.7 Out of scope
- Production metrics. CloudWatch (`monitoring/cloudwatch_metrics.py`) is archived AWS code, kept intact and off locally (`CLOUDWATCH_METRICS`, local-stack scope §6.4). It was never on for the Lambda or dashboard paths either.
- Alerting on eval regressions. The drift run (A7) reports; it doesn't page anyone.
- Self-hosted LangSmith or OpenTelemetry export.
