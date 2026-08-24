# MetricPulse — Project Documentation (Resume Source of Truth)

---

## 1. Project Summary

MetricPulse is an automated root cause analysis engine built on the Brazilian Olist e-commerce dataset (451,535 rows, 7 tables). It ingests raw CSVs into S3, transforms them through a 3-layer dbt pipeline on Redshift Serverless, runs z-score anomaly detection across 4 business metrics, decomposes metric changes by geography/product/payment, generates plain-English narratives via Jinja2 templates, and delivers findings to stakeholders via SNS email alerts — all triggered from a single API call. The Django REST API and SPA dashboard make every layer queryable and observable without writing SQL. End-to-end pipeline runtime is 10–15 seconds from trigger to alert. The full stack runs on AWS (S3, Redshift Serverless, SNS, CloudWatch, Lambda, ECR) with the web app deployed on Render.

That deterministic core (Phase 0, above) is now the foundation for two LangGraph agents, added in a
second, separately-scoped initiative (`docs/scoping.md`, `docs/ROADMAP.md`) and fully shipped as of
2026-08-19. **The investigation agent** (Phase 1, §7) drills into an anomaly's segment breakdown
when it's ambiguous — close contributors, or segments moving in opposite directions — and
synthesizes a plain-English explanation whose every factual claim is validated against real
computed data before it's shown to anyone; the model never free-writes a number. **The dataset
onboarding agent** (Phase 2, §8) closes the pipeline's original single-dataset limitation: given an
arbitrary flat CSV it's never seen, it profiles every column, proposes a role for each via an
LLM call checked against real statistics, has a human confirm the result, and generates a working
DuckDB-backed `detect → decompose → narrate` pipeline for it — with the same investigation agent
then running against that new dataset completely unmodified. Both agents were proven, not just
built: Phase 1 against a real 5-run eval suite (§7), and Phase 2 against a genuinely new, real
public dataset (Sample Superstore Sales, 8,399 rows) that surfaced and fixed six real integration
bugs no synthetic fixture had ever exercised (§8).

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
| Testing | pytest 9.0 | 81 tests across 13 files; all test pure functions with in-memory data, no mocking |
| Agent orchestration | LangGraph 1.2.10 | Stateful graph with conditional edges and bounded loops — the actual shape of both agents' control flow (gather evidence → reason → maybe gather more → decide), not a linear prompt chain or open-ended ReAct loop |
| LLM provider | Groq 0.37.1 (via `langchain-groq` 1.1.3) | Fast, cheap inference — matters directly for a pipeline whose value proposition is a 10–15s runtime; the LLM's job in both agents is narrow enough not to need frontier-model capability, since output is structurally validated, not trusted on the model's word |
| Structured LLM output | Pydantic 2.12.5 + `.with_structured_output(method='function_calling')` | Classic tool-calling structured output, not the newer strict-JSON-schema mode — broader compatibility across Groq-hosted models tested during Phase 1 |
| Onboarding backend | DuckDB 1.5.5 | Zero-infrastructure target for a dataset the pipeline has never seen — proves "works on a new dataset" as a live walkthrough, not "first, provision a data warehouse"; real dbt/Redshift codegen is a named, deferred v2 (`docs/scoping.md` §6.6) |

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
| `stg_orders` | `raw_data.orders` | Cast `order_purchase_timestamp` → `DATE` as `order_date`; filter `WHERE order_purchase_timestamp IS NOT NULL`; derives `order_year`, `order_month`, `order_day_of_week`, `delivery_days` |
| `stg_order_items` | `raw_data.order_items` | Add `total_item_value = price + freight_value` |
| `stg_customers` | `raw_data.customers` | Pass-through, no transforms |
| `stg_products` | `raw_data.products` LEFT JOIN `category_translation` | `COALESCE(english_name, portuguese_name, 'unknown')` for `product_category` |

There is no `stg_sellers` model — `sellers` data is loaded into `raw_data` but not used by any staging/marts/metrics model.

**Layer 2 — Marts (4 tables)**

Fact table + enrichment dimensions. Materialised as tables for join performance.

