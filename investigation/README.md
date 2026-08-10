# investigation/

The Phase 1 agentic layer: a LangGraph-shaped investigation of an anomaly, going beyond the
static pipeline's one-shot decomposition to conditionally drill into ambiguous dimensions and
synthesize a grounded plain-English explanation. Design record: `docs/scoping.md` Sections 2–4.
Roadmap status: `docs/ROADMAP.md` Phase 1.

## Scope as of M2

All 7 nodes from `docs/scoping.md` Section 2.3 now exist, are compiled into a real `StateGraph`
(`graph.py`), and are wired into `orchestration/run_pipeline.py` and `/api/investigate/`
(`docs/scoping.md` Section 4). This is a genuinely callable agent now, not just a library of
graph-shaped functions.

## Files

| File | Purpose |
|------|---------|
| `state.py` | `InvestigationState` TypedDict, `build_initial_state()` — the single state object threaded through every node, and the one place a fully-defaulted initial state gets built. |
| `graph.py` | `build_investigation_graph()` / `investigation_graph` — the compiled `StateGraph` wiring all 7 nodes and 3 routing functions. The only file in this package that imports `langgraph`. |
| `nodes.py` | All 7 node functions, plus `classify_ambiguity` and `_run_synthesis`. |
| `routing.py` | The 3 conditional-edge routing functions, plus `MAX_ITERATIONS`. |
| `tools.py` | Thin wrappers around `detection`/`decomposition`/`narrative` functions, plus `tool_drill_down`. |
| `schemas.py` | Pydantic structured-output models: `EvidenceCitation`, `SynthesisOutput`. |
| `llm.py` | `get_synthesis_llm()` — the one place the LLM provider/model is chosen. |
| `prompts.py` | `build_synthesis_prompt()` — formats state into the evidence bundle + system prompt. |
| `validation.py` | `validate_citation`, `validate_synthesis_output` — the grounding enforcement. |
| `rendering.py` | `render_investigation_summary()` — template-only number injection, no model-authored numbers. |
| `eval.py` | The Phase 1 eval suite: `GOLDEN_CASE_1` (Section 3.8), `run_investigation_eval()`, and the pure `summarize_results()` — `python -m investigation.eval --runs N`. |
| `__init__.py` | Empty — makes the folder an importable package. |

## State schema

```python
class AmbiguousDimension(TypedDict):
    dimension: str
    reason: str  # 'close_contributors' | 'offsetting_segments'

class InvestigationState(TypedDict):
    # Inputs
    metric: str
    current_date: Optional[str]
    previous_date: Optional[str]
    threshold: float
    force_investigate: bool
    # Evidence gathered
    detection_result: Optional[Dict]
    decomposition_results: Optional[Dict]
    ambiguous_dimensions: List[AmbiguousDimension]
    drill_down_results: Dict[str, Dict]
    drilled_dimensions: List[str]
    # Reasoning trace
    investigation_log: List[str]
    iteration_count: int
    should_continue: bool
    # Output
    top_driver: Optional[Dict]
    investigation_summary: Optional[str]
    narratives: Optional[Dict]
    grounding_failed: Optional[bool]  # True if synthesize fell back (M1, Section 3.6)
    # Control
    status: str
    error: Optional[str]
```

`detection_result`, `decomposition_results`, and `narratives` are byte-for-byte the same dicts
`detection.run_detection()`, `decomposition.decompose_metric()`, and
`narrative.generate_narrative()` already return — nothing here invents a new contract shape.

### `build_initial_state(metric, threshold=None, force_investigate=False, current_date=None, previous_date=None, detection_result=None, decomposition_results=None)`

Fills every field not explicitly passed with its safe empty default (`[]`/`{}`/`0`/`False`/`None`/
`'running'`). Every node already reads its own inputs defensively via `.get(key, default)` — a good
sign — but a *routing function* reading a key before any node has written it (see the
`route_after_ambiguity` gotcha below) has nothing to fall back on unless the caller seeded it.
Both real call sites (`orchestration/run_pipeline.py`'s pre-seeded path, `InvestigationView`'s
standalone path) build their initial state through this function rather than a hand-built dict, so
neither has to remember the full field list.

## Nodes (`nodes.py`)

