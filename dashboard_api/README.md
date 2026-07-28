# dashboard_api/

Django REST Framework app that exposes the analytics pipeline (`detection/`, `decomposition/`, `narrative/`, `orchestration/`) as a JSON API. This is the only bridge between the Python pipeline and the browser — the Django SPA in `templates/` calls nothing else. It is a thin adapter layer: every view does request parsing → call a pipeline function → wrap the result in `{status, data}` → return. No business logic lives here.

## File inventory

| File | Purpose |
|------|---------|
| `views.py` | 7 `APIView` classes — the entire API surface |
| `urls.py` | Maps the 7 views to `/api/*` routes, included from `metric_pulse_web/urls.py` under the `api/` prefix |
| `models.py` | Empty (`# Create your models here.`) — this app stores no data of its own; Redshift is the only datastore the pipeline reads/writes |
| `admin.py` | Empty — no models registered |
| `apps.py` | Standard `AppConfig` (`name = 'dashboard_api'`) |
| `tests.py` | Empty — no tests in this app. Django/API-level tests are not part of the 13 tests under `tests/` (those cover `detection/`, `decomposition/`, `narrative/` directly) |

There is no `serializers.py` — responses are built as plain dicts passed straight to `Response()`, no DRF serializer classes are used anywhere in this app.

## Views (`views.py`)

All views import pipeline functions directly (not via subprocess/HTTP) by doing `sys.path.insert(0, str(Path(__file__).parent.parent))` and importing from the project root. Every view wraps its body in `try/except Exception` and returns `{'status': 'error', 'message': str(e)}` with HTTP 500 on failure — there is no granular error typing.

| View | Route | Method | Calls into | Notes |
|------|-------|--------|-----------|-------|
| `HealthCheckView` | `/api/health/` | GET | — | Returns `{status: 'healthy', service, timestamp}`. No DB touch. |
| `MetricsListView` | `/api/metrics/` | GET | `detection.anomaly_detector.fetch_daily_metrics(lookback)` | `?days=` (default 30). Converts `metric_date` to string for JSON. |
| `AnomalyDetectionView` | `/api/anomalies/` | GET | `detection.anomaly_detector.run_detection(metric, threshold)` | `?metric=`, `?threshold=` (float, optional — falls through to env default if omitted). |
| `DecompositionView` | `/api/decomposition/` | GET | `decomposition.decomposer.decompose_metric()`, `get_comparison_dates()` | `?current_date=`, `?previous_date=`, `?metric=`. Auto-picks the latest two dates if either date param is missing. |
| `NarrativeView` | `/api/narrative/` | GET | `decomposition.decomposer.decompose_metric()` + `narrative.generator.generate_narrative()` | **Runs its own decomposition independently of `DecompositionView`** — if a client calls both endpoints for the same page load, `decompose_metric()` (3 Redshift queries) executes twice. `metric` param is not exposed here — always `total_revenue`. |
| `PipelineView` | `/api/pipeline/` | POST | `orchestration.run_pipeline.run_pipeline()` | Body: `{metric, force_alert, dry_run}`. Always passes `publish_metrics=False` so web-triggered runs never double-publish CloudWatch metrics (the CLI path publishes them). **`dry_run` defaults to `True`** here — note this is the opposite of `run_pipeline()`'s own default (`False`); the API is deliberately safer-by-default than the library function. |
| `ContactView` | `/api/contact/` | POST | — | Body: `{name, email, message}`. `message` is required (400 if blank). Currently only `print()`s the submission to stdout/logs — **actual `send_mail()` call is commented out** (lines ~190-196), hardcoded to `recipient_list=['nandury.k@northeastern.edu']`. To enable, uncomment and ensure `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` are set (see `metric_pulse_web/settings.py`). |

## Routes (`urls.py`)

```
GET  /api/health/
GET  /api/metrics/
GET  /api/anomalies/
GET  /api/decomposition/
GET  /api/narrative/
POST /api/pipeline/
POST /api/contact/
```

Included from root `metric_pulse_web/urls.py` via `path('api/', include('dashboard_api.urls'))`.

## Running / testing standalone

There's no way to exercise this app without the Django server — it has no CLI entry point.

```bash
python manage.py runserver
curl http://127.0.0.1:8000/api/health/
curl "http://127.0.0.1:8000/api/metrics/?days=30"
curl -X POST http://127.0.0.1:8000/api/pipeline/ -H "Content-Type: application/json" -d '{"dry_run": true}'
```

A live Redshift connection (correct `.env` / Render env vars) is required for every endpoint except `/api/health/`.

## Config / env dependency

None directly — all env vars (`REDSHIFT_*`, `ANOMALY_THRESHOLD_ZSCORE`, `LOOKBACK_DAYS`, `SNS_TOPIC_ARN`, etc.) are consumed by the pipeline modules this app imports, not by `dashboard_api` itself. The one exception is the (currently dead) `send_mail()` path in `ContactView`, which would need `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` from `metric_pulse_web/settings.py`.

## Gotchas

- **No auth on any endpoint**, including `PipelineView` — anyone who can reach `/api/pipeline/` on the live Render deployment can trigger a real SNS email by POSTing `{"force_alert": true, "dry_run": false}`.
- **`NarrativeView` and `DecompositionView` don't share results** — calling both re-runs the 3-dimension SQL decomposition twice per page load (the SPA's `loadDecomposition()` and `loadNarrative()` in `templates/partials/scripts.html` do exactly this on every dashboard open).
- Every exception is caught and returned as HTTP 500 with `str(e)` — this leaks internal exception messages (e.g. raw SQL/connection errors) to the client. Acceptable for a portfolio project, not for anything handling real credentials.
- `ContactView`'s recipient email is hardcoded in Python, not env-configurable.
