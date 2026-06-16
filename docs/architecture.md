# MetricPulse Architecture

## System Overview

MetricPulse is an automated root cause analysis engine that detects metric anomalies and explains what drove the change — before anyone asks.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            DATA LAYER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  S3 (Raw CSVs)  →  Redshift (raw_data)  →  dbt (staging/marts)         │
│                                                                         │
│  Brazilian E-Commerce Dataset (451K rows)                               │
│  • orders, order_items, customers, products, payments                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         TRANSFORMATION LAYER (dbt)                      │
├─────────────────────────────────────────────────────────────────────────┤
│  staging/              marts/                  metrics/                 │
│  ├── stg_orders        ├── fact_daily_metrics  ├── metric_by_geography │
│  ├── stg_order_items   ├── dim_geography       ├── metric_by_product   │
│  ├── stg_customers     ├── dim_product         └── metric_by_payment   │
│  └── stg_products      └── dim_payment                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DETECTION LAYER (Python)                        │
├─────────────────────────────────────────────────────────────────────────┤
│  anomaly_detector.py                                                    │
│  • Fetches daily metrics from Redshift                                  │
│  • Calculates z-scores for each metric                                  │
│  • Flags anomalies exceeding threshold (default: 2.0)                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       DECOMPOSITION LAYER (Python)                      │
├─────────────────────────────────────────────────────────────────────────┤
│  decomposer.py                                                          │
│  • Compares current vs previous date                                    │
│  • Slices by geography, product, payment                                │
│  • Calculates segment contribution to total change                      │
│  • Identifies top driver                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         NARRATIVE LAYER (Python)                        │
├─────────────────────────────────────────────────────────────────────────┤
│  generator.py                                                           │
│  • Converts analysis to plain English                                   │
│  • Generates full, Slack, and email formats                             │
│  • Uses Jinja2 templates                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DELIVERY LAYER                                  │
├─────────────────────────────────────────────────────────────────────────┤
│  sns_publisher.py          app.py (Streamlit)                           │
│  • Publishes to SNS        • Interactive dashboard                      │
│  • Email notifications     • Date selection                             │
│                            • Drill-down analysis                        │
│                            • One-click pipeline trigger                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Storage | AWS S3 | Raw data lake |
| Warehouse | AWS Redshift Serverless | Analytics database |
| Transformation | dbt | Data modeling & testing |
| Detection | Python + scipy | Statistical anomaly detection |
| Decomposition | Python + SQL | Segment contribution analysis |
| Narrative | Python + Jinja2 | Plain-English generation |
| Alerting | AWS SNS | Email notifications |
| Dashboard | Streamlit | Interactive visualization |
| Orchestration | Python | Pipeline coordination |

---

## Data Model

### Raw Layer (`raw_data` schema)

| Table | Rows | Description |
|-------|------|-------------|
| orders | 99,441 | Customer orders with timestamps |
| order_items | 112,650 | Line items per order |
| customers | 99,441 | Customer demographics |
| products | 32,951 | Product catalog |
| sellers | 3,095 | Seller information |
| payments | 103,886 | Payment transactions |
| category_translation | 71 | Category name mapping |

### Staging Layer (`staging` schema - dbt views)

| Model | Description |
|-------|-------------|
| stg_orders | Cleaned orders with date dimensions |
| stg_order_items | Order items with total value calculation |
| stg_customers | Customer location data |
| stg_products | Products with English categories |

### Marts Layer (`staging` schema - dbt tables)

| Model | Description |
|-------|-------------|
| fact_daily_metrics | Daily KPIs (revenue, orders, AOV) |
| dim_geography | State → Region mapping |
| dim_product | Category → Group mapping |
| dim_payment | Payment type display names |

### Metrics Layer (`staging` schema - dbt tables)

| Model | Description |
|-------|-------------|
| metric_by_geography | Daily metrics by state/region |
| metric_by_product | Daily metrics by product category |
| metric_by_payment | Daily metrics by payment type |

