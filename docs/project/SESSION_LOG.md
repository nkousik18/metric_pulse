# Session Log

Newest entry at the top. Append-only — past entries are never rewritten, only added above.
See `docs/WORKING_CONVENTIONS.md` for the discipline this file follows.

---

## 2026-08-13 — Built M4: onboarding profiling + classification (Phase 2 kickoff)

**What happened:**
First implementation session on Phase 2 (`docs/scoping.md` §§5–7, the dataset-onboarding agent) —
`docs/ROADMAP.md` milestone M4: Stage A deterministic column profiling
(`onboarding/profiling.py`) and Stage B LLM classification + validation (`onboarding/schemas.py`,
`llm.py`, `prompts.py`, `classification.py`), not codegen (§6) or the human-review CLI
flow/schema-fingerprint cache (§7) — both explicitly scoped to M5. Re-read §5 in full before
planning, which confirmed §5.5's control flow is deliberately *not* built as a LangGraph
`StateGraph` ("a single linear pass with one bounded retry, not a multi-round investigation") — so
`classify_columns_with_validation()` is a plain function, structurally identical to
`investigation/nodes.py`'s `_run_synthesis`, exactly the reuse §10.3 names M4 for.

Two real corrections found during implementation, not just following the design doc as pseudocode:
- **A genuine pandas quirk in `profiling.py`:** `pd.to_datetime()` coerces plain numbers into
  "successfully parsed" nanosecond-epoch timestamps at ~100% success — verified directly in a REPL
  (`pd.to_datetime(pd.Series([100.5, 200.3]), errors='coerce')` returns 100% non-null) before
  writing a guard that short-circuits `date_parse_rate` to `0.0` for any numeric-dtype column.
  Without it, every metric column (`mrr_amount`, `seats`, etc.) would have looked like a perfect
  date column.
- **A miscalibrated constant caught before the real eval run, not after:** `classification.py`'s
  `MAX_DIMENSION_CARDINALITY_RATIO` was first drafted at an arbitrary `0.5` (a plain midpoint
  against `ID_CARDINALITY_THRESHOLD`'s `0.9`). Re-checking it against §5.6's own worked example
  found this would have *accepted* `customer_id` (cardinality ratio 0.164) as a valid dimension —
  but the design doc's own worked example explicitly rejects exactly that column as "too high to
  be a useful grouping dimension." Recalibrated to `0.1`, chosen to sit between that real number
  and `plan_type`/`region`'s ~0.00006 — grounded in the doc's own example, not guessed twice.

`onboarding/eval.py`'s `GOLDEN_CASE_2` — a synthetic SaaS-subscription fixture (fixed-seed,
500 rows, not literally 50,000) reproducing §5.6's worked example's qualitative profile shape — was
built at the same minimal scope `investigation/eval.py` had at Phase 1's M1 (a fixture plus a bare
grading run), not Phase 1's later M3-formalized scope: `docs/ROADMAP.md` never names a Phase-2
equivalent of M3's formalization as its own milestone, so building one wasn't in scope here.

