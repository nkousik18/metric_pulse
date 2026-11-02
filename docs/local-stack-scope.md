# MetricPulse Local Stack — Scope

**Status:** Draft for approval · **Owner:** Kousik Nandury · **Date:** 2026-11-02
**Tracked in:** `docs/ROADMAP.md` → "Local Stack" (milestones L1–L3)
**Priority:** ahead of Action Agent A3 (see §9)

## 1. Why this exists

The AWS free trial ended and every AWS resource MetricPulse ran on has been deleted: Redshift
Serverless, S3, SNS, CloudWatch, Lambda, ECR, and the dbt models that lived on Redshift. Render
hosting had already gone. As a result, the original Olist pipeline can no longer run at all:
`config/db.get_connection()` points at a Redshift workgroup that no longer exists, and detection,
decomposition, `run_pipeline`, the Django dashboard and alerting all depend on it.

What still runs, because it never touched AWS: the onboarding path (DuckDB), the investigation
agent, the Action Agent (A1–A2) and the whole pytest suite.

## 2. Goal

Make the full Olist pipeline run again, locally and for free, end to end: raw CSV → dbt →
detection → decomposition → narrative → alert. Do it **without deleting or rewriting any AWS
code**, so the AWS implementation stays in the repo as working evidence of the original
architecture.

## 3. Ground rules (decided by Kousik, 2026-11-02)

- **R1. Never delete AWS code.** S3/Redshift ingestion, `sns_publisher`, `cloudwatch_metrics`,
  `lambda_handler`, `deploy/`, the Lambda `Dockerfile`, the Streamlit dashboard and the CD
  workflow all stay. They are switched off or bypassed, never removed. Code-level restructuring
  happens once, at the end of the project, by Kousik.
- **R2. Local is the default; AWS is a switch.** Every replaced component becomes a choice of
  backend selected in `config/settings.py`. The local backend is the default, and the AWS backend
  is the original code path, unchanged.
- **R3. Only necessary changes.** Change only what's required to make the local pipeline run and
  CI honest. No refactors, no renames, no moving files.
- **R4. Alerts go to a local outbox.** No email or chat service for now.
- **R5. Document everything.** Every touched doc states which implementation is *active (local)*
  and which is *archived (AWS)*, and how to switch.

## 4. Non-goals

- Deleting, moving or restructuring AWS code (R1).
- Hosting anything. Local-only, matching the Action Agent's D9.
- Loading the two Olist tables Redshift never loaded (`geolocation`, `reviews`).
- Porting the legacy Streamlit dashboard (`dashboard/app.py`). It connects to Redshift directly by
  design (see `config/README.md`) and stays an archived, AWS-only component.
- Re-pointing the archived Lambda path at DuckDB. Lambda's filesystem is ephemeral, so it stays a
  Redshift-only component.

## 5. Component status after this work

This table is the map for anyone reading the repo later.

| Component | Active (local) | Archived (AWS), kept intact | Switch |
|---|---|---|---|
| Warehouse | DuckDB file `data/warehouse.duckdb` | Redshift Serverless via `redshift_connector` | `WAREHOUSE=duckdb\|redshift` |
| Raw ingestion | `ingestion/load_local.py`: CSV → `raw_data.*` in DuckDB | `upload_to_s3` → `setup_redshift_tables` → `s3_to_redshift` | which command you run |
| dbt | `dbt-duckdb`, target `local` in a committed `dbt_project/profiles.yml` | `dbt-redshift`, target `redshift` (credentials from env vars) | `dbt build --target local\|redshift` |
| Pipeline alert | Local outbox `outbox/` | SNS `alerting/sns_publisher.py` | `ALERT_CHANNEL=outbox\|sns` |
| Action Agent `notify_owner` (A4) | Outbox, to the owner from `owners.yaml` | — (SNS was the original A4 plan) | `ALERT_CHANNEL` |
| Pipeline metrics | none (local logs only) | CloudWatch `monitoring/cloudwatch_metrics.py` | `--no-metrics` / not called locally |
| Scheduled runs | manual CLI | Lambda + EventBridge (`lambda_handler.py`, `deploy/`) | — |
| Web app | `python manage.py runserver` | Render (gone) | — |
| Legacy dashboard | — | Streamlit `dashboard/app.py` (Redshift only) | — |
| CI dbt | new `dbt-build-local` job: real `dbt build` on a committed sample | existing `dbt-check` (`dbt-redshift` parse, which cannot fail; see §6.5) | both run |
| CD | manual trigger only | `cd.yml` (AWS deploy) | `workflow_dispatch` |

