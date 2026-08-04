# Session Log

Newest entry at the top. Append-only — past entries are never rewritten, only added above.
See `docs/WORKING_CONVENTIONS.md` for the discipline this file follows.

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
