# MetricPulse — Project Documentation (Resume Source of Truth)

---

## 1. Project Summary

MetricPulse is an automated root cause analysis engine built on the Brazilian Olist e-commerce dataset (451,535 rows, 7 tables). It ingests raw CSVs into S3, transforms them through a 3-layer dbt pipeline on Redshift Serverless, runs z-score anomaly detection across 4 business metrics, decomposes metric changes by geography/product/payment, generates plain-English narratives via Jinja2 templates, and delivers findings to stakeholders via SNS email alerts — all triggered from a single API call. The Django REST API and SPA dashboard make every layer queryable and observable without writing SQL. End-to-end pipeline runtime is 10–15 seconds from trigger to alert. The full stack runs on AWS (S3, Redshift Serverless, SNS, CloudWatch, Lambda, ECR) with the web app deployed on Render.

---

## 2. Tech Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Object storage | AWS S3 | Durable raw data lake; COPY from S3 is native to Redshift |
| Data warehouse | AWS Redshift Serverless | Columnar storage for analytical queries; no cluster management |
| Data transformation | dbt 1.10 (dbt-redshift) | Version-controlled SQL with built-in testing and lineage |
| Anomaly detection | Python + NumPy (z-score) | Interpretable, no training data required, 30-day rolling window |
| Narrative generation | Jinja2 3.1 | Separates template logic from Python; 4 output formats from one render |
| Alerting | AWS SNS | Managed pub/sub; single API call to send email to N subscribers |
| Monitoring | AWS CloudWatch | Native AWS metrics; 3 custom metrics published per pipeline run |
| Serverless pipeline | AWS Lambda + ECR | Schedule pipeline without always-on compute; Docker image deployment |
| Web framework | Django 6.0 + DRF 3.17 | REST API + SPA with minimal boilerplate; SQLite for auth only |
| Production server | Gunicorn + WhiteNoise | WSGI-compatible; WhiteNoise serves static files without a CDN |
| Legacy dashboard | Streamlit 1.56 | Rapid prototyping; `@st.cache_resource` for persistent Redshift connection |
| Charts (web) | Chart.js (CDN) | Zero-dependency frontend charts; no build step |
| CI/CD | GitHub Actions | Native GitHub integration; parallel lint + test + dbt parse jobs |
| Deployment | Render | Zero-config PaaS; auto-deploys on push to main |
| Testing | pytest 9.0 | 13 tests across 3 files; mocks Redshift for unit tests |

---

## 3. Ingestion Pipeline (3 Steps)

Raw CSV files sourced from the Olist Brazilian E-Commerce dataset (Kaggle). 9 files on disk, 7 ingested, 2 skipped.

**Step 1 — Upload to S3 (`ingestion/upload_to_s3.py`)**

Walks `data/raw/` and uploads each CSV to S3 under the `raw/` prefix.

| Parameter | Value |
|-----------|-------|
| S3 prefix | `raw/` |
| Total files on disk | 9 CSVs |
| Total size on disk | ~120 MB |
| Files uploaded | 9 |
| S3 key format | `raw/{filename}.csv` |

**Step 2 — Create Redshift Tables (`ingestion/setup_redshift_tables.py`)**

Creates schema `raw_data` and 7 tables with typed DDL. `verify_tables()` queries `pg_tables` with `schemaname = 'raw_data'` to confirm creation.

| Table | Rows | Key columns |
|-------|------|-------------|
| `customers` | 99,441 | `customer_id`, `customer_zip_code_prefix`, `customer_state` |
| `orders` | 99,441 | `order_id`, `customer_id`, `order_status`, `order_purchase_timestamp` |
| `order_items` | 112,650 | `order_id`, `product_id`, `seller_id`, `price`, `freight_value` |
| `payments` | 103,886 | `order_id`, `payment_sequential`, `payment_type`, `payment_value` |
| `products` | 32,951 | `product_id`, `product_category_name` |
| `sellers` | 3,095 | `seller_id`, `seller_zip_code_prefix`, `seller_state` |
| `product_category_name_translation` | 71 | `product_category_name`, `product_category_name_english` |
| **Total** | **451,535** | |

