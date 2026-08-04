# Session Log

Newest entry at the top. Append-only — past entries are never rewritten, only added above.
See `docs/WORKING_CONVENTIONS.md` for the discipline this file follows.

---

## 2026-08-04 — Built M0: investigation graph skeleton (Phase 1 kickoff)

**What happened:**
First implementation session on the agentic-layer initiative — `docs/ROADMAP.md` Phase 1,
milestone M0. Re-read `docs/scoping.md` Sections 2–4 (the LangGraph design) and the real
`decomposition/decomposer.py`, `detection/anomaly_detector.py`, `orchestration/run_pipeline.py`,
and `narrative/generator.py` source before writing anything, then used plan mode to resolve one
ambiguity in the scoping doc before coding: Section 2.3 lists 7 graph nodes total, but M0's
milestone table (§10.2) says "5 deterministic nodes" — resolved as `detect`, `decompose_all`,
`assess_ambiguity`, `drill_down`, `finalize_skip`, deferring the real `finalize` to M1 alongside
`synthesize` (the LLM node), since `finalize`'s actual job — attaching `investigation_summary` —
only makes sense once `synthesize` produces that field. Consistent with M0's "depends on nothing
new," no `langgraph` package was added and no `StateGraph` was compiled — nodes/routing functions
are plain, independently-testable Python functions for now, matching the calling convention they'll
plug into once M1/M2 assembles a real graph.

Built: `investigation/` (new package — `state.py`'s `InvestigationState`, `nodes.py`'s 5 nodes +
`classify_ambiguity`, `routing.py`'s 3 routing functions + `MAX_ITERATIONS`, `tools.py`'s 4 tool
wrappers, `README.md`); `decomposition/decomposer.py`'s new `fetch_detail_metrics()` (the one
genuinely new backend capability this phase needs) plus a `summarize_dimension()` extraction so it
and the existing `decompose_metric()` share one summary implementation instead of duplicating a
15-line block; `tests/test_investigation_routing.py` (11 tests) and `tests/test_ambiguity_rules.py`
(9 tests). `ambiguous_dimensions` was built directly in its Section 3.4-amended typed form
(`list[{dimension, reason}]`), since that section is a documented amendment to Section 2 and
building the flat form first would've just meant redoing it.

**Decisions made:**
- `classify_ambiguity` checks the `offsetting_segments` condition before `close_contributors` when
  both could apply — a top contributor already over 100% makes "how close is #2" not meaningfully
  defined. Verified against `docs/scoping.md` §3.8's worked example directly (Southeast/Northeast →
  `close_contributors`, Payment → `offsetting_segments`) before trusting it.
- `drill_down` only drills the single top contributor's segment per ambiguous dimension, not every
  close contender — matches the §3.8 worked example (Southeast drilled, not Northeast).
- Followed `CONTRIBUTING.md`'s branch → PR → CI green → squash-merge flow for both the code (PR #5)
  and a small same-session docs follow-up (PR #6, fixing `tests/README.md`'s test count — stale the
  moment M0 added two new test files — and checking M0's `ROADMAP.md` box only after the full suite
  actually passed on `main` post-merge, per CLAUDE.md's "verifiably met" discipline).

**Current state:** PRs #5 and #6 merged and squash-merged into `main`, both branches deleted. Full
suite is 35 tests passing on `main` (15 pre-existing + 20 new), `flake8 --select=E9,F63,F7,F82`
clean. `docs/ROADMAP.md`'s M0 checkbox and its two named test files are checked off.
`investigation/` is not wired into anything yet — no compiled graph, nothing in `orchestration/` or
`dashboard_api/` calls it.

**Next steps:** M1 — `synthesize` (Section 3): Pydantic schemas (`EvidenceCitation`,
`SynthesisOutput`), the structured-output LLM call, `validate_citation`, the bounded retry/fallback
policy, and the Jinja rendering for `investigation_summary`. `docs/scoping.md` flags M1 as "the
highest-uncertainty milestone" — first time this design meets a real LLM provider — and the
designated calibration checkpoint for the rest of the rollout estimate (§10.3), worth an explicit
pause after it ships to check real grounding-pass-rate against the rest of the plan.

**Loose ends / reminders:**
- `main` is still not branch-protected on GitHub (carried over from the previous session's note).
- No `langgraph` dependency in `requirements.txt` yet — will be needed once M1/M2 actually compiles
  a `StateGraph`.

---

## 2026-08-04 — Full documentation staleness audit and fixes

**What happened:**
User asked for the same reconciliation treatment given to `docs/resume_project_doc.md` back on
2026-07-27→28 to be applied to `CLAUDE.md` and every other doc. Rather than re-reading everything
serially, split the ~21 files (`CLAUDE.md`, root `README.md`, `CONTRIBUTING.md`, 13 files under
`docs/`, and 16 folder-level `README.md`s) across 6 parallel audit agents, each verifying a
cluster's concrete claims (function signatures, counts, file paths, CI job names, described
behavior) directly against the running code rather than trusting prior docs. Found genuine
staleness in 10 files, ranging from cosmetic to structural:
- `docs/resume_project_doc.md` had fabricated detail in four places — a dbt test-type breakdown
  that was wrong on every number (and claimed 3 `relationships` FK tests that don't exist at
  all), a detection-functions table listing three functions that were never real
  (`fetch_metric_data`, `calculate_zscore(df, metric_col)`, `format_anomaly_summary`), wrong
  decomposition output field names (`segments`/auto-populated `dominant_driver` vs. the real
  `top_contributors` / separately-computed `get_top_driver()`), and a narrative-templates table
  citing 4 `.jinja2` files that don't exist anywhere in the repo (narrative templates are inline
  Python strings).