| Node | Purpose |
|------|---------|
| `detect(state)` | Calls `tool_run_detection`. Resolves `current_date`/`previous_date` via `decomposition.get_comparison_dates()` if not already supplied. **Idempotent** (Section 4.3): no-op if `detection_result` is already present in state (pre-seeded by a caller that already ran detection). |
| `decompose_all(state)` | Calls `tool_decompose_all` — decomposes all 3 dimensions in one call. **Idempotent**, same reasoning as `detect`: no-op if `decomposition_results` is already present. |
| `assess_ambiguity(state)` | Runs `classify_ambiguity` per dimension, builds `ambiguous_dimensions`, increments `iteration_count` by 1 (once per round, not per node). |
| `drill_down(state)` | For each not-yet-drilled `close_contributors` dimension, drills into its top contributor's segment via `tool_drill_down`. `offsetting_segments` dimensions are never drilled — more granular data can't resolve two segments genuinely moving in opposite directions. |
| `finalize_skip(state)` | No-anomaly path: `status='skipped_no_anomaly'`, everything past `detection_result` set to `None`. No decomposition, drill-down, or LLM call. |
| `synthesize(state)` | **The one LLM node.** See below. |
| `finalize(state)` | Calls `tool_generate_narrative(decomposition_results)` unchanged (Tier 1), attaches `investigation_summary` (Tier 2) alongside it, sets `top_driver` and `status='completed'`. Short-circuits to `{}` if a prior node already set `status='failed'`. |

Every node except `synthesize` returns a **partial state-update dict** and is wrapped in
try/except: on any exception it returns `{'status': 'failed', 'error': str(e)}` instead of
raising, mirroring `orchestration/run_pipeline.py`'s per-step convention (`docs/scoping.md`
Section 2.7).

### `classify_ambiguity(dim_data) -> Optional[str]`

The rule `assess_ambiguity` applies to each dimension's decomposition entry:

1. `'offsetting_segments'` if the top contributor's `contribution_pct` is outside `[0, 100]`
   (segments moved in opposite directions). Checked first — a top contributor already over 100%
   makes "how close is the #2 contributor" not meaningfully defined.
2. Else `'close_contributors'` if the top two contributors' `abs_contribution` are within
   `CLOSE_CONTRIBUTORS_THRESHOLD = 15` percentage points of each other.
3. Else `None` (not ambiguous).

## `synthesize` — the LLM node (Sections 3, 3.6)

**Deliberately doesn't follow the "every node fails to `status='failed'`" convention.** Per the
Tier-1/Tier-2 split (Section 3.2), a broken LLM call shouldn't discard an otherwise-successful
decomposition — it fails *open* to a deterministic fallback instead:

1. Short-circuits to `{}` if `state['status'] == 'failed'` already (nothing upstream succeeded).
2. Calls `_run_synthesis(state)`: one structured-output LLM call via `get_synthesis_llm()`,
   validated with `validate_synthesis_output`. On validation failure, retries **once** with the
   specific errors appended to the prompt (Section 3.6). `_run_synthesis` is a separate function
   from `synthesize` specifically so `eval.py` can call it directly and grade the raw
   `SynthesisOutput` — the eval suite reuses the exact production code path, not a parallel one.
3. If grounded (first attempt or after retry): renders `investigation_summary` via
   `rendering.render_investigation_summary` — every number in the output is looked up fresh from
   `state`, never taken from the model.
4. If the retry also fails validation, or the LLM call itself raises: falls back to a plain
   f-string built from `decomposer.get_top_driver()` (existing, unchanged function), sets
   `grounding_failed=True` and `should_continue=False`. Verified live: pointing `GROQ_MODEL` at a
   nonexistent model produces exactly this path — no exception escapes, `status` is untouched.

### Provider/model (`llm.py`)