**Archived-path defaults:** when `AWS_LAMBDA_FUNCTION_NAME` is set (that is, code running inside
Lambda), `WAREHOUSE` defaults to `redshift` and `ALERT_CHANNEL` to `sns`. The archived Lambda
image therefore keeps its original behavior with no env changes.

## 6. Design

### 6.1 Warehouse switch (`config/db.py`, `config/settings.py`)

- New settings:
  - `WAREHOUSE`: default `duckdb`, or `redshift` inside Lambda.
  - `WAREHOUSE_PATH`: default `data/warehouse.duckdb`, gitignored.
- `get_connection()` dispatches on `WAREHOUSE`. The existing Redshift body moves unchanged into
  `_redshift_connection()`, and `build_copy_credentials()` is untouched.
- The DuckDB branch opens `duckdb.connect(WAREHOUSE_PATH, read_only=True)`. Every caller of
  `get_connection()` only reads. Writes come from `load_local.py` and dbt, which open their own
  connections. Read-only also means the dashboard and a CLI run can read at the same time. The
  limit is that DuckDB allows one writer, so dbt can't build while a reader holds the file. That
  is documented in `config/README.md`.
- **No change needed in detection or decomposition.** M6 already proved
  `pd.read_sql`/`cursor()`/`close()` and the existing SQL run unchanged on DuckDB, and their
  table names (`staging.fact_daily_metrics`, `staging.metric_by_*`) are what dbt builds in schema
  `staging`.
- A missing `warehouse.duckdb` raises a clear error naming the two setup commands, not a DuckDB
  "file not found".

### 6.2 Local ingestion (`ingestion/load_local.py`, new)

- Loads the same 7 CSV → table mappings the archived `s3_to_redshift.py` uses, imported from
  that module rather than copied, so the two can't drift. It reads them into schema `raw_data`
  with `CREATE OR REPLACE TABLE … AS SELECT * FROM read_csv(...)`. That makes it idempotent and
  safe to re-run.
- Column types follow the archived Redshift DDL (`ingestion/setup_redshift_tables.py`), so
  local tables match what dbt saw on Redshift. Any column where DuckDB's auto-detection would
  differ (zip prefixes, IDs) gets an explicit type. The build compares the two and records any
  real difference in the decision log.
- Prints row counts per table. Gate: they total **451,535**, the Phase 0 figure.

### 6.3 dbt on DuckDB (`dbt_project/`)

- Add `dbt-duckdb` to `requirements.txt`, pinned to a version compatible with the existing
  `dbt-core==1.11.7` and checked with `pip check`. `dbt-redshift` stays.
- New committed `dbt_project/profiles.yml` with two targets:
  - `local` (default): `type: duckdb`, `path: ../data/warehouse.duckdb`, `schema: staging`.
  - `redshift`: `type: redshift`, with host, user and password from `env_var()`, so no secrets
    are committed. This reproduces the archived setup in `~/.dbt/profiles.yml`.

  dbt is run with `--profiles-dir .` so the committed file is used explicitly, never silently
  shadowed by `~/.dbt`.
- **Portability fixes.** Redshift dialect that DuckDB rejects was verified live on 2026-11-02:

  | Where | Redshift form | DuckDB result | Portable form (valid on both) |
  |---|---|---|---|
  | `stg_orders`, `fact_daily_metrics` | `DATE_PART(year, x)` (also `month`, `dow`) | Binder Error: column "year" not found | `EXTRACT(year FROM x)` |
  | `stg_orders`, `tests/assert_dates_continuous.sql` | `DATEDIFF(day, a, b)` | Binder Error: column "day" not found | `{{ dbt.datediff('a', 'b', 'day') }}`, dbt's cross-database macro |
  | `models/staging/schema.yml` source | `database: dev` | DuckDB's catalog is `warehouse` | `database: "{{ target.database }}"` |

  `DATE(x)` works on both and stays. These are the only model edits. Every rewrite is also valid
  Redshift, so the archived target keeps working (R1).

  One subtle difference: Redshift's `DATE_PART` returns a double while `EXTRACT` returns an
  integer. Only `metric_year`, `metric_month` and `day_of_week` are affected, and nothing in the
  Python code does arithmetic on them. This gets checked during the build.