| Model | Rows | Purpose |
|-------|------|---------|
| `fact_daily_metrics` | ~760 (1/day) | Daily `order_count`, `customer_count`, `total_revenue`, `avg/min/max_order_value` |
| `dim_geography` | 27 | 27 Brazilian states → 5 regions (Southeast, South, Northeast, Central-West, North) + `Unknown` fallback |
| `dim_product` | ~73 | 73 product categories → 7 product groups (`Electronics`, `Home & Furniture`, `Fashion & Sports`, `Health & Beauty`, `Kids & Toys`, `Auto & Tools`, `Other`) |
| `dim_payment` | 4 | Payment type codes → display labels |

There is no `dim_customers` or `dim_sellers` model.

**Layer 3 — Metrics (3 tables)**

Daily revenue pre-aggregated per decomposition dimension. These are the tables queried by the decomposition layer (`fact_daily_metrics`, above, is what the detection layer queries).

| Model | Grain | Metrics |
|-------|-------|---------|
| `metric_by_geography` | 1 row per day × region × state | Revenue and order count by geography |
| `metric_by_product` | 1 row per day × product group × category | Revenue and order count by product |
| `metric_by_payment` | 1 row per day × payment type | Revenue and order count by payment method |

**Test coverage (37 tests)**

| Test type | Count | Applied to |
|-----------|-------|-----------|
| `not_null` | 26 | Primary keys and required fields across all models |
| `unique` | 7 | Primary keys |
| `accepted_values` | 2 | `order_status` (8 values), `region` (6 values) |
| singular (`dbt_project/tests/`) | 2 | `assert_revenue_positive.sql`, `assert_dates_continuous.sql` |
| **Total** | **37** | |

No `relationships` (FK integrity) tests are defined anywhere in the schema — this was previously
misdocumented; there is no cross-table referential test between orders/customers/items/products.

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
| `fetch_daily_metrics(lookback_days=30)` | lookback window | DataFrame from `fact_daily_metrics` |
| `calculate_zscore(series)` | A single `pd.Series` | `pd.Series` of z-scores (`ddof=1`) |
| `detect_anomalies(df, metric_column, threshold=None)` | DataFrame + column + threshold | DataFrame with `zscore`, `is_anomaly`, `anomaly_direction`, `change_pct` columns added |
| `get_latest_anomaly(df, metric_col='total_revenue')` | Analysed DataFrame | Dict with latest anomalous date, value, z-score, or `None` |
| `run_detection(metric, threshold, days)` | All params | Full detection result dict, composing the functions above |

**Onboarding integration (M5, `docs/scoping.md` §6.2):** `fetch_daily_metrics`/`run_detection` gained
optional `metric_columns`, `table_name`, and `connection_factory` parameters, each defaulting to
exactly today's Olist/Redshift behavior — every call above is byte-identical for every existing
caller. When set (by an onboarded dataset, §8), they let this same, already-tested code run
z-score detection against a local DuckDB file's differently-named table/columns instead.

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

Each dimension key in `decompose_metric()`'s output dict has this shape:

| Field | Description |
|-------|-------------|
| `total_current` / `total_previous` | Summed metric value across all segments, per date |
| `total_change` / `total_change_pct` | Absolute / percentage change in the dimension total |
| `top_contributors` | Top 5 segments by `|contribution_pct|`, each `{segment, current_value, previous_value, change, contribution_pct}` |
| `segment_count` | Total number of segments in this dimension |

`dominant_driver` is not part of this output — it's produced by a separate call,
`get_top_driver(results)`, which scans `top_contributors` across all three dimensions and returns
the single highest-magnitude segment.

**Onboarding integration (M5):** `decompose_metric()`/`fetch_detail_metrics()` gained optional
`dimension_config` and `connection_factory` parameters, same additive/backward-compatible pattern
as §5's detection layer — an onboarded dataset supplies its own `{table, segment_col, detail_col}`
mapping per dimension instead of the hardcoded 3-dimension `DIMENSION_TABLES` dict, and the same
parameterized SQL query builder runs unchanged against DuckDB instead of Redshift.

**Stage 2 — Narrative Generation (`narrative/generator.py`)**

Renders decomposition output into natural language. Despite the "Jinja2 templates" framing below,
there are no `.jinja2` template files anywhere in the repo — `full` and `slack` are Jinja2
*string* templates defined inline as Python constants and rendered via
`jinja_env.from_string(...)`; `email_subject` is a one-line inline Jinja2 string; `summary` isn't
templated at all, it's built with an f-string.

