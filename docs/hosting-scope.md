# MetricPulse Hosting — Scope

**Status:** Draft 2026-11-12, awaiting Kousik's approval · **Owner:** Kousik Nandury · **Date:** 2026-11-12
**Tracked in:** `docs/ROADMAP.md` → "Hosting" (milestones H1–H3)

## 1. Why this exists

MetricPulse has nothing a reviewer can click. The Render deployment is gone (the old Render account
no longer works), the AWS stack was deleted on 2026-11-02, and eight places in `docs/` (plus the
README's framing) still say "live on Render". For the job search the project needs a link that shows
what the application actually does — the pipeline, the investigation agent, onboarding, and the
Action Agent with its approval queue — and loads instantly for someone giving it 30 seconds.

## 2. Goal

Two public surfaces, in this order:

1. **H1 — a static replay site on GitHub Pages.** Always up, instant, free, no abuse surface. Every
   result on it is a **recorded output of the real system**, not mock data: the real pipeline and
   agents are run once against Olist and Superstore, their API responses are saved, and the site
   plays them back. It is the primary link in the README and on the resume.
2. **H2 — the real Django app on Render's free tier, in demo mode**, linked from H1 as "Try it
   live (takes ~1 minute to wake up)". Real detection, decomposition and LLM investigations, with
   every effect outside the server switched off.

Then **H3**: point every doc at the real URLs.

## 3. Ground rules (decided by Kousik, 2026-11-12)

- **R1 — Show the real thing.** The static site replays real recorded outputs; no hand-written mock
  data or dummy functions standing in for the agents. Anything shown on the site must be
  reproducible by a command in this repo. The site says when the outputs were recorded.
- **R2 — Static first.** H1 ships before H2; H2 is additive.
- **R3 — Nothing public can cause an outside effect.** No GitHub issues, no real alerts, no email,
  and no unbounded spend on Kousik's Groq key, whatever a visitor sends.
- **R4 — AWS code stays** (`docs/local-stack-scope.md` R1 still holds). Hosting adds files; it
  doesn't remove the Lambda `Dockerfile`, `cd.yml` or `deploy/`.
- **R5 — A new Render account**, made by Kousik (the old one doesn't work). The repo holds only
  config; credentials live in Render's dashboard.

## 4. Non-goals

- A custom domain, paid hosting, or always-on (no-sleep) Render.
- User accounts or multi-tenant data. There is one shared demo dataset.
- Live onboarding of visitor-uploaded files on either surface (cost and abuse; the recorded
  Superstore onboarding run shows it instead).
- Rewriting the SPA in a framework. Both surfaces reuse the existing templates.
- The legacy Streamlit dashboard (`dashboard/app.py`) — not hosted.

## 5. Facts this scope is built on (measured 2026-11-12)

| Fact | Value | Consequence |
|---|---|---|
| SPA | `templates/index.html` + 6 partials (~92 KB); every data call is a `fetch('/api/...')` in `partials/scripts.html` (10 endpoints) | One fetch shim can redirect all calls to recorded JSON for H1 |
| Warehouse | `data/warehouse.duckdb` 34 MB, gitignored; raw CSVs 120 MB, gitignored | Can't deploy as-is |
| Tables the app reads | the `staging` schema only: 4 dims/facts + 3 `metric_by_*` (32,531 rows) | A staging-only snapshot is **2.1 MB** (230 KB gzipped) |
| Committed CI sample | Olist orders from 2018-08-01 only | Too thin to be the demo data |
| App memory | ~185 MB after importing Django + every agent module | Fits Render free (512 MB) with one gunicorn worker |
| Existing Render config | `render.yaml`, `Procfile`, `settings_prod.py` (whitenoise, `ALLOWED_HOSTS=.onrender.com`) | Reuse; fix rather than rewrite |
| Public-safety gap | `/api/actions/<id>/approve\|edit\|undo` take `"live": true` with no auth | A visitor could open real GitHub issues; must be closed for H2 |
| LLM cost | `/api/investigate/` and `/api/pipeline/` call Groq; throttled 5/min per client, no daily cap | Needs a global daily cap for H2 |

## 6. Design

### 6.1 H1 — Recording real runs (`demo/record.py`, new)

A recorder that drives the **real** Django views through Django's test client (no server, no
mocking) and writes each response to `demo/site/data/<endpoint>/<params>.json`, plus a
`manifest.json` (git SHA, model names, prompt hashes, record date, the command that produced it).

What it records:
- `/api/metrics/`, `/api/anomalies/` for each threshold the SPA offers, and `/api/decomposition/`
  + `/api/narrative/` for every anomaly date the dashboard lists (Olist, full data).
- `/api/investigate/` for a curated set of anomalies (Golden Case #1, Black Friday 2017, the
  2018-11-24 spike, and the data-tail freshness case) — real Groq calls, recorded once, with the
  LangSmith trace URL saved alongside each when tracing is on.
- The Action Agent: real proposals for the same anomalies, the pending queue, and one walk-through
  each of approve, edit, reject and undo (dry-run, `live=false`), so the Actions tab replays a real
  approval flow.
- Onboarding: the recorded Superstore run (classification, reconciliation, four-metric results).
- Evals: the latest drift report and per-eval numbers from `evals/ledger.jsonl`.

The recorder is deterministic apart from the LLM calls and refuses to run on a dirty tree, so every
recording maps to a commit.

### 6.2 H1 — Building the static site (`demo/build.py`, new)

- Render the existing Django templates to plain HTML (`render_to_string`), copy static assets, and
  inject a small `replay.js` before `scripts.html` that wraps `window.fetch`: `/api/...` requests are
  answered from `data/` by URL and parameters. Non-API requests pass through.
- A request the recording doesn't cover (e.g. an unrecorded threshold) gets a clear in-page message
  — "This demo replays recorded runs; try it live →" with the H2 link — never a fake answer (R1).
- Write actions (approve/edit/reject/undo) step through the recorded flow in order, so clicking
  Approve shows the real recorded result.
- A visible banner on every page: "Replaying real outputs recorded on <date> at commit <sha>".
- The contact form is hidden on the static site.

### 6.3 H1 — Publishing (`.github/workflows/pages.yml`, new)

GitHub Pages from Actions: on push to `main` touching `demo/`, run `demo/build.py` from the
committed recordings and deploy. Building needs no secrets and no LLM calls; re-recording is a
manual local step (`python -m demo.record`), committed like any other change.

### 6.4 H2 — Data snapshot (`ingestion/make_demo_snapshot.py`, new)

Copies the `staging` schema of `data/warehouse.duckdb` into `data/demo/warehouse_demo.duckdb`
(~2.1 MB, committed). Same licence and attribution as the CI sample (CC BY-NC-SA 4.0), noted in a
README beside it. Regenerate with the command, never hand-edit. Prod settings point `WAREHOUSE_PATH`
at it; the app opens it read-only.

### 6.5 H2 — Demo mode (`DEMO_MODE=true`, `config/settings.py`)

One switch, on in `render.yaml`, off everywhere else:
- **Live effects off, server-side:** the action views ignore `"live"` and always build the agent with
  `live=False`; the notifier is forced to the outbox. (R3)
- **Daily LLM cap:** a global counter (SQLite) on `/api/investigate/` and `/api/pipeline/`, e.g.
  50 calls/day; past it, the endpoint returns the recorded H1 answer for that anomaly, labelled as
  recorded. Per-client throttles stay.
- **No alerts:** `/api/pipeline/` runs with `dry_run`.
- **Ephemeral state is fine:** `actions.db`/checkpoints/outbox live on Render's temporary disk and
  reset on each deploy or wake; the queue is re-seeded with the recorded proposals at startup.
- **Contact form:** disabled (its email is already commented out).

### 6.6 H2 — Render config

Update `render.yaml`: one gunicorn worker (memory), `DEMO_MODE=true`, `WAREHOUSE=duckdb`,
`ALERT_CHANNEL=outbox`, `LANGSMITH_TRACING=false`, `GROQ_API_KEY` as a dashboard secret
(`sync: false`), health check on `/api/health/`. Install only what the web app needs: a new
`requirements-web.txt` (no dbt, Streamlit, Redshift/boto) to cut build time and memory.

## 7. Requirements

| # | Requirement | Check |
|---|---|---|
| Q1 | Static site loads with no backend and every visible number traces to a recording | Build with network to `/api` blocked; every tab renders |
| Q2 | Recordings are reproducible | `python -m demo.record` on the recorded SHA reproduces the deterministic files byte-for-byte |
| Q3 | No public request causes an outside effect | Tests: `DEMO_MODE` ignores `live: true`; notifier is outbox; pipeline is dry-run |
| Q4 | LLM spend is bounded | Test: the cap returns the recorded answer after N calls |
| Q5 | Render app fits the free tier | Deployed, `/api/health/` 200, peak memory < 400 MB |
| Q6 | Docs are true | No "live on Render" claim without a working URL |

## 8. Milestones

- **H1 — Static replay site.** Recorder, builder, `replay.js`, Pages workflow, README link.
  Gate: the Pages URL loads every tab from recordings (Q1, Q2), checked in a browser.
- **H2 — Render demo-mode app.** Snapshot, `DEMO_MODE`, daily cap, `requirements-web.txt`,
  `render.yaml`; Kousik creates the Render account and adds `GROQ_API_KEY`. Gate: Q3–Q5, a real
  investigation run on the live URL, and H1's "Try it live" button pointing at it.
- **H3 — Docs.** Replace the 8 "live on Render" mentions and the README's demo section with the H1/H2
  URLs; CHANGELOG. Gate: Q6.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Recordings go stale as the code changes | Banner shows record date + SHA; re-record is one command; drift run already flags quality changes |
| Render free sleeps (≈1 min cold start) | H1 is the primary link; H2 is labelled as slow to wake |
| Render free tier terms change | H1 doesn't depend on it |
| Olist licence is non-commercial (CC BY-NC-SA) | Portfolio use is non-commercial; attribution on both sites and beside the snapshot |
| Groq key abuse | Daily cap + per-client throttle + key only in Render's dashboard |

## 10. Decision log

| Date | Decision | By |
|---|---|---|
| 2026-11-12 | Static GitHub Pages site first, Render live app second | Kousik |
| 2026-11-12 | Static site replays real recorded outputs, not mock data or dummy functions | Kousik (on Claude's recommendation) |
| 2026-11-12 | New Render account, since the old one doesn't work | Kousik |
| 2026-11-12 | Demo data: a committed staging-only snapshot of full Olist (2.1 MB), not the CI sample | Proposed — confirm on approval |
| 2026-11-12 | Public H2 runs in demo mode: live effects off server-side, daily LLM cap | Proposed — confirm on approval |
