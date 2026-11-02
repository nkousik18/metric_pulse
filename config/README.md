# `config/`

Shared, side-effect-light utilities used by every other layer: environment loading, the warehouse connection factory, and the logger factory. No business logic lives here — if you're tempted to add a helper that touches metrics/decomposition/narrative, it belongs in that layer instead, not here.

> **Local stack (2026-11-02).** The AWS resources this was built on were deleted when the free tier ended. All AWS code is **kept, unchanged and switchable** (`docs/local-stack-scope.md`, rule R1).

## Warehouse backends (`WAREHOUSE`)

`get_connection()` returns a connection to whichever backend `config/settings.py`'s `WAREHOUSE` names. Every module that queries the warehouse goes through it, so this one setting switches the whole Olist pipeline, plus the Django API and the investigation agent.

| `WAREHOUSE` | Status | What `get_connection()` opens | How it's built |
|---|---|---|---|
| `duckdb` (default) | **Active** | `duckdb.connect(WAREHOUSE_PATH, read_only=True)`; default path `data/warehouse.duckdb` (gitignored) | `python -m ingestion.load_local`, then `cd dbt_project && dbt build --target local --profiles-dir .` |
| `redshift` | **Archived (AWS)** | `_redshift_connection()`: the original `redshift_connector.connect(...)`, body unchanged | `ingestion/` S3 → Redshift scripts + `dbt build --target redshift` |

- **Inside AWS Lambda** (`AWS_LAMBDA_FUNCTION_NAME` set), `WAREHOUSE` defaults to `redshift` via `settings.backend_default()`, so the archived Lambda image behaves exactly as before with no env changes.
- **Read-only, single writer.** Callers only read, so the DuckDB connection is read-only, and several readers (the dashboard plus a CLI run) can share the file. DuckDB allows one writer at a time, so `load_local` or `dbt build` fails while a reader holds the file, and vice versa. Stop the dashboard before rebuilding. The error message says so.
- **Missing warehouse file:** `get_connection()` raises a `RuntimeError` that names the two build commands.
- **`connection_factory(backend)`** returns the zero-argument connection function without calling it. Tests use it to check that `redshift` selects the archived code path without trying to connect (the workgroup no longer exists).
- `build_copy_credentials()` is untouched and only used by the archived `ingestion/s3_to_redshift.py`.
- **Unchanged:** the legacy Streamlit dashboard (`dashboard/app.py`) still opens its own Redshift connection directly and does **not** follow `WAREHOUSE`. It's an archived, AWS-only component (local-stack scope §4).

## Alerting and monitoring switches

Same pattern as `WAREHOUSE` (local-stack scope §6.4): a local default, the archived AWS behavior as a switch, and the AWS default inside Lambda via `backend_default()`.

| Setting | Default (local / Lambda) | What it controls |
|---|---|---|
| `ALERT_CHANNEL` | `outbox` / `sns` | `alerting/notifier.py`: write alerts to `OUTBOX_DIR`, or publish to the archived SNS topic. Unknown names raise. |
| `OUTBOX_DIR` | `<repo>/outbox` (gitignored) | Where outbox messages and `index.jsonl` go. |
| `ALERT_RECIPIENT` | `metric-pulse-alerts` | The recipient written on pipeline alerts in the outbox (named after the SNS topic). |
| `CLOUDWATCH_METRICS` | `false` / `true` | Whether `run_pipeline` calls the archived `monitoring/cloudwatch_metrics.py` after a non-dry run. Off locally because working AWS credentials would otherwise publish billed metrics. `lambda_handler.py` passes `publish_metrics=False` anyway. |

## Files

| File | Purpose |
|------|---------|
| `settings.py` | Reads every env var once at import time (via `load_dotenv()`) and exposes them as module-level constants. |
| `db.py` | `get_connection()` — the single Redshift connection factory used across the codebase — plus `build_copy_credentials()` for the `COPY` credential clause. |
| `logging_config.py` | `setup_logger(name)` — configured logger factory (console + daily rotating file). |
| `__init__.py` | Re-exports `setup_logger` and `*` from `settings` so callers can do `from config import setup_logger, S3_BUCKET_NAME` etc. |

## Key functions / constants

**`settings.py`** — constants, not functions:

