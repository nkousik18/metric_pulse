# Infrastructure & Deployment

Covers the monitoring layer, Django web application, CI/CD pipelines, and deployment targets (Render, Lambda).

---

## Monitoring (`monitoring/cloudwatch_metrics.py`)

Publishes operational metrics to AWS CloudWatch after each pipeline run. Called by `orchestration/run_pipeline.py` inside a try/except — a failure here never blocks the pipeline.

### Metrics published (namespace: `MetricPulse`)

| Metric name | Unit | Value |
|-------------|------|-------|
| `PipelineExecutionSuccess` | Count | `1` if status=completed, `0` if failed |
| `AnomaliesDetected` | Count | Number of anomalies found in the window |
| `AlertsSent` | Count | `1` if SNS alert was sent, `0` otherwise |

All metrics are published with a 1-day aggregation period (`period: 86400`).

### CloudWatch dashboard

`create_dashboard()` creates a 3-panel dashboard named `MetricPulse` in CloudWatch, one panel per metric above. Run once to set it up:

```bash
python -m monitoring.cloudwatch_metrics
```

### When it runs

`publish_pipeline_metrics(results)` is called at the end of `run_pipeline()` when `publish_metrics=True` (the default). The API endpoint (`PipelineView`) sets `publish_metrics=False` to avoid double-publishing from web requests.

---

## Django Web Application

### Settings hierarchy

| File | Used when |
|------|-----------|
| `metric_pulse_web/settings.py` | Local development |
| `metric_pulse_web/settings_prod.py` | Render deployment (imports `settings.py` then overrides) |

`settings_prod.py` is activated via the `DJANGO_SETTINGS_MODULE` environment variable, which is set in `render.yaml`.

### `settings.py` — key configuration

| Setting | Value | Notes |
|---------|-------|-------|
| `SECRET_KEY` | from `DJANGO_SECRET_KEY` env | Falls back to a hardcoded dev key — never use in prod |
| `DEBUG` | from `DJANGO_DEBUG` env | Default `True` in dev |
| `ALLOWED_HOSTS` | `['localhost', '127.0.0.1', '*']` | Wildcard is acceptable in dev |
| `DATABASES` | SQLite (`db.sqlite3`) | Django auth/sessions only — no business data |
| `CORS_ALLOW_ALL_ORIGINS` | `True` when `DEBUG=True` | CORS locked down automatically in prod |
| `STATIC_ROOT` | `staticfiles/` | Target for `collectstatic` |
| `STATICFILES_DIRS` | `static/` | Source for custom CSS/JS |

### `settings_prod.py` — overrides for Render

| Setting | Value |
|---------|-------|
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `['.onrender.com']` |
| WhiteNoise middleware | Inserted at position 1 (serves static files without a CDN) |
| `STATICFILES_STORAGE` | `CompressedManifestStaticFilesStorage` — fingerprinted filenames for cache-busting |
| `SECURE_PROXY_SSL_HEADER` | `('HTTP_X_FORWARDED_PROTO', 'https')` — trusts Render's TLS termination proxy |

### URL routing

```
/                   →  templates/index.html  (TemplateView)
/admin/             →  Django admin
/api/health/        →  HealthCheckView
/api/metrics/       →  MetricsListView        GET ?days=30
/api/anomalies/     →  AnomalyDetectionView   GET ?metric=total_revenue&threshold=2.0
/api/decomposition/ →  DecompositionView      GET ?current_date=&previous_date=&metric=
/api/narrative/     →  NarrativeView          GET ?current_date=&previous_date=
/api/pipeline/      →  PipelineView           POST {metric, force_alert, dry_run}
/api/contact/       →  ContactView            POST {name, email, message}
```

### API endpoints

| Endpoint | Method | Key params | Returns |
|----------|--------|------------|---------|
| `/api/health/` | GET | — | `{status, service, timestamp}` |
| `/api/metrics/` | GET | `days` (default 30) | Daily metrics array from `fact_daily_metrics` |
| `/api/anomalies/` | GET | `metric`, `threshold` | Detection results with anomaly list |
| `/api/decomposition/` | GET | `current_date`, `previous_date`, `metric` | Full decomposition dict |
| `/api/narrative/` | GET | `current_date`, `previous_date` | All 4 narrative formats |
| `/api/pipeline/` | POST | `metric`, `force_alert`, `dry_run` | Pipeline summary |
| `/api/contact/` | POST | `name`, `email`, `message` | Logs submission (email sending disabled) |

### Running locally

```bash
# Apply migrations (creates db.sqlite3 for Django sessions/admin)
python manage.py migrate

# Start dev server
python manage.py runserver
# → http://127.0.0.1:8000
```

---

## CI/CD (`.github/workflows/`)

### CI Pipeline (`ci.yml`)

Triggers on push and pull requests to `develop` and `main`.

**Two parallel jobs:**

| Job | Steps |
|-----|-------|
| `lint-and-test` | Checkout → Python 3.12 → pip cache → install deps → flake8 lint → pytest |
| `dbt-check` | Checkout → install dbt-redshift → `dbt parse` (syntax validation only) |

**Linting strategy (flake8):**

| Pass | Flags | Behaviour |
|------|-------|-----------|
| Hard errors | `--select=E9,F63,F7,F82` | Syntax errors, undefined names — **fails CI** |
| Style warnings | `--exit-zero --max-line-length=120` | Non-blocking — reports but does not fail |

**Tests:** Runs `pytest tests/ -v --tb=short` — CI fails if any test fails. 3 test files, 13 tests total.

