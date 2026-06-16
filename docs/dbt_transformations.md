# dbt Transformation Layer

The dbt layer sits between the raw Redshift tables (populated by ingestion) and the Python analytics pipeline. It cleans, joins, and pre-aggregates the data into analysis-ready tables using three layers: staging → marts → metrics.

---

## Overview

```
raw_data schema  (7 tables, 451,535 rows)
        │
        │  Layer 1: staging  (4 views)
        │  Clean types, add derived columns, translate categories
        ▼
staging.stg_orders          staging.stg_order_items
staging.stg_customers       staging.stg_products
        │
        │  Layer 2: marts  (4 tables)
        │  Dimension tables + daily fact rollup
        ▼
staging.fact_daily_metrics
staging.dim_geography       staging.dim_product       staging.dim_payment
        │
        │  Layer 3: metrics  (3 tables)
        │  Pre-aggregated daily metrics per decomposition dimension
        ▼
staging.metric_by_geography
staging.metric_by_product
staging.metric_by_payment
```

**11 models total — 4 views, 7 tables — 37 automated tests**

All models land in the `staging` schema on Redshift (configured in `~/.dbt/profiles.yml`).

---

## Project Configuration (`dbt_project.yml`)

| Setting | Value |
|---------|-------|
| Project name | `dbt_project` |
| Profile | `dbt_project` |
| Model paths | `models/` |
| Test paths | `tests/` |
| Clean targets | `target/`, `dbt_packages/` |

**Materialization defaults by directory:**

| Directory | Default Materialization |
|-----------|------------------------|
| `models/staging/` | view |
| `models/marts/` | table |
| `models/metrics/` | table |

Each model file also carries an inline `{{ config(materialized='...') }}` which takes precedence over directory defaults.

---

## Layer 1 — Staging (4 views)

Staging models are **views** — they add no storage cost and always reflect the latest raw data. Their job is to clean types, rename columns, and add derived fields. No business logic or aggregation here.

### `stg_orders`

**Source:** `raw_data.orders` (99,441 rows)

**What it does:**
- Filters out rows where `order_purchase_timestamp IS NULL` (orders with no purchase event)
- Extracts 3 date dimensions from the purchase timestamp: `order_date`, `order_year`, `order_month`, `order_day_of_week`
- Computes `delivery_days = DATEDIFF(day, order_purchase_timestamp, order_delivered_customer_date)`

**Output columns (13):**

| Column | Type | Notes |
|--------|------|-------|
| `order_id` | VARCHAR | PK — unique, not null |
| `customer_id` | VARCHAR | FK to customers — not null |
| `order_status` | VARCHAR | One of 8 valid statuses |
| `order_purchase_timestamp` | TIMESTAMP | Raw timestamp |
| `order_date` | DATE | Derived — used as the grouping key in all aggregations |
| `order_year` | INT | Derived |
| `order_month` | INT | Derived |
| `order_day_of_week` | INT | Derived (0=Sun … 6=Sat) |
| `order_approved_at` | TIMESTAMP | Nullable |
| `order_delivered_carrier_date` | TIMESTAMP | Nullable |
| `order_delivered_customer_date` | TIMESTAMP | Nullable |
| `order_estimated_delivery_date` | TIMESTAMP | |
| `delivery_days` | INT | Nullable when customer delivery date is NULL |

**Accepted order statuses (8):** `delivered`, `shipped`, `canceled`, `unavailable`, `invoiced`, `processing`, `created`, `approved`

**Tests:** unique + not_null on `order_id`, not_null on `customer_id` and `order_date`, accepted_values on `order_status` — **5 tests**

---

### `stg_order_items`

**Source:** `raw_data.order_items` (112,650 rows)

**What it does:**
- Pass-through clean with one derived column: `total_item_value = price + freight_value`
- An order can have multiple rows (multiple items) — this is intentional

**Output columns (7):**