Uses **Groq** (`langchain-groq`'s `ChatGroq`), not the doc's illustrative Anthropic/OpenAI
examples — an implementation-time choice per `docs/scoping.md` Section 4.8, which left this open.
Default model: `llama-3.3-70b-versatile` (`GROQ_MODEL` env var, `config/settings.py`) — chosen
over the newer `gpt-oss` models available on Groq because of a known LangChain/Groq incompatibility
between `gpt-oss-120b` and strict-JSON-schema structured output; `.with_structured_output(...,
method='function_calling')` is used explicitly for the same reason (classic tool-calling-based
structured output, broadly compatible, not the newer strict mode). Live-verified against Golden
Case #1 (see `eval.py` below) — grounded on the first attempt, correct citation, required
`uncertainty_note` present, stable across repeated runs.

### Prompt evidence layout (`prompts.py`)

One real lesson from live-testing this node: when a dimension has a drill-down, the drill-down's
`top_contributors` are nested **directly under** that dimension's own listing (not as a separate
trailing section), with an inline instruction naming the higher-level segment the model should
*not* cite as `primary_explanation`. A first version with drill-down data as a separate section
plus only a general system-prompt rule reliably got grounded, valid output — but the model kept
citing the higher-level ambiguous segment (e.g. `Southeast`) as `primary_explanation` instead of
the more specific drill-down finding (`SP`), even though `SP` showed up correctly as a *supporting*
citation. Restructuring the evidence layout (proximity + an explicit "use THIS, not that" pointer)
fixed it without touching validation or fallback logic — a good example of why Section 10.3 calls
M1 the calibration checkpoint: this kind of steering issue only surfaces against a real provider.

## Routing functions (`routing.py`)

| Function | Returns |
|----------|---------|
| `route_after_detection(state)` | `'decompose_all'` if an anomaly was detected or `force_investigate` is true, else `'finalize_skip'`. |
| `route_after_ambiguity(state)` | `'drill_down'` if any `close_contributors` dimension is still un-drilled and `iteration_count < MAX_ITERATIONS`, else `'synthesize'`. |
| `route_after_synthesis(state)` | `'assess_ambiguity'` if `should_continue` is true and under the iteration cap, else `'finalize'`. |

`MAX_ITERATIONS = 2` bounds the graph to at most 2 rounds of drill-down + synthesis regardless of
what `synthesize` requests — enforced here in code, not requested of the model.

**One implementation-time fix:** `route_after_ambiguity` reads `drilled_dimensions` via
`state.get('drilled_dimensions', [])` rather than direct indexing. The very first
`assess_ambiguity` → `route_after_ambiguity` transition in a real invocation has no node that's
set `drilled_dimensions` yet unless the caller pre-seeded it — every M0 test fixture happened to
include the key, which masked this until a real end-to-end graph run (M2) surfaced it.
`build_initial_state()` now seeds it too, but the routing function stays defensive regardless of
how the graph was invoked.

## The compiled graph (`graph.py`)

```python
from investigation.graph import investigation_graph
final_state = investigation_graph.invoke(initial_state)
```

Wires all 7 nodes and 3 routing functions exactly per Section 2.4's diagram:

```
START -> detect -> route_after_detection -> {decompose_all, finalize_skip}
decompose_all -> assess_ambiguity -> route_after_ambiguity -> {drill_down, synthesize}
drill_down -> synthesize
synthesize -> route_after_synthesis -> {assess_ambiguity, finalize}
finalize -> END
finalize_skip -> END
```

No checkpointer (Section 2.8: optional, purely for mid-run `investigation_log` inspection — not
required, and this graph has no cross-invocation persistence need). `graph.py` is the only file in
this package that imports `langgraph` — everything else is plain Python with zero LangGraph
dependency, importable and testable on its own.

## Integration (`orchestration/run_pipeline.py`, `dashboard_api/`)

Two call patterns, one graph, no duplicated code:

- **Pre-seeded (`run_pipeline(run_investigation=True)`):** Step 4.5 (after narrative generation,
  before alerting) builds initial state via `build_initial_state()`, passing the
  `detection_result`/`decomposition_results` steps 1/3 already computed. `detect`/`decompose_all`
  become no-ops, so investigating an anomaly the pipeline already found costs one `synthesize` LLM
  call plus up to `MAX_ITERATIONS` rounds of drill-down SQL — no duplicate Redshift queries
  (Section 4.3). The `investigation` import is local to this gated block, not module-level, so
  every existing caller that doesn't request it never pays LangGraph/Groq import weight or needs
  `GROQ_API_KEY` set (same lazy-import convention `orchestration/README.md` already documents for
  `monitoring.cloudwatch_metrics`). A failure here is caught, logged at WARNING, recorded as
  `results['investigation'] = {'status': 'failed', 'error': str(e)}` — never raised, never blocks
  alerting.
