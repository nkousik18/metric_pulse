# templates/

The Django templates powering the single-page app served at `/`. This is a **static-shell SPA**: Django renders the HTML once (no server-side data injection — no view ever passes a context dict with business data), and all data comes from client-side `fetch()` calls to `dashboard_api/` after page load. Tab switching between the 5 sections is pure client-side JS (`showTab()`), not separate page loads.

## File inventory

| File | Purpose |
|------|---------|
| `base.html` | The actual page shell — `<head>` with CDN imports, nav bar, includes all 5 partials + footer + `scripts.html`. **This file contains the real page content**, not `index.html`. |
| `index.html` | `{% extends 'base.html' %}` and nothing else — no blocks defined in either file, so this just renders `base.html` verbatim. This is what `metric_pulse_web/urls.py`'s `TemplateView` actually points at. |
| `partials/hero.html` | Tab 1 (`#content-hero`, visible by default) — marketing/portfolio landing content: headline, 4 hardcoded stat tiles (451K rows / 37 tests / <5s / 99.6%), before/after comparison, 4-step "How It Works", tech pill badges, CTA buttons. Static — no `id`s that JS touches, no API calls. |
| `partials/dashboard.html` | Tab 2 (`#content-dashboard`, hidden by default) — the real interactive UI: date/metric/threshold controls, 4 KPI cards, Chart.js canvas (`#revenueChart`), 3 decomposition panels (geography/product/payment) with drill-down toggles, narrative panel (with an "Investigate with AI Agent" button and a distinct `#investigation-result` block, Phase 1), pipeline control buttons. Every dynamic element has an `id` that `scripts.html` looks up. |
| `partials/actions.html` | Tab "Pending actions" (`#content-actions`, hidden; A6). The approver-token field, the pending proposals (`#pending-actions`, one card each with the dry run, editable params, reason, `live` checkbox and approve / edit / reject), executed reversible actions with undo (`#undoable-actions`), and the action log table (`#action-log-rows`). Rendered by `scripts.html`. |
| `partials/architecture.html` | Tab 3 (`#content-architecture`, hidden) — static visual architecture diagram (icon flow: Source → S3 → Redshift → dbt → Python → Dashboard) and hardcoded dbt model/tech-stack lists. No API calls; content can drift from actual pipeline (e.g. lists 4 marts / 3 metrics tables here — cross-check against `dbt_project/README.md` for the live count). |
| `partials/about.html` | Tab 4 (`#content-about`, hidden) — author bio, education/experience, skills, and the contact form (`#contact-name`, `#contact-email`, `#contact-message`, `#contact-status`) that posts to `/api/contact/`. |
| `partials/scripts.html` | All JavaScript for the SPA (~460 lines), one `<script>` block, no separate `.js` files, no build step. |

## `partials/scripts.html` — function inventory

| Function | Triggers on | Does |
|----------|------------|------|
| `showTab(tabName)` | nav clicks, in-page CTA buttons | Toggles `.hidden` on `.tab-content` divs; on first switch to `dashboard`, fires all 4 loaders below |
| `loadMetrics()` | dashboard tab open, `refreshData()` | `GET /api/metrics/?days=60` → populates date `<select>`s, KPI cards, and the trend chart |
| `populateDateDropdowns(data)` | called by `loadMetrics()` | Fills `#current-date`/`#previous-date` selects |
| `updateKPIs(latest, previous)` | `loadMetrics()`, `applyFilters()` | Computes % change client-side from two rows already in `metricsData` — does **not** call `/api/decomposition/` or any diff endpoint for this |
| `drawChart(data, metric)` / `setChartMetric(metric)` | chart toggle buttons | Chart.js line chart; destroys and rebuilds the chart instance on every metric switch |
| `loadAnomalies()` | dashboard tab open, `applyFilters()` | `GET /api/anomalies/?threshold=` → anomaly count KPI card |
| `loadDecomposition()` | dashboard tab open, `applyFilters()` | `GET /api/decomposition/` (with date params if set) → `renderBreakdown()` for each of the 3 panels |
| `renderBreakdown(elementId, contributors)` | `loadDecomposition()` | Renders top-5 contributors as progress bars, colored green/red by sign of `contribution_pct` |
| `toggleDrilldown(dimension)` | "Details" links | Shows/hides the `#{dim}-drilldown` div — **note: this only toggles visibility; nothing ever populates `#geo-details`/`#product-details`/`#payment-details` with content**, so the drill-down list is currently always empty when expanded |
| `loadNarrative()` | dashboard tab open, `applyFilters()` | `GET /api/narrative/` → strips `**` markdown bold markers and injects `<br>` for newlines into `#narrative` |
| `applyFilters()` / `resetFilters()` | "Apply Filters" / "Reset" buttons | Re-fire the 3 GET loaders (not `loadMetrics`) with current control values; reset restores default threshold/metric/dates |
| `copyNarrative()` / `downloadNarrative()` | Copy/Download buttons | Clipboard API / Blob download of the narrative's `innerText` |
| `runPipeline(forceAlert)` | "Run Analysis" / "Run & Send Alert" buttons | `POST /api/pipeline/` with `{metric, force_alert, dry_run: !forceAlert}`, then calls `refreshData()` |
| `investigateWithAgent()` | "Investigate with AI Agent" button | `POST /api/investigate/` with `{metric, current_date, previous_date}`. **Manual trigger only** — not part of `applyFilters()`'s auto-refresh (this one costs a real LLM call). Disables the button and shows a spinner while in flight; renders `investigation_summary` into `#investigation-content` (a distinct block beneath, not replacing, the Tier-1 `#narrative` div), or a status-specific message for `skipped_no_anomaly`/`failed`/`grounding_failed`. |
| `sendContactForm()` | Contact form submit | `POST /api/contact/` with `{name, email, message}` |
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
- The contact form's "Your Email" field is never validated as an email format client-side; the API (`ContactView`) doesn't validate it either.