| Column | Type | Notes |
|--------|------|-------|
| `order_id` | VARCHAR | FK to orders — not null |
| `order_item_id` | INT | Position within the order (1-based) |
| `product_id` | VARCHAR | FK to products — not null |
| `seller_id` | VARCHAR | FK to sellers |
| `price` | DECIMAL | Item price in BRL — not null |
| `freight_value` | DECIMAL | Shipping cost in BRL |
| `total_item_value` | DECIMAL | `price + freight_value` — used as revenue in all downstream models |

**Tests:** not_null on `order_id`, `product_id`, `price` — **3 tests**

---

### `stg_customers`

**Source:** `raw_data.customers` (99,441 rows)

**What it does:**
- Simple pass-through clean — no transformations. The raw schema is already clean.
- `customer_id` is the per-order customer identifier; `customer_unique_id` identifies the actual person across multiple orders.

**Output columns (5):**

| Column | Type | Notes |
|--------|------|-------|
| `customer_id` | VARCHAR | PK (per-order) — unique, not null |
| `customer_unique_id` | VARCHAR | Actual person identifier |
| `customer_city` | VARCHAR | |
| `customer_state` | VARCHAR | 2-letter Brazilian state code |
| `customer_zip_code_prefix` | VARCHAR | 5-digit zip prefix |

**Tests:** unique + not_null on `customer_id`, not_null on `customer_state` — **3 tests**

---

### `stg_products`

**Source:** `raw_data.products` (32,951 rows) LEFT JOIN `raw_data.category_translation` (71 rows)

**What it does:**
- Resolves Portuguese category names to English via LEFT JOIN on `category_translation`
- `COALESCE(english_name, portuguese_name, 'unknown')` — falls back gracefully if a category has no translation
- Drops `product_name_length` and `product_description_length` (text stats not used downstream)

**Output columns (6):**

| Column | Type | Notes |
|--------|------|-------|
| `product_id` | VARCHAR | PK — unique, not null |
| `product_category` | VARCHAR | English category name (or Portuguese fallback, or 'unknown') |
| `product_weight_g` | INT | |
| `product_length_cm` | INT | |
| `product_height_cm` | INT | |
| `product_width_cm` | INT | |

**Note:** The source CSV has typos in two column headers (`product_name_lenght`, `product_description_lenght`) — these are mapped correctly in the DDL and dropped in staging.

**Tests:** unique + not_null on `product_id` — **2 tests**

---

## Layer 2 — Marts (4 tables)

Marts are **persisted tables** — one fact table and three dimension tables that feed both the metrics layer and the anomaly detector.

### `fact_daily_metrics`

**Sources:** `stg_orders` INNER JOIN `stg_order_items`

**What it does:**
- Excludes canceled and unavailable orders (`order_status NOT IN ('canceled', 'unavailable')`)
- Aggregates to daily granularity — one row per `order_date`
- Computes 7 metrics: order count, customer count, total revenue, average/min/max order value

**Output columns (10):**

| Column | Type | Notes |
|--------|------|-------|
| `metric_date` | DATE | PK — unique, not null. Granularity: 1 day |
| `order_count` | INT | Distinct orders placed — not null |
| `customer_count` | INT | Distinct customers who ordered |
| `total_revenue` | DECIMAL(2) | Sum of `total_item_value` across all orders — not null |
| `avg_order_value` | DECIMAL(2) | Average revenue per order |
| `min_order_value` | DECIMAL(2) | Cheapest order of the day |
| `max_order_value` | DECIMAL(2) | Most expensive order of the day |
| `metric_year` | INT | Derived from `metric_date` |
| `metric_month` | INT | Derived from `metric_date` |
| `day_of_week` | INT | Derived (0=Sun … 6=Sat) |

**Data range:** September 2016 – October 2018 (~25 months, ~760 daily rows)

**Tests:** unique + not_null on `metric_date`, not_null on `order_count` and `total_revenue` — **4 tests**