- Gate: `dbt build --target local --profiles-dir .` passes all 11 models and all of
  their tests: the 37 the Phase 0 docs count, plus the 2 singular tests in `dbt_project/tests/`
  if they aren't already part of that 37 (the L1 build reports the real number).

### 6.4 Alerting: local outbox (`alerting/notifier.py`, new)

- `send_alert(subject, body, *, recipient=None, metadata=None, channel=None) -> dict`.
  - `channel` defaults to `ALERT_CHANNEL`: `outbox` (the default), or `sns` inside Lambda.
  - `outbox` writes one Markdown file per message to
    `outbox/YYYY-MM-DD/<HHMMSS>_<slug>.md`, with a front-matter header holding recipient,
    subject, channel and metadata. It also appends one line to `outbox/index.jsonl`.
    `outbox/` is gitignored.
  - `sns` calls the existing `alerting.sns_publisher.publish_metric_alert`, unchanged.
- The return shape matches what SNS returns today (`{'status': 'sent', …}` plus `channel` and
  `path`), so `run_pipeline`'s summary and `cloudwatch_metrics`' `status == 'sent'` check need
  no change.
- **The one wiring change:** `orchestration/run_pipeline.py` step 5 calls
  `notifier.send_alert(...)` with the same narrative it passes SNS today. Under
  `ALERT_CHANNEL=sns` this is byte-for-byte the old behavior.
- `python -m alerting.notifier --test` writes a test message, mirroring
  `sns_publisher --test`.

### 6.5 CI and CD (`.github/workflows/`)

- **The existing `dbt-check` job has never been able to fail.** It runs
  `dbt parse … || echo "…"`, so it reports green whether or not the dbt project parses. It stays,
  untouched (R1), and this doc records that it isn't a real check.
- **New `dbt-build-local` job:** installs `dbt-duckdb`, runs `load_local.py` against a committed
  Olist sample, then runs `dbt build --target local`. This is the real dbt gate, and it fails on
  a broken model or a failing test.
- **The committed sample** is `data/fixtures/olist_sample/`, a deterministic subset (orders from a
  fixed date window plus every row they reference) made by `ingestion/make_olist_sample.py`.
  The target size is a few MB, so CI never needs the 124 MB raw data. Olist is published as CC BY-NC-SA 4.0 (re-check this on the dataset page at L3),
  so the folder carries an attribution and license note. Because of ShareAlike, the sample stays
  under that license; this is a non-commercial portfolio repo.
- **`cd.yml` trigger changes from `push: main` to `workflow_dispatch`** (manual only). It has
  failed on every merge to `main` since at least 2026-08-19, because it needs the deleted AWS
  credentials and environment. Nothing else in the file changes, and it can still be run by hand
  (R1).

### 6.6 Action Agent alignment

These are text-only updates to `docs/action-agent-scope.md`, made in the same PR as L2:
- §4 `notify_owner` and D3: delivery is via `alerting.notifier` (outbox by default), not SNS.
  The pipeline alert and `notify_owner` stay separate messages.
- §13.7: CloudWatch moves from "known gap" to "archived" (R1).
- A4's "GitHub Issue and SNS executors" becomes "GitHub Issue and notifier executors".

## 7. Requirements

- **LS1.** From a fresh clone plus `data/raw/`, these commands, in order and with no cloud
  account, run the whole Olist pipeline:
  1. `python -m ingestion.load_local`
  2. `cd dbt_project && dbt build --target local --profiles-dir .`
  3. `python -m orchestration.run_pipeline --dry-run`
