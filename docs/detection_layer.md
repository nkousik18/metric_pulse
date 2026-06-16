# Detection Layer

The detection layer reads `fact_daily_metrics` from Redshift, runs z-score analysis over a configurable lookback window, and flags days whose metric value is statistically unusual. It is the first analytical step in the pipeline — its output determines whether decomposition and alerting are triggered.

---

## Overview

```
staging.fact_daily_metrics  (up to 760 daily rows)
        │
        │  fetch_daily_metrics(lookback_days=30)
        │  Most recent N rows via ORDER BY metric_date DESC LIMIT N
        ▼
DataFrame  (N rows × 5 columns)
        │
        │  calculate_zscore()
        │  z = (value − mean) / std   [std uses ddof=1, i.e. sample std]
        ▼
DataFrame + zscore column
        │
        │  detect_anomalies(threshold=2.0)
        │  Flag rows where |z| > threshold
        ▼
DataFrame + is_anomaly, anomaly_direction, change_pct, change_value
        │
        ├── get_latest_anomaly()  →  dict (most recent flagged day)
        └── run_detection()       →  full results dict
                                        │
                                        ▼
                            Decomposition layer
                            Narrative layer
                            Alerting layer
```

**Source file:** `detection/anomaly_detector.py`
**Unit tests:** `tests/test_anomaly_detector.py` (3 tests)
**Runtime:** ~2 seconds for a 30-day window

---

## Algorithm: Z-Score Detection

The detector uses the **whole-window z-score method**:

```
z = (x − μ) / σ

where:
  x = metric value on a given day
  μ = mean of the metric over the entire lookback window
  σ = sample standard deviation (ddof=1) over the lookback window
```

A day is flagged as an anomaly when `|z| > threshold`.

### Why sample std (ddof=1)?

With a default lookback of 30 days, the population is small. Sample standard deviation (`ddof=1`) applies Bessel's correction, which produces a less biased estimate than population std (`ddof=0`). For n=30, the difference is ~1.7% — small but appropriate for statistical rigour.

### Threshold behaviour

| Threshold | Meaning | ~% of normal days flagged |
|-----------|---------|--------------------------|
| 1.5 | Sensitive — flags moderate deviations | ~13% |
| **2.0** | **Default — flags clear outliers** | **~5%** |
| 2.5 | Conservative — flags only strong anomalies | ~1% |
| 3.0 | Strict — flags extreme outliers only | ~0.3% |

Configure via `ANOMALY_THRESHOLD_ZSCORE` in `.env` or pass directly to `run_detection()`.

### Worked example

```
Lookback window (30 days): daily revenue values
  Mean (μ) = $12,450
  Std  (σ) = $2,100

Day under review: revenue = $1,850
  z = (1850 − 12450) / 2100 = −5.05

|z| = 5.05 > 2.0 threshold  →  anomaly: direction='low'
change_pct = (1850 − previous_day) / previous_day × 100
```

---

## Functions

### `fetch_daily_metrics(lookback_days=30)`

Queries `staging.fact_daily_metrics` for the most recent N days.

**Query strategy:** `ORDER BY metric_date DESC LIMIT N` — fetches the freshest data regardless of the absolute date. The result is sorted ascending in `detect_anomalies()` before z-score calculation.

**Columns returned (5):**

| Column | Type | Description |
|--------|------|-------------|
| `metric_date` | DATE | Day of metrics |
| `order_count` | INT | Distinct orders placed |
| `customer_count` | INT | Distinct customers |
| `total_revenue` | DECIMAL | Sum of order revenue in BRL |
| `avg_order_value` | DECIMAL | Average revenue per order |

**Default window:** 30 days (configurable via `LOOKBACK_DAYS` env var or function argument)

---

### `calculate_zscore(series)`

Pure function — no I/O.

```python
z = (series - series.mean()) / series.std()  # ddof=1
```

Returns a `pd.Series` of the same length. Called internally by `detect_anomalies`.

---

### `detect_anomalies(df, metric_column='total_revenue', threshold=None)`

Adds 5 computed columns to the input DataFrame:

| Column added | Type | Description |
|--------------|------|-------------|
| `zscore` | float | Z-score of `metric_column` within the window |
| `is_anomaly` | bool | True when `\|zscore\| > threshold` |
| `anomaly_direction` | str | `'high'` / `'low'` / `'normal'` |
| `prev_value` | float | Previous day's value (shifted by 1) |
| `change_value` | float | Absolute day-over-day change |
| `change_pct` | float | Day-over-day % change (rounded to 2dp) |

**Supported metric columns:** any column returned by `fetch_daily_metrics` — `total_revenue`, `order_count`, `customer_count`, `avg_order_value`.

---

### `get_latest_anomaly(df, metric_col='total_revenue')`

Filters to rows where `is_anomaly=True`, sorts descending by date, and returns the most recent one as a dict.

**Returns** `None` if no anomalies exist in the window.

**Returns** (when an anomaly exists):

