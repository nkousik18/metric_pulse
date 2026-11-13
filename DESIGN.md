---
name: MetricPulse
description: A quiet, precise product UI that explains why a daily business metric moved; the only loud thing is real evidence.
colors:
  canvas: "#f7f7f8"
  surface: "#ffffff"
  surface-2: "#f1f2f4"
  border: "#e3e4e8"
  border-strong: "#cfd1d6"
  ink: "#111317"
  ink-2: "#3b3f47"
  ink-3: "#636874"
  accent: "#2563c9"
  accent-hover: "#1d52a8"
  accent-soft: "#e7f0fb"
  on-ink: "#ffffff"
  selection: "#cfe1f7"
  rise: "#2a78d6"
  fall: "#e34948"
  canvas-dark: "#0d0e11"
  surface-dark: "#15171b"
  surface-2-dark: "#1c1f24"
  border-dark: "#272a31"
  border-strong-dark: "#363a42"
  ink-dark: "#eceef1"
  ink-2-dark: "#c4c7ce"
  ink-3-dark: "#9096a1"
  accent-dark: "#58a6ff"
  accent-hover-dark: "#79b8ff"
  accent-soft-dark: "#0f2236"
  on-ink-dark: "#0d0e11"
  selection-dark: "#1d3a5c"
  rise-dark: "#3987e5"
  fall-dark: "#e66767"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "clamp(36px, 6vw, 64px)"
    fontWeight: 700
    lineHeight: 1.02
    letterSpacing: "-0.035em"
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "tnum on numeric values"
  body-sm:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 600
  mono:
    fontFamily: "ui-monospace, SF Mono, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.92em"
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
  "8": "64px"
  gap-tiles: "28px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-ink}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-primary-hover:
    backgroundColor: "{colors.ink-2}"
  button-primary-lg:
    padding: "12px 18px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  button-quiet-hover:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.fall}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
  nav-tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  nav-tab-active:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink}"
  tile:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "24px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
    height: "36px"
  chip:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.sm}"
    padding: "3px 8px"
  chip-next:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
  day-chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "7px 12px"
  day-chip-selected:
    backgroundColor: "{colors.accent-soft}"
  jump-link:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.pill}"
    padding: "6px 12px"
  segmented-active:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "5px 12px"
---

# Design System: MetricPulse

Recorded from the shipped build (`templates/partials/styles.html`, `templates/base.html`, the partials, `partials/scripts.html`) at commit d94d468. Tokens live as CSS custom properties on `:root`. Light is the default; the `-dark` colors apply under `prefers-color-scheme: dark` when `<html>` carries `dark-ready` (it always does in `base.html`). There is no manual theme toggle.

## Overview

**Creative North Star: "The Category Standard"**

A product UI built to Linear / Stripe Dashboard craft and not to a marketing-page template: cool neutral greys, white panels on a near-white canvas, near-black ink, one restrained blue accent, system type, hairline borders. The page stays quiet so the evidence (a 64px "Revenue fell 90.6%", the trend, the segment bars, eval figures with denominators) can carry the weight.

The density is moderate. Narrow reading pages (960px) use one column of stacked tiles. The single focal point on Overview is the answer headline, set at display size directly on the canvas with no card around it. Everything else sits in elevated white tiles or behind disclosures.

Where the build departs from the direction contract (`.impeccable/surfaces/templates-base-html.md`), the build is recorded here: the first viewport is one 960px column led by the answer headline, not a two-thirds anomaly panel with a one-third eval scorecard beside it; eval scores live on the AI agents tab, with a single proof line under the answer; tabs are Overview, AI agents, How it's built, About (not Investigate and Approvals); flagged days sit below the chart and breakdowns, not above the panel; the contribution view is per-dimension bars colored rise/fall, not a diverging-axis chart; the cited agent answer is one click away, not on the first screen.

**Key Characteristics:**
- System UI font stack only; monospace only for ids, code, payloads and action types.
- Tabular figures on every number (`.num`, tables, deltas, chips).
- One accent (blue, hue about 217 light / 212 dark), never indigo or violet.
- Data color is a validated blue/red diverging pair (rise/fall), used only for data.
- Hairline 1px borders, small radii (6/8/12px), soft ambient tile shadow; no gradients, no glow, no lift on hover.
- Sentence-case labels; no uppercase, no letter-spaced eyebrows, no emoji; icons are inline SVG.

## Colors

Cool neutrals carry everything; the accent and the data pair are the only chroma on screen.

### Primary
- **Restrained Blue** (`accent`; dark `accent-dark`): links, the chart line and its 7% fill, the "next recorded step" chip, the pipeline's agent tags, focus outlines. Hover deepens to `accent-hover`. `accent-soft` is its tinted fill (selected day chip, info callout, agent tags).

### Tertiary (data only)
- **Rise Blue** (`rise`) and **Fall Red** (`fall`): the diverging pair for segments that rose or fell, delta arrows, contribution bars and legend swatches. Validated with the dataviz palette tool on white and on the dark surface (CVD-safe, at least 3:1). Fall Red also doubles as the error and destructive color (`btn-danger`, `callout-error`, `status-text.is-error`), always tinted via `color-mix` rather than as a solid fill.

