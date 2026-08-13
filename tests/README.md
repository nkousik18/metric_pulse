# tests/

Unit tests for the pure-computation parts of the analytics pipeline: z-score anomaly detection,
contribution decomposition, narrative generation, the deterministic halves of the Phase 1
investigation graph and Phase 1's eval-metric aggregation, and (as of `docs/ROADMAP.md` milestone
M4) the deterministic halves of Phase 2's dataset-onboarding profiling and classification. Run via
`pytest` and gated by CI (`.github/workflows/ci.yml`'s `lint-and-test` job).

**Correction to `docs/`:** `docs/resume_project_doc.md` and `docs/infrastructure_and_deployment.md`
both state "13 tests, 3 files" and that "Redshift is mocked in all 13 tests." Neither claim is
accurate as of the current code:

- **Actual test count is 61, not 13** — the original 3 files still total 15
  (`test_anomaly_detector.py` 5, `test_decomposer.py` 4, `test_narrative.py` 6), plus 46 more added
  across the agentic-layer initiative's M0–M4: `test_investigation_routing.py` (11),
  `test_ambiguity_rules.py` (9), `test_citation_validation.py` (8), `test_eval_summarization.py` (4),
  `test_profiling.py` (8), `test_classification_validation.py` (6). `docs/detection_layer.md`,
  `docs/analytics_pipeline.md`, and `docs/dbt_transformations.md`-adjacent per-layer docs already
  list the correct 5/4/6 breakdown for the original 3 files — only the two summary docs above have
  the stale "13" total.
- **No mocking is used at all** — not `unittest.mock`, not a fixture, not `pytest-mock`, not
  `redshift_connector` monkeypatching. Every test constructs an in-memory `pandas.DataFrame` (or
  plain dict) and calls a pure function directly. None of the tested functions perform I/O or call
  an LLM — the DB-touching functions (`fetch_daily_metrics`, `run_detection`'s Redshift fetch,
  `fetch_dimension_metrics`, `fetch_detail_metrics`, `get_comparison_dates`) and the LLM-touching
  functions (`synthesize`/`_run_synthesis`, `classify_columns_with_validation`) are simply never
  called by any test in this directory — those are exercised by `investigation/eval.py` and
  `onboarding/eval.py` instead (real API calls, run manually, not part of `pytest`). "Redshift is
  mocked" should read "Redshift-dependent and LLM-dependent code paths are untested here by design;
  only the pure functions downstream of them are covered."

## Files

| File | Test functions | Covers |
|------|----------------|--------|
| `test_anomaly_detector.py` | 5 | `calculate_zscore` (mean≈0 for median value, scaling on an outlier), `detect_anomalies` (no false positives on stable data, detects an obvious 5x spike, labels `anomaly_direction='low'` on a sharp drop) |
| `test_decomposer.py` | 4 | `calculate_contribution` (adds `change`/`contribution_pct` columns, contributions sum to ~100% when all segments move the same direction, all-negative changes handled, zero `previous_value` doesn't raise) |
| `test_narrative.py` | 6 | `format_currency` (basic, large number with commas, `None`→`"0.00"`, negative→absolute value), `generate_narrative` (all 4 format keys present, `summary` contains metric name and top driver segment) |
| `test_investigation_routing.py` | 11 | `route_after_detection`, `route_after_ambiguity`, `route_after_synthesis` (`investigation/routing.py`) — anomaly found vs. not vs. `force_investigate`; pending `close_contributors` vs. `offsetting_segments`-only vs. already-drilled vs. iteration cap; `should_continue` vs. iteration cap |
| `test_ambiguity_rules.py` | 9 | `classify_ambiguity` and `assess_ambiguity` (`investigation/nodes.py`) — clear dominant contributor, close top two, offsetting (>100%/<0%) top contributor, offsetting-takes-priority edge case, single/no contributors, the `[0,100]` boundary, and an end-to-end node run against a full `decomposition_results` fixture |
| `test_citation_validation.py` | 8 | `validate_citation`/`validate_synthesis_output` (`investigation/validation.py`) — valid/invalid segment, wrong source, wrong dimension, the required-`uncertainty_note` rule |
| `test_eval_summarization.py` | 4 | `summarize_results` (`investigation/eval.py`) — all first-attempt-grounded, retry-grounded excluded from `grounding_pass_rate`, fallback trials counted correctly, empty-list edge case |
| `test_profiling.py` | 8 | `profile_column`/`profile_columns` (`onboarding/profiling.py`) — clean date-string column, numeric column never misread as a date, high-cardinality ID-like column, low-cardinality categorical column, high-null free-text column, already-`datetime64` column, sample-value cap, full-DataFrame profiling |
| `test_classification_validation.py` | 6 | `validate_classification` (`onboarding/classification.py`) — each of the three validation rules independently, all three combined, a fully-valid case, and a `date_column=None` non-error |
| `__pycache__/` | — | pytest bytecode cache, not source |

No `conftest.py`, no `__init__.py` in this directory (each test file does its own `sys.path.insert(0, str(Path(__file__).parent.parent))` to import from the repo root).

## Functions tested (imports per file)

```python
# test_anomaly_detector.py
from detection.anomaly_detector import calculate_zscore, detect_anomalies

# test_decomposer.py
from decomposition.decomposer import calculate_contribution

# test_narrative.py
from narrative.generator import format_currency, generate_narrative

# test_investigation_routing.py
from investigation.routing import MAX_ITERATIONS, route_after_ambiguity, route_after_detection, route_after_synthesis

# test_ambiguity_rules.py
from investigation.nodes import assess_ambiguity, classify_ambiguity

# test_citation_validation.py
from investigation.validation import validate_citation, validate_synthesis_output

# test_eval_summarization.py
from investigation.eval import summarize_results

# test_profiling.py
from onboarding.profiling import ID_CARDINALITY_THRESHOLD, profile_column, profile_columns

# test_classification_validation.py
from onboarding.classification import MAX_DIMENSION_CARDINALITY_RATIO, MIN_DATE_PARSE_RATE, validate_classification
```

## Running

```bash
# All tests, verbose
pytest tests/ -v

# Matches the CI command exactly
pytest tests/ -v --tb=short

# Single file
pytest tests/test_anomaly_detector.py -v

# Single test
pytest tests/test_narrative.py::TestFormatCurrency::test_none_value -v
```

No `pytest.ini` / `pyproject.toml` `[tool.pytest.ini_options]` section exists at the repo root — pytest runs with defaults, discovering `test_*.py` files anywhere pytest is pointed.

## Env vars / external dependencies

None. No `.env`, no AWS credentials, no live Redshift connection required — that's the point of testing only the pure functions. This is why CI can run these tests without any AWS secrets configured.

## How it connects to other folders

Imports directly from `detection/`, `decomposition/`, `narrative/`, `investigation/`, and (as of M4)
`onboarding/` (not `alerting/`, `orchestration/`, `monitoring/`, or any Django/`dashboard_api` code
— those have zero test coverage). `.github/workflows/ci.yml` runs `pytest tests/ -v --tb=short` in
the `lint-and-test` job; a failure here fails CI (previously a `|| echo ...` swallowed failures
silently — see `docs/infrastructure_and_deployment.md`'s Issues Fixed table — that swallow clause
is gone from the current `ci.yml`). No `GROQ_API_KEY` or live Redshift connection is needed to run
this directory's tests — verified explicitly each milestone by re-running the full suite with
`.env` removed entirely.

## Gotchas

- Because nothing mocks or exercises `fetch_daily_metrics`, `fetch_dimension_metrics`, `get_comparison_dates`, `run_detection`'s Redshift path, `publish_metric_alert`'s SNS path, or any Django view — a broken Redshift query, broken SQL, or broken SNS call would pass CI undetected. Coverage is limited to the arithmetic/formatting layer.
- `test_zscore_mean_is_zero` asserts `abs(zscores.iloc[2]) < 0.1` for the *middle* value of `[10,20,30,40,50]` — this only holds because the series is symmetric around its mean; it is not a general "median z-score is 0" guarantee.