**pip caching:** Keyed on `requirements.txt` hash — cache hit on unchanged dependencies saves ~60 seconds per run.

### CD Pipeline (`cd.yml`)

Triggers on push to `main` only. Requires `production` environment approval.

**Steps:** Checkout → Python 3.12 → install dependencies → configure AWS credentials → dbt run step (currently a placeholder — see note below) → deploy notification.

**Note:** The dbt step echoes a comment but does not execute `dbt run`. This is because `dbt run` requires a live Redshift connection and a `profiles.yml` with credentials. In the current setup, dbt transformations are run manually when the source data changes. Adding automated dbt runs to CD would require injecting Redshift credentials as GitHub secrets and providing a CI-specific `profiles.yml`.

---

## Deployment Targets

### Render (primary — live at `metricpulse-h9lu.onrender.com`)

| Setting | Value |
|---------|-------|
| Service type | Web |
| Runtime | Python 3.12 |
| Build command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Start command | `gunicorn metric_pulse_web.wsgi:application --bind 0.0.0.0:$PORT` |
| Settings module | `metric_pulse_web.settings_prod` |
| Secret key | Auto-generated by Render |

**Required env vars on Render** (set manually in Render dashboard):

```
DJANGO_SETTINGS_MODULE=metric_pulse_web.settings_prod
DJANGO_SECRET_KEY=<auto-generated>
DJANGO_DEBUG=false
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET_NAME=...
REDSHIFT_HOST=...
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=...
REDSHIFT_PASSWORD=...
SNS_TOPIC_ARN=...
ANOMALY_THRESHOLD_ZSCORE=2.0
LOOKBACK_DAYS=30
```

### AWS Lambda (analytics pipeline only)

The `Dockerfile` and `lambda_handler.py` package the analytics pipeline (not Django) as a Lambda function triggered by AWS EventBridge for scheduled runs.

**Dockerfile base:** `public.ecr.aws/lambda/python:3.12`

**Modules included in Lambda image:**

```
config/         detection/      decomposition/
narrative/      alerting/       orchestration/
lambda_handler.py
```

Django, dbt, and ingestion code are excluded — Lambda only runs the detection→decomposition→narrative→alert pipeline.

**Lambda event schema:**

```json
{
  "metric":       "total_revenue",
  "force_alert":  false,
  "dry_run":      false
}
```

**Lambda response:**

```json
{
  "statusCode": 200,
  "body": {
    "status":        "completed",
    "metric":        "total_revenue",
    "anomaly_count": 2,
    "alert_status":  "sent",
    "summary":       "Total Revenue decreased 90.6% on 2018-09-03...",
    "executed_at":   "2018-09-04T08:00:15"
  }
}
```

**Deploy scripts** (in `deploy/`):

```bash
deploy/setup_lambda.sh    # Create Lambda function, IAM role, ECR repo
deploy/deploy_lambda.sh   # Build Docker image, push to ECR, update Lambda
deploy/setup_schedule.sh  # Create EventBridge rule for scheduled runs
```

---

## Dependencies (`requirements.txt`)

97 packages. Key direct dependencies:

| Package | Version | Purpose |
|---------|---------|---------|
| `Django` | 6.0.3 | Web framework |
| `djangorestframework` | 3.17.1 | REST API views |
| `django-cors-headers` | 4.9.0 | CORS for API access |
| `gunicorn` | 25.3.0 | WSGI server for production |
| `whitenoise` | 6.12.0 | Static file serving in prod |
| `boto3` | 1.42.81 | AWS SDK (S3, SNS, CloudWatch) |
| `redshift_connector` | 2.1.13 | Redshift connection |
| `pandas` | 3.0.2 | DataFrame processing |
| `numpy` | 2.4.4 | Z-score arithmetic |
| `dbt-redshift` | 1.10.1 | dbt transformations |
| `Jinja2` | 3.1.6 | Narrative template rendering |
| `python-dotenv` | 1.2.2 | `.env` file loading |
| `pytest` | 9.0.2 | Unit testing |
| `streamlit` | 1.56.0 | Legacy dashboard (not active in prod) |
| `scikit-learn` | 1.8.0 | Available for future ML-based detection |

---

## Issues Fixed

| Area | Issue | Fix |
|------|-------|-----|
| `render.yaml` | `DJANGO_SETTINGS_MODULE` not set — `settings_prod.py` never loaded; WhiteNoise and HTTPS settings inactive on Render | Added `DJANGO_SETTINGS_MODULE=metric_pulse_web.settings_prod` to env vars; added `collectstatic` to build command |
| `settings_prod.py` | `ALLOWED_HOSTS = ['*', '.onrender.com']` — wildcard unnecessary and overly permissive in prod | Changed to `['.onrender.com']` only |
| `ci.yml` | `pytest ... \|\| echo "..."` swallowed test failures — CI passed even when tests failed | Removed `\|\| echo ...`; CI now fails correctly on test failure |
| `requirements.txt` | `scipy` listed as a dependency but removed as unused from `anomaly_detector.py` | Removed from requirements |

---

## Known Gaps

| Gap | Notes |
|-----|-------|
| CD dbt step is a placeholder | `dbt run` is commented out — transformations require manual execution when data changes |
| No `collectstatic` in CI | Static files are only collected on Render build, not verified in CI |
| Contact form email sending disabled | `ContactView` logs submissions but the `send_mail` call is commented out — requires `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` in env |
| Lambda deploy not automated | `deploy/` scripts exist but CD pipeline does not invoke them — Lambda deploys are manual |
