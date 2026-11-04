# action_agent/

The Action Agent (`docs/action-agent-scope.md`): turns a validated investigation into a proposed
action from a fixed catalog, gates it deterministically, and (from A2) routes it through human
approval to idempotent execution and an append-only log. Local-only (scope doc §11 D9).

**Built so far:**
- **A1:** the catalog, schemas, `policy_check`, owner resolution, identities and the dry-run
  payload builder.
- **A2:** the action graph with a SQLite checkpointer and `interrupt()` approvals, the CLI
  approver, `actions.db`, executors, decision replay and LangSmith run linking.

- **A3:** the LLM proposer (gpt-oss-20b drafts, one escalation to gpt-oss-120b, then the
  deterministic fallback, under a 10k-token budget), and `probe.py`, the live model test.

- **A6:** the HTTP API and the dashboard's "Pending actions" tab (`dashboard_api/action_views.py`,
  `templates/partials/actions.html`): pending, approve / edit / reject, log, undo, behind the
  approver token `ACTION_APPROVER_TOKEN`, with DRF throttling. See `dashboard_api/README.md`.

- **A4:** real executors (`notify_owner` through the notifier outbox, `open_incident` as a GitHub
  Issue behind `--live`), undo (F3), and the pipeline hooks: D3 suppression and D4 watch
  evaluation on local pipeline runs (`hooks.py`). `propose --dataset-id olist` works.

## Files

| File | Purpose |
|------|---------|
| `catalog.py` | `Tier` (T0 auto / T1 approval / T2 never), `ActionSpec`, the fixed `CATALOG` of five actions, `PERMITTED_TIERS`. |
| `schemas.py` | `ActionProposal` and one strict (`extra='forbid'`) params model per action; `SUPPRESS_MAX_DAYS`, `CONTROL_MAX_EXPIRY_DAYS`. |
| `policy.py` | `policy_check(proposal, evidence, catalog=CATALOG) -> PolicyResult` — the gate. |
| `owners.py` / `owners.yaml` | Segment → owner mapping and `resolve_owner()`. |
| `identity.py` | `anomaly_id()` (D1), `idempotency_key()`, `canonical_json()`, `OLIST_DATASET_ID`. |
| `dry_run.py` | `ActionContext`, `build_dry_run()` (exact target + payload + key), `render_dry_run()` for the CLI approver. |
| `proposer.py` | `fallback_proposal()`: deterministic `notify_owner` for the top driver. D2's fallback, and the proposer with `propose --no-llm`. |
| `llm_proposer.py` | `make_llm_proposer()`: the D2 sequence (20b → one 120b escalation → fallback) under the token budget, `validate_proposal()` (citations + `policy_check`), `build_messages()` (evidence as a JSON data block, N3). |
| `probe.py` | `python -m action_agent.probe [--small-only]`: live-tests the proposer on 12 real anomalies (Olist + Superstore) and prints a per-case table. Real Groq calls. |
| `store.py` | `ActionStore` over `actions.db`: insert-only `proposals` (UNIQUE `anomaly_id`), trigger-enforced append-only `action_log`, effect tables. |
| `executors.py` | `LocalStoreExecutor` (annotate/suppress/control → effect tables), `NotifierExecutor` (notify_owner → `alerting.notifier`), `GitHubIssueExecutor` + `GitHubClient` (open_incident, `--live` only), `SimulatedExecutor`, `RecordingExecutor` (tests), `default_executors(store, live)`. |
| `hooks.py` | What local pipeline runs read: `pipeline_suppression()` (D3) and `evaluate_controls()` (D4/F4). |
| `event_calendar.py` / `calendars/` | Scope §14: the trusted per-dataset calendar (`calendars/<dataset_id>.yaml`, generated from holiday law and date rules by `--write`, verified by `--check`), `calendar_context()` (weekdays, events on the date and within ±3 days with offsets) and `attach_calendar()`. A dataset with no file gets weekdays only. |
| `evidence.py` | `build_case()`: an anomaly's evidence, built exactly as the pipeline builds it, for Olist or an onboarded dataset. Used by `propose` and `probe.py`. |
| `graph.py` | `build_action_graph()`: the §5 flow, compiled with a checkpointer. |
| `runner.py` | `ActionAgent`: wires store + `SqliteSaver` + executors + LangSmith run config; `start`, `decide`, `undo`, `pending`, `waiting_on`. `live=True` allows effects outside this machine. |
| `replay.py` | `replay_decisions()`: re-runs every logged policy decision on its stored evidence snapshot (§13.6). |
| `eval.py` | `python -m action_agent.eval [--sets golden,adversarial,safety] [--set-baseline]`: the §7 eval suite. See `evals/README.md`. Real LLM calls. |
| `golden.py` | `python -m action_agent.golden [--check]`: writes the 15 golden candidates for Kousik to label, and validates the labels. |
| `adversarial.py` | The 10 adversarial cases and their synthetic CSV generator; `ensure_onboarded()` regenerates the dataset's tables from the committed classification. |
| `cli.py` | `python -m action_agent.cli propose|pending|show|approve|edit|reject|log|replay`. `propose` uses the LLM proposer; `--no-llm` uses the deterministic one. |

