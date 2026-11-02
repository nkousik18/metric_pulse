# action_agent/

The Action Agent (`docs/action-agent-scope.md`): turns a validated investigation into a proposed
action from a fixed catalog, gates it deterministically, and (from A2) routes it through human
approval to idempotent execution and an append-only log. Local-only (scope doc §11 D9).

**Built so far:**
- **A1:** the catalog, schemas, `policy_check`, owner resolution, identities and the dry-run
  payload builder.
- **A2:** the action graph with a SQLite checkpointer and `interrupt()` approvals, the CLI
  approver, `actions.db`, executors, decision replay and LangSmith run linking.

Nothing calls an LLM yet (A3). `notify_owner` and `open_incident` are simulated until A4's live
executors.

## Files

| File | Purpose |
|------|---------|
| `catalog.py` | `Tier` (T0 auto / T1 approval / T2 never), `ActionSpec`, the fixed `CATALOG` of five actions, `PERMITTED_TIERS`. |
| `schemas.py` | `ActionProposal` and one strict (`extra='forbid'`) params model per action; `SUPPRESS_MAX_DAYS`, `CONTROL_MAX_EXPIRY_DAYS`. |
| `policy.py` | `policy_check(proposal, evidence, catalog=CATALOG) -> PolicyResult` — the gate. |
| `owners.py` / `owners.yaml` | Segment → owner mapping and `resolve_owner()`. |
| `identity.py` | `anomaly_id()` (D1), `idempotency_key()`, `canonical_json()`, `OLIST_DATASET_ID`. |
| `dry_run.py` | `ActionContext`, `build_dry_run()` (exact target + payload + key), `render_dry_run()` for the CLI approver. |
| `proposer.py` | `fallback_proposal()`: deterministic `notify_owner` for the top driver. It is A2's proposer and D2's fallback. |
| `store.py` | `ActionStore` over `actions.db`: insert-only `proposals` (UNIQUE `anomaly_id`), trigger-enforced append-only `action_log`, effect tables. |
| `executors.py` | `LocalStoreExecutor` (annotate/suppress/control → effect tables), `SimulatedExecutor` (notify/incident until A4), `RecordingExecutor` (tests). |
| `graph.py` | `build_action_graph()`: the §5 flow, compiled with a checkpointer. |
| `runner.py` | `ActionAgent`: wires store + `SqliteSaver` + executors + LangSmith run config; `start`, `decide`, `pending`, `waiting_on`. |
| `replay.py` | `replay_decisions()`: re-runs every logged policy decision on its stored evidence snapshot (§13.6). |
| `cli.py` | `python -m action_agent.cli propose|pending|show|approve|edit|reject|log|replay`. |

## The catalog

| Action | Tier | Reversible | Params |
|---|---|---|---|
| `annotate_anomaly` | T0 | yes | `category`, `cause` — tag only, no alerting effect |
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
`targets` (`github_repo`, `sns_topic_arn`) are `None` until A4 configures them, and the dry run
shows them as `None` rather than hiding them. `now` is injectable so expiries are deterministic in
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

## Gotchas

- `anomaly_id` excludes the segment (D1): one anomaly gets one proposal for its lifetime.
- The idempotency key hashes the *validated* params, so an approver's edit gives a new key. This
  is intended (the scope doc's D8 note).
- Grounding uses decomposition-level segments only, not drill-down detail values. Owners and
  `create_control` evaluation (D4) are both segment-level, and `decompose_metric` is what D4
  re-runs.

## Tests

`tests/test_action_policy.py`, `tests/test_action_dry_run.py` (pure functions),
`tests/test_action_store.py`, `tests/test_action_graph.py` (real SQLite and a real `SqliteSaver`
on `tmp_path`, `RecordingExecutor`, injected clock and proposer). No mocks.