- `docs/architecture.md` predated the Django app entirely — its delivery-layer diagram, tech
  stack table, and "Future Enhancements" list all omitted/misstated the fact that Django is the
  live production interface, not a future item. Also caught (independently, while fixing this)
  that both this file and the root `README.md` still listed `scipy` as the detection stack, even
  though it was removed as an unused import a while ago (already correctly noted as removed in
  `docs/detection_layer.md` and `docs/infrastructure_and_deployment.md`'s own "fixed" tables) —
  fixed both.
- `docs/WORKING_CONVENTIONS.md` was the biggest find: it was still, word-for-word in places, the
  write-up from a different project ("Interpose") adopted on 2026-07-28 and never adapted — wrong
  project name throughout, citations to files that don't exist here
  (`docs/INTERPOSE_SCOPING.md`, two `concepts/` files that were never written for this repo), and
  a described CI/branch-protection setup (`lint`/`test`/`helm` jobs, enforced branch protection)
  that doesn't match this repo's actual `lint-and-test`/`dbt-check` CI or its (verified via
  `gh api`) actually-unprotected `main` branch. Rewrote it in place for MetricPulse: correct file
  names throughout, honest about `main` not being branch-protected (named as a gap, not hidden),
  and reframed the `concepts/` guidance to match how this repo actually seeded that folder (one
  pass from already-worked-out scoping ideas, not a grow-as-you-learn log).
- Smaller fixes: `docs/dashboard_layer.md` claimed a red anomaly-highlight feature on the trend
  chart that isn't implemented, and misdescribed `applyFilters()` as calling 4 loaders (it calls
  3); `docs/setup.md` said Python 3.10+ (real: 3.12+) and had a completely fabricated
  `requirements.txt` snippet (16 loose-pinned packages vs. the real ~90 exactly-pinned ones);
  `deploy/README.md` and `docs/resume_project_doc.md` both claimed the CD workflow deploys the
  Django app to Render, but `cd.yml` has no Render deploy step at all (Render deploys via its own
  git-push hook, outside GitHub Actions) — CD's only real current effect is a `dbt run` echo
  placeholder behind an environment-approval gate; `docs/detection_layer.md` and
  `docs/dbt_transformations.md` each had a one-line count mismatch (3 vs. 5 tests, 3 vs. 4 date
  dimensions); `CLAUDE.md` overstated `config/db.py` as "the only" connection factory when the
  Streamlit dashboard intentionally bypasses it.
- Confirmed clean, no changes needed: `docs/README.md`, `CONTRIBUTING.md`, `docs/ROADMAP.md`,
  `docs/ingestion_pipeline.md`, `docs/analytics_pipeline.md`, `docs/infrastructure_and_deployment.md`,
  `tests/README.md`, and 11 of the 16 folder READMEs.

**Decisions made:**
- Rewrite `docs/WORKING_CONVENTIONS.md` in place rather than delete it or leave the gap
  unaddressed (asked the user directly given it required a judgment call, not a mechanical fix)
  — the underlying discipline is genuinely being practiced now, it just needed its concrete
  references corrected.
- Fixed the `scipy` claim in `README.md` even though it wasn't in the original audit scope for
  that file, since it was directly confirmed false while fixing the same claim in
  `architecture.md` — no reason to leave a known-wrong fact standing once found.