---

## Pipeline Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   DETECT     │────▶│  DECOMPOSE   │────▶│   NARRATE    │
│              │     │              │     │              │
│ • Z-score    │     │ • Geography  │     │ • Templates  │
│ • Threshold  │     │ • Product    │     │ • Formatting │
│ • Flagging   │     │ • Payment    │     │ • Summary    │
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                                                  ▼
                     ┌──────────────┐     ┌──────────────┐
                     │  DASHBOARD   │◀────│    ALERT     │
                     │              │     │              │
                     │ • Streamlit  │     │ • AWS SNS    │
                     │ • Charts     │     │ • Email      │
                     │ • Drill-down │     │              │
                     └──────────────┘     └──────────────┘
```

---

## Key Algorithms

### Anomaly Detection (Z-Score)

```python
z_score = (value - mean) / std_dev

if abs(z_score) > threshold:
    flag_as_anomaly()
```

Default threshold: 2.0 (configurable via `ANOMALY_THRESHOLD_ZSCORE`)

### Contribution Analysis

```python
segment_contribution = segment_change / total_change * 100

# Rank by absolute contribution
top_driver = max(segments, key=lambda s: abs(s.contribution))
```

---

## Decomposition Dimensions

| Dimension | Segments | Use Case |
|-----------|----------|----------|
| **Geography** | Southeast, South, Northeast, Central-West, North | Regional performance |
| **Product** | Electronics, Home & Furniture, Fashion, Health & Beauty, Kids, Auto, Other | Category analysis |
| **Payment** | Credit Card, Boleto, Voucher, Debit Card | Payment mix shifts |

---

## AWS Resources

| Service | Resource Name | Purpose | Cost Estimate |
|---------|---------------|---------|---------------|
| S3 | metric-pulse-kousik | Raw data storage | ~$0.02/month |
| Redshift Serverless | metric-pulse-wg | Data warehouse | ~$0.50-2/day when active |
| SNS | metric-pulse-alerts | Email alerts | Free (< 1000/month) |
| IAM | metric-pulse-dev | Service credentials | Free |

---

## Output Formats

### Full Narrative (Email)
```
📊 MetricPulse Alert: Total Revenue decrease

2018-09-03 vs 2018-08-29

Total Revenue decreased 90.6% ($1,762.70 → $166.46), a change of $1,596.24.

Primary Driver:
The decrease was primarily driven by Payment — specifically Credit Card,
which accounted for 106.6% of the total change.

Breakdown by Dimension:
• Geography: Top contributor was Southeast (68.0% of change)
• Product: Top contributor was Other (49.0% of change)
• Payment: Top contributor was Credit Card (106.6% of change)
```

### Slack Format
```
:chart_with_downwards_trend: *MetricPulse Alert*

*Total Revenue* decreased *90.6%* on 2018-09-03

:mag: *Root Cause:* Credit Card (payment) drove 106.6% of the change

:bar_chart: Breakdown:
• Geography: Southeast (68.0%)
• Product: Other (49.0%)
• Payment: Credit Card (106.6%)
```

---

## Performance Characteristics

| Operation | Duration | Notes |
|-----------|----------|-------|
| S3 → Redshift load | ~2 min | 451K rows, 7 tables |
| dbt run (full) | ~30 sec | All models |
| Anomaly detection | ~2 sec | 30-day lookback |
| Decomposition | ~5 sec | 3 dimensions |
| Full pipeline | ~15 sec | End-to-end |

---

## Future Enhancements

1. **SageMaker Integration**: ML-based anomaly detection (Prophet, DeepAR)
2. **Django UI**: Production-grade web interface
3. **Slack Integration**: Direct Slack alerts via webhook
4. **Scheduling**: Airflow DAG for automated daily runs
5. **Multi-metric**: Extend to order_count, avg_order_value
6. **Bivariate Analysis**: Region × Product decomposition