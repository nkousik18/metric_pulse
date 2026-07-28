# Changelog

What's shipped, in user-facing terms — built from actual commit history, not aspirational. No
version tags exist for this project yet, so entries are dated. See `docs/ROADMAP.md` for what's
planned but not yet shipped, and `docs/project/SESSION_LOG.md` for session-by-session detail.

## 2026-07-28

### Added
- `CLAUDE.md` and a `README.md` in every top-level code folder, for anyone (human or AI) working
  in this codebase.
- `docs/scoping.md` — a full design spec for a planned LangGraph-based agentic layer (design
  only; not implemented).

### Fixed
- Documentation accuracy: unit test count (15, not 13; none are mocked), dbt model/mart counts,
  and two overstated "Future Enhancements" claims in the root README.

## 2026-06-16

### Added
- Full codebase audit: bug fixes and cleanup across the pipeline.
- `docs/` index and `docs/resume_project_doc.md` (single-file project source of truth).

## 2026-04-07

### Added
- Full UI redesign: hero section, visual architecture page, polished dashboard.
- Render deployment configuration; Lambda deployment scripts and cleanup.
- Professional root README with setup instructions.

## 2026-04-05

### Added
- Core analytics engine: z-score anomaly detection, segment decomposition, Jinja2 narrative
  generation, SNS alerting, and the orchestration pipeline tying them together.
- Django REST API and interactive UI with drill-down panels.
- Legacy Streamlit dashboard.
- dbt tests and per-model documentation.
- Docker + AWS Lambda deployment path, with CI/CD pipelines (GitHub Actions).
- CloudWatch monitoring and custom pipeline metrics.
- Architecture and setup documentation.

## 2026-04-02

### Added
- Initial project structure and environment/logging configuration.
- S3 upload script for the raw Olist CSV dataset.
- Redshift schema and raw-table DDL.
- S3 → Redshift data loading pipeline.
- Initial dbt marts layer and project README.
