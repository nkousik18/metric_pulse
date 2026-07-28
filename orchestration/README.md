# orchestration/

Single entry point that runs the full MetricPulse pipeline end-to-end: detect → decompose → narrate → alert → (optionally) publish ops metrics to CloudWatch. This is the module both the Django `PipelineView` (`dashboard_api/views.py`) and `lambda_handler.py` call to trigger a run — it's the only place in the codebase where all four analytics layers are wired together.

## Files

| File | Purpose |
|------|---------|
| `run_pipeline.py` | The orchestrator. Defines `run_pipeline()`, `print_summary()`, and a CLI (`__main__`). |
| `__init__.py` | Empty — makes the directory an importable package. |

## Key function

### `run_pipeline(metric='total_revenue', threshold=None, force_alert=False, dry_run=False, publish_metrics=True) -> Dict`

Runs 5 steps in strict sequence, all inside one `try/except`:

1. **`run_detection(metric, threshold)`** (`detection.anomaly_detector`) → `detection_results`, and `anomaly_detected = detection_results['anomaly_count'] > 0`
2. **`get_comparison_dates()`** (`decomposition.decomposer`) → `current_date, previous_date`
3. **`decompose_metric(current_date, previous_date, metric)`** (`decomposition.decomposer`) → `decomposition_results`
4. **`generate_narrative(decomposition_results)`** (`narrative.generator`) → `narratives`
5. **Alert, conditionally:**
   - Only runs `publish_metric_alert(narratives)` (`alerting.sns_publisher`) if `anomaly_detected or force_alert`
   - If `dry_run=True`, the alert step is skipped entirely and `results['alert'] = {'status': 'dry_run'}` — no SNS call is made even if an anomaly was detected
   - If no anomaly and `force_alert=False`, `results['alert'] = {'status': 'skipped', 'reason': 'no_anomaly'}`

**Note on decomposition/narrative:** unlike the alert step, decomposition and narrative generation run unconditionally on every call — even when no anomaly was detected. Only the alert send is gated by `anomaly_detected or force_alert`.

**Error handling:** any exception in steps 1–5 is caught once at the top level. `results['status']` is set to `'failed'`, `results['error'] = str(e)` is recorded, and whatever partial results were already accumulated (e.g. `detection` from step 1 if step 3 failed) are preserved and returned — the function never raises. `duration_seconds` is computed in both the success and failure paths.

**CloudWatch publish (after the try/except, separate try/except):** if `publish_metrics=True` **and** `dry_run=False`, imports `monitoring.cloudwatch_metrics.publish_pipeline_metrics` and calls it with the full `results` dict. A failure here is only logged at WARNING level — it can never fail the pipeline or change `results['status']`. Note `publish_metrics` has no effect when `dry_run=True`; CloudWatch publishing is silently skipped in that case regardless of the flag's value.

### `print_summary(results: Dict)`

Pretty-prints status, period, duration, anomaly count, narrative summary, and alert status to stdout. Used only by the CLI entry point, not by API callers.

## Return shape

```python
{
    'started_at': '...', 'metric': 'total_revenue', 'status': 'completed' | 'failed',
    'current_date': '...', 'previous_date': '...',
    'detection': {...},        # from run_detection()
    'decomposition': {...},    # from decompose_metric()
    'narratives': {...},       # from generate_narrative()
    'alert': {...},            # {'status': 'sent'|'dry_run'|'skipped'|'error', ...}
    'completed_at': '...', 'duration_seconds': 14.8,
    'error': '...'             # only present if status == 'failed'
}
```

## Running standalone

```bash
# Dry run — full pipeline, no SNS alert sent, no CloudWatch publish
python -m orchestration.run_pipeline --dry-run

# Force an alert regardless of anomaly detection
python -m orchestration.run_pipeline --force-alert

# Custom metric/threshold
python -m orchestration.run_pipeline --metric order_count --threshold 2.5 --dry-run

# Skip CloudWatch publishing (still sends alert if anomaly/force-alert)
python -m orchestration.run_pipeline --no-metrics --force-alert
```

CLI flags map directly to `run_pipeline()` kwargs: `--metric`, `--threshold`, `--force-alert` → `force_alert=True`, `--dry-run` → `dry_run=True`, `--no-metrics` → `publish_metrics=False`. If `run_pipeline()` itself raises (it shouldn't, given the internal try/except, but the CLI wraps the call in its own try/except as a backstop), the script logs the error and exits with code 1.

## Env vars

None read directly by this file — `load_dotenv()` is called so that downstream modules (`detection`, `alerting`, `monitoring`) can read their own env vars (`ANOMALY_THRESHOLD_ZSCORE`, `LOOKBACK_DAYS`, `SNS_TOPIC_ARN`, AWS credentials, etc.) when they're imported and run.

## Dependencies on other folders

`config.logging_config`, `detection.anomaly_detector`, `decomposition.decomposer`, `narrative.generator`, `alerting.sns_publisher`, and (lazily, inside the function body — not at module import time) `monitoring.cloudwatch_metrics`. The lazy import of `monitoring` means a broken/missing monitoring module would only surface at runtime after the pipeline already completed, not at import time.

## Gotchas

- `sys.path.insert(0, str(Path(__file__).parent.parent))` at the top means this module assumes it's being run from within the repo tree; if imported from elsewhere the path hack still points at the correct repo root via `__file__`, but it's a repo-relative-import pattern repeated in several other top-level modules (not centralized).
- `threshold=None` is passed straight through to `run_detection()` — this module does not read `ANOMALY_THRESHOLD_ZSCORE` itself; that fallback lives in `detection/anomaly_detector.py`.
