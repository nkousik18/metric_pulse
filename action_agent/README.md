# action_agent/

The Action Agent (`docs/action-agent-scope.md`): turns a validated investigation into a proposed
action from a fixed catalog, gates it deterministically, and (from A2) routes it through human
approval to idempotent execution and an append-only log. Local-only (scope doc §11 D9).

**Built so far: A1** — the catalog, schemas, `policy_check`, owner resolution, identities, and
the dry-run payload builder. All pure functions; no I/O except reading `owners.yaml`. Nothing here
executes an action yet, and nothing calls an LLM yet (A3).

## Files

| File | Purpose |
|------|---------|
| `catalog.py` | `Tier` (T0 auto / T1 approval / T2 never), `ActionSpec`, the fixed `CATALOG` of five actions, `PERMITTED_TIERS`. |
| `schemas.py` | `ActionProposal` and one strict (`extra='forbid'`) params model per action; `SUPPRESS_MAX_DAYS`, `CONTROL_MAX_EXPIRY_DAYS`. |
| `policy.py` | `policy_check(proposal, evidence, catalog=CATALOG) -> PolicyResult` — the gate. |
| `owners.py` / `owners.yaml` | Segment → owner mapping and `resolve_owner()`. |
| `identity.py` | `anomaly_id()` (D1), `idempotency_key()`, `canonical_json()`, `OLIST_DATASET_ID`. |
| `dry_run.py` | `ActionContext`, `build_dry_run()` (exact target + payload + key), `render_dry_run()` for the CLI approver. |

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

## Gotchas

- `anomaly_id` excludes the segment (D1): one anomaly gets one proposal for its lifetime.
- The idempotency key hashes the *validated* params, so an approver's edit gives a new key. This
  is intended (the scope doc's D8 note).
- Grounding uses decomposition-level segments only, not drill-down detail values. Owners and
  `create_control` evaluation (D4) are both segment-level, and `decompose_metric` is what D4
  re-runs.

## Tests

`tests/test_action_policy.py`, `tests/test_action_dry_run.py`. Pure functions, no mocks.