**Current state:** All 10 files fixed and committed via `docs/staleness-audit-fixes` branch →
PR → CI green → squash-merge, per `CONTRIBUTING.md`. `CHANGELOG.md` updated with both this fix
and the missing entry for last session's `docs/workflow_diagram.md` PR (#3).

**Next steps:** None outstanding from this pass. A natural future check: re-run this kind of
audit after Phase 1 (investigation agent) actually ships, since that's when `docs/scoping.md`'s
design claims start needing the same "is this actually true of the code now" scrutiny.

**Loose ends / reminders:**
- `main` is still not branch-protected on GitHub — named in `docs/WORKING_CONVENTIONS.md` now,
  but not fixed. Worth doing if this repo is ever shown to reviewers as a workflow-discipline
  example, not just a pipeline one.

---

## 2026-08-04 — Added end-to-end workflow diagram

**What happened:**
User asked for a single document/visual covering the full project workflow — every step, its
inputs, its outputs — suitable for handing to another LLM to generate an image from if a native
image couldn't be produced directly. Re-verified the pipeline shape against
`docs/resume_project_doc.md`, `docs/ROADMAP.md`, and the `orchestration/`, `dashboard_api/`, and
`monitoring/` READMEs before drawing anything, rather than trusting `docs/architecture.md`'s
existing (older, coarser) diagram as-is. Wrote `docs/workflow_diagram.md`: a system-overview
Mermaid flowchart (Data Foundation → Analytics Pipeline → Presentation, color-coded by phase), a
sequence diagram of one `run_pipeline()` call showing the exact data object passed at each
boundary, a CI/CD deployment diagram, per-step input/output tables for every layer, and a
portable natural-language image-generation prompt for another LLM/image tool. Published it as a
Claude artifact (renders the Mermaid live) and indexed it in `docs/README.md`.

**Decisions made:**
- Diagrams show Phase 0 (the live, verifiable system) only — the Phase 1 LangGraph investigation
  agent is named in a callout as scoped-but-not-built rather than drawn in, consistent with the
  "check a box only when verifiably met" discipline the roadmap already follows.
- Kept this as a new file rather than folding into `architecture.md` — that file is the
  component-level system diagram; this one is the data-flow view (concrete inputs/outputs per
  step, not just "layer A talks to layer B"), different enough to earn its own file.

**Current state:** `docs/workflow_diagram.md` created and indexed in `docs/README.md`; both
committed via `docs/workflow-diagram` branch → PR → CI green → squash-merge, per
`CONTRIBUTING.md`. No code changed — documentation only, no `ROADMAP.md` gates affected.

**Next steps:** None outstanding from this change.

**Loose ends / reminders:** none.

---

## 2026-07-28 — Adopted WORKING_CONVENTIONS.md scaffolding

**What happened:**
User shared `docs/WORKING_CONVENTIONS.md` — a documentation/session/git-workflow reflection
written for a different project (Interpose) — and asked to adopt everything in it for
MetricPulse. Built the scaffolding it describes that didn't exist yet: this file
(`docs/project/SESSION_LOG.md`), `docs/ROADMAP.md` (phase-based, Phase 0 = the already-shipped
core pipeline marked done, Phases 1–3 mapped directly onto `docs/scoping.md` §10's M0–M7
milestones), `CHANGELOG.md` (built from real git log history, not invented), `concepts/` (5 seed
files — `CLAUDE.md` as a mechanism, state graphs/LangGraph, grounding LLM output, the
deterministic-vs-LLM judgment split, human-in-the-loop design — plus `concepts/INDEX.md`), and
`CONTRIBUTING.md` (branch naming, the GitHub Flow sequence, squash-merge). Updated `CLAUDE.md`
with the session-start/session-end ritual as an explicit instruction and pointers to all the new
files, and `README.md` with an honest status line and a `concepts/` pointer.

**Decisions made:**
- Phase 0 (the original pipeline) gets one collapsed "done" entry in `ROADMAP.md` rather than a
  granular retroactive breakdown — that work already shipped and is documented elsewhere
  (`docs/resume_project_doc.md`); the roadmap's real job starts at Phase 1.
- `concepts/` is seeded with 5 files extracted from ideas already explained in depth during the
  `docs/scoping.md` conversation, rather than left empty until "new to the domain" learning
  happens live — MetricPulse isn't a from-scratch learning project the way Interpose is, so the
  mechanism is being used as a reusable reference library, not a live learning-in-public log.
- Not rewriting PR #1's already-merged history to retroactively squash it — the squash-merge
  convention applies from this PR forward.

