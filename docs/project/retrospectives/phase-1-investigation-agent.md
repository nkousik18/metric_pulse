# Retrospective: Phase 1 — Investigation Agent

**Milestones:** M0–M3 (`docs/ROADMAP.md`). **Design record:** `docs/scoping.md` Sections 2–4, 8.
**Calendar span:** 2026-08-04 → 2026-08-10 (6 days). **PRs:** #5–#12 (8 PRs — 4 feature, 4
docs/session-log follow-ups). **Full session-by-session detail:** `docs/project/SESSION_LOG.md`
entries dated 2026-08-04 through 2026-08-10 — this file doesn't repeat that detail, it reflects on
the phase as a whole.

## The gate, checked against actual evidence, not against effort spent

`docs/ROADMAP.md`'s Phase 1 gate: *"a real LangGraph agent, wired into
`orchestration/run_pipeline.py` and `/api/investigate/`, produces a grounded investigation summary
for a real anomaly — every citation in it validated against actual
`decomposition_results`/`drill_down_results`, not trusted on the model's word — and the existing
[pre-Phase-1] tests still pass unmodified."*

- **Real LangGraph agent:** `investigation/graph.py`'s compiled `StateGraph`, 7 nodes, 3
  conditional edges, a genuine bounded loop (`MAX_ITERATIONS`) — not a single prompt relabeled.
- **Wired into both integration points:** `run_pipeline(run_investigation=True)`'s Step 4.5 and
  `POST /api/investigate/`, both live-curled/CLI-run against real Redshift + real Groq (M2 session
  log), plus a dashboard button and Lambda passthrough beyond what the gate strictly required.
- **Grounded, for a real anomaly:** `python -m orchestration.run_pipeline --run-investigation`
  against live data produced a real `investigation_summary` citing real segments with real numbers
  (M2 session log). `python -m investigation.eval --runs 5` (M3) then ran the same grounding path 5
  more times against the live API: **`grounding_pass_rate=1.00`, `fallback_rate=0.00`,
  `golden_match_rate=1.00`, `uncertainty_ok_rate=1.00`** — not estimated, printed from a real run.
- **Citations validated, not trusted:** `validate_citation`/`validate_synthesis_output`
  (`investigation/validation.py`) check every citation against real `decomposition_results`/
  `drill_down_results` before it reaches rendering; `tests/test_citation_validation.py` covers this
  directly (valid/invalid/wrong-source/wrong-dimension cases).
- **Pre-existing tests unmodified:** all 15 tests that existed before Phase 1 started are still
  present, still passing, byte-identical — verified at the end of every one of M0–M3's sessions,
  including with `.env` entirely removed (M1) to confirm no accidental hard LLM dependency crept
  into the deterministic suite. The full suite is 47 now (15 original + 32 new across M0–M3), all
  green on `main` as of this retrospective.

Gate met on real evidence, not on "the milestones are checked off."

## What worked

- **The deterministic/LLM split (design Section 2.1) held up under actual implementation.** Every
  milestone's real surprises were in the ~10% of code that touches an LLM (prompt evidence layout
  in M1, metric-definition precision in M3) — the ~90% that's plain Python (routing, ambiguity
  rules, validation, idempotency) behaved exactly as designed and was fully covered by fast,
  free, deterministic tests. Section 8.1's stated bet — that this split would make the LLM-touching
  surface small and the rest cheaply testable — paid off in practice, not just on paper.
- **Grounding-by-validation, not grounding-by-prompting, actually caught something.** The prompt
  alone (M1's first version) reliably produced *valid* output but the *wrong* citation (a
  higher-level segment instead of the more specific drill-down finding) — a real instance of the
  exact failure class Section 3's design exists to make structurally hard, not just discouraged.
  Fixing it required restructuring the evidence layout, not adding a stricter validator — a good
  sign the validator was already doing its actual job (catching invented/wrong-source citations)
  and the steering problem was a separate, correctly-separated concern.
- **Scoping before coding paid for itself at least three times over.** `docs/scoping.md`'s existing
  design meant M0–M3 were "implement this specific thing," not "figure out what to build" — the
  actual implementation surprises were narrow and specific (see below), not architectural.

