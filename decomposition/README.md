# decomposition/

Segment-contribution analysis: given two dates, answers *which geography/product/payment segment drove the change in a metric*. This is the **second stage** of the analytics pipeline, run after `detection/` flags (or is told to force-analyze) a date.

## Files

| File | Purpose |
|------|---------|
| `decomposer.py` | Everything — dimension config, fetch, contribution math, orchestration. |
| `__init__.py` | Empty — makes the folder an importable package. |

## Dimension configuration

```python
DIMENSION_TABLES = {
    'geography': {'table': 'staging.metric_by_geography', 'segment_col': 'region',                 'detail_col': 'state_code'},
    'product':   {'table': 'staging.metric_by_product',   'segment_col': 'product_category_group',  'detail_col': 'product_category'},
    'payment':   {'table': 'staging.metric_by_payment',   'segment_col': 'payment_type_display',    'detail_col': 'payment_type'},
}
```

`decompose_metric` iterates this dict, so adding a 4th dimension is a matter of adding one entry here plus the matching dbt `metric_by_*` model (note: `detail_col` is defined here but not currently used anywhere in `decomposer.py` — it's metadata for downstream consumers like the dashboard drill-down, not read by this module itself).

## Functions

| Function | Signature | What it does |
|----------|-----------|---------------|
| `_validate_date` | `(date_str: str) -> str` | `datetime.strptime(date_str, '%Y-%m-%d')`, raises `ValueError` on anything else. **This is the SQL-injection guard** — every date that reaches an f-string SQL query in this module passes through here first, because `current_date`/`previous_date` are exposed as raw API query params in `dashboard_api/views.py`. |
| `fetch_dimension_metrics` | `(dimension, current_date, previous_date, metric_col='total_revenue') -> pd.DataFrame` | Validates both dates, then runs a single query: two CTEs (`current_day`, `previous_day`) `FULL OUTER JOIN`ed on segment, so a segment with data on only one of the two dates still appears (missing side defaults to `0` via `COALESCE`). Opens/closes its own Redshift connection per call — see Gotchas. |
| `calculate_contribution` | `(df: pd.DataFrame) -> pd.DataFrame` | Pure function. Adds `change`, `change_pct` (NaN/inf coerced to `0`), `contribution_pct = change / total_change * 100`, `abs_contribution`. Sorts descending by `abs_contribution`. If `total_change == 0` for the whole dimension, every row's `contribution_pct` is forced to `0` rather than dividing by zero. |
| `decompose_metric` | `(current_date, previous_date, metric_col='total_revenue') -> Dict` | Loops all 3 dimensions, calls the two functions above for each, keeps only the top 5 contributors per dimension. A per-dimension failure is caught and stored as `{'error': str(e)}` in that dimension's slot rather than aborting the whole call. |
| `get_top_driver` | `(results: Dict) -> Optional[Dict]` | Scans every dimension's `top_contributors` and returns the single segment with the highest `abs_contribution` across all of them — this is what "the root cause" boils down to in the narrative. |
| `get_comparison_dates` | `(target_date: str = None) -> tuple[str, str]` | No `target_date` → most recent 2 distinct dates in `fact_daily_metrics`. With `target_date` → most recent 2 dates `<= target_date`. Raises `ValueError` if fewer than 2 dates exist. |

### `decompose_metric()` return shape

```python
{
    'current_date': '2018-09-03', 'previous_date': '2018-08-29', 'metric': 'total_revenue',
    'dimensions': {
        'geography': {
            'total_current': 200.0, 'total_previous': 1100.0,
            'total_change': -900.0, 'total_change_pct': -81.82,
            'segment_count': 5,
            'top_contributors': [                          # top 5, dicts from calculate_contribution's columns
                {'segment': 'Southeast', 'current_value': 200.0, 'previous_value': 1100.0,
                 'change': -900.0, 'change_pct': -81.82, 'contribution_pct': 68.6, 'abs_contribution': 68.6},
                ...
            ]
        },
        'product': {...}, 'payment': {...}     # or {'error': '...'} if that dimension's query failed
    }
}
```

## Running standalone

```bash
python -m decomposition.decomposer
```

Uses `get_comparison_dates()` (no target date → latest 2 dates in the data) and prints per-dimension breakdowns plus the overall top driver.

## Config / env vars

Only `REDSHIFT_HOST/PORT/DATABASE/USER/PASSWORD`, read indirectly via `config.db.get_connection()`. No detection-style thresholds — this module is purely computational once given two dates.

## Upstream / downstream

- **Upstream:** `staging.metric_by_geography`, `staging.metric_by_product`, `staging.metric_by_payment` — all built by the dbt metrics layer. `get_comparison_dates` reads `staging.fact_daily_metrics` directly.
- **Downstream:** `narrative/generator.py`'s `generate_narrative()` takes `decompose_metric()`'s return dict as-is (reads `.dimensions`, `.metric`, `.current_date`/`.previous_date`, and each dimension's `top_contributors`). `orchestration/run_pipeline.py` calls `decompose_metric()` as step 3. `dashboard_api/views.py` exposes it via `/api/decomposition/`.

## Gotchas

- `fetch_dimension_metrics` opens a **new Redshift connection per call** — `decompose_metric` calls it 3 times (once per dimension), so one `decompose_metric()` call makes 3 separate connections. This is intentional (keeps the function self-contained) but is the acknowledged "future optimization" spot in `docs/analytics_pipeline.md` (pool one connection across the 3 queries).
- `contribution_pct` can legitimately exceed 100% or go negative — this happens when a segment moves opposite the overall trend (e.g. total revenue drops but one region grows). Not a bug; see the worked example in `docs/analytics_pipeline.md`.
- SQL is built via f-string interpolation of `metric_col`, `config['table']`, `config['segment_col']` — these come from the hardcoded `DIMENSION_TABLES` dict, not user input, so only the *date* args need (and get) `_validate_date`. If you ever make `metric_col` user-controllable, it needs the same treatment.

## Tests

Covered by `tests/test_decomposer.py` — 4 tests against `calculate_contribution` only (pure function, no DB needed): basic shape, contributions sum to ~100% when all segments move the same direction, negative-change handling, zero-previous-value handling (no crash / no div-by-zero).

```bash
pytest tests/test_decomposer.py -v
```

Note: `_validate_date`, `fetch_dimension_metrics`, `decompose_metric`, and `get_comparison_dates` (anything touching Redshift or date parsing) are **not** covered by this test file — only the pure `calculate_contribution` math is unit-tested.
