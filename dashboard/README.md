# dashboard/

The legacy Streamlit dashboard — `app.py` is the only file (plus `__init__.py`). It's a **standalone** interface: it connects directly to Redshift with its own credentials and its own query functions, and does not call `dashboard_api/` or reuse `decomposition/decomposer.py`. It is functional but not deployed anywhere (local-only, run with `streamlit run`).

## File inventory

| File | Purpose |
|------|---------|
| `app.py` | Entire Streamlit app — connection, data fetching, all render functions, `main()` |
| `__init__.py` | Empty package marker |

## Functions (`app.py`)

| Function | Cache | What it does |
|----------|-------|---------------|
| `get_connection()` | `@st.cache_resource` (session-scoped) | Opens a `redshift_connector` connection from `REDSHIFT_HOST/PORT/DATABASE/USER/PASSWORD` env vars. Deliberately does **not** use `config/db.get_connection()` — Streamlit's resource cache needs to own the connection lifecycle across reruns; wrapping the shared factory would create a new connection on every script rerun. |
| `fetch_daily_metrics()` | `@st.cache_data(ttl=300)` | `SELECT * FROM staging.fact_daily_metrics ORDER BY metric_date` |
| `fetch_metric_by_dimension(dimension)` | `@st.cache_data(ttl=300)` | `SELECT * FROM staging.metric_by_{geography|product|payment} ORDER BY metric_date` via a table-name lookup dict |
| `calculate_change(df, metric_col, current_date, previous_date)` | pure | Sums `metric_col` for each date, returns `(current, previous, change, change_pct)` |
| `render_header()` | — | Title + tagline + `st.divider()` |
| `render_date_selector(df)` | — | Two `st.selectbox`es; "Compare To" is filtered to dates strictly before the selected current date |
| `render_kpi_cards(df, current_date, previous_date)` | — | 3 `st.metric()` cards (Revenue $, Order Count, AOV $) with delta % |
| `render_trend_chart(df, metric)` | — | `plotly.express.line()` over the full date range for one metric |
| `render_decomposition(dimension, current_date, previous_date)` | — | **Independently recalculates** segment contribution (groups the dimension table by date, merges current vs. previous, computes `change` and `contribution = change/total_change*100`), then renders a Plotly horizontal waterfall chart plus an expandable sorted table. This duplicates the math in `decomposition/decomposer.py::calculate_contribution()` rather than calling it. |
| `render_alert_panel(current_date, previous_date, df)` | — | Z-score threshold slider (1.0–3.0) + "Run Pipeline Now" button that calls `orchestration.run_pipeline.run_pipeline(force_alert=True)` directly (imported inline inside the button's `if` block) |
| `main()` | — | Entry point: header → fetch data (bails with `st.error` if empty) → date selector → KPI cards → metric-choice trend chart → 3 tabs (`Geography`/`Product`/`Payment`) each calling `render_decomposition` → alert panel. Wraps the whole body in `try/except`, logging failures via `config.logging_config.setup_logger`. |

## Running standalone

```bash
streamlit run dashboard/app.py
# → http://localhost:8501
```

Requires a working `.env` with Redshift credentials and `dbt run` already completed (reads from `staging.fact_daily_metrics` and the 3 `staging.metric_by_*` tables — same tables the Python pipeline reads).

## Config / env vars

`REDSHIFT_HOST`, `REDSHIFT_PORT` (default 5439), `REDSHIFT_DATABASE`, `REDSHIFT_USER`, `REDSHIFT_PASSWORD` — loaded via `load_dotenv()` at import time. No Django/S3/SNS env vars are needed to run this dashboard on its own, **except** that clicking "Run Pipeline Now" triggers the full `orchestration.run_pipeline`, which then does need `SNS_TOPIC_ARN` etc. to succeed.

## How it connects to other folders

- `config.logging_config.setup_logger` — the only shared import for infrastructure (logging).
- `orchestration.run_pipeline.run_pipeline` — imported lazily inside `render_alert_panel()`'s button handler, not at module load time.
- Does **not** import `decomposition/`, `detection/`, or `narrative/` — all analysis logic here is reimplemented locally in `render_decomposition()`, which is why it can drift from `decomposer.py`'s behavior (see Gotchas).

## Gotchas

- **Contribution math is duplicated, not shared.** `render_decomposition()` reimplements `change_pct`/`contribution` from scratch instead of calling `decomposition.decomposer.calculate_contribution()`. If the formula or edge-case handling (e.g. zero-previous-value) in `decomposer.py` changes, this file won't pick it up automatically — verify both stay in sync when editing decomposition logic.
- No anomaly detection is run or displayed anywhere in this dashboard — the "Alert Configuration" panel only exposes the threshold slider and a manual trigger button; it never calls `detection.anomaly_detector` to show current anomalies (unlike the Django dashboard's KPI card).
- `get_connection()`'s `@st.cache_resource` means the same connection is reused across Streamlit reruns within a session; if Redshift Serverless auto-pauses mid-session, the cached connection can go stale and subsequent queries will fail until the page/session is manually restarted.
- Not covered by CI (`ci.yml` runs `pytest tests/`, and there's no `tests/test_dashboard*.py`); this file has zero automated test coverage.