### Neutral
- **Office Canvas** (`canvas`): page background.
- **Panel White** (`surface`): tiles, inputs, secondary buttons, the header (at 92% with blur), the footer.
- **Quiet Grey** (`surface-2`): hover fills, active tab and segmented-control track, chips, prose boxes, table headers, bar tracks.
- **Hairline** (`border`) and **Firm Hairline** (`border-strong`): dividers and tile edges; `border-strong` for interactive outlines (inputs, chips, secondary buttons).
- **Ink** (`ink`), **Ink 2** (`ink-2`), **Ink 3** (`ink-3`): headings and figures, body copy, meta and labels. `ink` is also the primary-button fill, with `on-ink` text.

### Named Rules
**The One Accent Rule.** Blue is the only UI accent. Primary buttons are ink, not accent; accent marks links, the trend line, focus and "next step" signals.
**The Data-Only Color Rule.** Rise and fall appear only where a value rose or fell (or an error/destructive state). Never decorative.
**The No Violet Rule.** The accent stays in the 210 to 220 hue band in both themes; the earlier periwinkle dark accent was replaced for this reason.

## Typography

**Body Font:** system UI stack (-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif)
**Mono Font:** ui-monospace, SF Mono, Menlo, Consolas

**Character:** One family, weight and tracking do the work. Large sizes tighten letter-spacing (to -0.035em at display); small sizes stay at normal tracking.

### Hierarchy
- **Display** (700, clamp(36px, 6vw, 64px), 1.02, -0.035em): the Overview answer headline only. One per page.
- **Headline** (650, 28px, 1.2, -0.02em): page titles and big figures (KPI values, eval score figures at 28px/1.1). The About/intro title grows to clamp(28px, 4vw, 40px).
- **Title** (600, 17px, 1.3, -0.01em): tile and section titles. Subheads are 600 at 15px.
- **Body** (400, 15px, 1.55): copy; ledes run at 17px in `ink-2` capped at 62ch; running text caps at 68 to 75ch.
- **Small** (13px): tabs, buttons, chips, meta lines, table cells, tile subtitles.
- **Label** (600, 12px, sentence case, `ink-3`): field labels, table headers, inline labels, score context.

### Named Rules
**The Tabular Figures Rule.** Every number that can be compared uses `font-variant-numeric: tabular-nums`.
**The Mono Means Machine Rule.** Monospace is only for ids, commit SHAs, code, JSON payloads and action-type chips.

## Layout

- **Container:** `page-max` 1200px for header, footer and banner; reading pages use `page-narrow` (960px), one column. Page padding 32px top, 24px sides, 64px bottom; 24/16/48px at 640px and below.
- **Header:** sticky, 56px minimum height, wordmark, tabs, then Source (quiet) and Contact on LinkedIn (primary) on the right.
- **Rhythm:** 4px base scale (4, 8, 12, 16, 24, 32, 48, 64). Tiles stack 28px apart (`gap-tiles`); 48px after an intro; 64px between sections on the long-read How it's built page; 4 to 8px inside groups, 16 to 24px inside tiles.
- **Grids:** three-column breakdowns and KPI rows, a four-step flow, a 4+auto filter grid, auto-fit score rows (min 170px), a 1fr/1.25fr About split with a sticky intro.
- **Breakpoints (max-width):** 960 (filters to two columns), 860 (About to one column), 760 (tabs wrap below the wordmark and scroll horizontally; breakdowns to one column), 640 (tighter padding, chart 300 to 220px tall, many two-column grids to one, tables stack into rows), 560 (KPIs to one column), 480 (filters to one column, approval buttons full width), 420 (button long labels hidden, skills list stacks).

## Elevation & Depth

A hybrid: mostly flat tonal layering (canvas, surface, surface-2) with one soft ambient shadow that marks a tile as a container. Shadows never respond to hover.

### Shadow Vocabulary
- **Tile** (`box-shadow: 0 1px 2px rgba(17,19,23,0.05), 0 8px 24px -8px rgba(17,19,23,0.14)`): every tile.
- **Small** (`0 1px 2px rgba(17,19,23,0.06)`): secondary buttons and the active segmented option.
- **Medium** (`0 4px 12px rgba(17,19,23,0.08), 0 1px 3px rgba(17,19,23,0.06)`): the fixed replay notice only.
- Dark theme swaps all three to black-alpha versions (0.4 to 0.6).
- The sticky header uses a 92% surface with `saturate(1.4) blur(10px)`, not a shadow.

### Named Rules
**The No Lift Rule.** Hover changes background or text color only; nothing translates, scales or gains shadow.

## Shapes

Gently rounded rectangles: 6px for small controls (tabs, chips, segmented options, code boxes), 8px for buttons, inputs, day chips and callouts, 12px for tiles and the replay notice. The only full pill is the agents-page jump link. Bars use 4px ends and swatches 3px. Borders are 1px hairlines; disclosure chevrons are drawn with two 1.5px borders, rotated.

## Components

