# templates/

The Django templates powering the single-page app served at `/`. This is a **static-shell SPA**: Django renders the HTML once (no server-side data injection — no view ever passes a context dict with business data), and all data comes from client-side `fetch()` calls to `dashboard_api/` after page load. Tab switching between the 5 sections is pure client-side JS (`showTab()`), not separate page loads.

## File inventory

| File | Purpose |
|------|---------|
| `base.html` | The page shell: `<head>` (Chart.js pinned, plus Tailwind and Font Awesome until U3 of `docs/ui-redesign-scope.md`), `partials/styles.html`, the top bar (wordmark, four tabs, LinkedIn), the four content partials, footer, `scripts.html`. **This file holds the page**, not `index.html`. |
| `partials/styles.html` | The design tokens (light, plus dark behind `html.dark-ready`) and base CSS, as one inline `<style>` so the Django app and the static replay get it with no build step. New markup uses these classes, not Tailwind. |
| `index.html` | `{% extends 'base.html' %}` and nothing else — no blocks defined in either file, so this just renders `base.html` verbatim. This is what `metric_pulse_web/urls.py`'s `TemplateView` actually points at. |
| `partials/dashboard.html` | Overview (`#content-dashboard`, the first screen): one intro line; the answer (`#answer-headline`, `#answer-sub`, `#answer-drivers`, the three `kpi-*` values) with the button to the agent; the trend (`#revenueChart`); "What drove the revenue change"; "Other days to look at" (`#flagged-days`) with the any-pair controls and the alert text (`#narrative`) in disclosures. |
| `partials/agents.html` | AI agents (`#content-agents`): one section per agent with its scores (`partials/score_row.html`, from the `scores` context) and its live part: the investigation (`#investigate-btn`, `#agent-days`, `#investigation-result`), the approval queue (`partials/actions.html`), the Superstore onboarding run (`#onboarding-results`, filled by the static replay). |
| `partials/score_row.html` | One agent's eval scores, numerator over denominator, with the run date and commit. |
| `partials/actions.html` | The Action Agent's approval queue, included in the AI agents tab (`#content-actions` is a section now, not a tab): approver token, pending proposals (`#pending-actions`), undoable actions (`#undoable-actions`), the action log (`#action-log-rows`). Loads whenever the agents tab opens. |
| `partials/architecture.html` | Tab 3 (`#content-architecture`, hidden) — static visual architecture diagram (icon flow: Source → S3 → Redshift → dbt → Python → Dashboard) and hardcoded dbt model/tech-stack lists. No API calls; content can drift from actual pipeline (e.g. lists 4 marts / 3 metrics tables here — cross-check against `dbt_project/README.md` for the live count). |
| `partials/about.html` | About (`#content-about`): bio, experience, education, skills, contact links. No contact form since the UI redesign (`/api/contact/` still exists, unused by the page). |
| `partials/scripts.html` | All JavaScript for the SPA (~460 lines), one `<script>` block, no separate `.js` files, no build step. |

## `partials/scripts.html` — function inventory

