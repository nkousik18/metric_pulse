# observability/

LangSmith tracing helpers shared by every agent (`docs/action-agent-scope.md` §13, D10, D11).

## Files

| File | Purpose |
|------|---------|
| `tracing.py` | `tracing_enabled()`, `run_config()` (root run id + §13.2 metadata/tags + thread), `post_feedback()`, `trace_url()`, `flush()`, `git_sha()`. |

`llm.py`, the shared LLM telemetry wrapper (§13.3: tokens, cost, latency, outcome →
LangSmith + `logs/llm_calls.jsonl`), arrives in A3.

## Turning tracing on

```bash
# .env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...
LANGSMITH_PROJECT=metricpulse     # default if unset
```

LangGraph and LangChain read these straight from the environment (`config/settings.py` loads
`.env`), so every graph node and LLM call is traced with no per-node code. `run_config()` gives
each invocation a known root run id (= its trace id), which callers store next to what the run
did. For the Action Agent that is `proposals.trace_id` and `action_log.trace_id`.

## Rules

- **Fail-open.** Every helper catches its own errors. A disabled, unreachable or rejecting
  LangSmith never blocks or fails a run (N5). This was verified live with a key LangSmith
  rejected (403): the proposal still paused, was approved and executed.
- **A mirror, not the record.** Nothing reads LangSmith to make a decision. The local files
  (`actions.db`, and the eval ledger once it exists) are the source of truth (D11).
- **Tests stay offline.** CI and pytest never set `LANGSMITH_TRACING`.
  `tests/test_tracing.py` asserts the helpers are no-ops in that state.
- **Data leaves the machine when tracing is on.** Prompts and evidence go to LangSmith's hosted
  service. Keep it off when onboarding a private dataset.