---

### `dim_geography`

**Source:** `stg_customers`

**What it does:**
- `SELECT DISTINCT customer_state` — deduplicated list of all states seen in orders
- Maps each 2-letter state code to one of 5 Brazilian macro-regions via CASE

**State-to-region mapping (27 states):**

| Region | States | Count |
|--------|--------|-------|
| Southeast | SP, RJ, MG, ES | 4 |
| South | PR, SC, RS | 3 |
| Northeast | BA, SE, AL, PE, PB, RN, CE, PI, MA | 9 |
| Central-West | GO, MT, MS, DF | 4 |
| North | AM, PA, AC, RO, RR, AP, TO | 7 |
| Unknown | Any unmapped state | fallback |

**Output columns (2):**

| Column | Type | Notes |
|--------|------|-------|
| `state_code` | VARCHAR | PK — 2-letter code, unique, not null |
| `region` | VARCHAR | Macro-region — not null |

**Tests:** unique + not_null on `state_code`, not_null + accepted_values on `region` — **4 tests**

---

### `dim_product`

**Source:** `stg_products`

**What it does:**
- `SELECT DISTINCT product_category` — deduplicated list of all English category names
- Maps 73 granular categories into 7 business groups via CASE

**Category-to-group mapping:**

| Group | Sample Categories | Categories Mapped |
|-------|------------------|-------------------|
| Electronics | computers_accessories, electronics, telephony, consoles_games | 6 |
| Home & Furniture | furniture_decor, bed_bath_table, home_comfort, office_furniture | 9 |
| Fashion & Sports | sports_leisure, fashion_bags_accessories, fashion_shoes | 8 |
| Health & Beauty | health_beauty, perfumery, diapers_and_hygiene | 3 |
| Kids & Toys | toys, baby, cool_stuff | 3 |
| Auto & Tools | auto, garden_tools, construction_tools_* | 5 |
| Other | All remaining categories | ~39 |

**Output columns (2):**

| Column | Type | Notes |
|--------|------|-------|
| `product_category` | VARCHAR | PK — English category name, unique, not null |
| `product_category_group` | VARCHAR | Business group — not null |

**Tests:** unique + not_null on `product_category`, not_null on `product_category_group` — **3 tests**

---

### `dim_payment`

**Source:** `raw_data.payments` (direct source — no staging model for payments)

**What it does:**
- `SELECT DISTINCT payment_type` — 4 payment codes found in the dataset
- Maps each code to a display label

**Payment type mapping:**

| `payment_type` (code) | `payment_type_display` |
|-----------------------|------------------------|
| `credit_card` | Credit Card |
| `boleto` | Boleto |
| `voucher` | Voucher |
| `debit_card` | Debit Card |
| anything else | Other |

**Output columns (2):**

| Column | Type | Notes |
|--------|------|-------|
| `payment_type` | VARCHAR | PK — unique, not null |
| `payment_type_display` | VARCHAR | Human-readable label |

**Tests:** unique + not_null on `payment_type` — **2 tests**

---

## Layer 3 — Metrics (3 tables)

These tables are the **direct input to the Python decomposition engine**. Each produces daily revenue totals sliced by one dimension, feeding the contribution analysis that identifies root causes.

All three models exclude canceled and unavailable orders. All aggregate to `(metric_date, segment)` granularity.

---

### `metric_by_geography`

**Joins:** `stg_orders` → `stg_order_items` → `stg_customers` → `dim_geography`

**Output columns (6):**

| Column | Type | Notes |
|--------|------|-------|
| `metric_date` | DATE | not null |
| `state_code` | VARCHAR | 2-letter state — not null |
| `region` | VARCHAR | Macro-region |
| `order_count` | INT | Distinct orders |
| `total_revenue` | DECIMAL(2) | Sum of item revenue — not null |
| `avg_item_value` | DECIMAL(2) | Average per line item |

