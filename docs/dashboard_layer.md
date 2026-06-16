# Dashboard Layer

MetricPulse has two independent UIs. The Django web app is the primary production interface served on Render. The Streamlit dashboard is a legacy interface that still works but is not deployed.

---

## UI 1 — Django Web App (primary, live on Render)

A single-page application served from `templates/index.html` via Django's `TemplateView`. All data is fetched from the Django REST API via browser-side JavaScript — no server-side template rendering for data.

### Page structure

```
base.html
├── nav bar (tab switcher)
├── partials/hero.html        ← #content-hero   (default visible)
├── partials/dashboard.html   ← #content-dashboard
├── partials/architecture.html← #content-architecture
├── partials/about.html       ← #content-about
├── footer
└── partials/scripts.html     ← all JavaScript
```

Tabs are toggled by `showTab(tabName)` in JS — visibility is controlled with Tailwind's `hidden` class. No page reloads.

### External dependencies (CDN — no local copies)

| Library | Version | Purpose |
|---------|---------|---------|
| Tailwind CSS | latest (CDN) | Utility-first styling |
| Chart.js | latest (CDN) | Time-series trend chart |
| Font Awesome | 6.4.0 | Icons throughout the UI |
| Inter (Google Fonts) | — | Typography |

### Hero tab (`partials/hero.html`)

Marketing/portfolio landing page. Static content — no API calls.

Sections:
- **Headline** with "30 Seconds, Not 2 Hours" hook
- **Stats bar** — 4 hardcoded figures: 451K rows, 37 tests, <5s speed, 99.6% time saved
- **Before/After** comparison — 2–4 hrs manual vs 30 sec automated
- **How It Works** — 4-step numbered flow (Ingest → Transform → Detect → Explain)
- **Tech stack** — 8 pill badges
- **CTA** — "Launch Dashboard" button → switches to Dashboard tab

### Dashboard tab (`partials/dashboard.html`)

The interactive analytics interface. Loads data lazily — API calls fire only when the tab is first opened.

**Controls:**

| Control | Type | Effect |
|---------|------|--------|
| Current Date | `<select>` | Populated from `/api/metrics/` response |
| Compare To | `<select>` | Populated from same; filtered to dates before current |
| Metric | `<select>` | `total_revenue` / `order_count` / `avg_order_value` |
| Anomaly Threshold | Range slider (1.0–3.0, step 0.1) | Passed to `/api/anomalies/` as `threshold` param |

**KPI cards (4):**

| Card | Metric | Source |
|------|--------|--------|
| Total Revenue | `total_revenue` — current value + Δ% vs previous | `/api/metrics/` |
| Order Count | `order_count` — current value + Δ% | `/api/metrics/` |
| Avg Order Value | `avg_order_value` — current value + Δ% | `/api/metrics/` |
| Anomalies | Count of anomalies in window | `/api/anomalies/` |

**Trend chart:** Chart.js line chart, last 60 days. Toggle between Revenue / Orders / AOV via 3 buttons. Anomaly dates are highlighted with red point markers.

**Decomposition panels (3 columns):**
Each panel shows geography / product / payment breakdown as progress bars sorted by `contribution_pct`. A "Details" toggle expands a drill-down list (region → state, group → category, payment display → payment type). Data source: `/api/decomposition/`.

**Root Cause Analysis narrative:**
Markdown rendered from `/api/narrative/` response. Copy and Download buttons for export.

**Pipeline Control panel:**
- "Run Analysis" → `POST /api/pipeline/` with `dry_run: true`
- "Run & Send Alert" → `POST /api/pipeline/` with `force_alert: true, dry_run: false`

### JS API integration pattern

All API calls follow this pattern in `partials/scripts.html`:

```javascript
async function loadMetrics() {
    const response = await fetch('/api/metrics/?days=60');
    const result = await response.json();
    // result.status === 'success' → use result.data
}
```

API calls triggered on dashboard tab open:
1. `loadMetrics()` → populates date selectors and chart
2. `loadAnomalies()` → populates anomaly KPI card
3. `loadDecomposition()` → populates 3 breakdown panels
4. `loadNarrative()` → populates narrative section