**Real, recorded result** (`python -m onboarding.eval`, live Groq API): the **first** classification
attempt proposed `customer_id` as a dimension; `validate_classification` correctly rejected it
(matching §5.6's own judgment exactly); the retry then matched **every** expected field —
`date_column=event_date`, `grain=other`, `metric_columns=[mrr_amount, seats]`,
`dimension_columns=[plan_type, region]`, `rejected_columns=[subscription_id, customer_id, notes]`,
`requires_human_review=False`, zero validation errors. A genuine, real demonstration of the
retry-then-validate mechanism catching an actual mistake mid-run, not just a case that happened to
pass on the first try — a stronger proof point than M1's Golden Case #1, which was grounded on the
first attempt every time it was run.

**Decisions made:**
- `SchemaClassification`'s `requires_human_review`/`validation_errors` fields are never populated by
  the LLM itself — `classify_columns_with_validation()` always overwrites them post-hoc
  (`clf.model_copy(update={...})`) based on the real validation outcome, never trusting whatever the
  model happened to put there. The system prompt doesn't even mention these two fields to the model.
- `requires_human_review` reflects validation outcome only in M4 (`True` only if the bounded retry
  still leaves errors) — §5.6's stronger rule ("still `True` for a first-ever run regardless of
  validation success") depends on the schema-fingerprint cache, explicitly M5's responsibility, not
  claimed here.
- While touching `tests/README.md` for the two new test files, also fixed its test count and file
  table, stale since M0 (never updated across M1's or M3's additions either) — same "don't leave a
  known-wrong fact standing once found" precedent as prior sessions.

**Current state:** PR #14 merged into `main`, branch deleted. Full suite is 61/61 passing
(15 pre-Phase-1 + 46 across the agentic-layer initiative's M0–M4), verified with `.env` removed
entirely too. `docs/ROADMAP.md`'s M4 checkbox is checked. No new dependencies, no new env vars —
Stage A/B reuse `GROQ_API_KEY`/`GROQ_MODEL`/pandas/pydantic exactly as they already existed.

**Next steps:** M5 — `onboarding/codegen.py` (turning a validated `SchemaClassification` into
actual queryable DuckDB tables, §6), the two additive `dimension_config`/`connection_factory`
parameters on `decomposer.py`/`anomaly_detector.py` (§6.2, backward-compatible defaults reproduce
today's exact behavior), the CLI confirmation flow (§7.3), and the schema-fingerprint cache (§7.5).
Explicitly the milestone that edits already-tested files, so a full pre-existing-suite re-run is
part of its own gate, not optional.

**Loose ends / reminders:**
- Golden Case #2's fixture is 500 rows, not literally 50,000 — named explicitly in
  `onboarding/README.md` as an intentional scope choice ("run for real" means real profiling + a
  real LLM call, not matching an arbitrary row count), not a shortcut hidden from the record.
- `GROQ_MODEL` default (`llama-3.3-70b-versatile`) continues working reliably; the one real retry
  seen this session resolved correctly on the second attempt, exactly as designed.

---

## 2026-08-10 — Built M3, closed Phase 1, wrote its retrospective

**What happened:**
Fourth implementation session on the agentic-layer initiative — `docs/ROADMAP.md` Phase 1,
milestone M3, the last one in the phase. Re-read `docs/scoping.md` §8 in full (not from memory)
before planning, which confirmed two scope boundaries precisely: §8.4's "two more small fixtures"
worth adding are Phase-2/onboarding-classification fixtures, not Phase-1 investigation ones, so no
new golden case was in scope — `GOLDEN_CASE_1` (built in M1) stays the sole Phase-1 case; and §8.5's
metrics are defined per real *call*, not per case, meaning the actual formalization work was running
the same case through multiple real trials and aggregating, not authoring new fixtures.

That re-read also surfaced a real correctness gap in M1's original eval harness: its `grounded`
field conflated `outcome == 'grounded_first_attempt'` with `'grounded_after_retry'` into one number,
and never computed a `fallback_rate` at all — neither matches §8.5's actual metric definitions
("grounding pass rate" is explicitly first-attempt-only, "the metric that shows whether the retry
path is doing real work"). Fixed by deriving both correctly from the `outcome` tag
`_run_synthesis` already returns, and extracted the aggregation into a new pure `summarize_results()`
function so it's unit-tested (`tests/test_eval_summarization.py`, 4 tests, no LLM calls) rather than
trusted by inspection. Added `--runs N` (default 5) to `investigation/eval.py`'s CLI.

**Real, recorded numbers** (`python -m investigation.eval --runs 5`, live Groq API, 5 real trials
of `GOLDEN_CASE_1`): **`grounding_pass_rate=1.00`, `fallback_rate=0.00`, `golden_match_rate=1.00`,
`uncertainty_ok_rate=1.00`** — every trial grounded on the first attempt, correctly cited the
drill-down-level driver, and correctly included the required uncertainty note. Recorded here
exactly as printed, not rounded up or estimated.

With M3 merged (PR #12), Phase 1's own gate (`docs/ROADMAP.md`: real LangGraph agent, wired into
both integration points, grounded summary for a real anomaly, citations validated, pre-existing
tests unmodified) was fully, verifiably met — so this session also closed Phase 1 and wrote its
retrospective, the first one actually practiced under the convention named (but never yet used)
since 2026-07-28: `docs/project/retrospectives/phase-1-investigation-agent.md`. It covers the full
M0–M3 arc: gate evidence, what worked (the deterministic/LLM split held up, grounding-by-validation
caught a real steering bug in M1), every real gap found and fixed across all four milestones (not
just this session's), estimate-vs-actual (§10.2's "weekend" units compressed into single AI-paired
sessions; the real calendar-time cost was a 4-day GitHub Actions outage stalling PR #10's merge, not
implementation), and honest gaps carried into Phase 2. Full detail lives in that file, not repeated
here.

**Decisions made:**
- While closing out the retrospectives convention, also fixed two other stale claims caught in the
  same pass rather than left standing: `docs/WORKING_CONVENTIONS.md` still said `main` "is not
  currently protected by GitHub branch-protection rules" — re-verified directly via `gh api
  .../branches/main/protection` (first checked during this same week's GitHub-outage debugging) and
  confirmed `main` *is* protected (`lint-and-test`/`dbt-check` required, `enforce_admins: true`) —
  this must have been configured at some point without ever being logged; corrected the doc rather
  than leave a two-sessions-old "loose end" note pointing at a already-resolved non-gap.

**Current state:** PR #12 merged into `main`, branch deleted. Full suite is 47/47 passing on `main`
(15 pre-Phase-1 + 32 added across M0–M3). `docs/ROADMAP.md`'s M3 checkbox and Phase 1's overall
gate are both checked/met. `docs/project/retrospectives/phase-1-investigation-agent.md` exists.
Phase 1 is done.

**Next steps:** Phase 2 (`docs/scoping.md` §§5–7) — milestone M4: `onboarding/profiling.py` (Stage
A, deterministic column profiling) and `onboarding/classification.py` (Stage B, LLM role
classification + validation), reusing M1's exact structured-output-plus-validation pattern per
§10.3's own note that M4 "reuses the exact same proven pattern... lower uncertainty than M1."

**Loose ends / reminders:**
- Eval corpus is still one golden case, small-n (5 real trials). Both named as accepted, not
  hidden, v1 sizing in the retrospective — not a defect to fix before Phase 2 starts.
- `GROQ_MODEL` default (`llama-3.3-70b-versatile`) continues working reliably; 5/5 real M3 trials
  all succeeded with zero fallbacks.

---

## 2026-08-10 — Built M2: wired investigation graph into pipeline, API, dashboard

**What happened:**
Third implementation session on the agentic-layer initiative — `docs/ROADMAP.md` Phase 1,
milestone M2 (integration). M0/M1 had built and LLM-integrated all 7 graph nodes as plain
functions, but nothing compiled them into an actual `StateGraph` and nothing outside
`investigation/` called into the package. Re-read `docs/scoping.md` §4 in full (integration
points: orchestration, Django API, dashboard, Lambda) plus the actual current code
(`orchestration/run_pipeline.py`, `dashboard_api/views.py`/`urls.py`, `lambda_handler.py`, the
dashboard templates/JS) before planning, rather than trusting the design doc's illustrative
snippets as literal implementation. That re-read surfaced three real gaps the fixture-based M0/M1
tests never exercised, since none of them ran an actual end-to-end graph invocation:
- `route_after_ambiguity` indexed `state['drilled_dimensions']` directly with no default — the
  very first `assess_ambiguity` → `route_after_ambiguity` transition in a real run has no node
  that's set it yet unless the caller pre-seeded it. Fixed with `.get(..., [])`.
- `detect`/`decompose_all` weren't actually idempotent despite §4.3 explicitly designing the
  pre-seeding mechanism around them being so — both would have silently re-run the exact
  double-Redshift-query anti-pattern already named as a known gap between `NarrativeView`/
  `DecompositionView`. Fixed: both now no-op if their output field is already present in state.
- Added `investigation.state.build_initial_state()` so every call site gets a fully-defaulted
  state by construction instead of each one needing to remember the full field list by hand.

Built: `investigation/graph.py` (compiled `StateGraph`, the only file in the package that imports
`langgraph`), `build_initial_state()`, the two idempotency fixes, `orchestration/run_pipeline.py`'s
Step 4.5 (`run_investigation` kwarg, lazily imported per this file's existing
`monitoring.cloudwatch_metrics` convention, new `--run-investigation` CLI flag), `dashboard_api`'s
new `InvestigationView` (`POST /api/investigate/`) and `PipelineView`'s optional
`run_investigation` field, `lambda_handler.py`'s event passthrough, and a dashboard "Investigate
with AI Agent" button rendering into a visually distinct block beneath the existing narrative
(manual trigger only, not part of `applyFilters()`'s auto-refresh, per §4.6's cost-control
philosophy). New dependency: `langgraph` (+ `langgraph-checkpoint`/`-prebuilt`/`-sdk`, `ormsgpack`);
`langgraph-sdk` downgraded `websockets` from M1's `17.0.1` to `15.0.1` — reconciled in
`requirements.txt` against exact resolved versions, `pip check` clean.

**Decisions made:**
- One correction to `docs/scoping.md` §4.4's `InvestigationView` snippet: it reads Django's
  `settings.ANOMALY_THRESHOLD_ZSCORE`, which doesn't exist (that constant lives in
  `config/settings.py`, never imported by `dashboard_api`). Followed the already-live
  `AnomalyDetectionView` pattern instead — optional `threshold` from the request, `None` otherwise,
  letting `run_detection()`'s own env-var fallback apply — no new settings dependency introduced.
- No new test files, per `docs/ROADMAP.md`'s own M2 description ("plumbing, verified by exercising
  the existing test suite still passes") — this milestone's real proof is live verification: real
  Redshift + real Groq, no mocking, confirmed via CLI (`--run-investigation`, checked the logs for
  exactly one `decompose_metric()` call to prove pre-seeding actually prevented the duplicate
  query), `curl` against both `/api/investigate/` and `/api/pipeline/` (with and without
  `run_investigation`, confirming the default-off response shape is byte-identical to before), a
  direct local call to `lambda_handler.handler()`, and a re-curl of every pre-existing endpoint.

**Current state:** PR #10 merged into `main`, branch deleted. Full suite is still 43/43 passing,
unmodified, `flake8` clean (verified with `.env` fully removed too). `docs/ROADMAP.md`'s M2
checkbox is checked. The investigation agent is now genuinely reachable from three real surfaces
(CLI, Django API, dashboard button) plus Lambda passthrough — not just a library of graph-shaped
functions.

**Next steps:** M3 — formalize `investigation.eval` as a real, separately-triggered command (not
part of `pytest`, since it costs real API money), recording §8.5's metrics (grounding pass rate,
fallback rate, golden-driver match rate) from a real run rather than the single manual Golden
Case #1 run M1 already did.

**Loose ends / reminders:**
- `main` is still not branch-protected... actually it *is* protected now (confirmed while
  debugging PR #10's CI — `required_status_checks: [lint-and-test, dbt-check]`,
  `enforce_admins: true` — this must have been set up between the last session's note and now, but
  was never logged here when it happened). Correcting the carried-over loose end: this is resolved,
  not outstanding.
- **GitHub Actions had a multi-hour platform-wide outage today** (per githubstatus.com: Major
  Outage, 15:22 UTC through at least 23:13 UTC) that blocked PR #10's CI from triggering at all —
  nothing wrong on our end; confirmed via GitHub's own status page, not guessed. Once GitHub's fix
  restored webhook throughput, an empty `git commit --allow-empty` retrigger got CI running again
  within minutes. Worth remembering this trick (push an empty commit to force a fresh
  `synchronize` webhook) if a future PR's CI silently never fires and `gh run list` shows zero runs
  for the branch — check githubstatus.com before assuming a config problem on our side.
- `GROQ_MODEL` default (`llama-3.3-70b-versatile`) is still working reliably as of this session's
  live testing.

---

## 2026-08-05 — Built M1: synthesize node, first live LLM integration

**What happened:**
Second implementation session on the agentic-layer initiative — `docs/ROADMAP.md` Phase 1,
milestone M1, the `synthesize` node. `docs/scoping.md` §4.8 explicitly left provider/model choice
as an implementation-time decision; asked the user directly rather than guessing, which surfaced a
real mix-up worth recording: the user's initial answer ("a grok API") led to building against
xAI's Grok (`langchain-xai`/`ChatXAI`) first, but their actual env var was named `GROQ_API_KEY` —
Groq (groq.com, fast inference of open models) is a different company from xAI's Grok (x.ai),
despite the near-identical name. Confirmed directly before writing more code, uninstalled
`langchain-xai` and its orphaned transitive deps (`aiohttp`/`langchain-openai`/`openai`/`tiktoken`
chain — none of it needed by `langchain-groq`, verified via `pip check` after cleanup), and
rebuilt on `langchain-groq`'s `ChatGroq` instead. Default model: `llama-3.3-70b-versatile` over the
newer Groq-hosted `gpt-oss` models, because research surfaced a known LangChain/Groq
incompatibility between `gpt-oss-120b` and strict-JSON-schema structured output — used
`method='function_calling'` explicitly on `.with_structured_output()` for the same reason.

Built (per `docs/scoping.md` §3): `investigation/schemas.py` (`EvidenceCitation`,
`SynthesisOutput`), `investigation/llm.py` (`get_synthesis_llm()`), `investigation/prompts.py`
(evidence formatting + system prompt), `investigation/validation.py` (`validate_citation`,
`validate_synthesis_output`), `investigation/rendering.py` (template-only number injection, reusing
`narrative.generator`'s `jinja_env`), and in `investigation/nodes.py`: `_run_synthesis` (the actual
LLM call + one bounded retry, kept separate from the `synthesize` node so `eval.py` can grade the
raw `SynthesisOutput` against the same production code path) plus the real `finalize` node
(deferred from M0). Added `investigation/eval.py` with `GOLDEN_CASE_1` (§3.8's worked example,
reconstructed as real `InvestigationState` data) and `tests/test_citation_validation.py` (8 tests).
Added `GROQ_API_KEY`/`GROQ_MODEL` to `config/settings.py`/`.env.example`, and 21 new exactly-pinned
packages to `requirements.txt` (the real `langchain-groq` dependency tree only — carefully excluded
`scipy`, which showed up in a `pip freeze` diff but turned out to be an unrelated pre-existing gap,
already a transitive dependency of `scikit-learn` and nothing to do with this change).

**Decisions made:**
- Fixed a bug in `docs/scoping.md` §3.5's illustrative `validate_citation` snippet rather than
  reproducing it as-is: it indexes `state["decomposition_results"]` directly, but the real shape
  (confirmed against `decomposition/decomposer.py`) nests per-dimension data one level deeper,
  under `"dimensions"`. Documented as a correction in both the code and `investigation/README.md`,
  not silently patched.
- `synthesize` deliberately does not follow §2.7's literal "every node fails to `status='failed'`"
  convention — per §3.2's Tier-1/Tier-2 split, an LLM failure fails *open* to a deterministic
  fallback (`decomposer.get_top_driver()` via a plain f-string) instead, so a broken LLM call can't
  discard an otherwise-successful decomposition. `finalize` still uses the literal convention.
- Real calibration finding from live-testing (exactly what §10.3 names M1 for): the first working
  version of `prompts.py` — drill-down data as a separate trailing section, plus a general
  system-prompt rule to "prefer the drill-down" — reliably produced grounded, valid output, but the
  model kept citing the higher-level ambiguous segment (`Southeast`) as `primary_explanation`
  instead of the more specific drill-down finding (`SP`), even though `SP` correctly showed up as a
  *supporting* citation. Fixed by restructuring evidence layout — nesting each drill-down directly
  under its parent dimension with an explicit "cite this specific segment, not that higher-level
  one" pointer — without touching validation or fallback logic at all. Confirmed stable across 3
  repeated live runs after the fix.

**Current state:** PR #8 merged into `main`, branch deleted. Full suite is 43 tests passing on
`main` (23 pre-existing + 8 new citation-validation tests + verified the whole suite also passes
with `.env` entirely removed, confirming CI needs no `GROQ_API_KEY` secret since no test invokes
the LLM). `flake8 --select=E9,F63,F7,F82` clean. Live-verified end to end: `python -m
investigation.eval` against Golden Case #1 is grounded on the first attempt, cites the correct
driver, includes the required `uncertainty_note`. Fallback path also verified live (invalid
`GROQ_MODEL` → deterministic summary, `grounding_failed=True`, no crash, no false `status=failed`).
`docs/ROADMAP.md` M1 checkbox checked. Still no `langgraph` dependency or compiled `StateGraph` —
that's M2. Nothing in `orchestration/` or `dashboard_api/` calls into `investigation/` yet.

**Next steps:** M2 — Integration (`docs/scoping.md` §4): assemble the actual `StateGraph` now that
all 7 nodes exist, `run_pipeline(run_investigation=...)`, `/api/investigate/`, `PipelineView`
extension, dashboard button, Lambda passthrough. M2's gate explicitly requires the full pre-existing
test suite to still pass unmodified — the milestone that touches the most existing call sites.

**Loose ends / reminders:**
- `main` is still not branch-protected on GitHub (carried over, still not addressed).
- `GROQ_MODEL` default (`llama-3.3-70b-versatile`) worked reliably in this session's live testing,
  but Groq's model catalog (like every provider's) changes — worth a quick sanity check if a future
  session finds `synthesize` suddenly falling back more often than expected.

---

## 2026-08-04 — Built M0: investigation graph skeleton (Phase 1 kickoff)

**What happened:**
First implementation session on the agentic-layer initiative — `docs/ROADMAP.md` Phase 1,
milestone M0. Re-read `docs/scoping.md` Sections 2–4 (the LangGraph design) and the real
`decomposition/decomposer.py`, `detection/anomaly_detector.py`, `orchestration/run_pipeline.py`,
and `narrative/generator.py` source before writing anything, then used plan mode to resolve one
ambiguity in the scoping doc before coding: Section 2.3 lists 7 graph nodes total, but M0's
milestone table (§10.2) says "5 deterministic nodes" — resolved as `detect`, `decompose_all`,
`assess_ambiguity`, `drill_down`, `finalize_skip`, deferring the real `finalize` to M1 alongside
`synthesize` (the LLM node), since `finalize`'s actual job — attaching `investigation_summary` —
only makes sense once `synthesize` produces that field. Consistent with M0's "depends on nothing
new," no `langgraph` package was added and no `StateGraph` was compiled — nodes/routing functions
are plain, independently-testable Python functions for now, matching the calling convention they'll
plug into once M1/M2 assembles a real graph.

Built: `investigation/` (new package — `state.py`'s `InvestigationState`, `nodes.py`'s 5 nodes +
`classify_ambiguity`, `routing.py`'s 3 routing functions + `MAX_ITERATIONS`, `tools.py`'s 4 tool
wrappers, `README.md`); `decomposition/decomposer.py`'s new `fetch_detail_metrics()` (the one
genuinely new backend capability this phase needs) plus a `summarize_dimension()` extraction so it
and the existing `decompose_metric()` share one summary implementation instead of duplicating a
15-line block; `tests/test_investigation_routing.py` (11 tests) and `tests/test_ambiguity_rules.py`
(9 tests). `ambiguous_dimensions` was built directly in its Section 3.4-amended typed form
(`list[{dimension, reason}]`), since that section is a documented amendment to Section 2 and
building the flat form first would've just meant redoing it.

**Decisions made:**
- `classify_ambiguity` checks the `offsetting_segments` condition before `close_contributors` when
  both could apply — a top contributor already over 100% makes "how close is #2" not meaningfully
  defined. Verified against `docs/scoping.md` §3.8's worked example directly (Southeast/Northeast →
  `close_contributors`, Payment → `offsetting_segments`) before trusting it.
- `drill_down` only drills the single top contributor's segment per ambiguous dimension, not every
  close contender — matches the §3.8 worked example (Southeast drilled, not Northeast).
- Followed `CONTRIBUTING.md`'s branch → PR → CI green → squash-merge flow for both the code (PR #5)
  and a small same-session docs follow-up (PR #6, fixing `tests/README.md`'s test count — stale the
  moment M0 added two new test files — and checking M0's `ROADMAP.md` box only after the full suite
  actually passed on `main` post-merge, per CLAUDE.md's "verifiably met" discipline).

**Current state:** PRs #5 and #6 merged and squash-merged into `main`, both branches deleted. Full
suite is 35 tests passing on `main` (15 pre-existing + 20 new), `flake8 --select=E9,F63,F7,F82`
clean. `docs/ROADMAP.md`'s M0 checkbox and its two named test files are checked off.
`investigation/` is not wired into anything yet — no compiled graph, nothing in `orchestration/` or
`dashboard_api/` calls it.

**Next steps:** M1 — `synthesize` (Section 3): Pydantic schemas (`EvidenceCitation`,
`SynthesisOutput`), the structured-output LLM call, `validate_citation`, the bounded retry/fallback
policy, and the Jinja rendering for `investigation_summary`. `docs/scoping.md` flags M1 as "the
highest-uncertainty milestone" — first time this design meets a real LLM provider — and the
designated calibration checkpoint for the rest of the rollout estimate (§10.3), worth an explicit
pause after it ships to check real grounding-pass-rate against the rest of the plan.

**Loose ends / reminders:**
- `main` is still not branch-protected on GitHub (carried over from the previous session's note).
- No `langgraph` dependency in `requirements.txt` yet — will be needed once M1/M2 actually compiles
  a `StateGraph`.

---

## 2026-08-04 — Full documentation staleness audit and fixes

**What happened:**
User asked for the same reconciliation treatment given to `docs/resume_project_doc.md` back on
2026-07-27→28 to be applied to `CLAUDE.md` and every other doc. Rather than re-reading everything
serially, split the ~21 files (`CLAUDE.md`, root `README.md`, `CONTRIBUTING.md`, 13 files under
`docs/`, and 16 folder-level `README.md`s) across 6 parallel audit agents, each verifying a
cluster's concrete claims (function signatures, counts, file paths, CI job names, described
behavior) directly against the running code rather than trusting prior docs. Found genuine
staleness in 10 files, ranging from cosmetic to structural:
- `docs/resume_project_doc.md` had fabricated detail in four places — a dbt test-type breakdown
  that was wrong on every number (and claimed 3 `relationships` FK tests that don't exist at
  all), a detection-functions table listing three functions that were never real
  (`fetch_metric_data`, `calculate_zscore(df, metric_col)`, `format_anomaly_summary`), wrong
  decomposition output field names (`segments`/auto-populated `dominant_driver` vs. the real
  `top_contributors` / separately-computed `get_top_driver()`), and a narrative-templates table
  citing 4 `.jinja2` files that don't exist anywhere in the repo (narrative templates are inline
  Python strings).
- `docs/architecture.md` predated the Django app entirely — its delivery-layer diagram, tech
  stack table, and "Future Enhancements" list all omitted/misstated the fact that Django is the
  live production interface, not a future item. Also caught (independently, while fixing this)
  that both this file and the root `README.md` still listed `scipy` as the detection stack, even
  though it was removed as an unused import a while ago (already correctly noted as removed in
  `docs/detection_layer.md` and `docs/infrastructure_and_deployment.md`'s own "fixed" tables) —
  fixed both.
- `docs/WORKING_CONVENTIONS.md` was the biggest find: it was still, word-for-word in places, the
  write-up from a different project ("Interpose") adopted on 2026-07-28 and never adapted — wrong
  project name throughout, citations to files that don't exist here
  (`docs/INTERPOSE_SCOPING.md`, two `concepts/` files that were never written for this repo), and
  a described CI/branch-protection setup (`lint`/`test`/`helm` jobs, enforced branch protection)
  that doesn't match this repo's actual `lint-and-test`/`dbt-check` CI or its (verified via
  `gh api`) actually-unprotected `main` branch. Rewrote it in place for MetricPulse: correct file
  names throughout, honest about `main` not being branch-protected (named as a gap, not hidden),
  and reframed the `concepts/` guidance to match how this repo actually seeded that folder (one
  pass from already-worked-out scoping ideas, not a grow-as-you-learn log).
- Smaller fixes: `docs/dashboard_layer.md` claimed a red anomaly-highlight feature on the trend
  chart that isn't implemented, and misdescribed `applyFilters()` as calling 4 loaders (it calls
  3); `docs/setup.md` said Python 3.10+ (real: 3.12+) and had a completely fabricated
  `requirements.txt` snippet (16 loose-pinned packages vs. the real ~90 exactly-pinned ones);
  `deploy/README.md` and `docs/resume_project_doc.md` both claimed the CD workflow deploys the
  Django app to Render, but `cd.yml` has no Render deploy step at all (Render deploys via its own
  git-push hook, outside GitHub Actions) — CD's only real current effect is a `dbt run` echo
  placeholder behind an environment-approval gate; `docs/detection_layer.md` and
  `docs/dbt_transformations.md` each had a one-line count mismatch (3 vs. 5 tests, 3 vs. 4 date
  dimensions); `CLAUDE.md` overstated `config/db.py` as "the only" connection factory when the
  Streamlit dashboard intentionally bypasses it.
- Confirmed clean, no changes needed: `docs/README.md`, `CONTRIBUTING.md`, `docs/ROADMAP.md`,
  `docs/ingestion_pipeline.md`, `docs/analytics_pipeline.md`, `docs/infrastructure_and_deployment.md`,
  `tests/README.md`, and 11 of the 16 folder READMEs.

**Decisions made:**
- Rewrite `docs/WORKING_CONVENTIONS.md` in place rather than delete it or leave the gap
  unaddressed (asked the user directly given it required a judgment call, not a mechanical fix)
  — the underlying discipline is genuinely being practiced now, it just needed its concrete
  references corrected.
- Fixed the `scipy` claim in `README.md` even though it wasn't in the original audit scope for
  that file, since it was directly confirmed false while fixing the same claim in
  `architecture.md` — no reason to leave a known-wrong fact standing once found.

**Current state:** All 10 files fixed and committed via `docs/staleness-audit-fixes` branch →
PR → CI green → squash-merge, per `CONTRIBUTING.md`. `CHANGELOG.md` updated with both this fix
and the missing entry for last session's `docs/workflow_diagram.md` PR (#3).

**Next steps:** None outstanding from this pass. A natural future check: re-run this kind of
audit after Phase 1 (investigation agent) actually ships, since that's when `docs/scoping.md`'s
design claims start needing the same "is this actually true of the code now" scrutiny.

**Loose ends / reminders:**
- `main` is still not branch-protected on GitHub — named in `docs/WORKING_CONVENTIONS.md` now,
  but not fixed. Worth doing if this repo is ever shown to reviewers as a workflow-discipline
  example, not just a pipeline one.

---

## 2026-08-04 — Added end-to-end workflow diagram

**What happened:**
User asked for a single document/visual covering the full project workflow — every step, its
inputs, its outputs — suitable for handing to another LLM to generate an image from if a native
image couldn't be produced directly. Re-verified the pipeline shape against
`docs/resume_project_doc.md`, `docs/ROADMAP.md`, and the `orchestration/`, `dashboard_api/`, and
`monitoring/` READMEs before drawing anything, rather than trusting `docs/architecture.md`'s
existing (older, coarser) diagram as-is. Wrote `docs/workflow_diagram.md`: a system-overview
Mermaid flowchart (Data Foundation → Analytics Pipeline → Presentation, color-coded by phase), a
sequence diagram of one `run_pipeline()` call showing the exact data object passed at each
boundary, a CI/CD deployment diagram, per-step input/output tables for every layer, and a
portable natural-language image-generation prompt for another LLM/image tool. Published it as a
Claude artifact (renders the Mermaid live) and indexed it in `docs/README.md`.

**Decisions made:**
- Diagrams show Phase 0 (the live, verifiable system) only — the Phase 1 LangGraph investigation
  agent is named in a callout as scoped-but-not-built rather than drawn in, consistent with the
  "check a box only when verifiably met" discipline the roadmap already follows.
- Kept this as a new file rather than folding into `architecture.md` — that file is the
  component-level system diagram; this one is the data-flow view (concrete inputs/outputs per
  step, not just "layer A talks to layer B"), different enough to earn its own file.

**Current state:** `docs/workflow_diagram.md` created and indexed in `docs/README.md`; both
committed via `docs/workflow-diagram` branch → PR → CI green → squash-merge, per
`CONTRIBUTING.md`. No code changed — documentation only, no `ROADMAP.md` gates affected.

**Next steps:** None outstanding from this change.

**Loose ends / reminders:** none.

---

## 2026-07-28 — Adopted WORKING_CONVENTIONS.md scaffolding

**What happened:**
User shared `docs/WORKING_CONVENTIONS.md` — a documentation/session/git-workflow reflection
written for a different project (Interpose) — and asked to adopt everything in it for
MetricPulse. Built the scaffolding it describes that didn't exist yet: this file
(`docs/project/SESSION_LOG.md`), `docs/ROADMAP.md` (phase-based, Phase 0 = the already-shipped
core pipeline marked done, Phases 1–3 mapped directly onto `docs/scoping.md` §10's M0–M7
milestones), `CHANGELOG.md` (built from real git log history, not invented), `concepts/` (5 seed
files — `CLAUDE.md` as a mechanism, state graphs/LangGraph, grounding LLM output, the
deterministic-vs-LLM judgment split, human-in-the-loop design — plus `concepts/INDEX.md`), and
`CONTRIBUTING.md` (branch naming, the GitHub Flow sequence, squash-merge). Updated `CLAUDE.md`
with the session-start/session-end ritual as an explicit instruction and pointers to all the new
files, and `README.md` with an honest status line and a `concepts/` pointer.

**Decisions made:**
- Phase 0 (the original pipeline) gets one collapsed "done" entry in `ROADMAP.md` rather than a
  granular retroactive breakdown — that work already shipped and is documented elsewhere
  (`docs/resume_project_doc.md`); the roadmap's real job starts at Phase 1.
- `concepts/` is seeded with 5 files extracted from ideas already explained in depth during the
  `docs/scoping.md` conversation, rather than left empty until "new to the domain" learning
  happens live — MetricPulse isn't a from-scratch learning project the way Interpose is, so the
  mechanism is being used as a reusable reference library, not a live learning-in-public log.
- Not rewriting PR #1's already-merged history to retroactively squash it — the squash-merge
  convention applies from this PR forward.

**Current state:** All scaffolding files created on branch `chore/adopt-working-conventions`,
not yet merged (see this branch's PR for status). No agentic-layer code exists yet.

**Next steps:** Commit and merge this scaffolding via the newly-adopted GitHub Flow (branch → PR
→ CI green → squash-merge → delete branch) — the first real use of the convention this session
just adopted. After that: begin `docs/ROADMAP.md` Phase 1, milestone M0.

**Loose ends / reminders:**
- `docs/project/retrospectives/` is named as a convention in `docs/ROADMAP.md` but intentionally
  not created yet — no phase has closed.

---

## 2026-07-27 → 2026-07-28 — Documentation pass + agentic-layer scoping

**What happened:**
Read the full existing `docs/` set to understand the project, then built out documentation that
didn't exist yet: `CLAUDE.md` (root), and a `README.md` in every top-level code folder
(`ingestion/`, `dbt_project/`, `config/`, `infrastructure/`, `detection/`, `decomposition/`,
`narrative/`, `alerting/`, `orchestration/`, `monitoring/`, `deploy/`, `tests/`, `dashboard_api/`,
`metric_pulse_web/`, `templates/`, `dashboard/`), each verified against actual source rather than
copied from existing docs. That reconciliation surfaced real stale facts, fixed in place: the
real unit test count is 15, not 13, and none of them mock anything (all pure functions); dbt
model/mart counts in `resume_project_doc.md` didn't match the real `dbt_project/models/` tree;
the dashboard's "Details" drill-down toggle is dead code (shows/hides an empty `<div>`, nothing
populates it); the root README overstated two "Future Enhancements" as fully missing when the
underlying capability (Lambda deploy, EventBridge scheduling) partially already existed.

Then read `docs/Kousik_Market_Gap_Analysis_July2026.md` (a personal job-search market-fit
analysis, kept out of git — see Loose Ends) and used it to scope a real feature addition: a
LangGraph-based agentic layer, chosen specifically because the analysis names multi-agent
frameworks as the single most closable gap in the target job market. CrewAI was evaluated as an
alternative framework and rejected in favor of staying with LangGraph. The result is
`docs/scoping.md` — a full 10-section design spec (goals/non-goals, a root-cause investigation
agent, a dataset-onboarding agent, grounding design, integration points, testing/eval strategy,
resume framing, and a rollout plan) built section-by-section over several turns, with its own
running decision log. **Design only — nothing in it is implemented yet.**

All of the above (except the gap-analysis file) was committed on `docs/comprehensive-documentation`
and merged into `main` via PR #1, after CI (`lint-and-test`, `dbt-check`) passed.

**Decisions made:**
- LangGraph over CrewAI, for both phases of the agentic layer — full reasoning in
  `docs/scoping.md`'s Decision Log.
- Bypass dbt/Redshift for the onboarding agent's v1 codegen target (a local DuckDB file instead)
  — the strongest proof of "works on a new dataset" is a fast, zero-infra live demo.
- No `dim_*` business-taxonomy remapping layer for onboarded datasets — that kind of mapping is a
  human judgment call with no generic automated equivalent.
- Human-in-the-loop for schema classification is a single CLI confirmation prompt, gated by three
  explicit triggers (first-time dataset, schema changed, validation failed) — not required on
  every run.
- The LLM eval suite (Section 8) reuses the same deterministic validators built for production
  grounding as its graders, rather than a separate LLM-as-judge pipeline.

**Current state:** `docs/scoping.md` is complete (all 10 sections). `CLAUDE.md` and every
top-level folder `README.md` are merged to `main`. `README.md`'s stale claims are fixed. No
agentic-layer code exists yet — `docs/ROADMAP.md`'s Phase 1, milestone M0, hasn't started.

**Next steps:** Adopt the documentation/session/git scaffolding described in
`docs/WORKING_CONVENTIONS.md` for this project (this file, `docs/ROADMAP.md`, `CHANGELOG.md`,
`concepts/`, `CONTRIBUTING.md`) — in progress as of this entry. After that: begin Phase 1, M0.

**Loose ends / reminders:**
- PR #1 was merged with a plain merge commit, not squash — the squash-merge convention wasn't
  established yet at that point. Not worth rewriting already-merged `main` history over; the
  convention applies from the next PR forward.
- `docs/Kousik_Market_Gap_Analysis_July2026.md` is intentionally untracked and gitignored — it
  contains personal job-search/company-fit/visa data that shouldn't be in this public repo.
  `CLAUDE.md` and `docs/scoping.md` reference it by name; keep it excluded from any future commit.
