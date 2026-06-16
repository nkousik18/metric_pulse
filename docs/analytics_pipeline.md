# Analytics Pipeline

The analytics pipeline is the core intelligence of MetricPulse. It runs after dbt has built the metric tables and produces a plain-English explanation of what drove a metric change. It consists of four layers that execute in sequence: decomposition → narrative → alerting, orchestrated by a single entry point.

---

## Pipeline Flow

```
staging.fact_daily_metrics
staging.metric_by_geography
staging.metric_by_product
staging.metric_by_payment
        │
        │  Step 1: decomposer.decompose_metric()
        │  Two SQL queries per dimension (current date, previous date)
        │  → segment contributions ranked by absolute % of total change
        ▼
decomposition_results dict
        │
        │  Step 2: narrative.generator.generate_narrative()
        │  Jinja2 templates → 4 output formats
        ▼
narratives dict  {full, slack, email_subject, summary}
        │
        │  Step 3: alerting.sns_publisher.publish_metric_alert()
        │  boto3 SNS publish → subscribed emails
        ▼
SNS email delivered to subscribers
```

All four layers are coordinated by `orchestration/run_pipeline.py`, which also wraps anomaly detection at the front.

---

## Layer 1 — Decomposition (`decomposition/decomposer.py`)

Answers: *which segment drove the most of the total metric change between two dates?*

### How it works

For each of the 3 dimensions (geography, product, payment), it runs a single SQL query that produces a `(segment, current_value, previous_value)` table using a `FULL OUTER JOIN` on the two dates. It then calculates each segment's share of the total change.

**Contribution formula:**

```
change_i            = current_value_i − previous_value_i
total_change        = Σ change_i  (across all segments)
contribution_pct_i  = (change_i / total_change) × 100
```

Contributions can exceed 100% or be negative — this is expected when some segments move in opposite directions to the total. The segment with the highest `|contribution_pct|` is the top driver.

**Worked example:**

```
Geography dimension — comparing 2018-08-29 → 2018-09-03

Segment       prev    current   change    contribution
Southeast     1100     200      −900        68.0%
Northeast      300      80      −220        16.6%
South          200     120       −80         6.0%
North          100      50       −50         3.8%
Central-West    62       0       −62         4.7%
─────────────────────────────────────────────────────
Total          1762     450    −1312        98.1%   ← Southeast is top driver
```

### Functions

| Function | What it does |
|----------|-------------|
| `fetch_dimension_metrics(dimension, current_date, previous_date, metric_col)` | Runs the pivot SQL and returns a 3-column DataFrame: `segment`, `current_value`, `previous_value` |
| `calculate_contribution(df)` | Pure function — adds `change`, `change_pct`, `contribution_pct`, `abs_contribution` columns; sorts by `abs_contribution` descending |
| `decompose_metric(current_date, previous_date, metric_col)` | Loops all 3 dimensions, returns full results dict |
| `get_top_driver(results)` | Scans all dimensions' top contributors, returns the single segment with the highest `abs_contribution` across all dimensions |
| `get_comparison_dates(target_date)` | Queries `fact_daily_metrics` for the two most recent dates ≤ `target_date` (or the two most recent dates overall) |
| `_validate_date(date_str)` | Validates `YYYY-MM-DD` format — raises `ValueError` on bad input to prevent SQL injection |

### Dimension configuration

| Dimension | Table | `segment_col` (group) | `detail_col` (drill-down) |
|-----------|-------|-----------------------|--------------------------|
| `geography` | `staging.metric_by_geography` | `region` | `state_code` |
| `product` | `staging.metric_by_product` | `product_category_group` | `product_category` |
| `payment` | `staging.metric_by_payment` | `payment_type_display` | `payment_type` |

### Return shape of `decompose_metric()`

```python
{
    'current_date':  '2018-09-03',
    'previous_date': '2018-08-29',
    'metric':        'total_revenue',
    'dimensions': {
        'geography': {
            'total_current':     450.00,
            'total_previous':   1762.00,
            'total_change':    -1312.00,
            'total_change_pct':  -74.46,
            'segment_count':        5,
            'top_contributors': [   # top 5, sorted by abs_contribution
                {
                    'segment':          'Southeast',
                    'current_value':    200.00,
                    'previous_value':  1100.00,
                    'change':          -900.00,
                    'change_pct':       -81.82,
                    'contribution_pct':  68.60,
                    'abs_contribution':  68.60
                },
                ...
            ]
        },
        'product': { ... },
        'payment': { ... }
    }
}
```