## The catalog

| Action | Tier | Reversible | Params |
|---|---|---|---|
| `annotate_anomaly` | T1 (T0 until A5) | yes | `category`, `cause`, `calendar_event` (optional, §14) — tag only, no alerting effect |
| `suppress_alerts` | T1 | yes | `days` (1–7), `reason` |
| `notify_owner` | T1 | no | `dimension`, `segment` |
| `open_incident` | T1 | yes | `dimension`, `segment`, `title`, `severity` |
| `create_control` | T1 | yes | `dimension`, `segment`, `direction`, `threshold`, `expires_in_days` (1–30) |

## `policy_check`

Three checks, in order, each failing closed: (1) in the catalog, (2) tier permitted, (3) params
pass schema and range checks. Returns a `PolicyResult` with `decision` = `auto_execute` (T0) |
`needs_approval` (T1) | `rejected`, plus `errors` and the validated `params`. It never raises on
bad input: a malformed proposal, a non-dict, an empty citation list or a smuggled extra field are
all rejections with a reason.

Range checks beyond the per-field bounds:
- Any action with `dimension`/`segment` params must name a pair that's actually in the
  investigation's `decomposition_results` (`top_contributors`). This is what stops an LLM (or an
  injected segment name) from targeting a segment the evidence doesn't contain.
- `create_control.threshold` must be within 10× either side of the segment's observed value,
  `max(current_value, previous_value)`. A segment with zero volume on both days is rejected.
- Calendar grounding (§14): `annotate_anomaly` with category `holiday` or `promotion` must set
  `calendar_event` to the name of an entry in `evidence['calendar']` (on the date or within ±3
  days); any `calendar_event` given must be one; `seasonal` needs `weekday_class_changed`. No
  calendar in the evidence fails closed. `ActionAgent.start` always recomputes the calendar from
  the committed file, so a caller can't supply one.
- Numeric params are strict: `true`, `"3"` and `3.0` are not accepted as an integer day count.

`catalog` is a parameter so tests can inject a T2 entry. Dependency injection, not a mock.

## Owners

`owners.yaml` resolution for `(dataset_id, dimension, segment)`: exact segment → the dimension's
`'*'` entry → `default_owner`. Every referenced id must exist under `people` (validated on load).
The recipient is **never** a proposal param: `notify_owner` and `create_control` always get their
owner from this file. The emails in the shipped file are placeholders; real delivery is set up
with the live executors (A4).

## Dry run

`build_dry_run(proposal, policy, ctx, owners, targets=None, now=None)` builds exactly what
execution will do: `target`, `payload`, `idempotency_key`, tier, reversibility. Message bodies
(notify/incident) are deterministic: narrative summary + the dimension's evidence table (target
segment bolded) + the cited evidence + the anomaly id. The only LLM-written text that reaches a
payload is the length-capped `cause`/`reason`/`title`. Segment names are escaped for Markdown.
`targets` (`alert_channel`, `github_repo`) come from settings (`ALERT_CHANNEL`,
`ACTION_GITHUB_REPO`); an unconfigured one shows as `None` rather than being hidden. `now` is injectable so expiries are deterministic in
tests. It raises `ValueError` if handed a rejected `PolicyResult`, since that is a programming
error rather than bad input.

## The approval flow (A2)

```
check_existing -> propose -> register -> policy -> T0: execute -> record
                                                 T1: await_approval (interrupt)
                                                       approve -> execute -> record
                                                       edit    -> policy (passes: execute / fails: back to await)
                                                       reject / expired -> record
```

```bash
python -m action_agent.cli propose --dataset-id superstore_sales --metric sales   # prints the dry run, pauses
python -m action_agent.cli pending                     # survives restarts: the pause is in checkpoints.db
python -m action_agent.cli approve e275 --reason "..." # any unique id prefix
python -m action_agent.cli edit e275 --params '{"days": 2, "reason": "holiday"}'
python -m action_agent.cli log [e275]
python -m action_agent.cli replay e275                 # exits 1 if today's code would decide differently
```

- **One thread per proposal.** `proposal_id` is the checkpointer `thread_id`. Every `start` and
  `decide` is its own invocation and its own LangSmith trace. That trace's root run id is
  stamped on the `action_log` rows it writes, and the first one is stored on the proposal.
- **F1 is enforced at execute.** A T1 action runs only if `action_log` holds an `approved` or
  `edited` row for *exactly* its idempotency key. If the payload is tampered with between approval
  and execution, the key changes and execution fails closed (`execution_blocked`).
