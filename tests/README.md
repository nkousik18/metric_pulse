# tests/

Unit tests for the pure-computation parts of the analytics pipeline: z-score anomaly detection, contribution decomposition, and narrative generation. Run via `pytest` and gated by CI (`.github/workflows/ci.yml`'s `lint-and-test` job).

**Correction to `docs/`:** `docs/resume_project_doc.md` and `docs/infrastructure_and_deployment.md` both state "13 tests, 3 files" and that "Redshift is mocked in all 13 tests." Neither claim is accurate as of the current code:

- **Actual test count is 15, not 13** — `test_anomaly_detector.py` has 5 test functions, `test_decomposer.py` has 4, `test_narrative.py` has 6 (5 + 4 + 6 = 15). `docs/detection_layer.md`, `docs/analytics_pipeline.md`, and `docs/dbt_transformations.md`-adjacent per-layer docs already list the correct 5/4/6 breakdown — only the two summary docs above have the stale "13" total.
- **No mocking is used at all** — not `unittest.mock`, not a fixture, not `pytest-mock`, not `redshift_connector` monkeypatching. Every test in all 3 files constructs an in-memory `pandas.DataFrame` (or plain dict) and calls a pure function directly (`calculate_zscore`, `detect_anomalies`, `calculate_contribution`, `format_currency`, `generate_narrative`). None of the tested functions perform I/O — the DB-touching functions (`fetch_daily_metrics`, `run_detection`'s Redshift fetch, `fetch_dimension_metrics`, `get_comparison_dates`) are simply never called by any test, so there's nothing to mock. "Redshift is mocked" should read "Redshift-dependent code paths are untested; only the pure functions downstream of the DB fetch are covered."

## Files

| File | Test functions | Covers |
|------|----------------|--------|
| `test_anomaly_detector.py` | 5 | `calculate_zscore` (mean≈0 for median value, scaling on an outlier), `detect_anomalies` (no false positives on stable data, detects an obvious 5x spike, labels `anomaly_direction='low'` on a sharp drop) |
| `test_decomposer.py` | 4 | `calculate_contribution` (adds `change`/`contribution_pct` columns, contributions sum to ~100% when all segments move the same direction, all-negative changes handled, zero `previous_value` doesn't raise) |
| `test_narrative.py` | 6 | `format_currency` (basic, large number with commas, `None`→`"0.00"`, negative→absolute value), `generate_narrative` (all 4 format keys present, `summary` contains metric name and top driver segment) |
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

Imports directly from `detection/`, `decomposition/`, and `narrative/` (not `alerting/`, `orchestration/`, `monitoring/`, or any Django/`dashboard_api` code — those have zero test coverage). `.github/workflows/ci.yml` runs `pytest tests/ -v --tb=short` in the `lint-and-test` job; a failure here fails CI (previously a `|| echo ...` swallowed failures silently — see `docs/infrastructure_and_deployment.md`'s Issues Fixed table — that swallow clause is gone from the current `ci.yml`).

## Gotchas

- Because nothing mocks or exercises `fetch_daily_metrics`, `fetch_dimension_metrics`, `get_comparison_dates`, `run_detection`'s Redshift path, `publish_metric_alert`'s SNS path, or any Django view — a broken Redshift query, broken SQL, or broken SNS call would pass CI undetected. Coverage is limited to the arithmetic/formatting layer.
- `test_zscore_mean_is_zero` asserts `abs(zscores.iloc[2]) < 0.1` for the *middle* value of `[10,20,30,40,50]` — this only holds because the series is symmetric around its mean; it is not a general "median z-score is 0" guarantee.
