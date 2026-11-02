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
# Only if your account is NOT on the default US (GCP) region, and for org-scoped keys:
LANGSMITH_ENDPOINT=https://aws.api.smith.langchain.com   # the API URL for your region
LANGSMITH_WORKSPACE_ID=<workspace uuid>                  # required for an org-scoped service key
```

**If every request returns 403 "Forbidden"** (the same response a made-up key gets), it's almost
always the setup, not the key. Found the hard way on 2026-11-02, when three valid keys in a row
were "rejected":
1. **Region.** Keys only work on the region their org was created in, and the SDK defaults to
   `https://api.smith.langchain.com` (GCP US). Read the host off the LangSmith web UI's address
   bar: `smith.langchain.com` → default; `eu.smith…` → `https://eu.api.smith.langchain.com`;
   `aws.smith…` → `https://aws.api.smith.langchain.com`. This account is on **AWS US**.
2. **Workspace.** An org-scoped service key authenticates (`/api/v1/orgs/current` and
   `/api/v1/workspaces` return 200) but every data call returns 403 until
   `LANGSMITH_WORKSPACE_ID` names a workspace (the SDK then sends `X-Tenant-Id`). The
   workspace id is the UUID after `/o/` in the UI URL.

Quick check without printing the key: `GET $LANGSMITH_ENDPOINT/api/v1/orgs/current` with an
`x-api-key` header. 200 means the key and region are right; then try `/sessions`.

**Plan limits (Developer, free):** 5,000 base traces a month, hard-capped on a personal org until
a card is added, and **14-day retention** for base traces (the project's `trace_tier` reads
`shortlived`). This is why LangSmith is a mirror and the local files are the record (D11):
anything older than two weeks exists only locally.

LangGraph and LangChain read these straight from the environment (`config/settings.py` loads
`.env`), so every graph node and LLM call is traced with no per-node code. `run_config()` gives
each invocation a known root run id (= its trace id), which callers store next to what the run
did. For the Action Agent that is `proposals.trace_id` and `action_log.trace_id`.

## Rules

- **Fail-open.** Every helper catches its own errors. A disabled, unreachable or rejecting
  LangSmith never blocks or fails a run (N5). This was verified live with a key LangSmith
  rejected (403): the proposal still paused, was approved and executed.
- **Feedback names the project as `session_id`, never `project_id`.** langsmith 0.10.x raises
  if `project_id` is passed with `run_id`/`trace_id`, and fail-open turned that into a silently
  dropped approval. `feedback_kwargs()` builds the arguments, and a test pins their shape.
- **A mirror, not the record.** Nothing reads LangSmith to make a decision. The local files
  (`actions.db`, and the eval ledger once it exists) are the source of truth (D11).
- **Tests stay offline.** CI and pytest never set `LANGSMITH_TRACING`.
  `tests/test_tracing.py` asserts the helpers are no-ops in that state.
- **Data leaves the machine when tracing is on.** Prompts and evidence go to LangSmith's hosted
  service. Keep it off when onboarding a private dataset.