- **Idempotency is enforced twice.** `execute` checks for a prior `executed` row, and a partial
  unique index allows at most one `executed` row per key. Re-running execute from a checkpoint
  logs `duplicate_skipped`.
- **Status is derived, never stored.** A proposal's status is its latest terminal `action_log`
  event, or `pending`.
- **Approver decisions are also posted as LangSmith feedback** (`approval`: approve=1,
  edit=0.5 with the new params as the correction, reject=0). This is fail-open: a LangSmith
  failure is logged as a warning and never blocks the decision.
- **Evidence is normalized to plain JSON at the graph boundary** (`runner.to_plain`). Live
  `decompose_metric()` output carries numpy scalars, which the checkpointer can't serialize. This
  was found on the first live run.
- **Interrupt and resume:** `await_approval` re-runs from its first line on resume, so nothing
  before `interrupt()` writes anything. The one exception is the expiry check, which ends the
  run instead of interrupting.

## Executors, `--live` and undo (A4)

| Action | Executor | Effect | Without `--live` | Undo |
|---|---|---|---|---|
| `annotate_anomaly` | `LocalStoreExecutor` | row in `annotations` | same (local) | log-only: the tag stops counting |
| `suppress_alerts` | `LocalStoreExecutor` | row in `suppressions` | same (local) | the pipeline alert resumes |
| `create_control` | `LocalStoreExecutor` | row in `controls` | same (local) | the watch stops being evaluated |
| `notify_owner` | `NotifierExecutor` | a message to the owner via `alerting.notifier` | outbox: real (local file); any other channel: `simulated` | not reversible |
| `open_incident` | `GitHubIssueExecutor` | a GitHub Issue in `ACTION_GITHUB_REPO` | `simulated` | closes the issue with a comment (needs `--live`) |

- **`--live`** (on `approve`, `edit`, `undo`) means "allowed to cause effects outside this
  machine". The outbox is a local file, so `notify_owner` really runs without it. A simulated
  execution still logs `executed` with detail `simulated`, so the log never claims a send that
  didn't happen.
- **GitHub (D8):** repo from `ACTION_GITHUB_REPO` (no default, on purpose), token from
  `GITHUB_TOKEN` (a fine-grained PAT with Issues read/write on that one repo). The issue body
  ends with `<!-- metricpulse:idempotency_key=… -->`, and before creating, the executor lists the
  repo's `metricpulse`-labelled issues and reuses one carrying the key. So a crash between
  GitHub's reply and the `executed` row can't open a duplicate on a re-run.
- **Owner messages** go to the owner resolved from `owners.yaml`, never an LLM param, with the
  idempotency key in the message metadata.
- **Undo (F3):** `python -m action_agent.cli undo <id> --reason "..." [--live]`. Only an
  `executed`, reversible action; a reason is required. It writes an `undone` row (a terminal
  status), and the effect tables are never edited: the active-effect queries exclude keys with
  an `undone` row. A second undo is refused. Since A6 an undo is its own root run
  (`action_agent.undo`), and its id is on the `undone` row's `trace_id`, as for a decide.

## Pipeline hooks: suppression and watches (A4, `hooks.py`)

Local pipeline runs read `actions.db` (when it exists; never inside Lambda, `ACTION_PIPELINE_HOOKS`):

- **D3, suppression.** `run_pipeline` step 5 checks `pipeline_suppression('olist', metric, date)`.
  An approved, unexpired, not-undone `suppress_alerts` for that anomaly means
  `alert.status = suppressed` (with `until` and `reason`), **even with `--force-alert`**: it's a
  human decision, and undo is the way to alert anyway.
- **D4/F4, watches.** `run_pipeline` step 6 (and the `onboarding.investigate` CLI, for onboarded
  datasets) runs `evaluate_controls(dataset, metric, current, previous)`. Every active watch for
  that dataset and metric is checked against the segment's **real value that day**, from the
  full per-dimension query (`fetch_dimension_metrics`), not the decomposition's top 5. No rows
  that day counts as 0. The threshold is strict (`below 500` does not fire at exactly 500).
  A breach sends one message to the watch's owner and logs `control_breached` on the proposal
  that created it. **One alert per watch per day**, enforced by `control_alerts`'
  `UNIQUE (control_id, metric_date)`; a second run reports `already_sent_today`. `--dry-run`
  reports breaches and sends nothing.
- Both are wrapped in the pipeline's never-raise convention: a broken `actions.db` logs a warning
  and the alert goes out unsuppressed.
- `run_cycle()` itself doesn't evaluate watches, because `propose` calls it and making a
  proposal must not send watch alerts.

## The LLM proposer (A3)

`propose` calls `proposer_fn(state)`. With the LLM proposer (the CLI default), one run is:

