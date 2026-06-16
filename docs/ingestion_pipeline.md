# Ingestion Pipeline

The ingestion pipeline is a one-time (or on-demand) process that moves the raw Brazilian E-Commerce CSV files from local disk into Redshift. It runs in three sequential steps and must be completed before any dbt transformation can run.

---

## Pipeline at a Glance

```
Local disk  (data/raw/  — 9 CSV files, 120 MB total)
        │
        │  Step 1: ingestion/upload_to_s3.py
        │  Uploads 7 of 9 CSVs  →  s3://<bucket>/raw/
        ▼
AWS S3  (raw/ prefix — 7 files, ~48 MB)
        │
        │  Step 2: ingestion/setup_redshift_tables.py   ← run once
        │  Executes infrastructure/redshift_setup.sql
        ▼
Redshift  raw_data schema  (7 empty tables, 40 columns)
        │
        │  Step 3: ingestion/s3_to_redshift.py
        │  COPY each CSV — 451,535 rows total
        ▼
Redshift  raw_data schema  (fully loaded, ready for dbt)
```

**Total ingestion time:** ~2 minutes (dominated by Redshift COPY throughput)

---

## Source Data

The dataset is the [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), covering 100K orders placed between 2016–2018.

### All files in `data/raw/`

| File | Size | Rows | Ingested |
|------|------|------|----------|
| `olist_orders_dataset.csv` | 17 MB | 99,441 | Yes |
| `olist_order_items_dataset.csv` | 15 MB | 112,650 | Yes |
| `olist_order_payments_dataset.csv` | 5.5 MB | 103,886 | Yes |
| `olist_order_reviews_dataset.csv` | 14 MB | 104,719 | **No** |
| `olist_customers_dataset.csv` | 8.6 MB | 99,441 | Yes |
| `olist_products_dataset.csv` | 2.3 MB | 32,951 | Yes |
| `olist_sellers_dataset.csv` | 171 KB | 3,095 | Yes |
| `olist_geolocation_dataset.csv` | 58 MB | 1,000,163 | **No** |
| `product_category_name_translation.csv` | 2.6 KB | 71 | Yes |
| **Total on disk** | **120 MB** | **1,556,417** | |
| **Total ingested** | **~48 MB** | **451,535** | **7 / 9** |

> `olist_geolocation_dataset.csv` (58 MB, 1M rows) and `olist_order_reviews_dataset.csv` (14 MB, 104K rows) are present in `data/raw/` but are not mapped to any Redshift table. They are not used in the current analytics pipeline.

---

## Step 1 — Upload to S3 (`ingestion/upload_to_s3.py`)

Scans `data/raw/` for all `.csv` files and uploads each to `s3://<S3_BUCKET_NAME>/raw/<filename>` using `boto3`.

### What it does

1. Reads `S3_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` from environment.
2. Scans `data/raw/` for `*.csv` files (currently finds 9).
3. Uploads each file with the `raw/` prefix. Logs file name and size (MB) before each upload.
4. Returns `{"success": [...], "failed": [...]}` — a file failure is logged but does not stop the rest.
5. Runs a verification pass (`list_objects_v2` with `Prefix="raw/"`) to confirm all objects landed.

### Key functions

| Function | Purpose |
|----------|---------|
| `get_s3_client()` | Creates boto3 S3 client from env credentials |
| `upload_file(client, path, bucket, key)` | Uploads a single file; returns `True/False` |
| `upload_raw_data(data_dir)` | Iterates all CSVs, calls `upload_file` for each |
| `verify_uploads()` | Lists `raw/` prefix and logs every object key |

### Run

```bash
python -m ingestion.upload_to_s3
```

### Expected output

```
UPLOAD SUMMARY
==================================================
Successful: 9
  ✓ olist_customers_dataset.csv
  ✓ olist_geolocation_dataset.csv
  ✓ olist_order_items_dataset.csv
  ✓ olist_order_payments_dataset.csv
  ✓ olist_order_reviews_dataset.csv
  ✓ olist_orders_dataset.csv
  ✓ olist_products_dataset.csv
  ✓ olist_sellers_dataset.csv
  ✓ product_category_name_translation.csv

Verifying uploads...
```

---

## Step 2 — Create Redshift Tables (`ingestion/setup_redshift_tables.py`)

Executes `infrastructure/redshift_setup.sql` against Redshift to create the `raw_data` schema tables. Only needs to run once — all DDL uses `CREATE TABLE IF NOT EXISTS`.

### What it does

1. Reads `infrastructure/redshift_setup.sql` from disk.
2. Splits the file on `;` to get individual statements, skipping comment-only blocks.
3. Executes each of the 7 `CREATE TABLE` statements individually — commits on success, rolls back on failure, so one bad statement does not block the others.
4. Calls `verify_tables()` after setup, querying `pg_tables` for schema `raw_data` to confirm all 7 tables exist.

