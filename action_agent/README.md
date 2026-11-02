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

`notify_owner` and `open_incident` are simulated until A4's live executors. Per D7, the build
stops for review after A3.

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
| `executors.py` | `LocalStoreExecutor` (annotate/suppress/control → effect tables), `SimulatedExecutor` (notify/incident until A4), `RecordingExecutor` (tests). |
| `graph.py` | `build_action_graph()`: the §5 flow, compiled with a checkpointer. |
| `runner.py` | `ActionAgent`: wires store + `SqliteSaver` + executors + LangSmith run config; `start`, `decide`, `pending`, `waiting_on`. |
| `replay.py` | `replay_decisions()`: re-runs every logged policy decision on its stored evidence snapshot (§13.6). |
| `cli.py` | `python -m action_agent.cli propose|pending|show|approve|edit|reject|log|replay`. `propose` uses the LLM proposer; `--no-llm` uses the deterministic one. |

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
  a case where a re-run proposed `notify_owner`. `annotate_anomaly` is T0 (auto) but tag-only.
- `propose` still only takes onboarded datasets (`run_cycle`). Olist runs locally since L1, but
  wiring `--dataset-id olist` into `propose` is left for A4/A5 (`probe.py` builds Olist cases).
- Grounding uses decomposition-level segments only, not drill-down detail values. Owners and
  `create_control` evaluation (D4) are both segment-level, and `decompose_metric` is what D4
  re-runs.

## Tests

`tests/test_action_policy.py`, `tests/test_action_dry_run.py` (pure functions),
`tests/test_action_store.py`, `tests/test_action_graph.py` (real SQLite and a real `SqliteSaver`
on `tmp_path`, `RecordingExecutor`, injected clock and proposer), `tests/test_llm_proposer.py`
(the D2 routing and budget with injected models that return canned structured outputs, N3, and
the graph wiring). No mocks.