- **LS2.** `python -m orchestration.run_pipeline --force-alert` writes an outbox message and
  reports `alert.status = sent`, `channel = outbox`.
- **LS3.** The Django dashboard's existing endpoints return Olist data from DuckDB.
- **LS4.** No AWS file is deleted or moved. `git diff --stat` on the AWS files shows only
  `config/db.py` (one function split in two, Redshift body unchanged) and the `cd.yml` trigger.
- **LS5.** `pytest tests/` stays green and offline. New code gets tests in the existing style:
  no mocks, a real DuckDB in `tmp_path`, a real outbox directory in `tmp_path`.
- **LS6.** `WAREHOUSE=redshift ALERT_CHANNEL=sns` reproduces the archived behavior. This can't be
  run live any more because the resources are gone, so it is covered by a test that the
  dispatch selects the Redshift and SNS code paths, without connecting.

## 8. Milestones

| # | Deliverable | Gate | Est. |
|---|---|---|---|
| L1 | Warehouse switch, `load_local.py`, `dbt-duckdb` + committed `profiles.yml`, the 3 portability fixes | LS1 and LS3 run live; row total = 451,535; dbt build passes all models and tests | 4h |
| L2 | `alerting/notifier.py` (outbox), `run_pipeline` step 5 wiring, Action Agent scope text updates | LS2 live; outbox file readable; `ALERT_CHANNEL=sns` dispatch test | 2h |
| L3 | Olist sample + `dbt-build-local` CI job, `cd.yml` to manual, docs pass (§10) | CI job passes on the PR, and fails on a deliberately broken model in a throwaway commit (verified once, then reverted); no red CD run on merge | 3h |

**Total: ~9h.** One PR per milestone, following GitHub Flow.

## 9. Ordering relative to the Action Agent

Do L1–L3 **before A3**. A3 itself (the 20b live test, the LLM proposer) could run on Superstore,
but several Action Agent pieces need the Olist path:
- the D6 golden set (15 cases from real Olist anomalies)
- D3 suppression and D4 control evaluation on local pipeline runs
- A4's `notify_owner` target
- the A7 detection eval

The A2 LangSmith verification is independent of this work and can happen whenever the key works.

## 10. Documentation plan (R5)

Every doc below gets updated in the PR that changes its behavior, not saved for the end:
- `config/README.md`: `WAREHOUSE`/`WAREHOUSE_PATH`, the read-only connection and single-writer
  limit, the Lambda defaults.
- `ingestion/README.md`: local vs. archived path, run order, row-count check.
- `dbt_project/README.md`: the committed profile, both targets, `--profiles-dir .`, the
  portability table from §6.3.
- `alerting/README.md`: outbox layout, `ALERT_CHANNEL`, SNS archived.
- `.github/` (in `CONTRIBUTING.md` or the workflow headers): which CI job is the real dbt gate,
  and why CD is manual.
- `CLAUDE.md` Commands section: the local setup sequence first, with the AWS commands kept and
  labeled *archived*.
- `docs/MetricPulse_resume_project_doc.md`: Tech Stack and Deployment describe the local stack as
  current and the AWS stack as what it originally ran on, both true and both kept.
- `docs/ROADMAP.md` and `docs/project/SESSION_LOG.md`: as always.

## 11. Risks

| Risk | Mitigation |
|---|---|
| DuckDB types differ from the Redshift DDL and change a dbt test result | Explicit types per §6.2; the dbt build gate catches it; differences go in the decision log |
| A dbt version mismatch between `dbt-duckdb` and the pinned `dbt-core` | Pin a compatible pair; `pip check` plus `dbt --version` in the L1 PR |
| A reader holds `warehouse.duckdb` while dbt tries to write | Documented; the dashboard opens read-only; the error message tells you to stop the reader |
| Olist sample licensing | CC BY-NC-SA 4.0 attribution and ShareAlike note in the sample folder; non-commercial repo |
| The portable SQL subtly changes the archived Redshift behavior | Each rewrite is documented Redshift syntax; the only known difference is the EXTRACT integer type (§6.3) |

## 12. Decision log

Filled in during the build. One line each: choice — reason.

_(none yet)_
