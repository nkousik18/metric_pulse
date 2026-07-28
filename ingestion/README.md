# `ingestion/`

One-time (or on-demand) scripts that move the raw Olist CSVs from local disk into Redshift so dbt has something to build on. Three scripts run in a strict order: **S3 upload → table DDL → COPY load**. Nothing here is imported by the analytics pipeline at runtime — this folder is only ever invoked manually or as a setup step.

## Files

| File | Purpose |
|------|---------|
| `upload_to_s3.py` | Scans `data/raw/*.csv` and uploads every file found to `s3://$S3_BUCKET_NAME/raw/<filename>`. |
| `setup_redshift_tables.py` | Executes `infrastructure/redshift_setup.sql` against Redshift to create the 7 `raw_data.*` tables (`CREATE TABLE IF NOT EXISTS`, safe to rerun). |
| `s3_to_redshift.py` | `TRUNCATE` + `COPY` for each of the 7 tables, reading CSVs straight from S3. |

## Key functions

**`upload_to_s3.py`**
- `get_s3_client()` — boto3 S3 client from `AWS_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
- `upload_file(client, path, bucket, key) -> bool` — single-file upload; catches `ClientError` and `FileNotFoundError`, returns `False` instead of raising, so one bad file doesn't abort the batch.
- `upload_raw_data(data_dir="data/raw") -> dict` — globs `*.csv` (not a fixed list — whatever's in `data/raw/` gets uploaded, including files with no downstream table), returns `{"success": [...], "failed": [...]}`.
- `verify_uploads() -> list` — re-lists the `raw/` prefix in S3 as a post-hoc check.

**`setup_redshift_tables.py`**
- `execute_sql_file(sql_file)` — splits the SQL file on `;`, executes each statement individually, commits per-statement, rolls back and continues on a per-statement failure (one bad `CREATE TABLE` doesn't block the rest).
- `verify_tables()` — queries `pg_tables WHERE schemaname='raw_data'` and returns what actually exists.

**`s3_to_redshift.py`**
- `FILE_TABLE_MAPPING` — the hardcoded dict of the 7 files that actually get loaded (2 files in `data/raw/`, `olist_geolocation_dataset.csv` and `olist_order_reviews_dataset.csv`, are **not** in this dict and never reach Redshift even though `upload_to_s3.py` uploads them).
- `truncate_table(cursor, table)` — `TRUNCATE` before every load, making reruns idempotent.
- `load_table(cursor, s3_file, table) -> int` — builds and executes the `COPY` statement (see options below), then `SELECT COUNT(*)` to report rows loaded.
- `load_all_tables() -> dict` — iterates the mapping, commits per table, `table -> row_count`.
- `verify_loads() -> dict` — opens a **second** connection post-commit and re-counts every table, to catch anything that looks fine in-transaction but didn't actually persist.

## COPY options used

```
CSV IGNOREHEADER 1 DATEFORMAT 'auto' TIMEFORMAT 'auto' TRUNCATECOLUMNS BLANKSASNULL EMPTYASNULL
```

Type enforcement is deliberately *not* done here — all Redshift columns are permissive (`VARCHAR`/`DECIMAL`/`TIMESTAMP`) so COPY never rejects a row. Real typing/casting happens in the dbt staging layer (see `dbt_project/README.md`).

## Running standalone

```bash
source metric_venv/bin/activate

python -m ingestion.upload_to_s3            # Step 1 — data/raw/*.csv -> S3
python -m ingestion.setup_redshift_tables   # Step 2 — DDL, run once (idempotent)
python -m ingestion.s3_to_redshift          # Step 3 — S3 -> raw_data.* (451,535 rows)
```

Each script has a `if __name__ == "__main__":` block that prints a summary table and exits `1` on unhandled failure — safe to run from CI or a shell script and check `$?`.

## Env vars required

`AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `REDSHIFT_HOST`, `REDSHIFT_PORT`, `REDSHIFT_DATABASE`, `REDSHIFT_USER`, `REDSHIFT_PASSWORD` — loaded via `config/db.py` and `config/settings.py` (both call `load_dotenv()`). `REDSHIFT_IAM_ROLE` is optional and, if set, is preferred over access-key credentials for the `COPY` statement (see `config/README.md`).

## Upstream / downstream

- **Upstream:** `data/raw/*.csv` (Kaggle Olist dataset, not committed to git).
- **Downstream:** `dbt_project/` — every dbt staging model sources directly from the `raw_data` tables this folder populates. Nothing in `dbt_project/` runs correctly until all three ingestion scripts have completed at least once.

## Gotchas

- **9 files on disk, only 7 loaded.** `upload_to_s3.py` uploads everything in `data/raw/`; `s3_to_redshift.py` only loads what's in `FILE_TABLE_MAPPING`. Adding a new file to `data/raw/` does *not* get it into Redshift automatically — you must also add a `CREATE TABLE` to `infrastructure/redshift_setup.sql` and a mapping entry here.
- **Credentials in COPY SQL.** If `REDSHIFT_IAM_ROLE` isn't set, `build_copy_credentials()` (in `config/db.py`) falls back to embedding the literal access key/secret in the `COPY` statement text — those then show up in Redshift's `STL_QUERYTEXT` history. Prefer the IAM role in any shared/production workgroup.
- **`s3_to_redshift.py` truncates before it loads.** Rerunning it wipes and reloads every table in `FILE_TABLE_MAPPING`, even if only one source file changed.