| Constant | Default | Notes |
|----------|---------|-------|
| `PROJECT_ROOT`, `DATA_DIR`, `LOGS_DIR` | derived from `Path(__file__).parent.parent` | |
| `AWS_REGION` | `us-east-1` | |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `None` if unset | |
| `S3_BUCKET_NAME` | `metric-pulse-data` | |
| `S3_RAW_PREFIX` | `raw/` | |
| `S3_PROCESSED_PREFIX` | `processed/` | not currently written to by any script — reserved |
| `REDSHIFT_HOST` / `PORT` / `DATABASE` / `USER` / `PASSWORD` | port `5439`, db `dev` | |
| `REDSHIFT_SCHEMA_RAW` | `raw_data` | |
| `REDSHIFT_SCHEMA_STAGING` | `staging` | dbt actually materializes staging **and** marts **and** metrics all into this one schema — `REDSHIFT_SCHEMA_MARTS` (below) is unused |
| `REDSHIFT_SCHEMA_MARTS` | `marts` | **dead constant** — no dbt model or Python code writes to a `marts` schema; everything lands in `staging` per `dbt_project/dbt_project.yml` |
| `SNS_TOPIC_ARN` | `None` if unset | |
| `ANOMALY_THRESHOLD_ZSCORE` | `2.0` | |
| `LOOKBACK_DAYS` | `30` | |

**`db.py`**
```python
get_connection() -> redshift_connector.Connection
```
Reads `REDSHIFT_HOST/PORT/DATABASE/USER/PASSWORD` from env on every call (opens a new connection each time — there is no pooling). Wraps any failure in `RuntimeError("Redshift connection failed: ...")`.

```python
build_copy_credentials() -> str
```
Returns the SQL credentials clause for a Redshift `COPY` statement. Prefers `IAM_ROLE '<arn>'` if `REDSHIFT_IAM_ROLE` is set; otherwise falls back to `ACCESS_KEY_ID '...' SECRET_ACCESS_KEY '...'`. Raises `ValueError` if neither is available — this is the only place in the codebase that hard-fails on missing credentials at call time rather than at connection time.

**`logging_config.py`**
```python
setup_logger(name: str, log_level: str = "INFO") -> logging.Logger
```
- Console handler at INFO, file handler at DEBUG (file includes `funcName:lineno`).
- File target: `logs/metric_pulse_YYYYMMDD.log` (new file per calendar day, `logs/` created if missing).
- Guards against duplicate handlers: `if logger.handlers: return logger` — safe to call repeatedly with the same `name` (e.g. from re-imported modules) without doubling log lines.

## Running / testing

Nothing here has a CLI entry point — it's a library. Sanity-check it directly:

```bash
python -c "from config.db import get_connection; get_connection().close(); print('OK')"
python -c "from config import S3_BUCKET_NAME, ANOMALY_THRESHOLD_ZSCORE; print(S3_BUCKET_NAME, ANOMALY_THRESHOLD_ZSCORE)"
```

## Env vars

All variables listed in `settings.py` above; see `.env.example` at project root for the full list with placeholder values. Loaded via `python-dotenv`'s `load_dotenv()`, called independently in both `settings.py` and `db.py` (harmless — `load_dotenv()` is idempotent, but it means this folder has two independent env-loading entry points instead of one).

## Upstream / downstream

- **Upstream:** `.env` file / process environment.
- **Downstream:** every other folder imports from here — `ingestion/`, `detection/`, `decomposition/`, `narrative/`, `alerting/`, `orchestration/`, `monitoring/`, `dashboard_api/` all call `config.db.get_connection()` and/or `config.logging_config.setup_logger()`. This is intentionally the *only* connection factory in the codebase (previously there were 5 duplicated copies — see `docs/detection_layer.md` / `docs/analytics_pipeline.md` "Issues Fixed" sections).

## Gotchas

- `REDSHIFT_SCHEMA_MARTS = "marts"` in `settings.py` doesn't correspond to anything real — all dbt models (staging, marts, metrics layers alike) land in the `staging` Redshift schema per `dbt_project/dbt_project.yml`. Don't use this constant to build a schema-qualified table name; it will point at a schema that doesn't exist.
- `get_connection()` opens a fresh connection per call — `decomposition/decomposer.py` deliberately opens 3 separate connections (one per dimension) rather than reusing one; see the design note in `docs/analytics_pipeline.md`.
- The Streamlit dashboard (`dashboard/app.py`) intentionally does **not** use `config.db.get_connection()` — it wraps its own connection in `@st.cache_resource` instead, because Streamlit's resource cache is the correct lifecycle manager for a long-lived rerun-based app.