`applyFilters()` re-calls all four when the user changes date/metric/threshold.

### Contact form (`partials/about.html`)

`POST /api/contact/` with `{name, email, message}`. The Django view logs the submission; actual email sending is disabled (code commented out in `ContactView`).

---

## UI 2 — Streamlit Dashboard (legacy)

Located at `dashboard/app.py`. Standalone — connects directly to Redshift, does not go through the Django API. Run with:

```bash
streamlit run dashboard/app.py
# → http://localhost:8501
```

### Layout

```
Header (title + tagline)
    │
    ├── Date selectors (Current / Compare To)
    │
    ├── KPI cards (Revenue, Order Count, AOV) with Δ% deltas
    │
    ├── Metric trend chart (Plotly line)
    │
    ├── Root Cause Analysis tabs
    │   ├── Geography — horizontal waterfall chart (Plotly)
    │   ├── Product   — horizontal waterfall chart
    │   └── Payment   — horizontal waterfall chart
    │
    └── Alert panel (threshold slider + "Run Pipeline" button)
```

### Data caching

| Cache decorator | TTL | Applied to |
|----------------|-----|------------|
| `@st.cache_resource` | session | `get_connection()` — Redshift connection, shared across reruns |
| `@st.cache_data` | 300s (5 min) | `fetch_daily_metrics()`, `fetch_metric_by_dimension()` |

The `get_connection()` in this file intentionally uses `@st.cache_resource` rather than `config/db.get_connection()` — Streamlit's resource cache manages the connection lifecycle across reruns, which is the correct pattern for Streamlit apps.

### Key functions

| Function | What it does |
|----------|-------------|
| `fetch_daily_metrics()` | `SELECT * FROM staging.fact_daily_metrics ORDER BY metric_date` |
| `fetch_metric_by_dimension(dim)` | Fetches full table for geography / product / payment |
| `calculate_change(df, col, current, previous)` | Returns `(current, previous, change, change_pct)` for a date pair |
| `render_header()` | Title + tagline + divider |
| `render_date_selector(df)` | Two selectboxes from available dates |
| `render_kpi_cards(df, cur, prev)` | `st.metric()` cards with delta |
| `render_trend_chart(df, metric)` | `px.line()` over all dates |
| `render_decomposition(dim, cur, prev)` | Waterfall chart + expandable table |
| `render_alert_panel(cur, prev, df)` | Threshold slider + "Run Pipeline" button |
| `main()` | Entry point — orchestrates all render functions |

### Waterfall chart logic

For each dimension, the Streamlit dashboard independently recalculates contribution:

```python
current_data  = df[df['metric_date'] == current_date].groupby(segment_col)['total_revenue'].sum()
previous_data = df[df['metric_date'] == previous_date].groupby(segment_col)['total_revenue'].sum()
merged['change']       = current - previous
merged['contribution'] = change / total_change * 100
```

This mirrors the Python decomposer logic but is self-contained (no call to `decomposer.py`).

### Differences from Django dashboard

| Aspect | Django UI | Streamlit |
|--------|-----------|-----------|
| Data source | Django REST API | Direct Redshift queries |
| Chart library | Chart.js | Plotly Express |
| Deployment | Render (live) | Local only |
| Caching | Browser / API | Streamlit `@st.cache_data` (5 min) |
| Auth | None | None |
| Narrative | From `/api/narrative/` | Not shown |

---

## Template file inventory

| File | Purpose |
|------|---------|
| `templates/base.html` | Shell — nav, footer, CDN imports, includes all partials |
| `templates/index.html` | Empty — `base.html` IS the index (`TemplateView` renders it directly) |
| `templates/partials/hero.html` | Landing page content |
| `templates/partials/dashboard.html` | Dashboard UI HTML |
| `templates/partials/architecture.html` | System architecture diagram tab |
| `templates/partials/about.html` | Author bio + contact form |
| `templates/partials/scripts.html` | All JavaScript (~400 lines) |

---

## Issues Fixed

| Issue | Fix |
|-------|-----|
| `dashboard/components/drilldown_chart.py` was an empty dead file | Deleted |
| `dashboard/components/metric_selector.py` was an empty dead file | Deleted |
