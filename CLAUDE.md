# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

MetricPulse is an automated root-cause-analysis pipeline: detects anomalous daily business metrics (z-score), decomposes the change by segment, generates a plain-English narrative, and alerts (to a local Markdown outbox by default; SNS is the archived channel) — end-to-end in ~10–15s. Exposed via a Django REST API + SPA dashboard (live on Render) and a standalone Lambda handler for scheduled runs; a legacy Streamlit dashboard also exists, unused in prod.

## Session Ritual

**Start every session by reading `docs/project/SESSION_LOG.md` (latest/top entry) and `docs/ROADMAP.md` (checkboxes)** before doing anything else — that's where things actually stopped last time and what's next. **End every session (or a natural mid-session stopping point) by appending** a new dated entry to `SESSION_LOG.md` (what happened, decisions made, current state, next steps, loose ends). Append-only — add above the previous entry, never edit past ones. Full reasoning: `docs/WORKING_CONVENTIONS.md`.

## Documentation Map — Read Before Rediscovering

Don't re-derive architecture from scratch in chat; it's already written down.

- `docs/README.md` — index of one doc per pipeline layer.
- `docs/MetricPulse_resume_project_doc.md` — single full source of truth (stats, decisions, known gaps). Renamed from `resume_project_doc.md` on 2026-11-02; older docs and session-log entries still use the old name.
- `docs/local-stack-scope.md` — design spec for running everything locally (DuckDB, dbt-duckdb, alert outbox) after the AWS resources were deleted (milestones L1–L3). **All AWS code is kept, never deleted**; local is the default backend and AWS is a switch.
- `docs/ROADMAP.md` — which phase the agentic-layer initiative is in, checkbox per milestone.
- `docs/scoping.md` — the section-by-section design spec for that initiative (goals, non-goals, decision log). `ROADMAP.md` tracks whether each part is *built*; this is the *design record* — don't assume a section being designed here means it's implemented.
- `docs/action-agent-scope.md` — design spec for the follow-on Action Agent initiative (milestones A1–A7 in `ROADMAP.md`); its §11 decisions are fixed for the build, and §13 specifies LangSmith tracing and replay.
- `docs/project/SESSION_LOG.md` — session-by-session history; read before assuming what's already been tried.
- `CHANGELOG.md` — what's actually shipped, in user-facing terms.
- `concepts/` (see `concepts/INDEX.md`) — one file per idea worth explaining once and linking to, rather than re-explaining at length in chat every time it comes up.
- `CONTRIBUTING.md` — branch naming and the GitHub Flow sequence (branch → PR → CI green → squash-merge). Follow it for every change, however small.
- Every top-level code folder has its own `README.md` (file-by-file detail, key functions, gotchas) — read the relevant one before editing that layer, instead of asking or guessing.

## Commands

### Setup
```bash
python -m venv metric_venv && source metric_venv/bin/activate
pip install -r requirements.txt
```

### Tests
```bash
pytest tests/ -v                          # full suite (this is what CI runs)
pytest tests/test_decomposer.py -v        # single file
pytest tests/test_decomposer.py::test_basic_contribution -v   # single test
pytest --cov=. --cov-report=html          # with coverage
```
No mocking anywhere — every test exercises a pure function with in-memory data, so no live AWS/DB connection is needed.

### Lint
```bash
flake8 . --select=E9,F63,F7,F82                                   # hard errors — this is what fails CI
flake8 . --exit-zero --max-complexity=10 --max-line-length=120    # style warnings — non-blocking in CI
```

### dbt (from `dbt_project/`)
```bash
cd dbt_project
# Always pass --profiles-dir . (uses the committed dbt_project/profiles.yml, not ~/.dbt)
dbt debug --target local --profiles-dir .     # local DuckDB (default target)
dbt build --target local --profiles-dir .     # 11 models + 37 tests, <1s; expect 1 WARN (real 2016 data gap)
dbt run --select staging --profiles-dir .     # or marts / metrics — build a single layer
dbt build --target redshift --profiles-dir .  # archived AWS target (needs REDSHIFT_* env vars)
```

### Pipeline (analytics engine, standalone)
```bash
python -m orchestration.run_pipeline --dry-run                    # full run, no alert sent
python -m orchestration.run_pipeline --force-alert                # send alert regardless of anomaly state (-> outbox/)
python -m orchestration.run_pipeline --metric order_count --threshold 2.5 --dry-run
python -m orchestration.run_pipeline --dry-run --force-alert --run-investigation  # + agentic investigation (Phase 1)
python -m investigation.eval --runs 5                               # Phase 1 eval suite (real LLM calls, real cost)
python -m onboarding.eval                                           # Phase 2 Golden Case #2 (real LLM call, real cost)
python -m action_agent.probe [--small-only]                         # Action Agent proposer on 12 real anomalies (real Groq calls, ~$0.005)
python -m action_agent.cli propose --dataset-id superstore_sales --metric sales   # LLM proposer -> approval queue (--no-llm: deterministic)
python -m onboarding.onboard --file data/some_new_dataset.csv       # Phase 2 dataset onboarding CLI (real LLM call, interactive confirm)
python -m onboarding.investigate --dataset-id <id> --metric <col> [--run-investigation]  # detect/decompose/narrate (+ Phase 1 agent) against an onboarded dataset
python -m detection.anomaly_detector                               # detection layer alone
python -m alerting.notifier --test                                 # write a test alert to outbox/ (ALERT_CHANNEL=outbox)
python -m alerting.sns_publisher --setup --email you@example.com   # archived: one-time SNS topic + subscription setup
python -m alerting.sns_publisher --test                             # archived: really publishes to SNS
```

