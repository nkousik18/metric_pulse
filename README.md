# MetricPulse

**Automated Root Cause Analysis Engine**

When business metrics move unexpectedly, MetricPulse automatically identifies what drove the change — before anyone asks.

🔗 **Demo:** https://nkousik18.github.io/metric_pulse/ — a static site that replays real recorded outputs (no server, no LLM calls). A live demo-mode app is planned (`docs/hosting-scope.md`).

**Status:** core pipeline (ingestion → dbt → detection → decomposition → narrative → alerting) is stable and runs locally (DuckDB + dbt-duckdb). On top of it sit three LangGraph / LLM agents, all built and evaluated: an **Investigation Agent** (explains an anomaly with every number checked against the data), a **Dataset Onboarding Agent** (points the pipeline at a new CSV) and an **Action Agent** (proposes a response and waits for human approval). See `docs/ROADMAP.md` for what's built vs. planned.

---

## The Problem

Every analyst has heard: *"Revenue dropped 15% yesterday — why?"*

The typical answer takes **2-4 hours**:
- Pull data from multiple systems
- Slice by region, product, channel
- Build spreadsheets manually
- Write email explaining findings

## The Solution

MetricPulse automates the entire workflow in **under 30 seconds**:
- **Detect** — Statistical anomaly detection using Z-score analysis
- **Decompose** — Break down changes across geography, product, and payment dimensions
- **Explain** — Generate plain-English narrative automatically
- **Alert** — Proactive alert before anyone asks (local Markdown outbox by default; AWS SNS archived)
- **Investigate** — An LLM agent drills into the segments that moved and writes a cited explanation
- **Act** — An LLM agent proposes a response from a fixed catalog; nothing runs until a human approves

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA INGESTION                              │
│  Kaggle Dataset → S3 (raw/) → Redshift (raw_data schema)           │
│  451K rows, 7 tables                                                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      dbt TRANSFORMATION                             │
│  staging/           marts/               metrics/                   │
│  • stg_orders       • fact_daily_metrics • metric_by_geography     │
│  • stg_order_items  • dim_geography      • metric_by_product       │
│  • stg_customers    • dim_product        • metric_by_payment       │
│  • stg_products     • dim_payment                                  │
│                                                                     │
│  11 models │ 37 automated tests │ 100% pass rate                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DETECTION & ANALYSIS                            │
│  Anomaly Detector ──→ Decomposer ──→ Narrative Generator           │
│  (Z-score)            (3 dimensions)   (Jinja2 templates)          │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        DELIVERY LAYER                               │
│       SNS Email Alerts  │  Django REST API  │  Dashboard UI        │
└─────────────────────────────────────────────────────────────────────┘
```

### AI agent layer

```
 anomaly (detection + decomposition evidence)
        │
        ▼
┌──────────────────────── INVESTIGATION AGENT (LangGraph) ────────────────────────┐
│ detect → decompose_all → assess_ambiguity → drill_down → synthesize → finalize  │
│ Groq gpt-oss-120b, structured output; every cited number is validated against   │
│ the decomposition before the answer is shown (deterministic fallback otherwise) │
└─────────────────────────────────────────────────────────────────────────────────┘
        │ validated investigation
        ▼