Skipped (too large / low signal for this analysis):
- `olist_geolocation_dataset.csv` — 1,000,163 rows, 58 MB
- `olist_order_reviews_dataset.csv` — 104,000 rows, 14 MB

**Step 3 — Load into Redshift (`ingestion/s3_to_redshift.py`)**

Issues a `COPY` command per table from S3 into `raw_data` schema.

| COPY option | Value | Purpose |
|-------------|-------|---------|
| `FORMAT AS CSV` | — | Explicit format declaration |
| `IGNOREHEADER 1` | — | Skip CSV header row |
| `DATEFORMAT 'auto'` | — | Handle mixed date formats in source data |
| `TIMEFORMAT 'auto'` | — | Handle mixed timestamp formats |
| `TRUNCATECOLUMNS` | — | Silently truncate values exceeding column width |
| Credentials | IAM role (preferred) / access key fallback | IAM role keeps credentials out of Redshift query history (`STL_QUERYTEXT`) |
| Total ingested | ~48 MB | Of 120 MB on disk |

---

## 4. dbt Transformation Layer (11 Models, 37 Tests)

3-layer architecture: staging (views) → marts (tables) → metrics (tables). All models land in the `staging` schema on Redshift.

**Layer 1 — Staging (4 views)**

Rename columns, cast types, filter statuses. No joins. Materialised as views so they always reflect the latest `raw_data`.

| Model | Source table | Key transforms |
|-------|-------------|----------------|
| `stg_customers` | `raw_data.customers` | Rename `customer_unique_id`; standardise column names |
| `stg_orders` | `raw_data.orders` | Cast `order_purchase_timestamp` → `DATE` as `order_date`; filter to 6 valid statuses |
| `stg_order_items` | `raw_data.order_items` | Add `total_item_value = price + freight_value` |
| `stg_sellers` | `raw_data.sellers` | Rename and standardise |

**Layer 2 — Marts (5 tables)**

Enrichment dimensions. Materialised as tables for join performance.

| Model | Rows | Purpose |
|-------|------|---------|
| `dim_customers` | 99,441 | Join key between orders and geography |
| `dim_geography` | 27 | 27 Brazilian states → 5 regions (North, Northeast, Midwest, Southeast, South) |
| `dim_product` | 32,951 | 73 product categories → 7 product groups |
| `dim_payment` | 5 | Payment type codes → display labels |
| `dim_sellers` | 3,095 | Seller location |

**Layer 3 — Metrics (2 tables)**

Final analytical tables. Aggregated daily. These are the tables queried by the detection and decomposition layers.

| Model | Grain | Metrics |
|-------|-------|---------|
| `fact_daily_metrics` | 1 row per day | `order_count`, `total_revenue`, `avg_order_value` |
| `metric_by_geography` | 1 row per day × region × state | Revenue and order count by geography |
| `metric_by_product` | 1 row per day × product group × category | Revenue and order count by product |
| `metric_by_payment` | 1 row per day × payment type | Revenue and order count by payment method |

**Test coverage (37 tests)**

| Test type | Count | Applied to |
|-----------|-------|-----------|
| `not_null` | 18 | Primary keys and required fields across all models |
| `unique` | 9 | All primary keys |
| `accepted_values` | 7 | `order_status` (6 values), `payment_type` (5 values), `region` (5 values) |
| `relationships` | 3 | FK integrity: orders → customers, items → orders, items → products |
| **Total** | **37** | |

**Notable fix — `metric_by_payment` double-count bug:**
Original query joined `stg_order_items` (N rows/order) × `raw_data.payments` (M rows/order) producing N×M rows per order. Fixed by pre-aggregating revenue per `order_id` in a CTE and using `payment_sequential = 1` to select one primary payment per order.

---

## 5. Anomaly Detection Layer

**Algorithm: Z-score (whole-window method)**

