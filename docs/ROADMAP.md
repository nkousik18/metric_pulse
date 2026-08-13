# Roadmap

Which phase MetricPulse is in, and what's actually left before the next one can be called done.
Not a calendar — paced by real availability alongside an active job search, not by a date. A
checkbox here only gets checked when its phase gate is actually, verifiably met (a real test
passing, a real command run against real output) — not when time budgeted for it runs out, and
not on the strength of a design that hasn't been run yet. See `docs/WORKING_CONVENTIONS.md` for
the full reasoning behind how this file is kept.

Phase 1–3 below are the direct implementation of `docs/scoping.md`'s Section 10 rollout plan —
this file tracks the same milestones (M0–M7) as living, checkable progress; `docs/scoping.md`
stays the design record and doesn't get re-edited as implementation proceeds.

---

## Phase 0 — Core Pipeline (done)

**Gate:** ingestion → dbt → detection → decomposition → narrative → alerting works end-to-end,
is tested, and is live.

- [x] Ingestion: S3 → Redshift, 451,535 rows across 7 tables (`ingestion/`)
- [x] dbt: 11 models, 37 tests, staging → marts → metrics (`dbt_project/`)
- [x] Detection: z-score anomaly flagging (`detection/`)
- [x] Decomposition: segment contribution analysis (`decomposition/`)
- [x] Narrative: Jinja2 → 4 output formats (`narrative/`)
- [x] Alerting: SNS email (`alerting/`)
- [x] Orchestration: single-entry-point pipeline (`orchestration/`)
- [x] Django REST API + SPA dashboard, live on Render (`dashboard_api/`, `templates/`)
- [x] CI (lint + test + dbt parse), CD to Render
- [x] 15 unit tests, all pure-function, no mocking

**Named gaps, not silently dropped** (full list: `docs/infrastructure_and_deployment.md`
Known Gaps, `docs/resume_project_doc.md` §12):
- CD's `dbt run` step is a placeholder — transformations are run manually on data refresh.
- Contact form email sending is disabled (`send_mail` commented out).
- Lambda deploy scripts exist and work but aren't invoked by CD — manual only.
- The dashboard's drill-down "Details" toggle is dead code — shows/hides an empty `<div>`,
  nothing populates it. (Phase 1 below is expected to finally give this real data to show.)

---

## Phase 1 — Investigation Agent (`docs/scoping.md` §§2–4)

**Gate:** a real LangGraph agent, wired into `orchestration/run_pipeline.py` and
`/api/investigate/`, produces a grounded investigation summary for a real anomaly — every
citation in it validated against actual `decomposition_results`/`drill_down_results`, not
trusted on the model's word — and the existing 15 tests still pass unmodified.

- [x] **M0** — `investigation/` skeleton: state schema, 5 deterministic nodes + 3 routing
      functions, tool wrappers around unchanged `detection`/`decomposition`/`narrative` calls,
      the one new `fetch_detail_metrics()` in `decomposer.py`. `test_investigation_routing.py`,
      `test_ambiguity_rules.py` passing.
- [x] **M1** — `synthesize`: structured-output LLM call, `validate_citation`, bounded
      retry/fallback, Jinja rendering. `test_citation_validation.py` passing; Golden Case #1
      (`docs/scoping.md` §3.8) run for real, not just designed on paper.
- [x] **M2** — Integration: `run_pipeline(run_investigation=...)`, `/api/investigate/`,
      `PipelineView` extension, dashboard button, Lambda passthrough. Full existing test suite
      re-run and green — this milestone touches the most call sites.
- [x] **M3** — `investigation.eval` command formalized; Section 8.5's metrics (grounding pass
      rate, fallback rate, golden-driver match rate) recorded from a real run, not estimated.

**Deferred, and why** (see `docs/scoping.md` for the reasoning behind each): parallel fan-out
for multi-dimension decomposition, free-form ReAct-style tool selection, multi-level drill-down,
cross-run agent memory.

---

## Phase 2 — Dataset Onboarding Agent (`docs/scoping.md` §§5–7)

**Gate:** a genuinely new, real (not synthetic) dataset — never referenced anywhere in this
repo before — goes from a raw CSV to a working `detect → decompose → narrate` cycle via
`onboarding/`, with a human confirming the schema classification along the way, and the
Phase 1 investigation agent runs against it *unmodified*.

- [x] **M4** — `onboarding/profiling.py` (Stage A) + `onboarding/classification.py` (Stage B +
      validation). `test_profiling.py`, `test_classification_validation.py` passing; Golden
      Case #2 (`docs/scoping.md` §5.6, the SaaS fixture) run for real.
- [ ] **M5** — `onboarding/codegen.py`, the two additive parameters on `decomposer.py`/
      `anomaly_detector.py`, the CLI confirmation flow, the schema-fingerprint cache.
      `test_codegen.py`, `test_reconciliation.py`, `test_schema_fingerprint.py` passing — **plus**
      a full re-run of the pre-existing suite, since this milestone edits already-tested files.
- [ ] **M6** — End-to-end run against a real, freshly-picked dataset (not the SaaS fixture).
      This is the actual proof of "MetricPulse works on more than one dataset" — a synthetic
      golden case can't substitute for it.

**Deferred, and why:** real dbt/Redshift codegen (targets a local DuckDB file for v1 instead —
`docs/scoping.md` §6.1), a `dim_*` business-taxonomy remapping layer for onboarded data (§6.4),
a dashboard-based onboarding wizard (CLI only for v1 — §7.3).

---

## Phase 3 — Portfolio Close-Out (`docs/scoping.md` §9–10)

**Gate:** resume bullets and interview talking points are filled in with real, measured numbers
— not the placeholders drafted in `docs/scoping.md` §9.4.

- [ ] **M7** — Section 9.3/9.4 claims updated with real numbers from M3 and M6's actual runs.
- [ ] Optional: recorded demo of the M6 live onboarding run (`docs/scoping.md` §9.6).

---

## Retrospectives

`docs/project/retrospectives/` is a named convention (end-of-phase reflection, heavier than a
session log entry). Phase 1 (M0–M3) closed on 2026-08-10 — see
[`phase-1-investigation-agent.md`](project/retrospectives/phase-1-investigation-agent.md) for its
retrospective, the first one actually written under this convention.
