# MetricPulse Documentation

Technical reference for the MetricPulse automated root cause analysis pipeline.

---

## Layers

| # | Layer | File | What it covers |
|---|-------|------|----------------|
| 1 | Ingestion | [ingestion_pipeline.md](ingestion_pipeline.md) | S3 upload, Redshift table creation, COPY command, 9 CSV files / 451K rows |
| 2 | dbt Transformations | [dbt_transformations.md](dbt_transformations.md) | 11 models, 37 tests, 3-layer architecture (staging → marts → metrics) |
| 3 | Anomaly Detection | [detection_layer.md](detection_layer.md) | Z-score algorithm, 30-day lookback, 4 supported metrics |
| 4 | Analytics Pipeline | [analytics_pipeline.md](analytics_pipeline.md) | Decomposition, narrative generation, SNS alerting, orchestration |
| 5 | Infrastructure & Deployment | [infrastructure_and_deployment.md](infrastructure_and_deployment.md) | Django API, CI/CD, Render, Lambda, CloudWatch |
| 6 | Dashboard | [dashboard_layer.md](dashboard_layer.md) | Django SPA (primary) and Streamlit (legacy) |

## Reference

| File | What it covers |
|------|----------------|
| [architecture.md](architecture.md) | System overview and component diagram |
| [setup.md](setup.md) | Local development setup and environment variables |
