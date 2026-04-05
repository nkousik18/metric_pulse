# MetricPulse — Automated Root Cause Analysis Engine

## What It Does

When a business metric moves unexpectedly, MetricPulse automatically identifies *which segment* drove the change and delivers a plain-English explanation — before anyone asks.

**Problem:** "Revenue dropped 11% yesterday — why?" → Analyst spends 2-4 hours slicing data manually.

**Solution:** MetricPulse detects the anomaly, decomposes it across dimensions (region, product, payment type), and delivers the answer in seconds via email alert.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Storage | AWS S3, Redshift Serverless |
| Transformation | dbt |
| Anomaly Detection | Python (scipy) |
| Decomposition | Python + SQL |
| Narrative | Jinja2 templates |
| Alerting | AWS SNS |
| Dashboard | Streamlit (coming) |

---

## Project Status

### ✅ Completed

| Component | Description |
|-----------|-------------|
| Infrastructure | S3 bucket, Redshift Serverless, IAM, SNS topic |
| Data Ingestion | Brazilian E-Commerce dataset (451K rows) in S3 → Redshift |
| dbt Staging | 4 views: stg_orders, stg_order_items, stg_customers, stg_products |
| dbt Marts | 3 dimension tables + fact_daily_metrics |
| dbt Metrics | metric_by_geography, metric_by_product, metric_by_payment |
| Anomaly Detection | Z-score based detection with configurable threshold |
| Decomposition | Segment contribution analysis across 3 dimensions |
| Narrative Generator | Plain-English summaries (full, Slack, email formats) |
| SNS Alerting | Email alerts via AWS SNS |
| Orchestration | End-to-end pipeline runner |

### 🔜 Remaining

| Component | Description |
|-----------|-------------|
| Streamlit Dashboard | Interactive drill-down interface |
| SageMaker Integration | ML-based anomaly detection (stretch goal) |

---

## Data Model
raw_data (S3 → Redshift)
├── orders (99K)
├── order_items (112K)
├── customers (99K)
├── products (32K)
├── sellers (3K)
├── payments (103K)
└── category_translation (71)
staging (dbt views)
├── stg_orders
├── stg_order_items
├── stg_customers
└── stg_products
marts (dbt tables)
├── dim_geography
├── dim_product
├── dim_payment
└── fact_daily_metrics
metrics (dbt tables)
├── metric_by_geography
├── metric_by_product
└── metric_by_payment

---

## Quick Start
```bash
# Activate environment
source metric_venv/bin/activate

# Run full pipeline (dry run)
python orchestration/run_pipeline.py --dry-run

# Run with forced alert
python orchestration/run_pipeline.py --force-alert

# Run dbt models
cd dbt_project
dbt run
```

---

## Pipeline Components

### Anomaly Detection
```bash
python detection/anomaly_detector.py
```
Detects unusual metric movements using z-score analysis.

### Decomposition
```bash
python decomposition/decomposer.py
```
Breaks down metric changes by geography, product, and payment type.

### Narrative Generation
```bash
python narrative/generator.py
```
Converts analysis into plain-English summaries.

### Full Pipeline
```bash
python orchestration/run_pipeline.py --force-alert
```
Runs detection → decomposition → narrative → alert end-to-end.

---

## Configuration

Copy `.env.example` to `.env` and configure:

---

## Sample Output

MetricPulse Alert: Total Revenue decrease
2018-09-03 vs 2018-08-29
Total Revenue decreased 90.6% ($1,762.70 → $166.46), a change of $1,596.24.
Primary Driver:
The decrease was primarily driven by Payment — specifically Credit Card,
which accounted for 106.6% of the total change.
Breakdown by Dimension:

Geography: Top contributor was Southeast (68.0% of change)
Product: Top contributor was Other (49.0% of change)
Payment: Top contributor was Credit Card (106.6% of change)

## Repository

https://github.com/nkousik18/metric-pulse