┌─────────────────────────── ACTION AGENT (LangGraph) ────────────────────────────┐
│ check_existing → propose → register → policy_check ─┬─ T0 → execute ─┐          │
│                                                     └─ T1 → await_approval      │
│                                                        (interrupt(), a human)   │
│                         approve / approve with edits ─→ execute ─→ record       │
│                         reject or expire (24h TTL)   ─→ record                  │
│ propose:  gpt-oss-20b drafts → one escalation to gpt-oss-120b → deterministic   │
│           fallback, under a 10k-token budget; evidence passed as a data block   │
│ policy:   fails closed — in catalog? tier allowed? params pass schema + range   │
│           checks? segment must exist in the evidence; holiday claims must match │
│           the trusted event calendar                                            │
│ execute:  idempotent executors; reversible actions can be undone                │
│ record:   append-only action_log in SQLite (trigger-enforced), SQLite           │
│           checkpointer, LangSmith tracing, decision replay                      │
└─────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────── DATASET ONBOARDING AGENT ────────────────────────┐
│ profile CSV (deterministic) → LLM classifies date / grain / metrics /    │
│ dimensions → human confirms → generated dbt-style SQL → the same detect, │
│ decompose, narrate (and investigate) pipeline on the new dataset         │
└──────────────────────────────────────────────────────────────────────────┘
```

**Action catalog** (`action_agent/catalog.py`): every action needs approval (tier T1); T2 actions can never run.

| Action | Reversible | What it does |
|---|---|---|
| `annotate_anomaly` | yes | Tags the anomaly with a category and cause (e.g. a calendar event) |
| `suppress_alerts` | yes | Mutes alerts for the metric for 1–7 days, with a reason |
| `notify_owner` | no | Notifies the owner of the driving segment (via the alert outbox) |
| `open_incident` | yes | Opens a GitHub Issue (only with `--live`) |
| `create_control` | yes | Adds a watch threshold on a segment, expiring in 1–30 days |

Approvals happen in the dashboard's AI agents tab or the CLI (`python -m action_agent.cli`), behind an approver token.

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Data Storage** | AWS S3, AWS Redshift Serverless |
| **Transformation** | dbt (11 models, 37 tests) |
| **Backend** | Python, Django REST Framework |
| **Detection** | NumPy, pandas (Z-score analysis) |
| **Alerting** | Local Markdown outbox (default); AWS SNS (archived, `ALERT_CHANNEL=sns`) |
| **Frontend** | Hand-written CSS design system (light + dark, see `DESIGN.md`), Chart.js |
| **Containerization** | Docker |
| **CI/CD** | GitHub Actions |
| **Local warehouse** | DuckDB + dbt-duckdb (default); Redshift kept as a switch (`WAREHOUSE=redshift`) |
| **Agents** | LangGraph (state graphs, `interrupt()` approvals, SQLite checkpointer), Pydantic |
| **LLMs** | Groq: gpt-oss-120b (investigation, onboarding, escalation), gpt-oss-20b (action drafts) |
| **Observability** | LangSmith tracing, per-call token / cost / latency telemetry, eval ledger + drift check |
| **Hosting** | GitHub Pages (static replay of real recorded outputs); Render (previous, removed) |

---

## Project Structure

```
metric_pulse/
├── config/                  # Configuration and settings
│   ├── settings.py
│   └── logging_config.py
├── ingestion/               # Data ingestion scripts
│   ├── upload_to_s3.py
│   ├── s3_to_redshift.py
│   └── setup_redshift_tables.py
├── detection/               # Anomaly detection
│   └── anomaly_detector.py
├── decomposition/           # Metric decomposition
│   └── decomposer.py
├── narrative/               # Narrative generation
│   ├── generator.py
│   └── templates/
├── alerting/                # alert delivery
│   ├── notifier.py          # ALERT_CHANNEL switch + local outbox (default)
│   └── sns_publisher.py     # archived AWS SNS channel
├── orchestration/           # Pipeline orchestration
│   └── run_pipeline.py
├── monitoring/              # CloudWatch metrics
│   └── cloudwatch_metrics.py
├── dashboard_api/           # Django REST API
│   ├── views.py
│   └── urls.py
├── metric_pulse_web/        # Django project settings
├── templates/               # Frontend templates
│   ├── base.html
│   ├── index.html
│   └── partials/
├── dbt_project/             # dbt models and tests
│   ├── models/
│   └── tests/
├── investigation/           # Investigation Agent (LangGraph): nodes, routing, citation validation, eval
├── action_agent/            # Action Agent: catalog, policy_check, graph, store, executors, CLI, evals
│   └── calendars/           # trusted per-dataset event calendars
├── onboarding/              # Dataset Onboarding Agent: profiling, LLM classification, codegen, eval
├── detection/eval.py        # detection eval against hand-labelled dates
├── observability/           # LangSmith tracing, LLM telemetry, eval ledger, drift, scorecard
├── evals/                   # eval sets, baselines and ledger.jsonl (every eval run, append-only)
├── demo/                    # static replay site: recorder, builder, recordings, replay.js
├── dashboard_api/action_views.py  # /api/actions/* endpoints (approve / edit / reject / undo)
├── data/fixtures/olist_sample/    # committed sample for CI's dbt build (CC BY-NC-SA 4.0)
├── concepts/                # one file per idea (state graphs, LLM grounding, ...)
├── DESIGN.md                # the UI design system
├── tests/                   # Unit tests
├── .github/workflows/       # CI/CD pipelines
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- AWS Account (S3, Redshift, SNS)
- dbt CLI

### 1. Clone the Repository

```bash
git clone https://github.com/nkousik18/metric_pulse.git
cd metric_pulse
```

### 2. Create Virtual Environment

```bash
python -m venv metric_venv
source metric_venv/bin/activate  # On Windows: metric_venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
# AWS Credentials
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1

# S3
S3_BUCKET_NAME=your-bucket-name

# Redshift
REDSHIFT_HOST=your-workgroup.region.redshift-serverless.amazonaws.com
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=admin
REDSHIFT_PASSWORD=your_password

# SNS
SNS_TOPIC_ARN=arn:aws:sns:region:account:topic-name

# Django
DJANGO_SECRET_KEY=your_secret_key
DJANGO_DEBUG=True

# Pipeline
ANOMALY_THRESHOLD_ZSCORE=2.0
LOOKBACK_DAYS=30
```

### 4. Set Up AWS Infrastructure

```bash
# Upload raw data to S3
python -m ingestion.upload_to_s3

# Create Redshift tables and load data
python -m ingestion.setup_redshift_tables
python -m ingestion.s3_to_redshift
```

### 5. Run dbt Transformations

```bash
cd dbt_project
dbt deps
dbt run
dbt test
```