### Tables created in `raw_data` schema

| Table | Columns | Description |
|-------|---------|-------------|
| `orders` | 8 | Order lifecycle — purchase, approval, delivery timestamps |
| `order_items` | 7 | Line items — product, seller, price, freight per order |
| `customers` | 5 | Customer location — city, state, zip code |
| `products` | 9 | Product catalog — category, name length, dimensions, weight |
| `sellers` | 4 | Seller location — city, state, zip code |
| `payments` | 5 | Payment transactions — type, installments, value |
| `category_translation` | 2 | Portuguese → English product category names |
| **Total** | **40** | |

### Column detail by table

**`raw_data.orders`** (8 cols)
`order_id`, `customer_id`, `order_status`, `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date`

**`raw_data.order_items`** (7 cols)
`order_id`, `order_item_id`, `product_id`, `seller_id`, `shipping_limit_date`, `price`, `freight_value`

**`raw_data.customers`** (5 cols)
`customer_id`, `customer_unique_id`, `customer_zip_code_prefix`, `customer_city`, `customer_state`

**`raw_data.products`** (9 cols)
`product_id`, `product_category_name`, `product_name_length`, `product_description_length`, `product_photos_qty`, `product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm`

**`raw_data.sellers`** (4 cols)
`seller_id`, `seller_zip_code_prefix`, `seller_city`, `seller_state`

**`raw_data.payments`** (5 cols)
`order_id`, `payment_sequential`, `payment_type`, `payment_installments`, `payment_value`

**`raw_data.category_translation`** (2 cols)
`product_category_name`, `product_category_name_english`

### Run

```bash
python -m ingestion.setup_redshift_tables
```

### Expected output

```
SETUP SUMMARY
==================================================
Statements executed: 7
Errors: 0

Tables created: 7
  ✓ raw_data.category_translation
  ✓ raw_data.customers
  ✓ raw_data.order_items
  ✓ raw_data.orders
  ✓ raw_data.payments
  ✓ raw_data.products
  ✓ raw_data.sellers
```

---

## Step 3 — Load S3 to Redshift (`ingestion/s3_to_redshift.py`)

Issues Redshift `COPY` commands to bulk-load each of the 7 CSVs from S3 into the corresponding `raw_data` table.

### What it does