**Decomposer uses:** `segment_col = 'region'`, `detail_col = 'state_code'`

**Tests:** not_null on `metric_date`, `state_code`, `total_revenue` — **3 tests**

---

### `metric_by_product`

**Joins:** `stg_orders` → `stg_order_items` → `stg_products` → `dim_product`

**Output columns (6):**

| Column | Type | Notes |
|--------|------|-------|
| `metric_date` | DATE | not null |
| `product_category` | VARCHAR | Granular English category — not null |
| `product_category_group` | VARCHAR | Business group |
| `order_count` | INT | Distinct orders |
| `total_revenue` | DECIMAL(2) | Sum of item revenue — not null |
| `avg_item_value` | DECIMAL(2) | Average per line item |

**Decomposer uses:** `segment_col = 'product_category_group'`, `detail_col = 'product_category'`

**Tests:** not_null on `metric_date`, `product_category`, `total_revenue` — **3 tests**

---

### `metric_by_payment`

**Joins:** `stg_orders` → `stg_order_items` (aggregated to order level) → `raw_data.payments` (primary payment only) → `dim_payment`

**Output columns (6):**

| Column | Type | Notes |
|--------|------|-------|
| `metric_date` | DATE | not null |
| `payment_type` | VARCHAR | Primary payment code — not null |
| `payment_type_display` | VARCHAR | Human-readable label |
| `order_count` | INT | Distinct orders |
| `total_revenue` | DECIMAL(2) | Sum of order revenue — not null |
| `avg_order_value` | DECIMAL(2) | Average per order |

**Decomposer uses:** `segment_col = 'payment_type_display'`, `detail_col = 'payment_type'`

**Tests:** not_null on `metric_date`, `payment_type`, `total_revenue` — **3 tests**

**Implementation note:** Orders in the Olist dataset can have multiple payment records (e.g., split between credit card and voucher). This model uses `payment_sequential = 1` to assign each order to a single primary payment type, preventing revenue from being counted multiple times.

---

## Automated Tests (37 total)

### Schema tests (35)

| Model | Test | Column |
|-------|------|--------|
| `stg_orders` | unique | `order_id` |
| `stg_orders` | not_null | `order_id` |
| `stg_orders` | not_null | `customer_id` |
| `stg_orders` | not_null | `order_date` |
| `stg_orders` | accepted_values (8) | `order_status` |
| `stg_order_items` | not_null | `order_id` |
| `stg_order_items` | not_null | `product_id` |
| `stg_order_items` | not_null | `price` |
| `stg_customers` | unique | `customer_id` |
| `stg_customers` | not_null | `customer_id` |
| `stg_customers` | not_null | `customer_state` |
| `stg_products` | unique | `product_id` |
| `stg_products` | not_null | `product_id` |
| `fact_daily_metrics` | unique | `metric_date` |
| `fact_daily_metrics` | not_null | `metric_date` |
| `fact_daily_metrics` | not_null | `order_count` |
| `fact_daily_metrics` | not_null | `total_revenue` |
| `dim_geography` | unique | `state_code` |
| `dim_geography` | not_null | `state_code` |
| `dim_geography` | not_null | `region` |
| `dim_geography` | accepted_values (6) | `region` |
| `dim_product` | unique | `product_category` |
| `dim_product` | not_null | `product_category` |
| `dim_product` | not_null | `product_category_group` |
| `dim_payment` | unique | `payment_type` |
| `dim_payment` | not_null | `payment_type` |
| `metric_by_geography` | not_null | `metric_date` |
| `metric_by_geography` | not_null | `state_code` |
| `metric_by_geography` | not_null | `total_revenue` |
| `metric_by_product` | not_null | `metric_date` |
| `metric_by_product` | not_null | `product_category` |
| `metric_by_product` | not_null | `total_revenue` |
| `metric_by_payment` | not_null | `metric_date` |
| `metric_by_payment` | not_null | `payment_type` |
| `metric_by_payment` | not_null | `total_revenue` |