## Real gaps found and fixed along the way (not smoothed over)

- **M1:** the user's env var (`GROQ_API_KEY`) named a different provider (Groq) than the one
  initially assumed from context (xAI's "Grok") — caught and corrected before much was built on
  the wrong foundation, not after.
- **M1:** `docs/scoping.md` §3.5's illustrative `validate_citation` snippet indexed
  `decomposition_results` one level too shallow relative to the real `decompose_metric()` shape —
  a genuine bug in the design doc's pseudocode, fixed in the real implementation and documented as
  a correction rather than silently diverging from the doc.
- **M2:** three real gaps that only surfaced once an actual end-to-end graph run was exercised —
  none of M0/M1's fixture-based tests ran a full graph invocation, so a missing `.get()` default in
  `route_after_ambiguity`, non-idempotent `detect`/`decompose_all` nodes (which would have silently
  reintroduced the exact double-Redshift-query anti-pattern Section 4.3 was designed to avoid), and
  the lack of any central defaulted-state constructor all went undetected until real wiring. This is
  the concrete argument for why M2's "full test suite green" gate was necessary but not sufficient —
  live verification caught what fixture tests structurally couldn't.
- **M3:** re-reading §8.5's metric definitions against M1's actual implementation found that
  "grounding pass rate" (first-attempt-only) had been silently conflated with "grounded, period"
  (first-attempt-or-after-retry) — a real, if small, measurement bug that would have overstated how
  often the retry path was doing nothing, fixed before it became a trusted-but-wrong number.

## Estimate vs. actual

`docs/scoping.md` §10.2 estimated Phase 1 at roughly M0 "1 weekend," M1 "1–2 weekends," M2 "1
weekend," M3 "a few days" — that estimate's implicit model was solo, part-time work paced around a
job search. What actually happened: each milestone was built, tested, live-verified, and merged
within a single focused session (2026-08-04 M0, 2026-08-05 M1, 2026-08-06 M2's code, 2026-08-10 M3)
— AI-paired implementation compressed the "weekend" unit into "a session," which §10.3 flagged M1
specifically as the checkpoint to recalibrate against; the real signal from M1 onward was exactly
this compression, not a change in scope or quality bar. The one real calendar-time cost wasn't
implementation at all: a multi-hour, platform-wide GitHub Actions outage (2026-08-06 15:22 UTC
onward, confirmed via githubstatus.com, not guessed) stalled PR #10's merge for four days despite
the code and live verification being done on 2026-08-06 — external infrastructure, not this
project's work, was the actual bottleneck between M2's code being ready and M2 being merged.

## Honest gaps carried into Phase 2

- **Eval corpus is still one golden case.** `GOLDEN_CASE_1` is the sole Phase-1 golden case by
  design (`docs/scoping.md` §8.4's "a handful, not dozens" v1 sizing) — real usage producing real
  failure cases worth adding is the named future trigger for expanding it, not guessed edge cases.
- **`investigation.eval`'s 5-run sample is small.** `grounding_pass_rate=1.00` across 5 real trials
  is a genuinely strong result, but n=5 against a single scenario doesn't rule out failure modes a
  differently-shaped anomaly might expose — Section 8.7 explicitly doesn't gate on this number for
  exactly this reason (too small to be a statistically meaningful threshold).
- **No parallel fan-out, no multi-level drill-down, no cross-run memory** — all explicitly deferred
  in Section 2.8 from the start, not discovered as gaps; naming them here only for completeness.
- **The dead drill-down-toggle UI wiring** (`docs/dashboard_layer.md`'s long-standing known bug)
  remains unfixed — Section 4.6 named it as an optional, not required, synergy with this phase's
  `drill_down_results` data, and it stayed optional.

## What's next

Phase 2 (`docs/scoping.md` §§5–7, `docs/ROADMAP.md` M4–M6): the dataset-onboarding agent. Its
strongest payoff — the Phase 1 investigation agent running *unmodified* against a dataset it's
never seen — only becomes real and demoable now that Phase 1 genuinely exists (Section 10.1's
stated reason for sequencing Phase 2 after Phase 1, not in parallel).