### Unit tests (`tests/test_decomposer.py`) — 4 tests

| Test | Verifies |
|------|----------|
| `test_basic_contribution` | Output has `change` and `contribution_pct` columns |
| `test_contribution_sums_to_100` | All contributions sum to 100% when all segments move in the same direction |
| `test_negative_change` | All changes negative when current < previous for all segments |
| `test_zero_previous_value` | No crash when a segment had zero revenue on the previous date |

---

## Layer 2 — Narrative (`narrative/generator.py`)

Converts the decomposition dict into human-readable text in 4 formats.

### Templates

All templates are inline Jinja2 strings inside `generator.py`. A `narrative/templates/` directory exists but holds no active files.

| Output key | Format | Used by |
|------------|--------|---------|
| `full` | Markdown with bold, emoji header, full breakdown | SNS email body |
| `slack` | Slack mrkdwn with `:chart:` emojis | Future Slack webhook |
| `email_subject` | Single-line subject | SNS email subject (≤ 100 chars) |
| `summary` | Plain one-sentence string | Pipeline logs, API response |

### Template context variables

| Variable | Example value |
|----------|---------------|
| `metric_name` | `"Total Revenue"` |
| `current_date` | `"2018-09-03"` |
| `previous_date` | `"2018-08-29"` |
| `current_value` | `166.46` |
| `previous_value` | `1762.70` |
| `change_value` | `-1596.24` |
| `change_pct` | `90.6` (absolute value) |
| `direction` | `"decrease"` |
| `direction_verb` | `"decreased"` |
| `top_driver.dimension` | `"payment"` |
| `top_driver.segment` | `"Credit Card"` |
| `top_driver.contribution_pct` | `106.6` |
| `dimensions` | Dict of `{dim_name: {top_segment, top_contribution, total_change_pct}}` |
| `generated_at` | `"2018-09-04 08:00:00"` |

### Sample outputs

**`full`:**
```
📊 MetricPulse Alert: Total Revenue decrease

2018-09-03 vs 2018-08-29

Total Revenue decreased 90.6% ($1,762.70 → $166.46), a change of $1,596.24.

Primary Driver:
The decrease was primarily driven by Payment — specifically Credit Card,
which accounted for 106.6% of the total change.

Breakdown by Dimension:
- Geography: Top contributor was Southeast (68.0% of change)
- Product: Top contributor was Other (49.0% of change)
- Payment: Top contributor was Credit Card (106.6% of change)
```

**`slack`:**
```
:chart_with_downwards_trend: *MetricPulse Alert*

*Total Revenue* decreased *90.6%* on 2018-09-03

:mag: *Root Cause:* Credit Card (payment) drove 106.6% of the change

:bar_chart: Breakdown:
• Geography: Southeast (68.0%)
• Product: Other (49.0%)
• Payment: Credit Card (106.6%)
```

**`email_subject`:**
```
MetricPulse: Total Revenue decrease 90.6% on 2018-09-03
```

**`summary`:**
```
Total Revenue decreased 90.6% on 2018-09-03. Primary driver: Credit Card (payment) contributed 106.6% of the change.
```

### `format_type` parameter

`generate_narrative(results, format_type='all')` controls which formats are returned:

| `format_type` | Returns |
|---------------|---------|
| `'all'` (default) | All 4 keys |
| `'full'` | Only `{'full': ...}` |
| `'slack'` | Only `{'slack': ...}` |
| `'email'` | Only `{'email_subject': ...}` |
| `'summary'` | Only `{'summary': ...}` |

### Custom Jinja2 filters

| Filter | Purpose |
|--------|---------|
| `format_currency` | `1762.7 → "1,762.70"` — uses absolute value, handles None |
| `abs` | Pass-through to Python's built-in `abs()` |

