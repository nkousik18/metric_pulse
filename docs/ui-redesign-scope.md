# MetricPulse UI Redesign — Scope

**Status:** Approved 2026-11-12 · **Owner:** Kousik Nandury
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

*(Revised 2026-11-12 after Kousik found the first U2 build "flooded": one focal point per screen.)*

| Tab | Content | Replaces |
|---|---|---|
| **Overview** (default) | One line on what MetricPulse is, then **the answer** for the selected day as the focal point ("Revenue fell 90.6%", the dates and values, the top two drivers, revenue/orders/AOV), one primary button to the agent's explanation. Below: the 60-day trend, "What drove the change", and "Other days to look at" with the any-pair controls and the generated alert text folded into disclosures. | Home, Dashboard |
| **AI agents** | One section per agent (investigation, action and approvals, onboarding): what it does, its own eval scores with denominators, and its live part (run an investigation; the approval queue; the Superstore onboarding run). | Pending actions, Recorded runs, the scorecard |
| **How it's built** | The pipeline diagram (real local stack), the full eval table, the Run panel, links to the repo docs. | Architecture |
| **About** | Bio facts, contact links. | About |

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

- **U1 — Foundation.** Tokens (light and dark), base CSS (`partials/styles.html`), the top bar, tab
  shell and footer; the old Home tab removed; About rebuilt. Gate: the detector reports none of the
  §1 findings in the files U1 rewrites; no tab overflows at 375 px or 1440 px.
  *(As built: Tailwind and Font Awesome stay loaded until U3, because the dashboard, actions and
  architecture partials still use them; dark mode switches on in U3 for the same reason.)*
- **U2 — Investigate.** Intro, flagged-days list, anomaly panel, diverging contribution chart,
  trend, narrative, investigation, eval scorecard, Run menu; `scripts.html` renderers rebuilt;
  `replay.js` "Recorded runs" folded in. Gate: in the static replay, the three recorded cases and a
  consecutive pair render; every number on the first screen traces to a recording.
- **U3 — Approvals and How it's built.** The queue, payload, decisions, undo, timeline; the stack
  diagram; the eval table; onboarding; then Tailwind and Font Awesome removed and dark mode on
  (`.dark-ready`). Gate: the recorded walk-through replays end to end; the detector reports none of
  the §1 findings anywhere.
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
| 2026-11-12 | Tailwind and Font Awesome come out in U3, not U1: until then the unconverted partials depend on them. Dark mode waits for the same reason | Claude (found building U1) |
| 2026-11-12 | U2 as built: the eval scorecard is rendered into the page from the ledger (Django `HomeView` at request time; the static build from the recorded ledger), not fetched, so no API change (R4). Rose/fell uses the dataviz reference diverging pair, blue `#2a78d6` / red `#e34948` (validated light and dark), replacing U1's green/red; bar values in ink. The anomaly count moved into "Days to look at". Onboarding and eval details stay on the static Recorded runs tab until U3 moves them to How it's built | Claude |
| 2026-11-12 | U4 finish review (Impeccable finish reviewer, two rounds): fixed the focal answer's missing incomplete-data warning, the banned eyebrow (the headline is now the h1), the missing author line, a stale test count, the F1 label, no agent eval number on Overview (now a one-line caption), the mobile chart height, the agents tab length (approval cards fold; the log is behind a disclosure), and a periwinkle dark accent (now #58a6ff; light #2563c9). Round two's remaining items (phone action row, selected/next-step states looking like focus rings, the onboarding table on phones) were fixed after the verdict pass and checked by Claude, not re-reviewed. Tabs got shareable addresses (#agents, #built, #about) | Reviewer findings; Claude implemented |
| 2026-11-12 | U3 as built: How it's built rewritten from verified facts (451,535 rows, 11 dbt models / 37 tests, 399 then 401 Python tests, 14 endpoints, the real local stack, AWS listed as retired) with the pipeline as one connected sequence and every eval metric in folded tables; the approval cards rebuilt; Tailwind and Font Awesome removed, with a small CSS reset replacing what the page relied on from Tailwind's preflight; dark mode on (`html.dark-ready`, the OS setting) | Claude |
| 2026-11-12 | After the first U2 build ("flooded, my eyes are not going to anything specific; keep agents in a separate tab"): distilled with the Impeccable distill method. Overview keeps one focal answer; the agents, their scores and Approvals move to an AI agents tab; the Run panel moves to How it's built; the Recorded runs tab is gone (onboarding renders in the agents tab); detection's F1 sits next to the flagged days | Kousik chose "one answer + agents tab" over "just move agents out"; Claude implemented |
| 2026-11-12 | After seeing U1: no purple anywhere, no emoji, more space between tiles, tiles raised with a soft shadow, and a short project intro at the top. Done in U1: the dashboard partial rebuilt (intro, raised tiles, KPI deltas, breakdown bars on one honest scale coloured by whether each segment rose or fell, emoji dropped from narratives on display); approvals and architecture swapped off purple and given the same tile shadow until U3 | Kousik (feedback); Claude (implementation) |