```python
{
    'metric_date':   <date>,
    'metric_value':  <value of the analyzed metric>,   # uses metric_col — not hardcoded
    'zscore':        <float, 2dp>,
    'direction':     'high' | 'low',
    'change_pct':    <float, day-over-day %>,
    'change_value':  <float, absolute change>
}
```

---

### `run_detection(metric='total_revenue', lookback_days=None, threshold=None)`

Top-level function that orchestrates the full detection flow. Called by `orchestration/run_pipeline.py` and `dashboard_api/views.py`.

**Parameters:**

| Parameter | Default | Source if None |
|-----------|---------|----------------|
| `metric` | `'total_revenue'` | passed directly |
| `lookback_days` | `30` | `LOOKBACK_DAYS` env var |
| `threshold` | `2.0` | `ANOMALY_THRESHOLD_ZSCORE` env var |

**Returns:**

```python
{
    'status':              'completed' | 'no_data',
    'metric':              'total_revenue',
    'lookback_days':       30,
    'total_days_analyzed': 30,
    'anomaly_count':       <int>,
    'latest_anomaly':      <dict | None>,
    'all_anomalies':       [<list of anomaly dicts>],
    'statistics': {
        'mean': <float>,
        'std':  <float>,
        'min':  <float>,
        'max':  <float>
    }
}
```

---

## Configuration

| Env Variable | Default | Effect |
|--------------|---------|--------|
| `ANOMALY_THRESHOLD_ZSCORE` | `2.0` | Z-score cutoff for flagging |
| `LOOKBACK_DAYS` | `30` | Days of history to include in the window |

Both can be overridden at call time via `run_detection(threshold=..., lookback_days=...)`.

---

## Supported Metrics

| `metric` value | Column in `fact_daily_metrics` | Unit |
|----------------|-------------------------------|------|
| `total_revenue` | `total_revenue` | BRL (Brazilian Real) |
| `order_count` | `order_count` | Count of orders |
| `avg_order_value` | `avg_order_value` | BRL per order |
| `customer_count` | `customer_count` | Unique customers |

The default is `total_revenue`. The API endpoint `/api/anomalies/` accepts a `metric` query parameter to switch between these.

---

## Unit Tests (`tests/test_anomaly_detector.py`)

3 tests covering `calculate_zscore` and `detect_anomalies`. No database connection required — tests use in-memory DataFrames.

| Test | What it verifies |
|------|-----------------|
| `test_zscore_mean_is_zero` | Z-score of the median value in a uniform series is ≈ 0 |
| `test_zscore_standard_deviation` | An extreme outlier gets a z-score > 1 |
| `test_no_anomalies_in_stable_data` | A flat series (variation < 5%) produces 0 anomalies at threshold=2.0 |
| `test_detects_obvious_anomaly` | A single 5× spike in a flat series is flagged |
| `test_anomaly_direction` | A sharp drop is labelled `direction='low'` |

**Run:**
```bash
pytest tests/test_anomaly_detector.py -v
```

---

## Running Detection Standalone

```bash
# Default: total_revenue, 30-day window, threshold=2.0
python -m detection.anomaly_detector
```

**Example output:**
```
ANOMALY DETECTION RESULTS
==================================================
Metric: total_revenue
Days analyzed: 30
Anomalies found: 2

Statistics:
  Mean: $12,450.00
  Std:  $ 2,100.00
  Min:  $ 1,850.00
  Max:  $18,200.00

Latest Anomaly:
  Date: 2018-09-03
  Value: $166.46
  Z-score: -5.05
  Direction: low
  Change: -90.6%
```

---

## API Endpoint

`GET /api/anomalies/`

| Query Param | Default | Example |
|-------------|---------|---------|
| `metric` | `total_revenue` | `?metric=order_count` |
| `threshold` | from env (`2.0`) | `?threshold=2.5` |

```bash
curl "http://127.0.0.1:8000/api/anomalies/?metric=total_revenue&threshold=2.0"
```

---

## Design Notes

**Why whole-window z-score and not rolling?**
A rolling z-score (e.g. 7-day window) is more sensitive to recent trends but needs more tuning and is noisier on sparse data. The whole-window approach over 30 days is robust, interpretable, and appropriate for daily business metrics with moderate seasonality.

**Why not Prophet or ARIMA?**
Z-score is the simplest model that works. It requires no training, no hyperparameter search, and produces a directly interpretable score. ML-based detection (Prophet, DeepAR via SageMaker) is listed as a future enhancement once a labelled anomaly dataset exists.

**Window size trade-off:**
- Too small (< 14 days): std is unstable, high false-positive rate
- Too large (> 60 days): recent structural shifts lower sensitivity
- 30 days: captures ~4 weekly cycles, stable enough, sensitive enough

---

## Issues Fixed

| Issue | Change |
|-------|--------|
| `get_connection()` duplicated (4th copy in codebase) | Removed — now imports from `config/db.get_connection()` |
| `from scipy import stats` imported but never used | Removed |
| `get_latest_anomaly` hardcoded `latest['total_revenue']` regardless of which metric was analyzed | Now uses `metric_col` parameter — works correctly for `order_count`, `avg_order_value`, etc. |
| `detection/config.yml` was an empty dead file | Deleted |