```
z = (x - μ) / σ
```

Where `μ` and `σ` are computed over the full 30-day lookback window using `ddof=1` (sample standard deviation). A date is flagged anomalous when `|z| > threshold`.

| Parameter | Value | Configurable |
|-----------|-------|-------------|
| Lookback window | 30 days | Yes (`LOOKBACK_DAYS` env var) |
| Default threshold | 2.0 | Yes (`ANOMALY_THRESHOLD_ZSCORE` env var) |
| `ddof` | 1 (sample std) | No — correct for finite samples |
| Supported metrics | `total_revenue`, `order_count`, `avg_order_value`, `revenue_per_order` | — |

**Threshold sensitivity**

| Threshold | Sensitivity | Typical use |
|-----------|-------------|-------------|
| 1.5 | High — flags ~13% of normal data | High-signal noisy metrics |
| 2.0 (default) | Medium — flags ~5% of normal data | General use |
| 2.5 | Low — flags ~1% of normal data | Low-noise metrics requiring certainty |
| 3.0 | Very low — flags ~0.3% of normal data | Only extreme outliers |

**Key functions (`detection/anomaly_detector.py`)**

| Function | Input | Output |
|----------|-------|--------|
| `fetch_metric_data(metric, days)` | metric name, lookback days | DataFrame from `fact_daily_metrics` |
| `calculate_zscore(df, metric_col)` | DataFrame + column name | DataFrame with `zscore`, `is_anomaly` columns |
| `get_latest_anomaly(df, metric_col)` | Analysed DataFrame | Dict with latest anomalous date, value, z-score |
| `run_detection(metric, threshold, days)` | All params | Full detection result dict |
| `format_anomaly_summary(result)` | Detection result | Human-readable summary string |

---

## 6. Analytics Pipeline (4 Stages)

**Stage 1 — Decomposition (`decomposition/decomposer.py`)**

For a current date vs previous date pair, fetches dimension metrics and calculates each segment's contribution to the total metric change.

```
contribution_pct = (segment_change / total_change) * 100
```

Note: `contribution_pct` can exceed 100% or be negative when segments move in opposite directions — this is mathematically correct, not a bug.

Dimensions supported: `geography` (region/state), `product` (group/category), `payment` (type).

SQL injection prevention: `_validate_date(date_str)` calls `datetime.strptime(date_str, '%Y-%m-%d')` and raises `ValueError` on any non-conforming input before interpolation into SQL.

| Field in output | Description |
|----------------|-------------|
| `dimension` | geography / product / payment |
| `segments` | List of `{name, current_value, previous_value, change, contribution_pct}` |
| `total_change` | Absolute change in metric |
| `total_change_pct` | Percentage change in metric |
| `dominant_driver` | Segment with highest `|contribution_pct|` |

**Stage 2 — Narrative Generation (`narrative/generator.py`)**

Renders decomposition output into natural language using Jinja2 templates.

| Template | File | Use case |
|----------|------|---------|
| `full` | `full_report.jinja2` | Complete multi-paragraph analysis |
| `slack` | `slack_message.jinja2` | Single-block Slack notification |
| `email_subject` | `email_subject.jinja2` | One-line email subject line |
| `summary` | `summary.jinja2` | 2–3 sentence executive summary |

`format_type` parameter controls output: `'all'` returns all 4 formats; any single key (e.g. `'slack'`) returns only that format. Previously this parameter was ignored — all 4 formats were always returned regardless.

**Stage 3 — Alerting (`alerting/sns_publisher.py`)**

Publishes to an SNS topic when anomalies are detected (or when `force_alert=True`).

| Scenario | Alert sent |
|----------|-----------|
| Anomaly detected + threshold exceeded | Yes |
| No anomaly detected | No |
| `force_alert=True` | Yes (regardless of anomaly) |
| `dry_run=True` | No (pipeline runs but SNS publish skipped) |

**Stage 4 — Orchestration (`orchestration/run_pipeline.py`)**