### 6. Run the Application

```bash
# Run Django server
python manage.py migrate
python manage.py runserver

# Access at http://127.0.0.1:8000
```

### 7. Run the Pipeline

```bash
# Dry run (no alerts)
python -m orchestration.run_pipeline --dry-run

# Full run with alerts
python -m orchestration.run_pipeline --force-alert
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health/` | GET | Health check |
| `/api/metrics/` | GET | Fetch daily metrics |
| `/api/anomalies/` | GET | Detect anomalies |
| `/api/decomposition/` | GET | Decompose metric changes |
| `/api/narrative/` | GET | Generate root cause narrative |
| `/api/pipeline/` | POST | Trigger pipeline run |
| `/api/investigate/` | POST | Run the Investigation Agent on an anomaly |
| `/api/actions/pending/` | GET | Action proposals waiting for a decision |
| `/api/actions/log/` | GET | Append-only action log |
| `/api/actions/<id>/approve/` | POST | Approve a proposal (approver token) |
| `/api/actions/<id>/edit/` | POST | Approve with edited params |
| `/api/actions/<id>/reject/` | POST | Reject, with a reason |
| `/api/actions/<id>/undo/` | POST | Undo a reversible executed action, with a reason |
| `/api/contact/` | POST | Submit contact form |

---

## Key Metrics

| Metric | Value |
|--------|-------|
| Data Volume | 451K rows |
| dbt Tests | 37 |
| Unit Tests | 401 (pure functions, no mocking) |
| Pipeline Speed | < 5 seconds |
| Time Saved | 99.6% (2 hrs → 30 sec) |
| API Endpoints | 14 |
| dbt Models | 11 |
| LLM Agents | 3 (investigation, onboarding, action) |
| Action Agent cost | ~$0.0004 per proposal, p95 latency 3.5 s |

### Evals

Every agent is scored by a repeatable eval against hand-labelled cases. Each run is appended to
`evals/ledger.jsonl` and compared with an accepted baseline (`python -m observability.drift`).
Latest runs (2026-11-12), weak numbers included:

| Eval | Result |
|---|---|
| **Action Agent: golden cases** | right action picked in **15/15**; all 15 grounded on the first attempt; 0 escalations, 0 fallbacks, 0 idempotency violations |
| **Action Agent: prompt injection** | **0/10** adversarial cases got an injected instruction through; all 10 held for approval |
| **Action Agent: safety probes** | **0/20** actions ran without approval; a fake holiday in the data was not accepted |
| **Investigation Agent** | every cited claim checked out in **25/30** runs (83%); named the expected root cause in **22/30** (73%); 0 fallbacks, 0 API errors |
| **Detection** (28 labelled dates) | precision 0.92, recall 0.92, F1 0.92; with the data-freshness check: recall 1.00, F1 0.96 |
| **Onboarding** (6 runs, 3 datasets incl. an adversarial CSV) | date column, grain and metrics right 6/6; dimensions 3/6, rejected columns 4/6; every answer grounded |

Commands: `python -m action_agent.eval`, `python -m investigation.eval`, `python -m detection.eval`,
`python -m onboarding.eval` (see `evals/README.md`).

---

## Documentation

Deeper reference lives in [`docs/`](docs/README.md) — one file per pipeline layer, plus `docs/resume_project_doc.md` (full source of truth), `docs/ROADMAP.md` (what's built vs. planned), and `docs/scoping.md` (in-progress agentic-layer design). Every top-level code folder (`ingestion/`, `dbt_project/`, `detection/`, etc.) also has its own `README.md` with file-by-file detail. [`concepts/`](concepts/INDEX.md) explains the ideas behind the newer, less-obvious parts of the system (state graphs, LLM grounding) in plain language. `CHANGELOG.md` tracks what's shipped; `CONTRIBUTING.md` covers the branch/PR workflow. `CLAUDE.md` is the entry point for AI coding assistants working in this repo.

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html
```

---

## Deployment

### Deploy to Render

1. Connect GitHub repository to Render
2. Configure environment variables
3. Deploy automatically on push to `main`

### Docker

```bash
# Build image
docker build -t metricpulse .

# Run container
docker run -p 8000:8000 --env-file .env metricpulse
```

---

## Future Enhancements

- [ ] Automate Lambda deployment in CD (`deploy/` scripts exist and work manually; CD doesn't invoke them yet)
- [ ] Additional decomposition dimensions
- [ ] Slack integration for alerts
- [ ] Automated `dbt run` in CD on data refresh (currently manual; EventBridge scheduling for the analytics pipeline itself already exists via `deploy/setup_schedule.sh`)
- [ ] ML-based anomaly detection

---

## Author

**Kousik Nandury**

-  MS Data Analytics Engineering, Northeastern University
-  2 years experience at Capgemini
-  [LinkedIn](https://www.linkedin.com/in/kousik-nandury)
-  [GitHub](https://github.com/nkousik18)
-  kousik.nandury@gmail.com

---

## License

This project is for portfolio and educational purposes.