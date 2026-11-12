# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary (confirmed 2026-11-12): hiring managers and recruiters giving the site about 30
seconds,** arriving from Kousik's resume or LinkedIn. In that time they need to see a working
product and what it proves, then decide whether to dig in. Technical interviewers checking depth
are a secondary audience; the depth has to be one click away, not on the first screen.

Analysts using MetricPulse as a day-to-day tool are not the audience for the public site.

## Product Purpose

MetricPulse explains why a daily business metric moved. It detects an anomalous day (z-score plus
a data-freshness check), decomposes the change across segments (geography, product, payment), and
writes a plain-English narrative. Three LLM agents sit on top: an investigation agent that
explains an anomaly with every claim cited to the numbers, an onboarding agent that classifies an
unseen CSV so the same pipeline runs on it, and an Action Agent that proposes a response and holds
it for human approval (approve, edit, reject, undo).

It is a portfolio project for an active job search. Success for the public site: a hiring manager
leaves believing the AI is real, grounded and measured, and that one person built the whole system.

## Positioning

The claim (confirmed: the AI and the evals should shine, together with end-to-end ownership):
**the agents are grounded and governed, and their quality is measured, not asserted.** Every agent
claim is checked against the evidence, every agent has an eval with a baseline and a drift run, and
the Action Agent cannot act without a human. That sits on a pipeline one person built end to end:
ingestion, dbt, detection, decomposition, agents, evals, CI.

What a neighbouring "AI analytics demo" can't truthfully copy: published eval numbers with their
denominators, adversarial and safety results, and replayed real runs instead of mock data.

## Operating Context

- The public surface is a static GitHub Pages site that replays real recorded API responses
  (`demo/`); nothing on it calls a server or an LLM. A live demo-mode app on Render is planned (H2).
- The same Django templates serve the local app and the static site, so the design must work for
  both. `templates/partials/scripts.html` drives the page through fixed element ids and builds
  some markup in JavaScript.
- Visitors arrive cold, often on a phone from LinkedIn, sometimes on a laptop from a resume link.

## Capabilities and Constraints

- Data: Olist Brazilian e-commerce (CC BY-NC-SA 4.0, attribution required), 451,535 rows across 7
  tables, 2016-09-04 to 2018-09-03. The dashboard shows the last 60 days. A second dataset,
  Superstore, demonstrates onboarding.
- Local stack: DuckDB + dbt-duckdb (11 models, 37 tests), Markdown alert outbox. The AWS stack
  (S3, Redshift, Lambda, SNS) was deleted in Nov 2026; its code is kept but nothing runs on it, so
  the site must not present AWS as the live architecture.
- Models: Groq `gpt-oss-120b` (investigation, onboarding, escalation) and `gpt-oss-20b` (Action
  Agent first draft). LangGraph for the agents, LangSmith tracing (private org).
- Known product gaps the design must not hide or misdraw: segment contributions can exceed 100%
  or offset each other; "Run Analysis" on Avg Order Value fails (BUG_LOG A4-1); the data ends
  with an incomplete day (2018-09-03).
- No build step today (CDN scripts). Undecided: whether the redesign keeps a no-build setup.

## Brand Commitments

- The name **MetricPulse** stays. Its wordmark treatment is open.
- **Contact links stay:** GitHub (github.com/nkousik18), LinkedIn (linkedin.com/in/kousik-nandury),
  email, and the repo link.
- **Architecture content stays,** corrected to the real local stack.
- Everything else (tabs, layout, copy structure, the current look) is open. The current indigo/
  violet, Inter, gradient-text look is explicitly rejected ("screams AI generated").

## Evidence on Hand

All real, from `evals/ledger.jsonl` (latest runs, 2026-11-12) and `demo/recordings/`:

- Action Agent: right action on 15/15 golden cases; grounding 15/15; 0 injection bypasses and 0
  injections followed in 10 adversarial cases; 0 unauthorized executions in 20 safety probes;
  about $0.0004 per run, p95 3.5 s.
- Investigation agent: grounding 25/30, matches the expected root cause 22/30, 0 fallbacks.
- Detection: F1 0.92 on 28 hand-labelled days (with the freshness check: precision 12/13, recall 12/12).
- Onboarding: date column, grain and metric columns right 6/6; dimension columns 3/6; all fields
  2/6. (Weaker numbers stay visible; they are part of "measured, not asserted".)
- Recorded runs: three labelled anomalies with real investigations and Action Agent proposals, an
  approve/edit/reject/undo walk-through, Superstore onboarding, 60 days of metrics.
- Bio facts in `templates/partials/about.html`: Northeastern MS Data Analytics Engineering
  (completed May 2026), prior Capgemini experience, Mahindra University B.Tech.

Absent, never to be invented: users, customers, testimonials, company logos, uptime or speed
claims beyond the measured numbers. The current hero's "99.6%" and "<5s" tiles are hand-written
and unverified; drop or replace them with recorded numbers.

**Degree status (confirmed by Kousik, 2026-11-12):** the Northeastern MS Data Analytics
Engineering finished in **May 2026**. The About section's "Expected: April 2026" is out of date and
must not be reused.

## Product Principles

1. **Show the real thing.** Every number and output on the site comes from a recording or the
   ledger, with its denominator. No mock data, no unverifiable claims.
2. **Lead with an answer, not a pitch.** The first screen shows a real anomaly explained, not a
   description of what the product could do.
3. **Make the guardrails visible.** Citations, eval scores, the approval step and the "not
   recorded" boundary are features to show, not fine print.
4. **Depth on demand.** A 30-second visitor gets the claim and the proof; an engineer can reach
   the architecture, evals and traces in one click.
5. **Honest about limits.** Weak eval numbers, the incomplete last day and over-100% contributions
   are shown accurately, not smoothed over.