### Buttons
- **Shape:** 8px radius, 13px at weight 550, 9px by 14px; large variant 15px, 12px by 18px.
- **Primary:** ink fill, `on-ink` text; hover to `ink-2`. In dark mode this inverts to a light button.
- **Secondary:** surface, `border-strong` outline, small shadow; hover to `surface-2`.
- **Quiet:** transparent, `ink-2`; hover fills `surface-2`.
- **Danger:** surface with fall-red text and a 45% fall-tinted border.
- **Transitions:** 120ms on color, background and border with `cubic-bezier(0.16, 1, 0.3, 1)`. Disabled is 50% opacity.

### Navigation
- Four text tabs (Overview, AI agents, How it's built, About), 13px/500 in `ink-3`. Hover and active both use the `surface-2` fill with `ink` text; active state is the fill, not an underline. At 760px and below the tabs move to a full-width, horizontally scrolling row.
- A segmented control (3px `surface-2` track, the active option a surface pill with small shadow) switches chart metrics.

### Chips
- **Chip:** 12px/500, `surface-2` fill, `ink-2`, 6px radius. `chip-strong` is mono 600 ink (action types). `chip-next` is accent text on `accent-soft`.
- **Day chip:** a selectable two-line button (date and metric in 600 tabular, meta in 12px `ink-3`), surface with `border-strong`. Selected is an `accent-soft` fill with a 55% accent border, never a ring; rings belong to keyboard focus.

### Cards / Containers
- **Tile:** surface, 1px `border`, 12px radius, tile shadow, 24px padding. Head row: title and subtitle left, actions or legend right, wrapping.
- **Prose box:** `surface-2`, 8px radius, 16px by 24px, line height 1.65, for generated narrative and investigation output.
- **Callout:** 8px radius, `surface-2` with `border`; info is `accent-soft` with a 30% accent border; error is a 10% fall tint.
- **Disclosure:** a top hairline, 600 13px summary with a rotating chevron (150ms).

### Inputs / Fields
- Surface fill, `border-strong`, 8px radius, 8px by 10px, minimum 36px tall, 13px text. Focus is a 2px `focus` (accent) outline offset 1px; globally `:focus-visible` is 2px offset 2px. Range and checkbox use `accent-color: ink`.

### Focal answer (Overview)
The answer section has no card: display headline, a 17px tabular subline, an optional warning note (`surface-2`, `border-strong`), a drivers line, an inline stat list (Revenue / Orders / Avg order value with delta arrows), then a large primary button and a quiet button, and a 13px eval proof line.

### Eval score row
A definition list in auto-fit columns (min 170px): the figure as `n/N` at 28px/650, the label in 13px `ink-2` beneath, context (denominator kind, percentage) at 12px `ink-3`, followed by an "Eval run date at commit sha" meta line with the sha in mono.

### Contribution bars
Per-dimension rows: name and tabular value on one line, an 8px `surface-2` track below with a rise or fall fill scaled to the column's largest share (min 2px). A legend of 10px swatches sits in the tile head.

### Trend chart (Chart.js 4.4.1)
Line chart, 300px tall (220px on phones), colors read from the CSS tokens at draw time so it follows the theme: 2px accent line, monotone interpolation, accent fill at 7% alpha, no legend. Points are hidden except flagged days (5px ink dots) and the selected day (7px ring: surface fill, ink border). Y axis starts at zero with at most 5 ticks and `border` gridlines; no x gridlines; ticks 12px `ink-3`. Tooltip is a surface box with a `border` outline, 10px padding, no color swatches, plus a crosshair plugin.

### Approval card
A tile with a chip row (action type, tier and reversibility, tabular subject), the narrative in ink at 1.6 line height, a "Evidence, payload and decision" disclosure (cited evidence bullets, target, mono JSON payload textarea, reason field, checkbox), and Approve (primary), Approve with edits (secondary) and Reject (danger) actions, then a 12px meta line with the proposal id in mono. Undo rows use a four-column grid that collapses at 640px.

### Pipeline diagram (How it's built)
A vertical timeline: 2px `border` rail, 12px ring nodes (surface fill, 2px ink border), a 160px stage-name column, and accent-soft agent tags where an agent attaches.

## Do's and Don'ts

### Do:
- **Do** take every color, size, space, radius and shadow from the `:root` custom properties; charts read them with `getComputedStyle`.
- **Do** keep primary buttons ink and reserve the accent for links, the trend line, focus and next-step signals.
- **Do** use tabular figures for numbers and show eval scores with their denominators (`25/30`).
- **Do** mark selection with a tinted fill and 1px border, and focus with a 2px accent outline.
- **Do** keep hover to a background or text-color change at 120ms.
- **Do** honor `prefers-reduced-motion` (transitions and animations drop to 0.01ms).

### Don't:
- **Don't** use indigo, violet or purple anywhere, in either theme.
- **Don't** use gradients, glow, colored shadows or lift-on-hover.
- **Don't** add webfonts or display faces; the system stack is the type system.
- **Don't** use emoji or icon fonts; icons are small inline SVGs using `currentColor`.
- **Don't** use rise/fall colors decoratively.
- **Don't** set labels in uppercase or add letter-spaced eyebrow lines above titles.