1. Resolves auth credentials via `build_copy_credentials()` (see [credentials section](#credentials) below).
2. For each of the 7 file-to-table mappings: **TRUNCATE** then **COPY**.
3. Commits after each successful table load. If any load fails, rolls back that table only.
4. Queries `COUNT(*)` on each table immediately after COPY to confirm row count.
5. Runs a final `verify_loads()` pass — opens a fresh connection and re-queries all counts — to cross-check in-run numbers against post-commit state.

### File-to-table mapping and row counts

| S3 File | Redshift Table | Rows | File Size |
|---------|----------------|------|-----------|
| `olist_orders_dataset.csv` | `raw_data.orders` | 99,441 | 17 MB |
| `olist_order_items_dataset.csv` | `raw_data.order_items` | 112,650 | 15 MB |
| `olist_order_payments_dataset.csv` | `raw_data.payments` | 103,886 | 5.5 MB |
| `olist_customers_dataset.csv` | `raw_data.customers` | 99,441 | 8.6 MB |
| `olist_products_dataset.csv` | `raw_data.products` | 32,951 | 2.3 MB |
| `olist_sellers_dataset.csv` | `raw_data.sellers` | 3,095 | 171 KB |
| `product_category_name_translation.csv` | `raw_data.category_translation` | 71 | 2.6 KB |
| **Total** | | **451,535** | **~48 MB** |

### COPY command options

| Option | Effect |
|--------|--------|
| `CSV IGNOREHEADER 1` | Skips the header row present in all 7 files |
| `DATEFORMAT 'auto'` | Handles mixed timestamp formats in the source data |
| `TIMEFORMAT 'auto'` | Same — avoids parse failures on `order_*_timestamp` columns |
| `TRUNCATECOLUMNS` | Silently trims values exceeding column width instead of erroring |
| `BLANKSASNULL` | Stores blank/whitespace-only strings as NULL |
| `EMPTYASNULL` | Stores zero-length strings as NULL |

### Credentials

Credential injection is handled by `config/db.build_copy_credentials()`, which checks for `REDSHIFT_IAM_ROLE` first:

```
REDSHIFT_IAM_ROLE set?
    Yes → IAM_ROLE '<arn>'            ← credentials never appear in query text
    No  → ACCESS_KEY_ID / SECRET_ACCESS_KEY from env vars
```

**Preferred:** attach an IAM role to the Redshift workgroup and set `REDSHIFT_IAM_ROLE=<arn>` in `.env`. This keeps credentials out of Redshift's `STL_QUERYTEXT` query history.

### Key functions

| Function | Purpose |
|----------|---------|
| `truncate_table(cursor, table)` | Clears existing rows before each load (idempotent reruns) |
| `load_table(cursor, file, table)` | Builds and executes COPY; returns row count |
| `load_all_tables()` | Iterates `FILE_TABLE_MAPPING`, commit per table |
| `verify_loads()` | Re-queries COUNT(*) on all tables post-commit |

### Run

```bash
python -m ingestion.s3_to_redshift
```

### Expected output

```
LOAD SUMMARY
==================================================
  raw_data.orders: 99,441 rows
  raw_data.order_items: 112,650 rows
  raw_data.customers: 99,441 rows
  raw_data.products: 32,951 rows
  raw_data.sellers: 3,095 rows
  raw_data.payments: 103,886 rows
  raw_data.category_translation: 71 rows

Total rows loaded: 451,535
✓ All tables verified successfully
```

---

## Supporting Modules

### `infrastructure/redshift_setup.sql`

7 `CREATE TABLE IF NOT EXISTS` statements — one per `raw_data` table. All column types are kept permissive (VARCHAR, DECIMAL, INTEGER, TIMESTAMP) to avoid COPY rejections on malformed source data. Type enforcement and casting happens downstream in the dbt staging layer.

### `config/db.py`

Shared connection factory used by both ingestion scripts:

| Function | Purpose |
|----------|---------|
| `get_connection()` | Returns a `redshift_connector.Connection` from env vars |
| `build_copy_credentials()` | Returns the credential clause for COPY — IAM role preferred, key-based fallback |

### `config/settings.py`

Centralised config module that reads all environment variables at import time. Defines `REDSHIFT_SCHEMA_RAW = "raw_data"`, `S3_RAW_PREFIX = "raw/"`, and threshold defaults for detection.

### `config/logging_config.py`

Shared logger factory. Each module calls `setup_logger(__name__)` to get a configured logger:

| Sink | Level | Format |
|------|-------|--------|
| Console (stdout) | INFO and above | `timestamp \| level \| module \| message` |
| File (`logs/metric_pulse_YYYYMMDD.log`) | DEBUG and above | Includes `funcName:lineno` |

Log files rotate daily by date. Multiple calls to `setup_logger` with the same name are safe — duplicate handlers are prevented.

---

## Running the Full Ingestion

```bash
# Activate environment
source metric_venv/bin/activate

# Step 1 — upload all CSVs to S3
python -m ingestion.upload_to_s3

# Step 2 — create raw_data tables (first time only)
python -m ingestion.setup_redshift_tables

# Step 3 — load 451,535 rows into Redshift
python -m ingestion.s3_to_redshift
```

After Step 3 completes, run `cd dbt_project && dbt run` to build the staging and marts layers on top.

---

## Performance

| Operation | Duration | Notes |
|-----------|----------|-------|
| S3 upload (7 files, ~48 MB) | ~30 sec | Depends on upload bandwidth |
| Redshift table creation (7 DDL) | ~5 sec | `CREATE TABLE IF NOT EXISTS` |
| S3 → Redshift COPY (451K rows) | ~90 sec | Parallel COPY via Redshift Serverless |
| Full ingestion end-to-end | **~2 min** | |

---

## Data Quality Notes

| Table | Known Issues in Source Data |
|-------|---------------------------|
| `products` | Column headers have typos in the CSV: `product_name_lenght`, `product_description_lenght` (missing 'h') — mapped correctly in DDL |
| `category_translation` | File has a UTF-8 BOM (`﻿`) at the start — handled transparently by Redshift COPY |
| `orders` | Some `order_approved_at` and delivery timestamps are NULL (orders that were never approved or delivered) |
| `order_items` | `freight_value` can be 0.00 for certain seller promotions |

---

## Files Not Ingested

Two files in `data/raw/` have no corresponding table in the DDL and are not in `FILE_TABLE_MAPPING`:

| File | Size | Rows | Reason not ingested |
|------|------|------|---------------------|
| `olist_geolocation_dataset.csv` | 58 MB | 1,000,163 | Not used in current analytics models |
| `olist_order_reviews_dataset.csv` | 14 MB | 104,719 | Not used in current analytics models |

These files can be added to the pipeline in the future by:
1. Adding `CREATE TABLE` DDL to `infrastructure/redshift_setup.sql`
2. Adding the mapping entry to `FILE_TABLE_MAPPING` in `ingestion/s3_to_redshift.py`
