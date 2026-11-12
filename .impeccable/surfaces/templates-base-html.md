---
version: 1
slug: "templates-base-html"
primary_target: "templates/base.html"
related_targets: ["templates/index.html","templates/partials/scripts.html"]
---

# Surface brief: the MetricPulse site (local app + static replay)

**Scope:** `templates/base.html` and every partial, plus the markup `partials/scripts.html` builds,
served by Django and by the static replay (`demo/build.py`). **Mode:** Persuade on the first screen
(a hiring manager decides to reach out); Operate inside Investigate and Approvals.

**Audience and job:** hiring managers giving it 30 seconds (PRODUCT.md). They must see a real
anomaly explained, with citations and eval scores, and know who built it. **Primary action:**
contact on LinkedIn. **Structure (confirmed):** a short intro first; then a real anomaly
explained with the eval scorecard beside it; flagged days replace the date dropdowns; tabs become
Investigate · Approvals · How it's built · About. **Must not feel:** like a SaaS template, or playful.

## Direction contract

THESIS: The category standard, executed straight at Linear / Stripe-dashboard craft: a quiet,
precise product UI whose only loud thing is real evidence. Refuses the marketing landing page
(hero, feature cards, gradient CTA) that the old site was.

OWN-WORLD: Light by default (daytime office, phone from LinkedIn), dark via the OS setting. Cool
neutral greys, white panels on a near-white canvas, near-black ink, one restrained accent that is
not indigo or violet; data colours from the dataviz skill's validated palette, never decoration.
System UI type with tabular figures, monospace only for ids and code. Hairline borders, small
radii, no gradients, no glow, no lift-on-hover, no emoji, inline SVG icons.

STORY: The visitor reads who built it and what it does in one line, sees revenue fell 90.6% on a
real day, reads the agent's answer with each claim cited, sees the eval scores with denominators
beside it, and clicks LinkedIn; an engineer goes on to Approvals and How it's built.

FIRST VIEWPORT: Top bar: wordmark left, four tabs, LinkedIn button right. Intro line under it
with the author's name. Main row: the anomaly panel (two thirds) with the headline change at
display size, the trend with the flagged day marked, a diverging contribution chart and the cited
finding; the eval scorecard panel (one third) with four evals. Flagged days as a selectable list
above the panel.

FORM: Category standard (canon), chosen by Kousik on the decision page; benchmarks Linear and
Stripe Dashboard + docs. Seed key 9f8299ad.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
