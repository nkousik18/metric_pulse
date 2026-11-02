# `dbt_project/`

> **Local stack (2026-11-02).** The AWS resources this was built on were deleted when the free tier ended. All AWS code is **kept, unchanged and switchable** (`docs/local-stack-scope.md`, rule R1). This project now runs on **DuckDB** (`dbt-duckdb`, target `local`, the default), and the original **Redshift** target is kept as `redshift`. Both are defined in the committed `dbt_project/profiles.yml`.

A standard dbt project (originally `dbt-redshift`) that transforms the 7 raw tables loaded by `ingestion/` into analysis-ready tables for the Python detection/decomposition pipeline. Three layers — **staging → marts → metrics** — 11 models total, 37 automated tests. Everything materializes into the single `staging` schema on Redshift (see `dbt_project.yml`; there is no separate `marts` schema despite the folder name — `config/settings.py`'s `REDSHIFT_SCHEMA_MARTS` constant is unused/dead for this reason).

> Note: this file was previously a stale top-level project overview (project-status checklist from an early milestone, wrong table counts, no mention of the metrics layer). It's been replaced with a folder-specific reference; see the root `README.md` and `docs/` for the whole-project story.

## Layout

```
dbt_project/
├── dbt_project.yml          # project config — materialization defaults per directory
├── models/
│   ├── staging/              4 views  — clean/cast raw_data, no joins
│   │   ├── stg_orders.sql
│   │   ├── stg_order_items.sql
│   │   ├── stg_customers.sql
│   │   ├── stg_products.sql
│   │   └── schema.yml         source defs + column tests
│   ├── marts/                 4 tables — dimensions + daily fact
│   │   ├── fact_daily_metrics.sql
│   │   ├── dim_geography.sql
│   │   ├── dim_product.sql
│   │   ├── dim_payment.sql
│   │   └── schema.yml
│   └── metrics/                3 tables — daily revenue by dimension (decomposer input)
│       ├── metric_by_geography.sql
│       ├── metric_by_product.sql
│       ├── metric_by_payment.sql
│       └── schema.yml
├── tests/                     2 singular (non-schema) tests
│   ├── assert_revenue_positive.sql
│   └── assert_dates_continuous.sql
├── analyses/, macros/, seeds/, snapshots/   # all empty (.gitkeep only) — unused
```

## Model reference

### Staging (views, no aggregation)

| Model | Source | What it does |
|-------|--------|---------------|
| `stg_orders` | `raw_data.orders` | Filters `order_purchase_timestamp IS NOT NULL`; derives `order_date`, `order_year`, `order_month`, `order_day_of_week`, `delivery_days` |
| `stg_order_items` | `raw_data.order_items` | Adds `total_item_value = price + freight_value` |
| `stg_customers` | `raw_data.customers` | Pass-through, no transform |
| `stg_products` | `raw_data.products` LEFT JOIN `raw_data.category_translation` | `COALESCE(english_name, portuguese_name, 'unknown')` for `product_category` |

### Marts (tables)

| Model | Grain | What it does |
|-------|-------|---------------|
| `fact_daily_metrics` | 1 row/day | Joins `stg_orders` + `stg_order_items`, excludes `canceled`/`unavailable`, aggregates `order_count`, `customer_count`, `total_revenue`, `avg/min/max_order_value` |
| `dim_geography` | 1 row/state (27) | `DISTINCT customer_state` from `stg_customers` → `CASE` maps to 5 regions + `Unknown` fallback |
| `dim_product` | 1 row/category | `DISTINCT product_category` from `stg_products` → `CASE` maps to 7 groups (`Other` catch-all) |
| `dim_payment` | 1 row/payment type | `DISTINCT payment_type` straight from `raw_data.payments` (no staging model — see gotcha below) → display-label `CASE` |

### Metrics (tables — decomposer input)

All three exclude `canceled`/`unavailable` orders and grain to `(metric_date, segment)`.

| Model | Joins | `segment_col` used by `decomposition/decomposer.py` |
|-------|-------|------------------------------------------------------|
| `metric_by_geography` | `stg_orders` → `stg_order_items` → `stg_customers` → `dim_geography` | `region` (detail: `state_code`) |
| `metric_by_product` | `stg_orders` → `stg_order_items` → `stg_products` → `dim_product` | `product_category_group` (detail: `product_category`) |
| `metric_by_payment` | `stg_order_items` (pre-aggregated per order) → `raw_data.payments` (`payment_sequential=1` only) → `dim_payment` | `payment_type_display` (detail: `payment_type`) |

`metric_by_payment` pre-aggregates order revenue in a CTE *before* joining payments — this avoids the N(items) × M(payments) row-multiplication bug that previously double-counted revenue for orders with multiple payment records (split credit-card/voucher payments, common in the Olist dataset).

## Tests — 37 total (35 schema + 2 singular)

| Layer | Schema tests | Models covered |
|-------|-------------|-----------------|
| staging | 13 | `stg_orders` (5: unique+not_null `order_id`, not_null `customer_id`/`order_date`, accepted_values `order_status` — 8 values), `stg_order_items` (3: not_null `order_id`/`product_id`/`price`), `stg_customers` (3: unique+not_null `customer_id`, not_null `customer_state`), `stg_products` (2: unique+not_null `product_id`) |
| marts | 13 | `fact_daily_metrics` (4), `dim_geography` (4: unique+not_null `state_code`, not_null+accepted_values `region` — 6 values incl. `Unknown`), `dim_product` (3), `dim_payment` (2) |
| metrics | 9 | `metric_by_geography` (3), `metric_by_product` (3), `metric_by_payment` (3) — all not_null on `metric_date`/segment key/`total_revenue` |
| singular | 2 | `assert_revenue_positive.sql` (ERROR if any `fact_daily_metrics.total_revenue < 0`), `assert_dates_continuous.sql` (WARN if any gap > 30 days between consecutive `metric_date`s) |

Verified directly against `models/*/schema.yml` and `tests/*.sql` — this matches `docs/dbt_transformations.md`; an earlier version of `docs/resume_project_doc.md` stated 5 marts / 2 metrics tables and was wrong (fixed as part of this documentation pass).

## Running

**Always pass `--profiles-dir .`** so the committed `profiles.yml` is used, not a personal `~/.dbt/profiles.yml`:

```bash
cd dbt_project
dbt debug --target local --profiles-dir .
dbt build --target local --profiles-dir .     # active: 11 models + 37 tests, under 1s on DuckDB
dbt build --target redshift --profiles-dir .  # archived: needs REDSHIFT_* env vars and a live workgroup
```

Verified 2026-11-02 on the full Olist data: `PASS=47 WARN=1 ERROR=0`, which is all 11 models and 37 tests. The one warning is `assert_dates_continuous` (severity `warn` by design). It flags a real 74-day gap in Olist, from 2016-10-10 to 2016-12-23, when the dataset has no orders at all. It isn't a porting artifact.

**CI runs the same build** in the `dbt-build-local` job (`.github/workflows/ci.yml`), on the committed sample `data/fixtures/olist_sample/` (orders from 2018-08-01), where the result is `PASS=48 WARN=0 ERROR=0`: the 2016 gap is outside the sample. This is the real dbt gate; a broken model or failing test fails it. The older `dbt-check` job (`dbt parse … || echo`) can't fail and is kept unchanged as archived. To reproduce CI locally:

```bash
python -m ingestion.load_local --raw-dir data/fixtures/olist_sample --warehouse-path /tmp/sample.duckdb
cd dbt_project && WAREHOUSE_PATH=/tmp/sample.duckdb dbt build --target local --profiles-dir .
```

### Portable SQL (changed 2026-11-02)

Three Redshift-only constructs failed on DuckDB with Binder Errors. Each was rewritten to a form that is valid on **both** adapters, so the archived Redshift target still works:

| File | Was (Redshift-only) | Now (portable) |
|---|---|---|
| `models/staging/stg_orders.sql` | `DATE_PART(year\|month\|dow, x)`, `DATEDIFF(day, a, b)` | `EXTRACT(year\|month\|dow FROM x)`, `{{ dbt.datediff('a', 'b', 'day') }}` |
| `models/marts/fact_daily_metrics.sql` | `DATE_PART(year\|month\|dow, x)` | `EXTRACT(… FROM x)` |
| `tests/assert_dates_continuous.sql` | `DATEDIFF(day, …)` | `{{ dbt.datediff(…) }}` |
| `models/staging/schema.yml` (source) | `database: dev` | `database: "{{ target.database }}"` (`dev` on Redshift, `warehouse` on DuckDB) |

One known type difference: `EXTRACT` returns an integer (`BIGINT` on DuckDB) where Redshift's `DATE_PART` returned a double. It affects only `order_year`, `order_month`, `order_day_of_week`, `metric_year`, `metric_month` and `day_of_week`, and no Python code does arithmetic on those columns.

### Archived Redshift commands (original)

```bash
cd dbt_project
dbt deps        # first time only — no packages currently declared, effectively a no-op
dbt debug        # verify ~/.dbt/profiles.yml connection
dbt run          # build all 11 models (~30s on 8 RPU Redshift Serverless)
dbt test         # run all 37 tests
dbt build        # run + test in one pass

dbt run --select staging   # single layer
dbt run --select marts
dbt run --select metrics
dbt run --select fact_daily_metrics   # single model
```

`dbt_project.yml`'s `profile: 'dbt_project'` must match a `dbt_project:` block in `~/.dbt/profiles.yml` — see `docs/setup.md` Step 7 for the exact YAML.

## Upstream / downstream

- **Upstream:** `raw_data.*` tables, populated by `ingestion/` (must run at least once before `dbt run`).
- **Downstream:** `detection/anomaly_detector.py` reads `staging.fact_daily_metrics`; `decomposition/decomposer.py` reads `staging.metric_by_{geography,product,payment}`; the Streamlit dashboard (`dashboard/app.py`) also queries `staging.fact_daily_metrics` and the three `metric_by_*` tables directly.

## Gotchas

- **No `stg_payments` model.** `dim_payment` and `metric_by_payment` both read `raw_data.payments` directly — the only place in the metrics layer that skips the staging layer. Flagged in `docs/dbt_transformations.md` as future work; if you add one, keep the `payment_sequential = 1` filtering logic somewhere reachable by both downstream models.
- **Everything lands in `staging` schema**, including marts and metrics tables — the directory name `marts/`/`metrics/` is a dbt project-organization convention only, not a Redshift schema. Don't go looking for a `marts.dim_geography` table; query `staging.dim_geography`.
- **`Unknown` region / `Other` product group / `Other` payment display** are real fallback values that appear in `dim_geography`/`dim_product`/`dim_payment` for any code not explicitly matched in the `CASE` statements — don't treat their appearance in query results as a bug.
- `analyses/`, `macros/`, `seeds/`, `snapshots/` are present but empty (`.gitkeep` only) — this project doesn't use any of those dbt features yet.
