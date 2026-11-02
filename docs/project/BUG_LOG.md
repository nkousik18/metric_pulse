# Bug Log

Every real bug found in MetricPulse since the agentic-layer work began (2026-08), in one place:
what broke, how it was found, the root cause, the fix, and what now stops it coming back.
Newest first within each section. Append a row when a bug is found; never rewrite an old one
(same rule as `SESSION_LOG.md`, where the fuller story of each lives).

**Kinds:** *code* (the program was wrong) · *test* (a test was wrong or unsafe) · *config/setup*
(the code was fine, the environment wasn't) · *design doc* (the spec was wrong) · *process*
(something I did while building went wrong) · *constraint* (not a bug, but it changes how
things must be run).

**How found:** *live* = by running the real command against real data or a real service ·
*test* = a unit test caught it · *review* = by reading code or docs.

## Summary

| | Count |
|---|---|
| Bugs logged | 34 |
| Found by running it live | 24 |
| Found by a unit test | 2 |
| Found by review | 8 |
| Kinds | code 22, config/setup 6, constraint 1, design doc 2, process 2, test 1 |

**The pattern:** 24 of 34 were found only by running the real thing (a real dataset, a real
API, a real CI run). Each milestone's unit tests were green while these bugs existed, because the
tests used tidy fixtures: plain floats instead of numpy, Olist-only dimension names, in-memory
data instead of a CSV, a fake key instead of a real account. That is why every roadmap box is
checked only after a live run (CLAUDE.md), and why several fixes below come with a regression
test that was confirmed to fail without the fix.

---

## Action Agent (A1–A4, 2026-11)

| # | Milestone | Kind | Bug | How found | Root cause | Fix | Guard |
|---|---|---|---|---|---|---|---|
| A4-1 | A4 | code | `propose --dataset-id olist --metric customer_count` crashed with a bare `KeyError: 'total_current'` | live (the new Olist propose path) | Olist's per-dimension tables carry only `total_revenue` and `order_count`, so every dimension's decomposition is an error, and `generate_narrative` indexes the first one without checking. The pipeline has the same latent issue (it reports `status: failed` with the KeyError) | `evidence.require_decomposable()` refuses such a metric with a clear message, and `propose` exits with it | `test_action_hooks.py::test_a_metric_no_dimension_carries_is_refused_clearly` |
| A3-3 | A3 | constraint | Back-to-back proposer runs slow from ~1s to 19–30s | live (probe, 12 runs) | Groq allows gpt-oss-20b **8,000 tokens/minute** on this account (confirmed from `x-ratelimit-*` headers); the SDK silently waits and retries | None needed for single proposals; recorded so A5's batch evals pace themselves | `action_agent/README.md` Gotchas |
| A3-2 | A3 | code | The same case gave `annotate_anomaly` once and `notify_owner` on a re-run | live (probe re-run) | LLM output isn't deterministic even at temperature 0 (expected, §13.6). It matters because `annotate_anomaly` is T0 and runs without approval | None in code: annotations are tag-only and never affect alerting | Recorded for an A5 adversarial case |
| A3-1 | A3 | code | LLM telemetry metadata (tokens, cost, outcome) never appeared on the LangSmith run | live (traced CLI propose, inspecting the run tree) | `observability/llm.py` added metadata *after* the `traceable` function returned, when LangSmith had already closed the run. Fail-open hid it | The call and all its bookkeeping now run inside the traced function | Re-verified on a live trace; `observability/README.md` Gotcha |
| A2-6 | A2 verify | code | Every approval's LangSmith feedback was silently dropped | live (first run with a working key) | `post_feedback` passed `project_id` together with `trace_id`, which langsmith 0.10.16 rejects. It had been added to silence a deprecation warning, but only ever run against a rejecting key. Fail-open turned the error into a log warning | Project goes in `session_id`, built by `feedback_kwargs()` | `test_tracing.py::test_feedback_names_the_project_as_session_id_not_project_id` |
| A2-5 | A2 verify | config/setup | Three valid LangSmith keys all returned 403, looking exactly like a made-up key | live | The account is on LangSmith's **AWS US** region (`aws.smith.langchain.com`), but the SDK defaults to GCP US; and the org-scoped service key also needs a workspace id | `LANGSMITH_ENDPOINT=https://aws.api.smith.langchain.com` and `LANGSMITH_WORKSPACE_ID` in `.env`; no code change | 403 checklist in `observability/README.md`; `.env.example` |
| A2-4 | A2 | code | `pending` listed proposals already past their 24h TTL | live | TTL was checked only when a decision arrived, not when listing | `pending()` filters expired proposals | `test_action_graph.py` (TTL cases) |
| A2-3 | A2 | code | The action graph crashed when checkpointing live evidence | live (Superstore) | Real `decompose_metric()` output contains numpy scalars, which the checkpointer's msgpack serializer rejects. The tests used plain floats | `runner.to_plain()` normalizes evidence at the graph boundary | Regression test, confirmed to fail without the fix (`test_action_graph.py`, numpy evidence) |
| A1-1 | A1 | code | `suppress_alerts` accepted `days: true` (as 1) and `days: "5"` | test (probing the schema) | Pydantic's lax mode coerces bools and numeric strings | `Field(strict=True)` on every numeric param | `test_action_policy.py` non-strict cases |

## Local stack (L1–L3, 2026-11)

| # | Milestone | Kind | Bug | How found | Root cause | Fix | Guard |
|---|---|---|---|---|---|---|---|
| L3-3 | L3 | process | A "revert" of a deliberately broken dbt model didn't revert it | review (the push was rejected) | `git revert -q` isn't a valid flag, so the revert never ran; the following `--amend` just renamed the break commit | Reset the branch to the remote, reverted properly, diffed against the pre-break commit | Nothing wrong reached GitHub |
| L3-2 | L3 | config/setup | CI's `dbt-check` failed on a docs-only commit | live (CI) | Its `pip install dbt-redshift` is unpinned, and the newest dbt downloads a parser wheel from GitHub, which returned HTTP 500 | Re-run passed. Job left unchanged (never-delete-AWS rule) | Recorded in `docs/local-stack-scope.md` |
| L3-1 | L3 | config/setup | CI's `dbt-check` could never catch a broken dbt model | review, then proven live | It runs `dbt parse … \|\| echo`, so it always exits 0 | New `dbt-build-local` job runs a real `dbt build` on a committed sample; proven to fail on a deliberately broken model while `dbt-check` passed | `.github/workflows/ci.yml` |
| L3-0 | L3 | config/setup | CD failed on every merge to `main` from at least 2026-08-19 (including all of PRs #24–#29) | review (`gh run list`) | `cd.yml` needs the deleted AWS credentials. "CI green" had been reported without checking CD | `cd.yml` is manual only (`workflow_dispatch`) | Verified: the next merge triggered no CD run |
| L2-2 | L2 | code | A local run with live AWS credentials would have published billed CloudWatch metrics | review (after L2-1) | `run_pipeline` published CloudWatch metrics on every non-dry run | New `CLOUDWATCH_METRICS` setting, off locally, on in Lambda | `config/README.md` |
| L2-1 | L2 | test | A unit test **really published one SNS message** | live (the test passed with a real SNS response) | The test removed `SNS_TOPIC_ARN` from the environment, but `sns_publisher` calls `load_dotenv()` on import, which refills a *missing* variable from `.env`. The topic and credentials were still live despite the AWS teardown | Set the variable to `''` instead (dotenv never overrides a set variable) | Comment in `tests/test_notifier.py`; warning in `alerting/README.md` and `CLAUDE.md` |
| L1-3 | L1 | code | `parse_ddl` lost columns from a single-line `CREATE TABLE` | test | It matched one column per line | Split on top-level commas | `test_local_warehouse.py::test_parse_ddl_ignores_comments_and_keeps_decimal_precision` |
| L1-2 | L1 | code | Three dbt models failed on DuckDB | live (`dbt build`) | Redshift-only SQL: `DATE_PART(year, x)`, `DATEDIFF(day, …)`, and the source's hardcoded database. I had first claimed the models had no Redshift-specific SQL, from a case-sensitive grep | Portable SQL valid on both: `EXTRACT`, `dbt.datediff`, `target.database` | `dbt build` passes on both targets; CI's `dbt-build-local` |
| L1-1 | L1 | design doc | "Revenue decreased 80.0%, Credit Card 107.1%" was presented as real output in launch-video materials | live (cross-checked against the raw CSVs) | It is `docs/scoping.md` §3.8's illustrative example; the real figures for 2018-09-03 are −90.6% and 106.6% | Recorded; the user's untracked `brag-output/` was not edited | `docs/local-stack-scope.md` decision log |
| L1-0 | L1 | process | A Redshift host and password were printed into the session transcript | review | A BSD `sed` redaction of `~/.dbt/profiles.yml` failed silently | The user was told to change that password anywhere it's reused; that file is never printed again | Rule: secrets are shown only as prefix, length or hash |

## Phase 2: dataset onboarding (M4–M6, 2026-08)

| # | Milestone | Kind | Bug | How found | Root cause | Fix | Guard |
|---|---|---|---|---|---|---|---|
| M6-6 | M6 | code | Onboarding crashed reading the Superstore CSV | live | The file is Windows-1252, not UTF-8 | `cp1252` fallback on `UnicodeDecodeError` in `onboard.py` | Live re-run |
| M6-5 | M6 | config/setup | The Phase 1 model stopped working | live | `llama-3.3-70b-versatile` was removed from Groq's catalog | Live-tested replacements; `openai/gpt-oss-120b` was the only reliable one (4/4) and became the default | `config/settings.py` |
| M6-4 | M6 | code | Reconciliation reported a spurious 1-cent mismatch | live (Superstore) | Rounding to 2 decimals before `.equals()`; real sums straddled a rounding boundary | Compare unrounded sums with `np.allclose(atol=0.01, rtol=1e-6)` | `test_reconciliation.py` |
| M6-3 | M6 | code | `Sales` and `Profit` were classified as ID columns | live (Superstore) | The ID heuristic's cardinality check also applied to floats, and continuous dollar amounts are nearly unique | Float columns exempt from the cardinality check; integers still checked | `test_profiling.py` |
| M6-2 | M6 | code | Column names with spaces broke DuckDB `CREATE TABLE` | live (Superstore) | Real names like `Order Priority` aren't bare SQL identifiers | `sanitize_identifier()` on every generated identifier | `test_codegen.py` |
| M6-1 | M6 | code | **Phase 1 fell back on every run against a non-Olist dataset** | live (the first real non-Olist run) | `EvidenceCitation.dimension` was `Literal['geography', 'product', 'payment']`, an Olist-only assumption, so real citations were coerced into wrong names and then failed grounding | Plain `str`; the grounding check already validates the real pair | Golden Case #1 re-verified 3/3; comment in `investigation/schemas.py` |
| M5-2 | M5 | code | Re-running onboarding on the same file crashed | live (the CLI, second run) | `CREATE TABLE` on a table left by the previous run | `CREATE OR REPLACE TABLE` | Live re-run |
| M5-1 | M5 | code | A `region` value `"NA"` (North America) was silently read as null, failing reconciliation | live (the CLI on a real CSV) | `"NA"` is in pandas' default `na_values` | `keep_default_na=False, na_values=['']` | Live re-run; M4's eval was in-memory and couldn't have caught it |

## Phase 1: investigation agent (M0–M3, 2026-08)

| # | Milestone | Kind | Bug | How found | Root cause | Fix | Guard |
|---|---|---|---|---|---|---|---|
| M3-1 | M3 | code | "Grounding pass rate" would have overstated how often the first attempt worked | review | First-attempt-only and grounded-after-retry were conflated in the eval metric | Separate first-attempt and overall rates | `test_eval_summarization.py` |
| M2-3 | M2 | code | No central constructor for a fully defaulted graph state | live (first full graph run) | Fixture tests never built state the way production does | `build_initial_state()` | Used by every caller |
| M2-2 | M2 | code | `detect`/`decompose_all` nodes weren't idempotent and would re-query the warehouse | live (first full graph run) | Nodes recomputed instead of reusing state | Nodes skip work already in state | `test_investigation_routing.py` |
| M2-1 | M2 | code | `route_after_ambiguity` raised on a missing key | live (first full graph run) | A `.get()` without a default | Defaulted | `test_investigation_routing.py` |
| M1-3 | M1 | code | The model produced *valid* output citing the *wrong* segment (a parent instead of the drill-down finding) | live | The evidence layout steered the model to higher-level segments | Restructured the evidence layout in the prompt | Golden Case #1 |
| M1-2 | M1 | design doc | The scoping doc's `validate_citation` snippet indexed the decomposition one level too shallow | review | The doc's pseudocode didn't match the real `decompose_metric()` shape | Implemented against the real shape; documented as a correction | `investigation/validation.py` docstring |
| M1-1 | M1 | config/setup | `GROQ_API_KEY` was first read as xAI's "Grok" | review | Name ambiguity | Corrected to Groq before anything depended on it | — |

## Older known issues (pre-initiative, still open)

| Issue | Where documented |
|---|---|
| The dashboard's drill-down toggle UI wiring is dead | `docs/dashboard_layer.md` |
| `sns_publisher`'s actual boto3 publish has no test | `alerting/README.md`, `tests/README.md` |
