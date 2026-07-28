# monitoring/

Publishes MetricPulse's own operational health as custom AWS CloudWatch metrics, and can provision a CloudWatch dashboard to visualize them. This is observability for the *pipeline itself* (did it run, did it succeed, did it alert) — not for the business metrics (`total_revenue`, etc.) that the pipeline analyzes.

## Files

| File | Purpose |
|------|---------|
| `cloudwatch_metrics.py` | All CloudWatch integration: publishing custom metrics and creating the dashboard. |
| `__init__.py` | Empty — makes the directory an importable package. |

## Key functions

| Function | Purpose |
|----------|---------|
| `get_cloudwatch_client()` | `boto3.client('cloudwatch', ...)` built from `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` env vars. A fresh client is created on every call — no caching/pooling. |
| `publish_metric(metric_name, value, unit='Count')` | Thin wrapper over `put_metric_data` — publishes one metric point with `Namespace='MetricPulse'` and `Timestamp=datetime.utcnow()`. |
| `publish_pipeline_metrics(results: dict)` | Called by `orchestration.run_pipeline` after each run. Derives and publishes 3 metrics from the pipeline's `results` dict (see below). |
| `create_dashboard()` | One-time setup — creates/overwrites a 3-panel CloudWatch dashboard named `MetricPulse` (`put_dashboard`, idempotent — reruns just replace the same dashboard). |

### Metrics published by `publish_pipeline_metrics`

| Metric name | Value | Derived from |
|-------------|-------|--------------|
| `PipelineExecutionSuccess` | `1` if `results['status'] == 'completed'` else `0` | `results['status']` |
| `AnomaliesDetected` | `results['detection']['anomaly_count']` (default `0` if key missing) | `results['detection']` |
| `AlertsSent` | `1` if `results['alert']['status'] == 'sent'` else `0` | `results['alert']` |

All three calls go through `publish_metric()`, i.e. 3 separate `put_metric_data` API calls per pipeline run (not batched into one call).

## Running standalone

```bash
# One-time: create the 3-panel CloudWatch dashboard
python -m monitoring.cloudwatch_metrics
```

`publish_pipeline_metrics()` is not meant to be invoked directly from the CLI — it's called automatically by `orchestration.run_pipeline.run_pipeline()` when `publish_metrics=True` and `dry_run=False`.

## Env vars

| Var | Default | Used for |
|-----|---------|----------|
| `AWS_REGION` | `us-east-1` | CloudWatch client region |
| `AWS_ACCESS_KEY_ID` | — | boto3 credentials |
| `AWS_SECRET_ACCESS_KEY` | — | boto3 credentials |

## How it connects to other folders

Only consumer: `orchestration/run_pipeline.py`, which imports `publish_pipeline_metrics` **lazily inside the function body** (not at module top), wrapped in its own `try/except` that only logs a WARNING on failure — a CloudWatch outage or missing credentials can never fail the overall pipeline run or change its `status`.

## Gotchas

- `publish_pipeline_metrics` does `results.get('detection', {}).get('anomaly_count', 0)` — if `run_detection()` itself failed and step 1 never populated `results['detection']`, this safely reports `0`, which could understate a failure rather than surfacing it.
- No retry/backoff on `put_metric_data` — any boto3 exception propagates up to orchestration's WARNING-only catch and the metric silently isn't recorded for that run.
- `create_dashboard()` is not called anywhere automatically (not part of `run_pipeline`); it must be run manually once per environment.
