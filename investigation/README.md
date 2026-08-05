# investigation/

The Phase 1 agentic layer: a LangGraph-shaped investigation of an anomaly, going beyond the
static pipeline's one-shot decomposition to conditionally drill into ambiguous dimensions and
synthesize a grounded plain-English explanation. Design record: `docs/scoping.md` Sections 2–4.
Roadmap status: `docs/ROADMAP.md` Phase 1.

## Scope as of M1

All 7 nodes from `docs/scoping.md` Section 2.3 now exist — `synthesize` (the one LLM node) and
the real `finalize` shipped in M1. **No `langgraph` dependency or compiled `StateGraph` exists
yet**, though: every node and routing function is still a plain, independently-testable Python
function operating on a state dict. Wiring them into an actual graph and calling it from
`orchestration/run_pipeline.py` / `/api/investigate/` is M2 (integration), per `docs/ROADMAP.md`.

## Files

| File | Purpose |
|------|---------|
| `state.py` | `InvestigationState` TypedDict — the single state object threaded through every node. |
| `nodes.py` | All 7 node functions, plus `classify_ambiguity` and (M1) `_run_synthesis`. |
| `routing.py` | The 3 conditional-edge routing functions, plus `MAX_ITERATIONS`. |
| `tools.py` | Thin wrappers around `detection`/`decomposition`/`narrative` functions, plus `tool_drill_down`. |
| `schemas.py` | Pydantic structured-output models: `EvidenceCitation`, `SynthesisOutput`. |
| `llm.py` | `get_synthesis_llm()` — the one place the LLM provider/model is chosen. |
| `prompts.py` | `build_synthesis_prompt()` — formats state into the evidence bundle + system prompt. |
| `validation.py` | `validate_citation`, `validate_synthesis_output` — the grounding enforcement. |
| `rendering.py` | `render_investigation_summary()` — template-only number injection, no model-authored numbers. |
| `eval.py` | Minimal eval harness + `GOLDEN_CASE_1` (Section 3.8) — run manually, not yet the formalized M3 CLI. |
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

## Nodes (`nodes.py`)

| Node | Purpose |
|------|---------|
| `detect(state)` | Calls `tool_run_detection`. Resolves `current_date`/`previous_date` via `decomposition.get_comparison_dates()` if not already supplied. |
| `decompose_all(state)` | Calls `tool_decompose_all` — decomposes all 3 dimensions in one call. |
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
  `synthesize` (and `eval.py`) call a real Groq API and require `GROQ_API_KEY` in `.env`.

## Tests

`tests/test_investigation_routing.py`, `tests/test_ambiguity_rules.py`, and (M1)
`tests/test_citation_validation.py` — fixture-dict-in, exact-value-out style, no mocking, no LLM
calls (see `tests/README.md`). `synthesize`/`_run_synthesis` are **not** unit-tested this way —
per `docs/scoping.md` Section 8.1's deterministic-vs-LLM split, LLM-touching code is graded by
`eval.py` against golden cases instead.

## Running the eval manually

```bash
python -m investigation.eval
```

Runs `GOLDEN_CASE_1` (Section 3.8's worked example, reconstructed as real `InvestigationState`
data) against the live Groq API and prints grounded/golden-match/uncertainty-note results. Costs a
real API call. This is *not* yet the formalized `investigation.eval` command Section 8.6 and
`docs/ROADMAP.md` milestone M3 describe (metrics tracked over time) — just enough to satisfy M1's
"run Golden Case #1 manually" requirement.

## Upstream / downstream

- **Upstream:** `detection.anomaly_detector.run_detection()`, `decomposition.decomposer`
  (`decompose_metric`, `fetch_detail_metrics`, `get_comparison_dates`, `calculate_contribution`,
  `summarize_dimension`, `get_top_driver`), `narrative.generator` (`generate_narrative`, `jinja_env`)
  — all called unchanged. `config.settings.GROQ_API_KEY`/`GROQ_MODEL`.
- **Downstream:** nothing yet. No graph is compiled and nothing in `orchestration/` or
  `dashboard_api/` calls into this package — that's M2, per `docs/ROADMAP.md`.
