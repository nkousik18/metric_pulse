# investigation/

The Phase 1 agentic layer: a LangGraph-shaped investigation of an anomaly, going beyond the
static pipeline's one-shot decomposition to conditionally drill into ambiguous dimensions and
(eventually) synthesize a grounded plain-English explanation. Design record: `docs/scoping.md`
Sections 2–4. Roadmap status: `docs/ROADMAP.md` Phase 1.

## M0 scope only

This folder currently contains **only the deterministic half** of the design — milestone M0. There
is no `langgraph` dependency yet and no compiled `StateGraph`; every node and routing function
below is a plain, independently-testable Python function operating on a state dict. Two things
named in `docs/scoping.md` Section 2.3 are intentionally **not** here yet:

- `synthesize` — the one LLM node (structured-output citation synthesis). Milestone M1.
- `finalize` — its real job is attaching `investigation_summary` (produced by `synthesize`), so it
  ships alongside M1/M2 rather than half-built now. `finalize_skip` (the no-anomaly path, which
  needs neither) *is* built here.

Actually wiring these functions into a compiled `StateGraph` also waits until `synthesize`/
`finalize` exist, so the graph can be assembled complete rather than half-stubbed (M1/M2).

## Files

| File | Purpose |
|------|---------|
| `state.py` | `InvestigationState` TypedDict — the single state object threaded through every node. |
| `nodes.py` | The 5 deterministic node functions, plus the `classify_ambiguity` rule they share. |
| `routing.py` | The 3 conditional-edge routing functions, plus `MAX_ITERATIONS`. |
| `tools.py` | Thin wrappers around `detection`/`decomposition`/`narrative` functions, plus the one new `tool_drill_down`. |
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
    # Control
    status: str
    error: Optional[str]
```

`detection_result`, `decomposition_results`, and (eventually) `narratives` are byte-for-byte the
same dicts `detection.run_detection()`, `decomposition.decompose_metric()`, and
`narrative.generate_narrative()` already return — nothing here invents a new contract shape.

## Nodes (`nodes.py`)

| Node | Purpose |
|------|---------|
| `detect(state)` | Calls `tool_run_detection`. Resolves `current_date`/`previous_date` via `decomposition.get_comparison_dates()` if not already supplied. |
| `decompose_all(state)` | Calls `tool_decompose_all` — decomposes all 3 dimensions in one call. |
| `assess_ambiguity(state)` | Runs `classify_ambiguity` per dimension, builds `ambiguous_dimensions`, increments `iteration_count` by 1 (once per round, not per node). |
| `drill_down(state)` | For each not-yet-drilled `close_contributors` dimension, drills into its top contributor's segment via `tool_drill_down`. `offsetting_segments` dimensions are never drilled — more granular data can't resolve two segments genuinely moving in opposite directions. |
| `finalize_skip(state)` | No-anomaly path: `status='skipped_no_anomaly'`, everything past `detection_result` set to `None`. No decomposition, drill-down, or LLM call. |

Every node returns a **partial state-update dict** (the standard LangGraph node convention) and is
wrapped in try/except: on any exception it returns `{'status': 'failed', 'error': str(e)}` instead
of raising, mirroring `orchestration/run_pipeline.py`'s per-step convention.

### `classify_ambiguity(dim_data) -> Optional[str]`

The rule `assess_ambiguity` applies to each dimension's decomposition entry:

1. `'offsetting_segments'` if the top contributor's `contribution_pct` is outside `[0, 100]`
   (segments moved in opposite directions). Checked first — a top contributor already over 100%
   makes "how close is the #2 contributor" not meaningfully defined.
2. Else `'close_contributors'` if the top two contributors' `abs_contribution` are within
   `CLOSE_CONTRIBUTORS_THRESHOLD = 15` percentage points of each other.
3. Else `None` (not ambiguous).

## Routing functions (`routing.py`)

| Function | Returns |
|----------|---------|
| `route_after_detection(state)` | `'decompose_all'` if an anomaly was detected or `force_investigate` is true, else `'finalize_skip'`. |
| `route_after_ambiguity(state)` | `'drill_down'` if any `close_contributors` dimension is still un-drilled and `iteration_count < MAX_ITERATIONS`, else `'synthesize'`. |
| `route_after_synthesis(state)` | `'assess_ambiguity'` if `should_continue` is true and under the iteration cap, else `'finalize'`. |

`MAX_ITERATIONS = 2` bounds the graph to at most 2 rounds of drill-down + synthesis regardless of
what `synthesize` (M1) requests — enforced here in code, not requested of a model.

## Tools (`tools.py`)

| Tool | Wraps | New code? |
|------|-------|-----------|
| `tool_run_detection(metric, threshold, lookback_days=30)` | `detection.anomaly_detector.run_detection()` | No |
| `tool_decompose_all(current_date, previous_date, metric)` | `decomposition.decomposer.decompose_metric()` | No |
| `tool_drill_down(dimension, segment, current_date, previous_date, metric)` | `decomposition.decomposer.fetch_detail_metrics()` + `calculate_contribution()` + `summarize_dimension()` | Yes — the one genuinely new capability this phase adds |
| `tool_generate_narrative(decomposition_results)` | `narrative.generator.generate_narrative()` | No (unused by any M0 node — `finalize` is M1) |

`tool_drill_down`'s return shape is identical to one entry of `decompose_metric()`'s `dimensions`
dict (same `summarize_dimension()` helper both call), so `drill_down_results[dim]` and
`decomposition_results['dimensions'][dim]` are structurally interchangeable.

## Gotchas

- `drill_down` only drills into the **single top contributor's** segment per ambiguous dimension,
  not every close contender — matches the worked example in `docs/scoping.md` Section 3.8 (Southeast
  drilled, not Northeast).
- `iteration_count` increments once per pass through `assess_ambiguity`, not once per node — so
  `MAX_ITERATIONS = 2` really does mean at most two drill-down rounds, not two node calls.
- Nothing here calls an LLM or costs money to run — every function is pure/deterministic and safe
  to call freely in tests or a REPL.

## Tests

`tests/test_investigation_routing.py` (the 3 routing functions) and `tests/test_ambiguity_rules.py`
(`classify_ambiguity` and `assess_ambiguity`) — same fixture-dict-in, exact-value-out style as the
rest of `tests/` (see `tests/README.md`).

## Upstream / downstream

- **Upstream:** `detection.anomaly_detector.run_detection()`, `decomposition.decomposer` (`decompose_metric`,
  `fetch_detail_metrics`, `get_comparison_dates`, `calculate_contribution`, `summarize_dimension`),
  `narrative.generator.generate_narrative()` — all called unchanged via `tools.py`.
- **Downstream:** nothing yet. No graph is compiled and nothing in `orchestration/` or
  `dashboard_api/` calls into this package — that's M1 (`synthesize`) and M2 (integration), per
  `docs/ROADMAP.md`.