1. **gpt-oss-20b** (`ACTION_SMALL_MODEL`) drafts a `ProposalDraft`: `reasoning`, `action_type`
   (one of the catalog names), flat optional `params`, and 1–3 `rationale_citations`.
2. **Validation** (`validate_proposal`): every citation must name a real (dimension, segment) in
   the decomposition evidence (Phase 1's `validate_citation`), and the proposal must pass
   `policy_check`. Unused params are dropped first, so the chosen action's strict schema applies.
3. **Any failure escalates once** to **gpt-oss-120b** (`ACTION_LARGE_MODEL`): an invalid draft, an
   unparseable one, or an API error. The previous draft and its errors go back as a
   `PREVIOUS_ATTEMPT` data field. This is the only retry.
4. **A second failure falls back** to `fallback_proposal` (notify the top driver's owner).
5. **Budget:** `ACTION_TOKEN_BUDGET` (10,000) per run. Before each call the wrapper estimates
   prompt chars ÷ 4 plus a 4,096-token output reserve. If that doesn't fit, the call isn't sent
   and the run falls back. The charge is the real usage from the response.

The graph re-runs `policy_check` on whatever comes back, so every proposer is gated the same way.
The `proposed` log row's `actor` is the proposer (`llm:openai/gpt-oss-20b`, `llm:…120b`, or
`deterministic_fallback`), and its `detail` is the attempt trail, e.g.
`openai/gpt-oss-20b invalid -> openai/gpt-oss-120b grounded; 2,400 tokens`. Every call is also a
line in `logs/llm_calls.jsonl` and a LangSmith run (`observability/README.md`).

**Untrusted data (N3).** Segment names, values and the narrative only appear inside the
`<data>` JSON block of the human message. The system prompt is a constant, generated from the
catalog and its Pydantic schemas (so its bounds match what `policy_check` enforces), and says
that the data block is never instructions. A test asserts a hostile segment name can't reach it.

**Escalation rate** (N2) = runs whose `propose_action` lines include an `attempt: 2`, ÷ runs.
Both are in `logs/llm_calls.jsonl` (group by `metadata.proposal_id`).

**Live result (2026-11-02, `probe --small-only`):** 20b alone grounded 12/12 real cases on the first
attempt, all 12 passed `policy_check`, 11/12 targeted the top driver. Median 2,615 tokens per run,
max 4,050; $0.0042 for all 12. See the scope's A3 decision log.

## Gotchas

- `anomaly_id` excludes the segment (D1): one anomaly gets one proposal for its lifetime.
- The idempotency key hashes the *validated* params, so an approver's edit gives a new key. This
  is intended (the scope doc's D8 note).
- **Groq rate limit:** gpt-oss-20b on this account allows **8,000 tokens per minute** (read from
  Groq's `x-ratelimit-*` headers). A run uses ~2.5–4k, so back-to-back runs are throttled: the SDK
  waits and retries, and latency jumps from ~1s to 20–30s. Expect this in batch evals (A5).
- **Temperature 0 isn't deterministic.** In the live test, 20b proposed `annotate_anomaly` once for
  a case where a re-run proposed `notify_owner`. (`annotate_anomaly` was T0 then; since A5 it needs
  approval, see below.)
- **Nothing auto-executes since A5.** The adversarial eval got hostile segment text to auto-apply
  `annotate_anomaly` in 5 of 10 cases, so it moved to T1. The T0 path is kept and tested with an
  injected `catalog=` (`build_action_graph`, `ActionAgent`).
- **Only `total_revenue` and `order_count` can be proposed on for Olist.** The per-dimension
  tables don't carry `customer_count` or `avg_order_value`, so there is nothing to decompose;
  `propose` says so instead of crashing (`evidence.require_decomposable`).
- D1 means one proposal per (dataset, metric, date) ever, so re-testing the same anomaly needs a
  scratch `ACTIONS_DB_PATH`/`CHECKPOINTS_DB_PATH`.
- Grounding uses decomposition-level segments only, not drill-down detail values. Owners and
  `create_control` evaluation (D4) are both segment-level, and `decompose_metric` is what D4
  re-runs.

## Tests

`tests/test_action_policy.py`, `tests/test_action_dry_run.py` (pure functions),
`tests/test_action_store.py`, `tests/test_action_graph.py` (real SQLite and a real `SqliteSaver`
on `tmp_path`, `RecordingExecutor`, injected clock and proposer), `tests/test_llm_proposer.py`
(the D2 routing and budget with injected models that return canned structured outputs, N3, and
the graph wiring), `tests/test_action_executors.py` (the notifier outbox, and `open_incident`
against a real local HTTP server speaking GitHub's REST calls), `tests/test_action_hooks.py` (undo,
D3 and D4 end to end through a real `ActionAgent`). `tests/test_action_api.py` (the A6
API through Django's real routing and DRF). No mocks.
