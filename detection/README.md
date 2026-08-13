# detection/

Anomaly detection on daily business metrics using a whole-window z-score. This is the **first stage** of the analytics pipeline: it decides whether anything unusual happened at all, and its output gates whether decomposition/narrative/alerting run.

## Files

| File | Purpose |
|------|---------|
| `anomaly_detector.py` | Everything — fetch, score, flag, summarize. Single-file module. |
| `__init__.py` | Empty — makes the folder an importable package. |

## Functions (`anomaly_detector.py`)

| Function | Signature | What it does |
|----------|-----------|---------------|
| `fetch_daily_metrics` | `(lookback_days=30, metric_columns=None, table_name='staging.fact_daily_metrics', connection_factory=get_connection) -> pd.DataFrame` | `SELECT metric_date, {metric_columns joined} FROM {table_name} ORDER BY metric_date DESC LIMIT N`. `metric_columns=None` defaults to Olist's 4 (`order_count`, `customer_count`, `total_revenue`, `avg_order_value`) — always pulls all 4 regardless of which one you'll analyze in that case. Opens/closes its own connection via `connection_factory()`. `metric_columns`/`table_name`/`connection_factory` are additive (Phase 2, `docs/scoping.md` §6.2) — every existing call site omits all three and gets byte-identical Redshift behavior; an onboarded dataset passes its classified `metric_columns` + `row_count`, its own fact table name, and a `duckdb.connect(path)` callable. `metric_columns` itself isn't in §6.2's own additive-parameters list for this function (only `table_name`/`connection_factory` are) — added because the SELECT clause is otherwise hardcoded to Olist-specific column names that don't exist on an onboarded dataset. |
| `calculate_zscore` | `(series: pd.Series) -> pd.Series` | `(series - series.mean()) / series.std()`. Pure — no I/O. `pandas.Series.std()` defaults to `ddof=1` (sample std), which is what makes the z-score "correct for a 30-day sample" per the design notes in `docs/detection_layer.md`. |
| `detect_anomalies` | `(df, metric_column='total_revenue', threshold=None) -> pd.DataFrame` | Sorts by date ascending, adds `zscore`, `is_anomaly` (`\|zscore\| > threshold`), `anomaly_direction` (`'high'`/`'low'`/`'normal'`), `prev_value`, `change_value`, `change_pct`. If `threshold` is `None` it reads `ANOMALY_THRESHOLD_ZSCORE` from env (default `2.0`) **inside this function**, not in `run_detection`. |
| `get_latest_anomaly` | `(df, metric_col='total_revenue') -> Optional[dict]` | Filters `is_anomaly == True`, returns the most recent one as a dict, or `None`. Uses `metric_col` to pull `metric_value` — this was previously hardcoded to `total_revenue`, so callers analyzing `order_count` etc. get the right value back. |
| `run_detection` | `(metric='total_revenue', lookback_days=None, threshold=None, metric_columns=None, table_name='staging.fact_daily_metrics', connection_factory=get_connection) -> dict` | Top-level orchestration function. `lookback_days=None` → reads `LOOKBACK_DAYS` env (default `30`). Returns `{'status': 'no_data', 'anomalies': []}` early if the query returns nothing — note this shape is *different* from the normal return (no `metric`/`statistics` keys), so callers must check `status` before assuming the full shape exists. `metric_columns`/`table_name`/`connection_factory` are passed straight through to `fetch_daily_metrics` — added here specifically so that function's new parameters are reachable at all from its one real caller. |

### `run_detection()` return shape (normal path)

```python
{
    'status': 'completed',
    'metric': 'total_revenue',
    'lookback_days': 30,
    'total_days_analyzed': 30,
    'anomaly_count': 2,
    'latest_anomaly': {                      # or None
        'metric_date': ...,
        'metric_value': ...,
        'zscore': 2.41,
        'direction': 'high' | 'low',
        'change_pct': ...,
        'change_value': ...
    },
    'all_anomalies': [ {...}, ... ],          # full DataFrame rows as dicts, includes zscore/prev_value/etc.
    'statistics': {'mean': ..., 'std': ..., 'min': ..., 'max': ...}
}
```

## Running standalone

```bash
python -m detection.anomaly_detector
```

Runs `run_detection()` with all defaults (`total_revenue`, 30-day lookback, threshold from env) and pretty-prints stats + the latest anomaly to stdout.

## Config / env vars

| Var | Default | Read by |
|-----|---------|---------|
| `ANOMALY_THRESHOLD_ZSCORE` | `2.0` | `detect_anomalies()` when `threshold=None` |
| `LOOKBACK_DAYS` | `30` | `run_detection()` when `lookback_days=None` |
| `REDSHIFT_HOST/PORT/DATABASE/USER/PASSWORD` | — | indirectly, via `config.db.get_connection()` |

Loaded via `python-dotenv`'s `load_dotenv()` at module import time.

## Upstream / downstream

- **Upstream:** `staging.fact_daily_metrics`, built by the dbt marts layer (`dbt_project/models/marts/fact_daily_metrics.sql`). If dbt hasn't run, this returns an empty DataFrame and `run_detection` short-circuits to `status: 'no_data'`.
- **Downstream:** `orchestration/run_pipeline.py` calls `run_detection()` as step 1 and uses `anomaly_count` / `latest_anomaly` to decide whether to proceed to decomposition and whether to send an alert. `dashboard_api/views.py` also calls it directly for the `/api/anomalies/` endpoint. Nothing downstream depends on the DataFrame — only the dict returned by `run_detection`.

## Gotchas

- `calculate_zscore` has no guard against `series.std() == 0` (e.g. a perfectly flat window) — this produces `NaN`/`inf` z-scores silently rather than raising.
- `fetch_daily_metrics` interpolates `lookback_days` directly into an f-string SQL query, but it's an internal `int` parameter never sourced from raw user input, so this is not an injection vector (unlike `decomposition/decomposer.py`, which explicitly validates date strings because those *are* exposed via API query params).
- The `no_data` early-return dict has a different shape than the normal-completion dict (no `metric`, `statistics`, etc.) — callers that assume the full shape without checking `status` first will `KeyError`.

## Tests

Covered by `tests/test_anomaly_detector.py` (top-level `tests/` folder, not inside this one) — 5 tests against `calculate_zscore` and `detect_anomalies` using in-memory DataFrames, no live Redshift needed:

```bash
pytest tests/test_anomaly_detector.py -v
```