### Ingestion (one-time / on data refresh, in order)
```bash
# Active: local (default WAREHOUSE=duckdb)
python -m ingestion.load_local                      # data/raw/*.csv -> data/warehouse.duckdb (451,535 rows)
python -m ingestion.make_olist_sample               # regenerate the committed CI sample data/fixtures/olist_sample/ (CC BY-NC-SA)
cd dbt_project && dbt build --target local --profiles-dir .   # always pass --profiles-dir .

# Archived: AWS (resources deleted 2026-11-02; code kept intact, never delete it)
python -m ingestion.upload_to_s3
python -m ingestion.setup_redshift_tables   # idempotent, CREATE TABLE IF NOT EXISTS
python -m ingestion.s3_to_redshift
```

### Web app
```bash
python manage.py migrate      # local SQLite, Django auth/sessions only — no business data here
python manage.py runserver    # http://127.0.0.1:8000
streamlit run dashboard/app.py  # legacy dashboard, http://localhost:8501, talks to Redshift directly
```

### Docker / Lambda
```bash
docker build -t metricpulse .
docker run -p 8000:8000 --env-file .env metricpulse
deploy/setup_lambda.sh    # create Lambda fn / IAM role / ECR repo (manual — not wired into CD)
deploy/deploy_lambda.sh   # build image, push to ECR, update Lambda
```

## Conventions Worth Knowing

- Six pipeline layers (`ingestion/` → `dbt_project/` → `detection/` → `decomposition/` → `narrative/` → `alerting/`), coordinated by `orchestration/run_pipeline.py`, connected by plain dict contracts — not classes. Exact shapes are documented in each producer's own folder `README.md`; read it before changing a consumer.
- **AWS code is archived, never deleted** (`docs/local-stack-scope.md` R1). The AWS resources were deleted on 2026-11-02. Local is the default backend (`WAREHOUSE=duckdb`, `ALERT_CHANNEL=outbox`, `CLOUDWATCH_METRICS=false`), and AWS stays a switch. **The SNS topic and AWS credentials still work** (found in L2): `ALERT_CHANNEL=sns` or `sns_publisher --test` really publishes, and in tests set `SNS_TOPIC_ARN=''` rather than unsetting it (`sns_publisher`'s `load_dotenv()` refills a missing var). Don't remove, move or "clean up" AWS files; Kousik restructures the codebase once, at the end of the project.
- **CI:** `dbt-build-local` (`.github/workflows/ci.yml`) is the real dbt gate: `dbt build` on DuckDB against the committed Olist sample `data/fixtures/olist_sample/` (CC BY-NC-SA 4.0, attribution in its README; regenerate with `make_olist_sample`, never hand-edit). `dbt-check` can't fail and is kept as archived. **CD (`cd.yml`) is manual only** (it deploys to the deleted AWS stack), so a merge triggers no CD run.
- Shared infra used by nearly every module: `config/db.py` (the warehouse connection factory: DuckDB by default, Redshift when `WAREHOUSE=redshift`; used everywhere except the legacy Streamlit dashboard, which intentionally connects directly for `@st.cache_resource`'s connection lifecycle — see `config/README.md`), `config/settings.py` (all env vars as constants — don't `os.getenv` ad hoc in new code), `config/logging_config.py` (shared logger). See `config/README.md`.
- `orchestration/run_pipeline.py`'s per-step try/except-never-raise pattern (failure sets `status`/`error` in the result dict, never raises) is the standard error-handling convention for new pipeline code — see `orchestration/README.md`.
- Date strings get validated (`decomposition/decomposer.py`'s `_validate_date()`) before SQL interpolation, since `redshift_connector` doesn't support parameterized queries for the DDL/COPY/date-filtered SQL used here — follow this pattern for any new SQL touching user-supplied values.
- Two independent, non-interchangeable UIs: the Django SPA (production) and the Streamlit app (`dashboard/app.py`, local-only, reimplements its own contribution math rather than calling `decomposition.decomposer`) — see `dashboard/README.md`. A decomposition-math fix needs checking in both places.
- Module invocation is consistently `python -m <package>.<module>` — follow it for new CLI entry points.

## Working on the Agentic-Layer Initiative

This project is being extended for an active job-search portfolio push (context: `docs/Kousik_Market_Gap_Analysis_July2026.md`, kept out of this public repo). New, non-trivial features for that initiative should already be scoped in `docs/scoping.md` before implementation — if a `docs/ROADMAP.md` milestone doesn't have a corresponding scoped section, scope it first rather than jumping straight to code. Check a checkbox only when its gate is actually, verifiably met (a real test run, a real command executed) — not when the code merely looks right.