| Format | Defined as | Use case |
|--------|-----------|---------|
| `full` | `METRIC_CHANGE_TEMPLATE` (inline Jinja2 string) | Complete multi-paragraph analysis |
| `slack` | `SLACK_TEMPLATE` (inline Jinja2 string) | Single-block Slack notification |
| `email_subject` | `EMAIL_SUBJECT_TEMPLATE` (inline Jinja2 string) | One-line email subject line |
| `summary` | Python f-string (no template) | 2–3 sentence executive summary |

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

## 7. Investigation Agent (LangGraph, Phase 1)

Runs after the static decomposition (§6) when its segment breakdown is ambiguous — two segments
close in magnitude, or segments moving in opposite directions — and drills deeper, the way an
analyst would ask a follow-up question rather than stop at the first chart. Package: `investigation/`.

**Graph structure** — a compiled `StateGraph` (`investigation/graph.py`), 7 nodes, 3 conditional
routing functions:

```
START → detect → route_after_detection → {decompose_all, finalize_skip}
decompose_all → assess_ambiguity → route_after_ambiguity → {drill_down, synthesize}
drill_down → synthesize
synthesize → route_after_synthesis → {assess_ambiguity, finalize}
finalize / finalize_skip → END
```

No checkpointer — purely a single-invocation graph, no cross-run persistence need.

| Node | Type | Purpose |
|------|------|---------|
| `detect` | Deterministic | Thin wrapper around unchanged `run_detection()`; no-op if `detection_result` is pre-seeded |
| `decompose_all` | Deterministic | Thin wrapper around unchanged `decompose_metric()`; no-op if pre-seeded |
| `assess_ambiguity` | Deterministic rule | Flags each dimension `close_contributors` (top two segments' `abs_contribution` within 15 percentage points, `CLOSE_CONTRIBUTORS_THRESHOLD`) or `offsetting_segments` (top contributor's `contribution_pct` outside `[0, 100]`) |
| `drill_down` | Deterministic | Calls the new `fetch_detail_metrics()` for each `close_contributors` dimension; `offsetting_segments` dimensions are never drilled — more data can't resolve segments genuinely moving in opposite directions, only honest narration can |
| `synthesize` | **LLM call** | The only node that calls an LLM — see Grounding design, below |
| `finalize` / `finalize_skip` | Deterministic | Terminal nodes; `finalize_skip` used when no anomaly and `force_investigate=False` |

**Routing** (`investigation/routing.py`): `MAX_ITERATIONS = 2` hard-caps drill-down/re-synthesis
rounds regardless of what the model requests — enforced in the routing function, never left to the
model to self-limit.

**Grounding design — the actual engineering, not the LLM call itself.** The model never
free-writes prose containing numbers. `synthesize` calls `ChatGroq.with_structured_output
(SynthesisOutput, method='function_calling')`; its output is a set of *citations* —
`{dimension: str, segment: str, source, claim}` — references into evidence already in state, not
typed values. `validate_citation()` (`investigation/validation.py`) then checks every citation's
`(dimension, segment)` pair against the real `decomposition_results`/`drill_down_results` before
it's trusted. On failure: one retry with the specific errors fed back into the prompt; if that also
fails, fail *open* to a deterministic f-string built from `decomposer.get_top_driver()` — the
pipeline never returns wrong information, worst case "no bonus explanation available." Once
validated, `render_investigation_summary()` renders the final text via Jinja2, looking up every
number **fresh from state** using the citation as a key, so even a stray number in the model's own
`claim` text never reaches the rendered output.

