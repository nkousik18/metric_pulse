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
| [MetricPulse_resume_project_doc.md](MetricPulse_resume_project_doc.md) | Full project source of truth — all layers, all stats, decisions, known gaps (renamed from `resume_project_doc.md`, 2026-11-02) |
| [scoping.md](scoping.md) | Design record for the agentic-layer initiative (Phases 1–3, M0–M7, complete) |
| [action-agent-scope.md](action-agent-scope.md) | Design record for the Action Agent (A1–A7) **and** for observability, LangSmith tracing/replay and the system-wide eval suite (§7.1–7.2, §13) |
| [local-stack-scope.md](local-stack-scope.md) | Design record for the local stack (DuckDB, dbt-duckdb, alert outbox) replacing the deleted AWS resources (L1–L3); AWS code kept as an archived, switchable backend |
| [architecture.md](architecture.md) | System overview and component diagram |
| [workflow_diagram.md](workflow_diagram.md) | End-to-end data flow — Mermaid diagrams + per-step input/output tables across all layers |
| [setup.md](setup.md) | Local development setup and environment variables |
