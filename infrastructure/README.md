# `infrastructure/`

Raw SQL DDL for the Redshift `raw_data` schema, plus a placeholder for IAM policy documents. This is the only folder in the repo that isn't Python — it's consumed by `ingestion/setup_redshift_tables.py`, not imported.

## Files

| File | Purpose |
|------|---------|
| `redshift_setup.sql` | 7 `CREATE TABLE IF NOT EXISTS` statements for the `raw_data` schema. |
| `iam_policies.json` | **Empty file (0 bytes).** No IAM policy JSON is actually version-controlled here — IAM permissions are set up manually via the AWS console per `docs/setup.md` (attach `AmazonS3FullAccess`, `AmazonRedshiftFullAccess`, `AmazonSNSFullAccess`, `AWSLambda_FullAccess`, `AmazonEC2ContainerRegistryFullAccess` to a `metric-pulse-dev` IAM user). |

## Tables defined (`redshift_setup.sql`)

All columns are permissive types (`VARCHAR`, `DECIMAL(10,2)`, `INTEGER`, `TIMESTAMP`) so that Redshift's `COPY` never rejects a row on type mismatch — real type enforcement happens later in the dbt staging layer.

| Table | Columns |
|-------|---------|
| `raw_data.orders` | `order_id`, `customer_id`, `order_status`, `order_purchase_timestamp`, `order_approved_at`, `order_delivered_carrier_date`, `order_delivered_customer_date`, `order_estimated_delivery_date` |
| `raw_data.order_items` | `order_id`, `order_item_id`, `product_id`, `seller_id`, `shipping_limit_date`, `price`, `freight_value` |
| `raw_data.customers` | `customer_id`, `customer_unique_id`, `customer_zip_code_prefix`, `customer_city`, `customer_state` |
| `raw_data.products` | `product_id`, `product_category_name`, `product_name_length`, `product_description_length`, `product_photos_qty`, `product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm` |
| `raw_data.sellers` | `seller_id`, `seller_zip_code_prefix`, `seller_city`, `seller_state` |
| `raw_data.payments` | `order_id`, `payment_sequential`, `payment_type`, `payment_installments`, `payment_value` |
| `raw_data.category_translation` | `product_category_name`, `product_category_name_english` |

Note: the source CSV headers have typos (`product_name_lenght`, `product_description_lenght`) — this DDL uses the *correct* spelling for the Redshift column names; `s3_to_redshift.py`'s `COPY ... IGNOREHEADER 1` matches columns positionally, not by header name, so the CSV typo doesn't matter at load time.

## Running

Not run directly — executed by `ingestion/setup_redshift_tables.py`, which reads this file, splits on `;`, and executes each statement individually (commit-per-statement, rollback-per-statement-on-failure):

```bash
python -m ingestion.setup_redshift_tables
```

Safe to rerun — every statement is `CREATE TABLE IF NOT EXISTS`.

## Upstream / downstream

- **Upstream:** none — this is source-of-truth DDL, hand-written.
- **Downstream:** `ingestion/s3_to_redshift.py` loads data into these exact tables; every dbt staging model (`dbt_project/models/staging/*.sql`) sources from these tables via `{{ source('raw_data', '<table>') }}`.

## Gotchas

- Adding a new source table requires editing **three** places in sync: this file (DDL), `ingestion/s3_to_redshift.py`'s `FILE_TABLE_MAPPING`, and `dbt_project/models/staging/schema.yml`'s `sources:` block — none of them are generated from each other.
- `iam_policies.json` looks like it should document the IAM policy but is empty; don't assume it reflects actual production permissions. If you need the real policy, check the AWS console directly or `docs/setup.md` for the policy names attached.
