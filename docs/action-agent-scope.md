# MetricPulse Action Agent — Scope

**Status:** Approved for A1–A3 · **Owner:** Kousik Nandury · **Date:** 2026-10-26 (revised 2026-11-01)
**Builds on:** Phase 1 Investigation Agent, Phase 2 Dataset Onboarding Agent (`docs/scoping.md`)
**Tracked in:** `docs/ROADMAP.md` → "Action Agent" (milestones A1–A6)

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
| `notify_owner` | Send the narrative and evidence to the segment owner (SNS/email) | T1: approval | No (logged) |
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
- N1: Every LLM call logs model, input/output tokens, cost, and latency. Each run has a token budget (D2) and stops gracefully with the fallback when exceeded. The budget covers Action Agent calls only; Phase 1's `synthesize` call is logged under N1 but not counted against it.
- N2: Model routing: a small model drafts the proposal; escalate to a larger model only after a grounding failure. Report the escalation rate.
- N3: Data values are untrusted input. Segment names and column values are passed as data fields, never concatenated into instructions.
- N4: Rate limiting (DRF throttling) on approve/execute and on investigation endpoints. This closes a known Phase 1 limitation.

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

## 8. Milestones

| # | Deliverable | Est. |
|---|---|---|
| A1 | Action catalog, Pydantic schemas, `policy_check`, dry-run payload builder, and tests | 6h |
| A2 | Checkpointer, `interrupt` approval flow, CLI approver, action log, idempotency | 8h |
| A3 | Live-test `gpt-oss-20b`; `propose_action` node, citation validation, fallback, model routing, cost telemetry | 6h |
| A4 | GitHub Issue and SNS executors, `suppress_alerts` and `create_control` evaluation, undo | 6h |
| A5 | Golden and adversarial eval suite, results table in README | 6h |
| A6 | API endpoints and SPA "Pending actions" tab, throttling | 5h |

**Total: ~37h.** A1 to A3 are the minimum demonstrable slice: propose, gate, approve in the CLI, and log.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Golden set too small to mean much | Report n and the per-case table. Make no rate claims beyond the set. |
| GitHub/SNS side effects during tests | Executor interface with a recording fake for tests. Real executors run only behind an `--live` flag. |
| Scope creep into autonomous remediation | Non-goals in §3. Any new action type needs a catalog entry plus a tier assignment. |
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

**D3. Existing SNS alert vs `notify_owner`.** The existing pipeline alert stays as it is. It is the detection alert and goes to the pipeline's topic. `notify_owner` is a separate message to one segment owner, carrying the narrative plus the evidence table. `suppress_alerts` (T1) applies to the existing alert on local pipeline runs: a suppressed anomaly key raises no repeat pipeline alert until the suppression expires or is undone. `annotate_anomaly` never affects alerting. The Lambda path is unchanged and does not read suppressions.

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

**D7. Build scope.** Build A1 to A3 now, then stop for review before starting A4. A4 to A6 are approved in scope but are not started in this pass.

**D8. Choices left to the agent.** Decide these, then record each choice in the "Decision log" below with a one-line reason:
- the `owners.yaml` schema and the default owner entry
- bounds on N days for `suppress_alerts` (`policy_check` must enforce a hard maximum)
- whether an approver's edit may change `action_type` or only `params`
- how expiry after the 24h TTL is applied (lazily on read, or by a sweep)
- how the API checks the single approver identity
- which GitHub repo and SNS topic the live executors target, and where their credentials come from

An edit produces new params and so a new idempotency key. That is intended: the edited action counts as a different action.

**D9. Local only.** The Action Agent runs locally only (Render is no longer available, and Lambda's ephemeral filesystem can't hold `actions.db`/`checkpoints.db`). D3 suppression and D4 control evaluation apply to local pipeline runs; the Lambda handler is unchanged.

## 12. Decision log

Filled in as the D8 choices are made during the build. One line each: choice — reason.

_(none yet)_