Coordinates all stages in sequence. Called by the Django `PipelineView` and by `lambda_handler.py`.

```
fetch data → run detection → decompose (if anomaly) → generate narrative → publish alert → log to CloudWatch
```

End-to-end runtime: ~10–15 seconds. CloudWatch metrics published: `PipelineExecutionSuccess` (1/0), `AnomaliesDetected` (count), `AlertsSent` (1/0).

---

## 7. Django REST API (7 Endpoints)

Single-page app served from `templates/base.html` via `TemplateView`. All data fetched client-side. SQLite used only for Django sessions/admin — no business data stored locally.

| Endpoint | Method | Key params | Returns |
|----------|--------|-----------|---------|
| `/api/health/` | GET | — | Service status + timestamp |
| `/api/metrics/` | GET | `days` (default 30) | Daily metrics array from `fact_daily_metrics` |
| `/api/anomalies/` | GET | `metric`, `threshold` | Detection results with flagged dates |
| `/api/decomposition/` | GET | `current_date`, `previous_date`, `metric` | Full decomposition dict for 3 dimensions |
| `/api/narrative/` | GET | `current_date`, `previous_date` | All 4 narrative format outputs |
| `/api/pipeline/` | POST | `metric`, `force_alert`, `dry_run` | Pipeline execution summary |
| `/api/contact/` | POST | `name`, `email`, `message` | Logs submission (email send disabled) |

---

## 8. Dashboard (2 Interfaces)

**Django SPA (primary — live on Render)**

4-tab SPA: Home / Dashboard / Architecture / About. Tab switching via JS `showTab()` — no page reloads. All charts rendered with Chart.js (CDN). No local CSS dependencies.

| Component | Details |
|-----------|---------|
| KPI cards | 4 cards: Revenue, Orders, AOV, Anomaly count |
| Trend chart | Chart.js line — last 60 days; anomaly dates highlighted red |
| Decomposition | 3 panels (geography / product / payment) as contribution % bars + drill-down |
| Narrative | Rendered markdown from `/api/narrative/`; Copy + Download buttons |
| Pipeline control | "Run Analysis" (dry run) / "Run & Send Alert" buttons → `POST /api/pipeline/` |
| Anomaly threshold | Range slider 1.0–3.0 (step 0.1) → passed as `threshold` param |

**Streamlit Dashboard (legacy — local only)**

Direct Redshift connection. `@st.cache_resource` for connection (session-scoped), `@st.cache_data(ttl=300)` for query results (5-minute cache). Waterfall charts via Plotly Express. Not deployed.

---

## 9. Deployment Architecture

**Render (web app — live)**

| Setting | Value |
|---------|-------|
| Runtime | Python 3.12 |
| Server | Gunicorn |
| Build command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Static files | WhiteNoise (`CompressedManifestStaticFilesStorage` — fingerprinted filenames) |
| Settings module | `metric_pulse_web.settings_prod` (via `DJANGO_SETTINGS_MODULE` env var) |
| `ALLOWED_HOSTS` | `['.onrender.com']` |
| HTTPS | Trusted via `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` |

**AWS Lambda (analytics pipeline)**

Docker image built from `public.ecr.aws/lambda/python:3.12`. Contains only pipeline modules — Django, dbt, and ingestion excluded. Triggered by EventBridge on a schedule.

| File | Purpose |
|------|---------|
| `Dockerfile` | Lambda container image definition |
| `lambda_handler.py` | Entry point — maps Lambda event to `run_pipeline()` |
| `deploy/setup_lambda.sh` | Create Lambda function, IAM role, ECR repo |
| `deploy/deploy_lambda.sh` | Build image, push to ECR, update Lambda function |
| `deploy/setup_schedule.sh` | Create EventBridge scheduled rule |

**GitHub Actions CI/CD**

| Pipeline | Trigger | Jobs |
|----------|---------|------|
| CI (`ci.yml`) | Push / PR to `develop`, `main` | `lint-and-test` (flake8 + pytest) + `dbt-check` (dbt parse) — parallel |
| CD (`cd.yml`) | Push to `main` | Requires `production` environment approval; deploys to Render |