### Unit tests (`tests/test_narrative.py`) — 6 tests

| Test | Verifies |
|------|----------|
| `test_basic_formatting` | `format_currency(1234.56) == "1,234.56"` |
| `test_large_number` | Comma formatting on 7-digit numbers |
| `test_none_value` | `format_currency(None) == "0.00"` |
| `test_negative_value` | `format_currency(-100.50) == "100.50"` (absolute) |
| `test_generates_all_formats` | All 4 keys present in output |
| `test_summary_contains_key_info` | Summary contains metric name and top driver segment |

---

## Layer 3 — Alerting (`alerting/sns_publisher.py`)

Publishes the narrative to AWS SNS, which fans it out to all confirmed email subscribers.

### Functions

| Function | Purpose |
|----------|---------|
| `get_sns_client()` | Creates boto3 SNS client from env credentials |
| `create_topic_if_not_exists(name)` | Idempotent — AWS `create_topic` returns existing ARN if topic already exists |
| `subscribe_email(topic_arn, email)` | Adds an email subscriber — requires confirmation click |
| `publish_alert(subject, message, topic_arn)` | Core publish call — truncates subject to 100 chars (SNS limit) |
| `publish_metric_alert(narratives, topic_arn)` | Convenience wrapper — strips markdown `**` and `*` for plain-text email body |
| `setup_sns(email)` | One-time setup: create topic + subscribe email + print ARN to paste into `.env` |

### Publish flow

```
narratives dict
    │
    │  publish_metric_alert()
    │  • subject = narratives['email_subject']
    │  • message = narratives['full'] with ** and * stripped
    ▼
publish_alert(subject, message, SNS_TOPIC_ARN)
    │
    │  boto3 SNS.publish()
    ▼
SNS → email to all confirmed subscribers
    returns: {'status': 'sent', 'message_id': '<uuid>', 'topic_arn': '...'}
```

### Return values from `publish_alert`

| Scenario | Return |
|----------|--------|
| Sent successfully | `{'status': 'sent', 'message_id': '<uuid>', 'topic_arn': '...'}` |
| No `SNS_TOPIC_ARN` configured | `{'status': 'skipped', 'reason': 'no_topic_arn'}` |
| AWS error | `{'status': 'error', 'error': '<message>'}` |

### CLI usage

```bash
# Create topic and subscribe email (first-time setup)
python -m alerting.sns_publisher --setup --email your@email.com

# Send a test alert
python -m alerting.sns_publisher --test
```

---

## Layer 4 — Orchestration (`orchestration/run_pipeline.py`)

The single entry point that runs the full pipeline end-to-end.

### Execution steps

```
Step 1  run_detection(metric, threshold)
            → detection_results + anomaly_count

Step 2  get_comparison_dates()
            → current_date, previous_date

Step 3  decompose_metric(current_date, previous_date, metric)
            → decomposition_results

Step 4  generate_narrative(decomposition_results)
            → narratives

Step 5  publish_metric_alert(narratives)      ← only if anomaly_detected OR force_alert
            → alert_result                    ← skipped if dry_run=True
```

### Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `metric` | `'total_revenue'` | Which metric to analyze |
| `threshold` | from env (`2.0`) | Z-score cutoff passed to detection |
| `force_alert` | `False` | Send alert even when no anomaly detected |
| `dry_run` | `False` | Run full pipeline but skip SNS publish |
| `publish_metrics` | `True` | Emit results to CloudWatch after completion |

### Return shape

```python
{
    'started_at':       '2018-09-04T08:00:00',
    'completed_at':     '2018-09-04T08:00:15',
    'duration_seconds': 14.8,
    'status':           'completed',          # or 'failed'
    'metric':           'total_revenue',
    'current_date':     '2018-09-03',
    'previous_date':    '2018-08-29',
    'detection':        { ... run_detection() output ... },
    'decomposition':    { ... decompose_metric() output ... },
    'narratives':       { ... generate_narrative() output ... },
    'alert':            { 'status': 'sent' | 'skipped' | 'dry_run' | 'error', ... }
}
```

### CLI usage

