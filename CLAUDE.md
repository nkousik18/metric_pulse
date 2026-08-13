# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

MetricPulse is an automated root-cause-analysis pipeline: detects anomalous daily business metrics (z-score), decomposes the change by segment, generates a plain-English narrative, and alerts via SNS — end-to-end in ~10–15s. Exposed via a Django REST API + SPA dashboard (live on Render) and a standalone Lambda handler for scheduled runs; a legacy Streamlit dashboard also exists, unused in prod.

## Session Ritual

**Start every session by reading `docs/project/SESSION_LOG.md` (latest/top entry) and `docs/ROADMAP.md` (checkboxes)** before doing anything else — that's where things actually stopped last time and what's next. **End every session (or a natural mid-session stopping point) by appending** a new dated entry to `SESSION_LOG.md` (what happened, decisions made, current state, next steps, loose ends). Append-only — add above the previous entry, never edit past ones. Full reasoning: `docs/WORKING_CONVENTIONS.md`.

## Documentation Map — Read Before Rediscovering

Don't re-derive architecture from scratch in chat; it's already written down.

- `docs/README.md` — index of one doc per pipeline layer.
- `docs/resume_project_doc.md` — single full source of truth (stats, decisions, known gaps).
- `docs/ROADMAP.md` — which phase the agentic-layer initiative is in, checkbox per milestone.
- `docs/scoping.md` — the section-by-section design spec for that initiative (goals, non-goals, decision log). `ROADMAP.md` tracks whether each part is *built*; this is the *design record* — don't assume a section being designed here means it's implemented.
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
dbt debug              # verify Redshift connection (needs ~/.dbt/profiles.yml)
dbt run                # build all models
dbt test                # run all schema + singular tests
dbt build               # run + test in one step
dbt run --select staging   # or marts / metrics — build a single layer
```

### Pipeline (analytics engine, standalone)
```bash
python -m orchestration.run_pipeline --dry-run                    # full run, no SNS alert sent
python -m orchestration.run_pipeline --force-alert                # send alert regardless of anomaly state
python -m orchestration.run_pipeline --metric order_count --threshold 2.5 --dry-run
python -m orchestration.run_pipeline --dry-run --force-alert --run-investigation  # + agentic investigation (Phase 1)
python -m investigation.eval --runs 5                               # Phase 1 eval suite (real LLM calls, real cost)
python -m onboarding.eval                                           # Phase 2 Golden Case #2 (real LLM call, real cost)
python -m detection.anomaly_detector                               # detection layer alone
python -m alerting.sns_publisher --setup --email you@example.com   # one-time SNS topic + subscription setup
python -m alerting.sns_publisher --test                             # send a test alert
```

### Ingestion (one-time / on data refresh, in order)
```bash
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
- Shared infra used by nearly every module: `config/db.py` (the Redshift connection factory used everywhere except the legacy Streamlit dashboard, which intentionally connects directly for `@st.cache_resource`'s connection lifecycle — see `config/README.md`), `config/settings.py` (all env vars as constants — don't `os.getenv` ad hoc in new code), `config/logging_config.py` (shared logger). See `config/README.md`.
- `orchestration/run_pipeline.py`'s per-step try/except-never-raise pattern (failure sets `status`/`error` in the result dict, never raises) is the standard error-handling convention for new pipeline code — see `orchestration/README.md`.
- Date strings get validated (`decomposition/decomposer.py`'s `_validate_date()`) before SQL interpolation, since `redshift_connector` doesn't support parameterized queries for the DDL/COPY/date-filtered SQL used here — follow this pattern for any new SQL touching user-supplied values.
- Two independent, non-interchangeable UIs: the Django SPA (production) and the Streamlit app (`dashboard/app.py`, local-only, reimplements its own contribution math rather than calling `decomposition.decomposer`) — see `dashboard/README.md`. A decomposition-math fix needs checking in both places.
- Module invocation is consistently `python -m <package>.<module>` — follow it for new CLI entry points.

## Working on the Agentic-Layer Initiative

This project is being extended for an active job-search portfolio push (context: `docs/Kousik_Market_Gap_Analysis_July2026.md`, kept out of this public repo). New, non-trivial features for that initiative should already be scoped in `docs/scoping.md` before implementation — if a `docs/ROADMAP.md` milestone doesn't have a corresponding scoped section, scope it first rather than jumping straight to code. Check a checkbox only when its gate is actually, verifiably met (a real test run, a real command executed) — not when the code merely looks right.