- **Standalone (`POST /api/investigate/`, `dashboard_api/views.py`'s `InvestigationView`):** no
  pre-seeding — a user investigating an arbitrary date pair from the dashboard has no prior
  detection/decomposition necessarily run for that exact pair. `force_investigate=True` always, so
  the investigation runs regardless of the z-score gate (a user who clicks "Investigate" wants an
  answer, unlike the automated pipeline path where investigation is cost-gated to real anomalies).
  Returns the entire final state as the response `data` — not curated, matching how
  `AnomalyDetectionView` already returns `run_detection()`'s full result.

Verified live (real Redshift + real Groq, no mocking): `python -m orchestration.run_pipeline
--dry-run --force-alert --run-investigation` produces a real grounded `investigation_summary` with
exactly one `decompose_metric()` call in the logs (confirming no duplicate query); `curl -X POST
/api/investigate/` returns a JSON-serializable full state; `lambda_handler.handler({'run_investigation':
True, ...}, None)` passes through correctly when called directly in a local REPL.

## Tools (`tools.py`)

| Tool | Wraps | New code? |
|------|-------|-----------|
| `tool_run_detection(metric, threshold, lookback_days=30)` | `detection.anomaly_detector.run_detection()` | No |
| `tool_decompose_all(current_date, previous_date, metric)` | `decomposition.decomposer.decompose_metric()` | No |
| `tool_drill_down(dimension, segment, current_date, previous_date, metric)` | `decomposition.decomposer.fetch_detail_metrics()` + `calculate_contribution()` + `summarize_dimension()` | Yes — the one genuinely new capability this phase adds |
| `tool_generate_narrative(decomposition_results)` | `narrative.generator.generate_narrative()` | No — used by `finalize` as of M1 |

`tool_drill_down`'s return shape is identical to one entry of `decompose_metric()`'s `dimensions`
dict (same `summarize_dimension()` helper both call), so `drill_down_results[dim]` and
`decomposition_results['dimensions'][dim]` are structurally interchangeable.

## Grounding (`validation.py`, `rendering.py`)

- `validate_citation(citation, state)` — checks a citation's `(dimension, segment)` pair actually
  appears in the evidence under the `source` it claims. **One correction to `docs/scoping.md`
  Section 3.5's illustrative snippet:** it indexes `state["decomposition_results"]` directly, but
  the real shape nests per-dimension data one level deeper, under `"dimensions"` — fixed here.
  `drill_down_results` has no such wrapper (matches `tool_drill_down`'s flat return shape).
- `validate_synthesis_output(output, state)` — runs `validate_citation` over every citation, plus
  enforces that `uncertainty_note` is non-null whenever an `offsetting_segments` dimension is
  present in the evidence (Section 3.4). Returns a list of human-readable error strings (empty =
  valid) — these strings are exactly what feeds the retry prompt.
- `render_investigation_summary(output, state)` — Jinja2 template reusing `narrative.generator`'s
  `jinja_env` (its `format_currency`/`abs` filters). Looks up every number fresh from `state` using
  the model's citation as a key; the model's own text never reaches the rendered output as a number.

## Gotchas

- `drill_down` only drills into the **single top contributor's** segment per ambiguous dimension,
  not every close contender — matches the worked example in `docs/scoping.md` Section 3.8 (Southeast
  drilled, not Northeast).
- `iteration_count` increments once per pass through `assess_ambiguity`, not once per node — so
  `MAX_ITERATIONS = 2` really does mean at most two drill-down rounds, not two node calls.
- Every node except `synthesize` is pure/deterministic and safe to call freely with no cost.
  `synthesize` (and `eval.py`, and any real graph invocation that reaches it) call a real Groq API
  and require `GROQ_API_KEY` in `.env`.
- `detect`/`decompose_all`'s idempotency is keyed on the *presence* of `detection_result`/
  `decomposition_results` in state, not on whether the values are still fresh — invoking the graph
  standalone with stale pre-seeded data (not currently done anywhere, but possible via direct
  `investigation_graph.invoke()`) would silently skip re-fetching. Both real call sites always
  either pre-seed with data just computed in the same call or don't pre-seed at all.
- `finalize` calls `tool_generate_narrative(decomposition_results)` to build its own Tier-1
  narrative, even when the caller (e.g. `run_pipeline`'s Step 4) already generated one from the
  same `decomposition_results` moments earlier. This is a second, redundant *Jinja render* — cheap,
  in-memory, no DB round-trip — not a second Redshift query, so it doesn't violate Section 4.3's
  no-duplicate-queries goal, but it is duplicated work worth knowing about if this ever needs
  further optimization.

## Tests

`tests/test_investigation_routing.py`, `tests/test_ambiguity_rules.py`, `tests/test_citation_validation.py`,
and (M3) `tests/test_eval_summarization.py` — fixture-dict-in, exact-value-out style, no mocking, no
LLM calls (see `tests/README.md`). `synthesize`/`_run_synthesis` are **not** unit-tested this way —
per `docs/scoping.md` Section 8.1's deterministic-vs-LLM split, LLM-touching code is graded by
`eval.py`'s real-API `run_investigation_eval()` against golden cases instead; only its pure
aggregation half (`summarize_results()`) gets exact-value tests.

## Running the eval suite

```bash
python -m investigation.eval --runs 5     # --runs defaults to 5
```

Runs `GOLDEN_CASE_1` (Section 3.8's worked example, reconstructed as real `InvestigationState`
data) through `_run_synthesis()` — the real production LLM call path — `--runs` times against the
live Groq API, then aggregates Section 8.5's named metrics via the pure `summarize_results()`
function (unit-tested in `tests/test_eval_summarization.py`, no LLM calls there):

| Metric | Definition |
|--------|------------|
| `grounding_pass_rate` | Fraction of trials where every citation validated on the **first** attempt, before the bounded retry (Section 3.6) — shows whether the retry path is doing real work or rarely triggers. |
| `fallback_rate` | Fraction of trials that exhausted the retry and fell back to the deterministic-only summary. |
| `golden_match_rate` | Fraction where `primary_explanation` matched the hand-labeled expected answer (`{dimension: 'geography', segment: 'SP'}` for `GOLDEN_CASE_1`). A fallback trial has no model citation to check, so it always counts as a non-match here — grounding failures fold into this end-to-end rate rather than being hidden from it. |
| `uncertainty_ok_rate` | Fraction where `uncertainty_note` was present whenever the evidence included an `offsetting_segments` dimension (Section 3.4's requirement). |

One golden case run once is an n=1 coin flip, not a rate — running it `--runs` times against the
real API is what makes these numbers statistically real rather than estimated (`docs/ROADMAP.md`
M3's gate). No new golden case was added for this milestone: Section 8.4's "two more small
fixtures" are Phase-2/onboarding-classification fixtures, not Phase-1 investigation ones —
`GOLDEN_CASE_1` stays the sole Phase-1 case, consistent with Section 8.4's own "a handful of
well-chosen cases, not dozens" v1 sizing.

Costs real API calls every run — not part of `pytest tests/` (Section 8.6). Run before merging a
prompt/model change, or periodically to catch drift, not on every commit.

## Upstream / downstream

- **Upstream:** `detection.anomaly_detector.run_detection()`, `decomposition.decomposer`
  (`decompose_metric`, `fetch_detail_metrics`, `get_comparison_dates`, `calculate_contribution`,
  `summarize_dimension`, `get_top_driver`), `narrative.generator` (`generate_narrative`, `jinja_env`)
  — all called unchanged. `config.settings.GROQ_API_KEY`/`GROQ_MODEL`.
- **Downstream:** `orchestration/run_pipeline.py`'s Step 4.5 (`run_investigation=True`, lazily
  imported), `dashboard_api/views.py`'s `InvestigationView` (`POST /api/investigate/`) and
  `PipelineView` (`run_investigation` body field), `lambda_handler.py`'s `run_investigation` event
  passthrough, and the dashboard's "Investigate with AI Agent" button
  (`templates/partials/scripts.html`'s `investigateWithAgent()`).