```bash
# Dry run — full pipeline, no alert sent
python -m orchestration.run_pipeline --dry-run

# Full run with alert
python -m orchestration.run_pipeline --force-alert

# Custom metric and threshold
python -m orchestration.run_pipeline --metric order_count --threshold 2.5 --dry-run

# Skip CloudWatch metrics
python -m orchestration.run_pipeline --no-metrics --dry-run
```

### Expected output

```
============================================================
METRICPULSE PIPELINE SUMMARY
============================================================

Status: COMPLETED
Metric: total_revenue
Period: 2018-08-29 → 2018-09-03
Duration: 14.80s

Anomaly Detection:
  Days analyzed: 30
  Anomalies found: 2

Summary:
  Total Revenue decreased 90.6% on 2018-09-03. Primary driver: Credit Card (payment) contributed 106.6% of the change.

Alert Status: sent
  Message ID: abc123-...
============================================================
```

### Error handling

Each pipeline step is wrapped in a try/except. A failure in any step:
- Logs the error at ERROR level
- Sets `results['status'] = 'failed'` and `results['error'] = str(e)`
- Returns the partial results dict (upstream steps are preserved)
- Does not re-raise — the caller always gets a results dict

CloudWatch publish failure is caught separately with just a WARNING log — it never blocks the pipeline.

---

## Running the Full Analytics Pipeline

```bash
# Activate environment
source metric_venv/bin/activate

# Dry run (safe — no email sent)
python -m orchestration.run_pipeline --dry-run

# Full run with SNS alert
python -m orchestration.run_pipeline --force-alert

# Via Django API
curl -X POST http://127.0.0.1:8000/api/pipeline/ \
     -H "Content-Type: application/json" \
     -d '{"metric": "total_revenue", "dry_run": true}'
```

---

## Performance

| Step | Typical Duration | Notes |
|------|-----------------|-------|
| Anomaly detection (30-day fetch) | ~2 sec | 1 Redshift query |
| Date lookup | < 1 sec | 1 Redshift query |
| Decomposition (3 dimensions) | ~5 sec | 3 Redshift queries, 1 connection each |
| Narrative generation | < 0.1 sec | Pure Python / Jinja2 |
| SNS publish | ~1 sec | 1 AWS API call |
| **End-to-end** | **~10–15 sec** | |

---

## Issues Fixed

| Layer | Issue | Fix |
|-------|-------|-----|
| Decomposition | `get_connection()` duplicated (5th copy in codebase) | Removed — imports from `config/db` |
| Decomposition | `import redshift_connector` + unused `List` left over | Removed both |
| Decomposition | Date strings interpolated into SQL — SQL injection vector from API query params | Added `_validate_date()` — strict `YYYY-MM-DD` format check before any SQL use |
| Decomposition | `dimensions.yml` and `significance.py` were empty dead files | Deleted |
| Narrative | `load_dotenv()` imported and called with no env vars used | Removed |
| Narrative | `format_type` parameter was accepted but ignored — all 4 formats always generated | Now filters output to the requested format only |
| Narrative | `narrative/templates/metric_drop.jinja2` was a dead file (templates are inline) | Deleted |
| Alerting | `slack_webhook.py` was an empty dead file | Deleted |

---

## Design Notes

**Why `get_comparison_dates()` returns consecutive dates, not week-over-week?**
The decomposer compares the current date to the immediately preceding date in the data. For a daily business metric, day-over-day is the most sensitive comparison. Week-over-week would reduce noise but mask same-day volatility. The `target_date` parameter allows callers to compare any date against its predecessor.

**Why 3 separate Redshift connections for 3 dimensions?**
`fetch_dimension_metrics` opens and closes its own connection per call. This is slightly chatty but keeps the function self-contained and avoids connection lifetime management. A future optimization would pool a single connection across all 3 dimension queries in `decompose_metric`.

**Why does `contribution_pct` sometimes exceed 100% or go negative?**
This is mathematically correct and intentional. If Southeast revenue dropped 900 BRL but Central-West revenue *increased* 200 BRL, Southeast's contribution to the total −700 BRL change is `−900 / −700 × 100 = 128.6%` and Central-West's is `+200 / −700 × 100 = −28.6%`. The contributions still sum to 100%.