`EvidenceCitation.dimension` is a plain `str`, not a fixed `Literal` of Olist's 3 dimension names —
this was a real bug, found live during Phase 2's M6 (§8): a hardcoded `Literal['geography',
'product', 'payment']` silently made "the agent runs unmodified against new data" untrue until
fixed, since it forced every real citation from a differently-named dimension to fail validation.

**Real measured results** (`python -m investigation.eval --runs 5`, M3, against live Groq):
`grounding_pass_rate=1.00`, `fallback_rate=0.00`, `golden_match_rate=1.00`, `uncertainty_ok_rate=1.00`.
A small, hand-curated golden-case suite (§12), not a large-scale benchmark — the number demonstrates
the validation architecture works as designed.

**Dataset targeting (M6):** `InvestigationState` carries an optional `dataset_config` field
(`None` by default — zero behavior change for every pre-M6 caller), threaded through
`investigation/tools.py`'s tool wrappers via a small `_dataset_kwargs()` helper that forwards only
the keys actually present. This is the mechanism that lets the graph above run, completely
unmodified, against an onboarded dataset's DuckDB tables instead of Olist's Redshift tables (§8).

**Integration:** `run_pipeline(run_investigation=False)` (default off — zero behavior change for
existing callers), `POST /api/investigate/` (§9), a dashboard "Investigate" button, Lambda event
passthrough. `detection_result`/`decomposition_results` are pre-seeded into `build_initial_state()`
when invoked from a caller that already has them, so `detect`/`decompose_all` short-circuit instead
of re-querying — matches `orchestration/run_pipeline.py`'s own pre-seeding convention.

---

## 8. Dataset Onboarding Agent (LangGraph, Phase 2)

Closes the pipeline's original hardcoding: `decomposition/decomposer.py`'s `DIMENSION_TABLES` dict
mapped exactly 3 semantic roles (date/metric/dimension) to exact Olist table/column names — a much
smaller, more tractable problem than "generalize the whole pipeline," since the rest of the math
(`calculate_contribution`, `detect_anomalies`, the narrative templates) was already dataset-agnostic.
Package: `onboarding/`.

**Flow (7 steps):**

| # | Step | Module | LLM call? |
|---|------|--------|-----------|
| 1 | Profiling — per-column dtype, cardinality ratio, null rate, date-parse rate, sample values | `profiling.py` | No |
| 2 | Classification — proposes a role for every column | `classification.py`, `llm.py`, `prompts.py` | Yes, 1 call |
| 3 | Human confirmation — `[y]`/`[e]`/`[n]` CLI prompt | `onboard.py` | No |
| 4 | Schema-fingerprint cache — SHA-256 of sorted `(column, dtype)` pairs; unchanged schema skips straight to codegen | `fingerprint.py` | No |
| 5 | Codegen — writes real DuckDB tables (`fact_daily_metrics`, one `metric_by_<dimension>` per confirmed dimension); reconciles every dimension's totals against the fact table's | `codegen.py` | No |
| 6 | Bridge to the pipeline — `run_detection()`/`decompose_metric()`/`generate_narrative()`, unmodified, against the new tables | `investigate.py` | No |
| 7 | Optional `--run-investigation` — feeds the same dataset config into the completely unmodified Phase 1 graph (§7) | `investigate.py` | Yes, ≤2 calls |

**Classification output shape** (`schemas.py`, `SchemaClassification`): `date_column`,
`grain` (`'daily'` or `'other'`), `metric_columns: List[str]`, `dimension_columns:
List[DimensionCandidate]` (`{column, cardinality, confidence, reasoning}`), `rejected_columns:
List[RejectedColumn]` (`{column, reason}`), `requires_human_review: bool`, `validation_errors:
List[str]`.

**Validation** (`classification.py`): `MIN_DATE_PARSE_RATE = 0.95`,
`MAX_DIMENSION_CARDINALITY_RATIO = 0.1` — the same bounded-retry-then-fail-open pattern as §7's
`synthesize`: one real LLM call, validate against Stage A's real profiling numbers, one retry with
errors fed back into the prompt, then emit with `requires_human_review=True` if still failing.
Never silently wrong, never crashes.

**Codegen** (`codegen.py`): `sanitize_identifier()` converts arbitrary real-world column names
(spaces, hyphens) into safe, unquoted SQL identifiers before they're used as real DuckDB table/
column names; `dimension_config`'s dict *keys* stay human-readable (never themselves embedded in
SQL). `validate_generated_tables()` reconciles every dimension table's per-date totals against the
fact table's via `np.allclose(atol=0.01, rtol=1e-6)`, not exact float equality.

**M6 — real-world proof, not just a synthetic golden case.** Ran the full flow against "Sample
Superstore Sales" (8,399 rows, real public retail data, never referenced anywhere in this repo
before), including `--run-investigation` against the unmodified Phase 1 graph. Surfaced and fixed
six real bugs, none caught by the 81-test suite:

| # | Bug | Fix |
|---|-----|-----|
| 1 | `EvidenceCitation.dimension` hardcoded to 3 Olist-only names (§7) — "agent runs unmodified" was silently untrue | Changed to plain `str`; re-verified Golden Case #1 still 3/3 after the fix |
| 2 | Column names with spaces (`"Order Priority"`) broke `CREATE TABLE` outright | New `sanitize_identifier()` |
| 3 | `Sales`/`Profit` (float, cardinality ratios 0.971/0.930) misclassified as IDs | Float columns exempted from the cardinality-ID check; integers still checked |
| 4 | Reconciliation's round-then-`.equals()` produced a spurious 1-cent mismatch on real-scale sums | `np.allclose(atol=0.01, rtol=1e-6)` on unrounded values |
| 5 | `llama-3.3-70b-versatile` silently retired from Groq's model catalog | Confirmed via direct `GET /openai/v1/models`; `openai/gpt-oss-120b` adopted after live-testing 3 candidates |
| 6 | CSV wasn't valid UTF-8 (legacy Windows-1252) | `cp1252` fallback on `UnicodeDecodeError` |

Real verified output (`python -m onboarding.investigate --dataset-id superstore_sales --metric
sales --run-investigation`): anomaly detected 2012-12-30 (-83.2%), primary driver Small Box
(Product Container, 89.4% of the change); investigation agent status `completed`, no fallback,
grounded citations across repeated live runs. A real, unedited terminal recording of this flow is
at `docs/project/demos/m6_onboarding_demo.cast` (`asciinema play <path>` to replay).

**Not built (named, not silent):** no multi-table/join inference — single flat file only; no
`dim_*` business-taxonomy remapping layer for onboarded data (`drill_down` degrades to a no-op —
there's no finer grain than the dimension itself); no real dbt/Redshift codegen (DuckDB only, v1);
no dashboard-based onboarding wizard (CLI only, v1).

---

## 9. Django REST API (8 Endpoints)

Single-page app served from `templates/base.html` via `TemplateView`. All data fetched client-side. SQLite used only for Django sessions/admin — no business data stored locally.

| Endpoint | Method | Key params | Returns |
|----------|--------|-----------|---------|
| `/api/health/` | GET | — | Service status + timestamp |
| `/api/metrics/` | GET | `days` (default 30) | Daily metrics array from `fact_daily_metrics` |
| `/api/anomalies/` | GET | `metric`, `threshold` | Detection results with flagged dates |
| `/api/decomposition/` | GET | `current_date`, `previous_date`, `metric` | Full decomposition dict for 3 dimensions |
| `/api/narrative/` | GET | `current_date`, `previous_date` | All 4 narrative format outputs |
| `/api/pipeline/` | POST | `metric`, `force_alert`, `dry_run` | Pipeline execution summary |
| `/api/investigate/` | POST | `metric`, `current_date`, `previous_date`, `threshold` | Full `InvestigationState` dict from a standalone Phase 1 agent run (§7); `force_investigate=True` always — a user explicitly requesting an investigation gets one regardless of z-score threshold, unlike the automated pipeline path where it's gated to actual anomalies to control LLM cost |
| `/api/contact/` | POST | `name`, `email`, `message` | Logs submission (email send disabled) |

---

## 10. Dashboard (2 Interfaces)

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
| Investigation | "Investigate" button → `POST /api/investigate/` (§7, §9); renders `investigation_summary` alongside the existing narrative panel |

**Streamlit Dashboard (legacy — local only)**

Direct Redshift connection. `@st.cache_resource` for connection (session-scoped), `@st.cache_data(ttl=300)` for query results (5-minute cache). Waterfall charts via Plotly Express. Not deployed. Reimplements its own contribution math rather than calling `decomposition.decomposer` — predates both agentic phases and isn't wired to either.

---

## 11. Deployment Architecture

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
| `GROQ_API_KEY` / `GROQ_MODEL` | New env vars for both agentic phases — `GROQ_MODEL` defaults to `openai/gpt-oss-120b` (`config/settings.py`; recalibrated M6 after `llama-3.3-70b-versatile`'s retirement from Groq's catalog) |

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
| CD (`cd.yml`) | Push to `main` | Requires `production` environment approval; installs deps, configures AWS credentials, echoes a `dbt run` placeholder — **does not itself deploy anything** |

CD does not deploy the Django app — Render deploys independently via its own git-push auto-deploy
hook, entirely outside this GitHub Actions workflow. `cd.yml`'s only real effect today is the
environment-approval gate; its dbt step is a no-op echo (see §14).

Flake8 strategy: hard errors (`E9,F63,F7,F82`) fail CI; style warnings (`--exit-zero`) are non-blocking. pip cache keyed on `requirements.txt` hash — saves ~60s per run on cache hit.

---

## 12. Test Coverage (81 Tests, 13 Files)

| File | Tests | What's covered |
|------|-------|---------------|
| `tests/test_anomaly_detector.py` | 5 | Z-score calculation, threshold logic, anomaly flagging, `get_latest_anomaly` per metric, empty DataFrame handling |
| `tests/test_decomposer.py` | 4 | Contribution % formula, dominant driver selection, date validation rejection, multi-dimension output shape |
| `tests/test_narrative.py` | 6 | All 4 format outputs present, `format_type` filtering, currency formatting (basic/large/none/negative), summary content |
| `tests/test_investigation_routing.py` | 11 | `route_after_detection`/`route_after_ambiguity`/`route_after_synthesis` against fixture states, `MAX_ITERATIONS` enforcement |
| `tests/test_ambiguity_rules.py` | 9 | `assess_ambiguity`'s `close_contributors`/`offsetting_segments` classification against fixture decomposition results |
| `tests/test_citation_validation.py` | 8 | `validate_citation`/`validate_synthesis_output` against real and deliberately-broken citation fixtures |
| `tests/test_investigation_tools.py` | 5 | `_dataset_kwargs()` — `None`/empty/partial/full `dataset_config` forwarding (M6) |
| `tests/test_eval_summarization.py` | 4 | `investigation.eval`'s metric-aggregation helpers |
| `tests/test_profiling.py` | 8 | `profile_column`/`profile_columns` — dtype, cardinality ratio, null rate, date-parse rate, `is_likely_id` (including the M6 float-exemption fix) |
| `tests/test_classification_validation.py` | 6 | `validate_classification` against real and deliberately-invalid `SchemaClassification` fixtures |
| `tests/test_codegen.py` | 6 | `load_and_aggregate`/`write_fact_table`/`write_dimension_tables`/`sanitize_identifier` against a real in-memory DuckDB connection |
| `tests/test_reconciliation.py` | 3 | `validate_generated_tables` — including a deliberately-corrupted fixture confirming it actually catches a broken case |
| `tests/test_schema_fingerprint.py` | 6 | `schema_fingerprint`'s order-independence and sensitivity to rename/retype/add/remove |

No mocking is used anywhere in the suite — every test calls a pure function directly with in-memory
DataFrames/dicts/fixture state, or (for codegen/reconciliation) a real in-memory DuckDB connection.
Redshift-touching functions are simply never exercised by the suite, so no live AWS connection is
required to run CI. The two LLM-touching functions per phase (`synthesize`'s citation generation,
`classify_columns_with_validation`) are **not** covered by this suite — they can't be, since the
same input can produce differently-worded but equally correct output. They're exercised instead by
a separate, manually-triggered, real-API eval suite (`investigation.eval`, `onboarding.eval`) that
grades output by property (is every citation grounded? does the primary explanation match the known
driver?) using the same deterministic validators that gate production behavior, not a separate
LLM-as-judge pipeline. `pytest tests/ -v --tb=short` is the CI command; previously a `|| echo`
clause swallowed failures silently.

---

## 13. Key Engineering Decisions

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
| Agent orchestration | LangGraph | CrewAI, plain while-loop, open-ended ReAct tool selection | Both agents' shape (evidence → reason → maybe gather more → decide, with loop-back edges) is what a stateful graph with conditional edges is for; open-ended tool selection was a named non-goal — it breaks auditability, wastes LLM cost on decisions a rule already makes correctly, and can't be unit-tested the way a routing function can |
| LLM provider | Groq | OpenAI/Anthropic-hosted, local models | Speed and cost fit for a narrow, structurally-validated task; the tradeoff (smaller models) is acceptable specifically because grounding doesn't depend on the model being maximally capable |
| Grounding mechanism | Structured-output citations + deterministic validation, render-from-state | Prompting the model not to hallucinate; a separate LLM-as-judge layer | Turns "probably correct" into "provably grounded, or it doesn't reach the user" — a structural check, not a rate reduction; reused identically across both agents (citation validation, classification validation) and the eval suite's grading |
| Control flow inside both agents | Deterministic Python rules (ambiguity assessment, classification validation, routing) | Delegating to LLM judgment | Every decision expressible as a rule over real numbers is written as one — cheaper, auditable, reproducible; the LLM is reserved for the two genuinely fuzzy judgment calls (which citation is most informative; is this column plausibly a date/metric/dimension) |
| Onboarding codegen target | Local DuckDB (v1) | Real dbt/Redshift codegen | Zero-infrastructure live demo of "works on a new dataset"; the same already-parameterized SQL query builder (§6) runs against DuckDB unchanged — real dbt/Redshift codegen is a named, deferred v2, not built because it's harder but because it's more expensive to demo |
| Schema mapping for a new dataset | LLM proposal + statistical validation + human confirmation | Fully automated, no human step | The one deliberately non-autonomous step in either agent — a validated classification can still be *semantically* wrong (e.g. summing a column that shouldn't be summed) in a way no statistical check catches, named explicitly as a residual risk in `docs/scoping.md` §7.6 |

---

## 14. Known Limitations & Future Work

| Item | Type | Notes |
|------|------|-------|
| CD dbt step is a placeholder | Limitation | `dbt run` is commented out in `cd.yml` — transformations must be run manually when source data changes. Requires Redshift credentials as GitHub secrets and a CI-specific `profiles.yml` |
| Contact form email disabled | Limitation | `ContactView` logs submissions but `send_mail` is commented out — requires `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` env vars |
| Lambda deploy not automated | Limitation | `deploy/` scripts exist but CD pipeline does not invoke them — Lambda deploys are manual |
| No `collectstatic` verification in CI | Limitation | Static files are only collected on Render build, not validated in CI — a broken static file would only surface post-deploy |
| No auth or rate-limiting on `/api/investigate/` | Limitation | Unlike every other endpoint, this one costs real LLM-provider money per call. Accepted risk for a low-traffic portfolio deployment; DRF's built-in throttling is the named cheap hardening step if this became load-bearing |
| No `dim_*` business-taxonomy remapping for onboarded data | Limitation, named not silent | There's no generic, automatable equivalent of "what's a sensible regional grouping" for a domain the system has never seen — `drill_down` degrades to a no-op for onboarded datasets as a direct consequence |
| No multi-table/join inference for onboarding | Limitation, named not silent | Single flat file only — a user with normalized data flattens it themselves first, the same thing a human did by hand to build Olist's own `fact_daily_metrics` |
| `requires_human_review` doesn't implement the stronger "always `True` on a first-ever run" rule | Limitation, named not silent | The fingerprint cache (§8) only tracks match/mismatch, not review *history* per dataset — that stronger rule was scoped but not built |
| No protection against a rushed-but-wrong human confirmation | Limitation, named not silent | The confirmation screen shows column *roles*, not *aggregation semantics* — a statistically-plausible but business-nonsense classification can still be approved. Named explicitly, not solved |
| Streamlit dashboard not deployed | Future work | `dashboard/app.py` is fully functional locally; could be deployed to Streamlit Cloud with Redshift credentials. Predates both agentic phases and isn't wired to either |
| Automated dbt on data refresh | Future work | Trigger `dbt run` via Lambda or GitHub Actions when new data lands in S3, instead of manual execution |
| Real dbt/Redshift codegen for onboarded datasets | Future work, named v2 (`docs/scoping.md` §6.6) | Would remove DuckDB's single-file, single-machine ceiling for onboarded datasets that need to scale past local memory |
| Dashboard-based onboarding wizard | Future work, named v1 boundary | CLI only today (`onboarding/onboard.py`) |
| Multi-level drill-down / cross-run agent memory | Future work, deliberately deferred | `detail_col` is the deepest grain currently modeled; each investigation is a fresh graph invocation with no memory of prior runs — neither was needed to prove the core design worked |
| Parallel fan-out for multi-dimension decomposition | Future work, deliberately deferred | LangGraph's `Send` API could run the 3+ dimension queries concurrently; at current data volume (sub-5s sequential) the latency savings are marginal against the added debugging complexity |
