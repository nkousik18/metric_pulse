# Changelog

What's shipped, in user-facing terms — built from actual commit history, not aspirational. No
version tags exist for this project yet, so entries are dated. See `docs/ROADMAP.md` for what's
planned but not yet shipped, and `docs/project/SESSION_LOG.md` for session-by-session detail.

## 2026-11-13

### Added
- **A public demo site:** https://nkousik18.github.io/metric_pulse/. It replays real recorded
  outputs of the pipeline and the AI agents (no server, no LLM calls), including the Action Agent's
  approve → edit → reject → undo walk-through. It republishes on every change to the site.
- `DESIGN.md`: the design system of the redesigned UI, recorded from the shipped code.

### Changed
- The redesigned UI is finished: each tab has its own shareable address, and the finish-review
  fixes landed on Overview, the AI agents tab and phone widths.

## 2026-11-12

### Changed
- Every eval (detection, onboarding, investigation, Action Agent) now has an accepted baseline, and
  the first clean full drift run against them found no regressions. Investigation answers improved
  since their baseline (matching the expected root cause 73% of the time, up from 57%, with no
  fallbacks); the Action Agent picked the right action on all 15 golden cases.
- Changes to `main` now have to pass the real dbt build on DuckDB, not just the lint and tests.
- Added terminal screenshots of the investigation and onboarding agents to `docs/project/demos/`.

### Removed
- The SNS email alert channel no longer works: the AWS topic was deleted and the AWS key turned
  off. Alerts go to the local Markdown outbox, as they have by default since 2026-11-02. The SNS
  code is kept.

## 2026-11-06

### Added
- **A data-freshness alert.** MetricPulse now notices when a day has far fewer records than usual
  (under a quarter of the recent median) and alerts that the data looks incomplete, even when the
  numbers don't look statistically unusual. On the end of the Olist data, where orders slide from
  ~250 a day to 1, the old detector stayed quiet; it now alerts, and says the segment breakdown is
  likely an artefact of missing data. The Action Agent tags such a day as a data issue instead of
  paging anyone. Sparse datasets (under 50 records a day) are skipped.

## 2026-11-04

### Changed
- The Action Agent no longer pages an owner just because their segment is the biggest. It now
  compares each segment's share of a change with its normal share of volume, so Credit Card (most of
  Olist's sales) moving with everything else on Black Friday reads as a broad change to tag, not a
  payments problem. A segment that moved out of proportion still gets its owner notified.
- The Action Agent now knows the calendar. Its evidence shows the weekday of the anomaly and of the
  day it's compared with, and any national holiday or retail event (Black Friday, Mother's Day, ...)
  on or within three days of it, from a fixed calendar per dataset. It tags known-cause anomalies
  more often instead of paging an owner (golden set: 7 of 15 right → 10 of 15).
- A "holiday" or "promotion" tag must now name a real entry in that calendar, or it's refused. A
  segment name claiming a holiday that isn't there can no longer get one through.

## 2026-11-03

### Added
- **Approving actions from the dashboard.** A "Pending actions" tab shows each Action Agent
  proposal with its exact dry run, and lets the approver approve, edit, reject or undo it, with
  the full action log underneath. Behind it, `/api/actions/` endpoints (pending, approve, edit,
  reject, log, undo) that need an approver token, `ACTION_APPROVER_TOKEN` in `.env`; without one
  they are switched off.
- Rate limits on the endpoints that cost money or change state: the AI investigation, the
  pipeline run and the actions API.
- System-wide evals: whether detection alarms at the right times (replaying the pipeline's own
  decision), whether the investigation finds the right cause on 10 cases, whether onboarding
  understands 3 different datasets, and a drift run that compares every eval with its accepted
  baseline. Waiting on hand-labelled answers before their first scored run.

### Fixed
- Onboarding now refuses a classification that "rejects" a column which doesn't exist.

## 2026-08-04

### Added
- `docs/workflow_diagram.md` — end-to-end data-flow reference: system-overview and sequence
  Mermaid diagrams, per-step input/output tables across all six pipeline layers, and a portable
  image-generation prompt.

### Fixed
- A full documentation staleness audit across `CLAUDE.md` and every `docs/` and folder-level
  `README.md`: corrected fabricated function signatures and a wrong dbt test breakdown in
  `docs/resume_project_doc.md`, brought `docs/architecture.md` up to date with the Django layer
  (it predated it entirely), rewrote `docs/WORKING_CONVENTIONS.md` (it was still describing a
  different project, unadapted), and fixed smaller drift in `docs/dashboard_layer.md`,
  `docs/setup.md`, `deploy/README.md`, and two other docs.

## 2026-07-28

### Added
- `CLAUDE.md` and a `README.md` in every top-level code folder, for anyone (human or AI) working
  in this codebase.
- `docs/scoping.md` — a full design spec for a planned LangGraph-based agentic layer (design
  only; not implemented).
- `docs/ROADMAP.md`, `docs/project/SESSION_LOG.md`, `CONTRIBUTING.md`, and `concepts/` (5 seed
  files + index) — session/roadmap/git-workflow scaffolding adopted from another project's
  written-up conventions and adapted for this repo.

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