| Function | Triggers on | Does |
|----------|------------|------|
| `showTab(tabName)` | nav clicks; once on `DOMContentLoaded` with `dashboard` (Investigate is the first screen) | Toggles `.hidden` on `.tab-content` divs and `.tab-active` / `aria-current` on the tab; on first switch to `dashboard`, fires all 4 loaders below |
| `loadMetrics()` | dashboard tab open, `refreshData()` | `GET /api/metrics/?days=60` → populates date `<select>`s, KPI cards, and the trend chart |
| `populateDateDropdowns(data)` | called by `loadMetrics()` | Fills `#current-date`/`#previous-date` selects |
| `updateKPIs(latest, previous)` | `loadMetrics()`, `applyFilters()` | Computes % change client-side from two rows already in `metricsData` — does **not** call `/api/decomposition/` or any diff endpoint for this |
| `drawChart(data, metric)` / `setChartMetric(metric)` | chart toggle buttons | Chart.js line chart; destroys and rebuilds the chart instance on every metric switch |
| `loadAnomalies()` | dashboard tab open, `applyFilters()` | `GET /api/anomalies/?threshold=` → the flagged-days count, `lastDetection`, `renderFlaggedDays()`, and a chart redraw |
| `renderFlaggedDays()` / `selectFlaggedDay(i)` | anomalies loaded, filters applied; a day chip | Lists the detector's flagged days, the incomplete-data day and `window.extraFlaggedDays` (the static replay's recorded AI investigations); a chip selects the day vs the day before (and replays the investigation for a recorded one) |
| `loadDecomposition()` | dashboard tab open, `applyFilters()` | `GET /api/decomposition/` (with date params if set) → `renderBreakdown()` for each of the 3 panels |
| `renderBreakdown(elementId, contributors)` | `loadDecomposition()` | Top-5 segments as bars on one scale per column (the largest share shown, so shares over 100% or below 0 draw honestly), coloured by whether the segment rose or fell (the validated `--rise`/`--fall` pair); values in ink. Returns the scale so the caller can add the over-100% note |
| `toggleDrilldown(dimension)` | "Details" links | Shows/hides the `#{dim}-drilldown` div — **note: this only toggles visibility; nothing ever populates `#geo-details`/`#product-details`/`#payment-details` with content**, so the drill-down list is currently always empty when expanded |
| `loadNarrative()` | dashboard tab open, `applyFilters()` | `GET /api/narrative/` → strips `**` markdown bold markers and injects `<br>` for newlines into `#narrative` |
| `applyFilters()` / `resetFilters()` | "Apply Filters" / "Reset" buttons | Re-fire the 3 GET loaders (not `loadMetrics`) with current control values; reset restores default threshold/metric/dates |
| `copyNarrative()` / `downloadNarrative()` | Copy/Download buttons | Clipboard API / Blob download of the narrative's `innerText` |
| `runPipeline(forceAlert)` | "Run Analysis" / "Run & Send Alert" buttons | `POST /api/pipeline/` with `{metric, force_alert, dry_run: !forceAlert}`, then calls `refreshData()` |
| `investigateWithAgent()` | "Investigate with AI Agent" button | `POST /api/investigate/` with `{metric, current_date, previous_date}`. **Manual trigger only** — not part of `applyFilters()`'s auto-refresh (this one costs a real LLM call). Disables the button and shows a spinner while in flight; renders `investigation_summary` into `#investigation-content` (a distinct block beneath, not replacing, the Tier-1 `#narrative` div), or a status-specific message for `skipped_no_anomaly`/`failed`/`grounding_failed`. |
| `loadActions()` | opening the Pending actions tab, Refresh, after a decision | `GET /api/actions/pending/` and `/api/actions/log/` with the approver token, then `renderPendingActions` / `renderUndoable` / `renderActionLog` |
| `decideAction(id, decision)` / `undoAction(id)` | the card buttons | `POST /api/actions/<id>/approve\|edit\|reject\|undo/`. Results and errors show inline; an edit that fails policy re-renders the card with the policy errors |
| `escapeHtml()` | every server value rendered by the actions tab | Segment names and narratives are untrusted data (N3); nothing from the API is inserted unescaped |

## Running / testing standalone

Not runnable in isolation — templates only render through `python manage.py runserver` (see `metric_pulse_web/README.md`). To check for broken `id` references or dead JS handlers, open the rendered page and inspect the DOM directly; there's no template unit test.

## Config dependency

None (no template tags reference settings/env vars beyond the standard `TEMPLATES[0].DIRS` path in `metric_pulse_web/settings.py`).

## External dependencies (all CDN, no local copies, no build step)

Tailwind CSS (latest), Chart.js (latest), Font Awesome 6.4.0, Google Fonts (Inter) — all loaded in `base.html`'s `<head>`.

## Gotchas

- **The approver token lives in `sessionStorage`** (this browser tab only, gone when it closes), never `localStorage` or a cookie. The actions tab uses no `alert()`/`confirm()`/`prompt()`: a reason is typed into the card.
- **`runserver --noreload` caches templates**, so a template edit needs a server restart to show.

- **`index.html` is a decoy** — if you're looking for the SPA markup, it's in `base.html`, not `index.html`. This is backwards from the usual Django convention (base defines blocks, children fill them in) — here `base.html` holds 100% of the content and `index.html` exists only because `TemplateView` needs a template name to point at.
- **Drill-down toggles don't populate data** — `toggleDrilldown()` reveals an empty div; the state → detail expansion (region → state, category-group → category) described in `docs/dashboard_layer.md` is not implemented in the current JS.
- `architecture.html`'s dbt model/table counts are hand-written HTML, not generated from `dbt_project/` — verify against `dbt_project/README.md` before trusting the numbers shown in that tab.
