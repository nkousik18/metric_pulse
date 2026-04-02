# MetricPulse — Automated Root Cause Analysis Engine

## What It Does

When a business metric moves unexpectedly, MetricPulse automatically identifies *which segment* drove the change and delivers a plain-English explanation — before anyone asks.

**Problem:** "Revenue dropped 11% yesterday — why?" → Analyst spends 2-4 hours slicing data manually.

**Solution:** MetricPulse detects the anomaly, decomposes it across dimensions (region, product, payment type), and delivers the answer in seconds.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Storage | AWS S3, Redshift Serverless |
| Transformation | dbt |
| Anomaly Detection | Python (scipy/SageMaker) |
| Alerting | AWS SNS |
| Dashboard | Streamlit |

---

## Project Status

### ✅ Completed

| Step | Description |
|------|-------------|
| Project Setup | Folder structure, git repo, logging config |
| AWS Infrastructure | IAM user, S3 bucket, Redshift Serverless |
| Data Ingestion | Brazilian E-Commerce dataset (451K rows) uploaded to S3 |
| Raw Layer | 7 tables loaded into `raw_data` schema |
| dbt Staging | 4 staging views: orders, order_items, customers, products |
| dbt Marts | 3 dimension tables + 1 fact table (`fact_daily_metrics`) |

### 🔜 Remaining

| Step | Description |
|------|-------------|
| Decomposition Models | dbt models for segment-level metrics |
| Anomaly Detection | Z-score based detection on daily metrics |
| Decomposition Engine | Python logic to rank segment contributions |
| Narrative Generator | Template-based plain-English summaries |
| SNS Alerting | Push alerts to email/Slack |
| Streamlit Dashboard | Drill-down interface |

---

## Data Model
```
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
```

---

## Quick Commands
```bash
# Activate environment
source metric_venv/bin/activate

# Run dbt models
cd dbt_project
dbt run --select staging
dbt run --select marts

# Load data from S3 to Redshift
python ingestion/s3_to_redshift.py
```

---

## Repository

https://github.com/nkousik18/metric-pulse