### Singular tests (2)

| Test file | What it checks | Severity |
|-----------|---------------|----------|
| `tests/assert_revenue_positive.sql` | No rows in `fact_daily_metrics` where `total_revenue < 0` | ERROR |
| `tests/assert_dates_continuous.sql` | No gaps > 30 days between consecutive dates in `fact_daily_metrics` | WARN |

### Run tests

```bash
cd dbt_project
dbt test                          # all 37 tests
dbt test --select staging         # staging layer only (13 tests)
dbt test --select marts           # marts layer only (13 tests)
dbt test --select metrics         # metrics layer only (9 tests)
```

---

## Running dbt

```bash
cd dbt_project

# Install dependencies (first time)
dbt deps

# Verify connection
dbt debug

# Build all 11 models
dbt run

# Run all 37 tests
dbt test

# Build and test in one command
dbt build

# Build a single layer
dbt run --select staging
dbt run --select marts
dbt run --select metrics

# Build a single model
dbt run --select fact_daily_metrics
```

**Expected `dbt run` output:**
```
Running with dbt=1.7.x
Found 11 models, 37 tests
...
Completed successfully
Done. PASS=11 WARN=0 ERROR=0 SKIP=0 TOTAL=11
```

**Expected `dbt test` output:**
```
Finished running 35 tests, 2 singular tests
Done. PASS=37 WARN=0 ERROR=0 SKIP=0 TOTAL=37
```

**Estimated run time:** ~30 seconds for a full `dbt run` on Redshift Serverless (8 RPU).

---

## Model Dependency Graph

```
raw_data.orders ──────────────────────────────┐
raw_data.order_items ──────────────────────────┤
raw_data.customers ────────────────────────────┤
raw_data.products ─────────────────────────────┤
raw_data.category_translation ─────────────────┤
raw_data.payments ─────────────────────────────┤
                                               ▼
                        ┌──────────────────────────────┐
                        │      STAGING LAYER           │
                        │  stg_orders                  │
                        │  stg_order_items             │
                        │  stg_customers               │
                        │  stg_products                │
                        └──────────────┬───────────────┘
                                       │
               ┌───────────────────────┼─────────────────────────┐
               ▼                       ▼                         ▼
     ┌──────────────────┐   ┌──────────────────────┐   ┌──────────────────┐
     │   MARTS LAYER    │   │   MARTS LAYER        │   │   MARTS LAYER    │
     │ fact_daily_      │   │ dim_geography        │   │ dim_product      │
     │ metrics          │   │ dim_payment          │   │                  │
     └──────────────────┘   └──────────┬───────────┘   └────────┬─────────┘
                                       │                        │
               ┌───────────────────────┼────────────────────────┤
               ▼                       ▼                        ▼
     ┌──────────────────────────────────────────────────────────────────┐
     │                       METRICS LAYER                              │
     │   metric_by_geography   metric_by_product   metric_by_payment    │
     └──────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                            Python Analytics Pipeline
                    (detection → decomposition → narrative)
```

---

## Issues Fixed

| Issue | File | Change |
|-------|------|--------|
| Stale `example` model config for non-existent directory | `dbt_project.yml` | Replaced with proper `staging/marts/metrics` directory defaults |
| `state_name` column was a copy of `state_code` (never used downstream) | `dim_geography.sql` | Removed redundant column |
| Double-count bug: items (N) × payments (M) rows per order inflated revenue | `metric_by_payment.sql` | Pre-aggregate order revenue before joining; use `payment_sequential=1` for primary payment |

---

## Missing Model (Future Work)

`dim_payment` and `metric_by_payment` both read directly from `raw_data.payments` with no staging model. A `stg_payments` model would be consistent with the staging pattern used for orders, items, customers, and products. It could also handle edge cases like null payment types and normalize installment data.
