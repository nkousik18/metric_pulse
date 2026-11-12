# MetricPulse UI Redesign — Scope

**Status:** Draft 2026-11-12, awaiting Kousik's approval · **Owner:** Kousik Nandury
**Tracked in:** `docs/ROADMAP.md` → "UI redesign" (milestones U1–U4)
**Inputs:** `PRODUCT.md` (product brief, approved), `.impeccable/surfaces/templates-base-html.md`
(direction contract), `docs/hosting-scope.md` (H1's static replay, which renders these templates)

## 1. Why this exists

Kousik rejected the current UI before publishing the static site ("screams AI generated"). The
Impeccable detector agrees: Inter everywhere, an indigo→violet palette, gradient text. Under the
paint the UX is also wrong for the audience:

- the breakdown bars cap at 100%, so "Credit Card: 251% of the change" draws the same as 100%;
- the dashboard opens on two date dropdowns, with nothing pointing at the interesting days;
- the home page is a template (stat tiles, before/after, 4-step "how it works", tech pills), with
  hand-written numbers ("<5s", "99.6%") nothing backs;
- Architecture still presents the deleted AWS stack as live;
- the nav overflows on a phone; the narrative opens with an emoji.

The GitHub Pages deploy is held until this lands (hosting scope §10, 2026-11-12).

## 2. Goal

A hiring manager arriving from LinkedIn understands in 30 seconds that MetricPulse explains why a
metric moved, that its AI is grounded and measured, and who built it, then contacts Kousik on
LinkedIn. An engineer can reach the depth (approvals, architecture, evals) in one click.

## 3. Rules

- **R1 — Real content only** (PRODUCT.md principle 1). Every number on the site comes from a
  recording or the eval ledger, with its denominator. The hand-written hero numbers go.
- **R2 — The category standard, played straight** (Kousik's choice on the decision page). Benchmarks:
  Linear, Stripe Dashboard + docs. No themed world, no novelty.
- **R3 — One template set, two hosts.** The Django app and the static replay keep rendering the same
  templates; `demo/build.py`'s anchors and `replay.js` keep working. Every element id that
  `scripts.html` or `replay.js` uses either stays or is changed in the same PR as its caller.
- **R4 — No API change.** The redesign doesn't touch `dashboard_api/` responses, so the recordings
  stay valid (they are re-recorded once on `main` before Pages goes live, for the commit SHA only).
- **R5 — No build step.** Plain CSS with custom properties, no Tailwind CDN script (it is not for
  production use), no Font Awesome; Chart.js stays, pinned to an exact version.

## 4. Non-goals

- New product features, endpoints or agent behaviour.
- The legacy Streamlit dashboard.
- A framework rewrite (React etc.).
- Fixing the AOV pipeline bug (BUG_LOG A4-1); the redesign only shows its result honestly.

## 5. Information architecture

| Tab | Content | Replaces |
|---|---|---|
| **Investigate** (default) | Intro line (what it is, who built it, LinkedIn). Flagged-days list (the three recorded cases first, then the 60 days). The selected day: headline change, trend with the day marked, diverging contribution chart per dimension, the deterministic narrative, and the agent's cited investigation. Eval scorecard beside it. Pipeline controls tucked into a secondary "Run" menu. | Home, Dashboard, Recorded runs |
| **Approvals** | The Action Agent queue: proposal, cited evidence, exact payload, decision; executed actions with undo; the log as a timeline. The static site's walk-through guide stays. | Pending actions |
| **How it's built** | The pipeline as one diagram of the real local stack (DuckDB, dbt, detection, decomposition, three agents, outbox), the eval table with every metric and denominator, Superstore onboarding results, links to the repo docs. | Architecture, parts of Recorded runs |
| **About** | Bio facts (MS completed May 2026, Capgemini, B.Tech), contact links. No contact form. | About |

The top bar carries the wordmark, the four tabs, and a LinkedIn button. On a phone the tabs become
a scrollable segmented control; nothing overflows at 375 px.

## 6. Visual system (direction contract, summarized)

- **Light by default, dark via the OS setting.** Cool neutral greys, white panels, near-black ink,
  one restrained accent that is not indigo or violet. Tokens on `:root`, redefined for dark.
- **Type:** the system UI stack with tabular figures; monospace only for ids and code. No web font.
- **Charts:** designed with the dataviz skill. The contribution chart is diverging and shows values
  over 100% and offsetting segments honestly (an axis wide enough for the largest value, labelled
  values, positive and negative in a colour-blind-safe pair).
- **Components:** hairline borders, small radii, no gradients, glow, hover-lift or emoji; inline SVG
  icons; visible focus states; tabular numbers in every table.
- **Narrative display:** markdown bold rendered as bold, the emoji stripped on display only (the
  recorded output is unchanged).

## 7. Milestones

- **U1 — Foundation.** Tokens (light and dark), base CSS, the top bar, tab shell and footer;
  Tailwind CDN and Font Awesome removed; About and the empty-state/notice components. Gate: the
  detector reports none of the §1 findings; tabs work at 375 px and 1440 px.
- **U2 — Investigate.** Intro, flagged-days list, anomaly panel, diverging contribution chart,
  trend, narrative, investigation, eval scorecard, Run menu; `scripts.html` renderers rebuilt;
  `replay.js` "Recorded runs" folded in. Gate: in the static replay, the three recorded cases and a
  consecutive pair render; every number on the first screen traces to a recording.
- **U3 — Approvals and How it's built.** The queue, payload, decisions, undo, timeline; the stack
  diagram; the eval table; onboarding. Gate: the recorded walk-through replays end to end.
- **U4 — Finish.** One batched desktop and mobile screenshot round, one fix batch; Vercel
  web-interface guidelines review; Impeccable finish review and `DESIGN.md` by its documenter.
  Then re-record on `main`, enable Pages, check the live URL: that also passes H1.
  Gate: the finish reviewer's verdict, `DESIGN.md` committed, the live URL checked in a browser.

Each milestone is one PR through the usual branch → PR → CI → squash-merge flow.

## 8. Risks

| Risk | Mitigation |
|---|---|
| The canon reads generic ("indistinguishable by design") | Craft carries it: Linear/Stripe-level type, spacing and charts, plus content no other portfolio has (cited answers, eval denominators, a real approval flow) |
| JS-built markup drifts from the templates | `scripts.html` renderers rebuilt in the same PR as their templates; the build anchors fail loudly |
| Breaking the static replay | `tests/test_demo_site.py` runs in CI; the browser check per milestone |
| Dark mode doubles the visual QA | Tokens only; checked once per milestone in the screenshot round |

## 9. Decision log

| Date | Decision | By |
|---|---|---|
| 2026-11-12 | Audience: hiring managers, 30-second skim; main claim: grounded, measured AI plus end-to-end ownership; primary action: LinkedIn | Kousik |
| 2026-11-12 | Structure: short intro first, then the explained anomaly with the eval scorecard beside it; four tabs | Kousik |
| 2026-11-12 | Must not feel like a SaaS template or playful | Kousik |
| 2026-11-12 | Visual direction: the category standard (over the Incident Record, Working Papers and Cutting Bench directions); benchmarks Linear and Stripe Dashboard + docs | Kousik (decision page) |
| 2026-11-12 | Keep: the name, contact links, architecture content (corrected) | Kousik |
| 2026-11-12 | System fonts, plain CSS, no Tailwind CDN or Font Awesome; light default with OS dark mode | Claude (from R2, R5 and the visitor's scene); open to change on review |