Flake8 strategy: hard errors (`E9,F63,F7,F82`) fail CI; style warnings (`--exit-zero`) are non-blocking. pip cache keyed on `requirements.txt` hash — saves ~60s per run on cache hit.

---

## 10. Test Coverage (13 Tests, 3 Files)

| File | Tests | What's covered |
|------|-------|---------------|
| `tests/test_anomaly_detector.py` | 5 | Z-score calculation, threshold logic, anomaly flagging, `get_latest_anomaly` per metric, empty DataFrame handling |
| `tests/test_decomposer.py` | 4 | Contribution % formula, dominant driver selection, date validation rejection, multi-dimension output shape |
| `tests/test_narrative.py` | 4 | All 4 format outputs present, `format_type` filtering, unknown format raises `ValueError`, template renders without error |

Redshift is mocked in all 13 tests — no live AWS connection required to run CI. `pytest tests/ -v --tb=short` is the CI command; previously a `|| echo` clause swallowed failures silently.

---

## 11. Key Engineering Decisions

| Decision | Chosen | Rejected | Reason |
|----------|--------|----------|--------|
| Anomaly detection algorithm | Z-score (whole-window) | Prophet, ARIMA, Isolation Forest | No training data needed; interpretable z-score value; 451K rows too small for reliable time-series model training |
| Standard deviation | `ddof=1` (sample std) | `ddof=0` (population std) | 30-day window is a sample, not the full population — `ddof=1` gives unbiased estimate |
| Redshift credentials in COPY | IAM role (preferred) / key fallback | Hardcoded in SQL string | IAM role keeps credentials out of Redshift query history (`STL_QUERYTEXT`) |
| SQL injection prevention | `datetime.strptime()` strict format check | Parameterised queries (not supported by `redshift_connector` for DDL/COPY) | Simplest correct solution; raises `ValueError` on any non-YYYY-MM-DD input |
| Connection sharing in Streamlit | `@st.cache_resource` (local) | `config/db.get_connection()` | Streamlit's resource cache manages connection lifecycle across reruns — replacing it with a plain function would create a new connection on every rerun |
| Shared connection factory | `config/db.py` (single module) | 5 separate `get_connection()` copies | Eliminated duplication; one place to change host/port/credentials |
| Business data storage | Redshift only | Django ORM / PostgreSQL | Django is a UI layer — mixing business data into SQLite would couple the web app to the pipeline |
| Static file serving | WhiteNoise | Nginx, S3 + CDN | No infrastructure overhead; handles compression + cache-busting at the Python layer |
| Frontend dependencies | CDN only (Tailwind, Chart.js, Font Awesome) | npm / build pipeline | No build step; deploy is just `collectstatic`; acceptable for a portfolio project |
| Narrative output | Jinja2 templates | f-strings, LLM generation | Maintainable, testable, format-specific templates; deterministic output without API costs |

---

## 12. Known Limitations & Future Work

| Item | Type | Notes |
|------|------|-------|
| CD dbt step is a placeholder | Limitation | `dbt run` is commented out in `cd.yml` — transformations must be run manually when source data changes. Requires Redshift credentials as GitHub secrets and a CI-specific `profiles.yml` |
| Contact form email disabled | Limitation | `ContactView` logs submissions but `send_mail` is commented out — requires `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` env vars |
| Lambda deploy not automated | Limitation | `deploy/` scripts exist but CD pipeline does not invoke them — Lambda deploys are manual |
| No `collectstatic` verification in CI | Limitation | Static files are only collected on Render build, not validated in CI — a broken static file would only surface post-deploy |
| Streamlit dashboard not deployed | Future work | `dashboard/app.py` is fully functional locally; could be deployed to Streamlit Cloud with Redshift credentials |
| Automated dbt on data refresh | Future work | Trigger `dbt run` via Lambda or GitHub Actions when new data lands in S3, instead of manual execution |