**Current state:** All scaffolding files created on branch `chore/adopt-working-conventions`,
not yet merged (see this branch's PR for status). No agentic-layer code exists yet.

**Next steps:** Commit and merge this scaffolding via the newly-adopted GitHub Flow (branch → PR
→ CI green → squash-merge → delete branch) — the first real use of the convention this session
just adopted. After that: begin `docs/ROADMAP.md` Phase 1, milestone M0.

**Loose ends / reminders:**
- `docs/project/retrospectives/` is named as a convention in `docs/ROADMAP.md` but intentionally
  not created yet — no phase has closed.

---

## 2026-07-27 → 2026-07-28 — Documentation pass + agentic-layer scoping

**What happened:**
Read the full existing `docs/` set to understand the project, then built out documentation that
didn't exist yet: `CLAUDE.md` (root), and a `README.md` in every top-level code folder
(`ingestion/`, `dbt_project/`, `config/`, `infrastructure/`, `detection/`, `decomposition/`,
`narrative/`, `alerting/`, `orchestration/`, `monitoring/`, `deploy/`, `tests/`, `dashboard_api/`,
`metric_pulse_web/`, `templates/`, `dashboard/`), each verified against actual source rather than
copied from existing docs. That reconciliation surfaced real stale facts, fixed in place: the
real unit test count is 15, not 13, and none of them mock anything (all pure functions); dbt
model/mart counts in `resume_project_doc.md` didn't match the real `dbt_project/models/` tree;
the dashboard's "Details" drill-down toggle is dead code (shows/hides an empty `<div>`, nothing
populates it); the root README overstated two "Future Enhancements" as fully missing when the
underlying capability (Lambda deploy, EventBridge scheduling) partially already existed.

Then read `docs/Kousik_Market_Gap_Analysis_July2026.md` (a personal job-search market-fit
analysis, kept out of git — see Loose Ends) and used it to scope a real feature addition: a
LangGraph-based agentic layer, chosen specifically because the analysis names multi-agent
frameworks as the single most closable gap in the target job market. CrewAI was evaluated as an
alternative framework and rejected in favor of staying with LangGraph. The result is
`docs/scoping.md` — a full 10-section design spec (goals/non-goals, a root-cause investigation
agent, a dataset-onboarding agent, grounding design, integration points, testing/eval strategy,
resume framing, and a rollout plan) built section-by-section over several turns, with its own
running decision log. **Design only — nothing in it is implemented yet.**

All of the above (except the gap-analysis file) was committed on `docs/comprehensive-documentation`
and merged into `main` via PR #1, after CI (`lint-and-test`, `dbt-check`) passed.

**Decisions made:**
- LangGraph over CrewAI, for both phases of the agentic layer — full reasoning in
  `docs/scoping.md`'s Decision Log.
- Bypass dbt/Redshift for the onboarding agent's v1 codegen target (a local DuckDB file instead)
  — the strongest proof of "works on a new dataset" is a fast, zero-infra live demo.
- No `dim_*` business-taxonomy remapping layer for onboarded datasets — that kind of mapping is a
  human judgment call with no generic automated equivalent.
- Human-in-the-loop for schema classification is a single CLI confirmation prompt, gated by three
  explicit triggers (first-time dataset, schema changed, validation failed) — not required on
  every run.
- The LLM eval suite (Section 8) reuses the same deterministic validators built for production
  grounding as its graders, rather than a separate LLM-as-judge pipeline.

**Current state:** `docs/scoping.md` is complete (all 10 sections). `CLAUDE.md` and every
top-level folder `README.md` are merged to `main`. `README.md`'s stale claims are fixed. No
agentic-layer code exists yet — `docs/ROADMAP.md`'s Phase 1, milestone M0, hasn't started.

**Next steps:** Adopt the documentation/session/git scaffolding described in
`docs/WORKING_CONVENTIONS.md` for this project (this file, `docs/ROADMAP.md`, `CHANGELOG.md`,
`concepts/`, `CONTRIBUTING.md`) — in progress as of this entry. After that: begin Phase 1, M0.

**Loose ends / reminders:**
- PR #1 was merged with a plain merge commit, not squash — the squash-merge convention wasn't
  established yet at that point. Not worth rewriting already-merged `main` history over; the
  convention applies from the next PR forward.
- `docs/Kousik_Market_Gap_Analysis_July2026.md` is intentionally untracked and gitignored — it
  contains personal job-search/company-fit/visa data that shouldn't be in this public repo.
  `CLAUDE.md` and `docs/scoping.md` reference it by name; keep it excluded from any future commit.
