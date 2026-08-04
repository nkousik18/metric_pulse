# How we work: documentation and session conventions

This started as a written-up reflection from a different project (Interpose) and was adopted
wholesale into MetricPulse on 2026-07-28 (see `docs/project/SESSION_LOG.md`'s entry for that
date) — the scaffolding it describes (`docs/ROADMAP.md`, `docs/project/SESSION_LOG.md`,
`CHANGELOG.md`, `concepts/`, `CONTRIBUTING.md`) didn't exist here before that. What follows has
since been rewritten to describe what MetricPulse itself actually does, not what Interpose did —
the discipline is genuine now, evidenced by real session log entries and roadmap checkbox
history, but every concrete file name, command, and example below is this project's own.

The short version: **every session starts with total amnesia**, so anything that needs to
survive to the next session has to be written down, in the right file, in a shape a cold read
can actually use. Everything below is in service of that one constraint.

## The document map

These files carry project state, each answering a different question and changing at a
different rate. Knowing which one to reach for is most of this discipline.

| File | Question it answers | Changes... | Audience |
|---|---|---|---|
| `README.md` | What is this, why should I care, how do I run it | rarely | an outside visitor |
| `CLAUDE.md` | How do we work together, what's non-negotiable | rarely | a fresh AI session |
| `docs/ROADMAP.md` | Which phase are we in, what's left to hit the gate | phase-by-phase | anyone tracking progress |
| `docs/scoping.md` | The design record for the agentic-layer initiative — goals, non-goals, decision log | as sections get designed | whoever's about to implement a milestone |
| `docs/resume_project_doc.md` | The full, exhaustively verified source of truth — every stat, table, and decision in one place | when a layer's real behavior changes | resume-writing, interview prep, or anyone needing ground truth fast |
| `docs/project/SESSION_LOG.md` | What happened *last time*, what's next | every session | the very next session |
| `CHANGELOG.md` | What's shipped, in user-facing terms | every notable change | a user of the software |

`concepts/` sits alongside these as one more thing, but it's not project *state* — it's an
accumulating explainer library. Unlike a from-scratch learning project where this folder grows
one file at a time as new ideas are first encountered, MetricPulse seeded it in one pass
(`concepts/00`–`04`, covering `CLAUDE.md`-as-mechanism, state graphs/LangGraph, grounding LLM
output, deterministic-vs-LLM judgment, and human-in-the-loop design) from ideas already worked
out during the `docs/scoping.md` conversation — it's being used as a reusable reference library
for the agentic-layer work, not a live "here's something new to me" log. New files still get
added the same way going forward, when a genuinely new idea shows up.

`docs/scoping.md` and `docs/ROADMAP.md` track the same milestones but answer different
questions — `docs/ROADMAP.md` says whether a milestone is *built* (checkbox), `docs/scoping.md`
is the *design record* (what it should do and why). A section being written up in the scoping
doc does not mean it's implemented; don't assume otherwise.

## Writing the README

Audience: someone who has never seen this project and is deciding whether to keep reading —
a recruiter, an interviewer, a stranger who found the repo. It is *not* written for the next
work session (that's what `SESSION_LOG.md` is for) and it is not written for the AI (that's
`CLAUDE.md`'s job) — mixing those audiences into one file is how READMEs turn into unreadable
kitchen-sink documents.

What ours actually does, in order:

1. **One paragraph: what it is**, plus a one-line "Live Demo" link — the fastest possible proof
   this is real and running, not just described.
2. **A status line, stated honestly.** "core pipeline ... is live and stable. A LangGraph-based
   agentic layer is currently in design — see `docs/ROADMAP.md` for what's built vs. planned." —
   a reader should never have to infer maturity from vibes or dig through commits to find out how
   far along something is. Overstating status is the single fastest way to lose credibility with
   the audience this file is for.
3. **The Problem / The Solution**, in plain language, before any architecture diagram — the
   business case has to land before the tech stack does, since the audience here (interviewers,
   recruiters) is judging "does this person understand why this matters," not just "can they
   build a pipeline."
4. **Quickstart that actually runs**, copy-pasteable real commands (`python -m venv` + `pip
   install`, the ingestion scripts, `dbt run`, `python manage.py runserver`), not prose
   describing commands. If a reader can't get something running from this section alone, the
   section has failed regardless of how good the prose above it is.
5. **Repo layout**, as a short annotated tree, not a paragraph — someone deciding whether to
   dig further wants a map, not a narrative.
6. **A pointer to `docs/` and `concepts/`**, not a copy of either — this is where the depth
   becomes visible to an outside reader without bloating the README itself.

The test for whether the README is doing its job: could someone with no context clone the repo
and be running it within the quickstart section alone, with no other file open?

## Writing CLAUDE.md

Audience: a fresh Claude Code session with zero memory of anything that happened before it.
This file gets loaded into *every* session's context automatically, whether or not anything in
it is relevant to that session's actual task — which sets the one hard constraint everything
else follows from: **it has to earn its keep at the top of every context window, forever, so it
stays short.**

What it holds, and — just as important — what it deliberately doesn't:

- **What this project is**, in a couple of sentences, plus pointers to the real docs
  (`docs/README.md`'s index, `docs/resume_project_doc.md`, `docs/ROADMAP.md`). Not the docs
  themselves.
- **The session-start/session-end ritual**, stated as an instruction, not a suggestion — "read
  `SESSION_LOG.md` and `ROADMAP.md` before doing anything else" and "append a session log entry
  at the end" are the two lines that make every other convention in this document actually
  happen, session after session, without being re-asked.
- **How the owner wants to work.** For MetricPulse specifically: this is a portfolio project run
  alongside an active job search, so pacing is "paced by real availability, not by a date" (per
  `docs/ROADMAP.md`'s own framing) — but the quality bar doesn't relax to match: a roadmap
  checkbox only gets checked when its gate is *actually, verifiably met* (a real test run, a real
  command executed), never on the strength of code that merely looks right.
- **Repo conventions** stated as pointers, not payloads — "module invocation is
  `python -m <package>.<module>`, see each layer's own `README.md`," not a copy of that
  README. If a convention needs more than a sentence to state, it belongs in `docs/` or
  `concepts/` with a one-line reference here.

What it explicitly is *not*: an enforcement mechanism. Nothing stops a session from drifting
from it — it works because it's read in good faith at the top of context, the same way an
onboarding doc doesn't physically stop a new hire from cutting a corner. When something drifts,
the fix is a `CLAUDE.md` update (or a spoken correction), not a technical guardrail.

## Keeping the session log

`docs/project/SESSION_LOG.md` is the one file that closes the actual amnesia gap — it's the
only one granular enough to say "we corrected X, decided Y, and the very next thing to do is
Z," the texture that would otherwise only ever have existed in a chat transcript nobody else
can read.

**Mechanics that matter:**

- **Newest entry at the top.** The file's own header says "append-only," which is about the
  *editing* discipline (past entries are never rewritten to fix history) — in practice that
  means every new entry is *added above* the previous newest one, not appended to the bottom
  of a growing file a reader would have to scroll through. A session starting cold reads the
  top of the file first and gets the freshest state immediately.
- **One entry per work session**, not per calendar day — a single long session and a quick
  five-minute one both get exactly one entry, sized to what actually happened.
- **A fixed shape**, every time, because a cold reader shouldn't have to guess where to look
  for a given kind of fact:
  - **What happened** — the concrete work, in enough detail that a decision can be
    reconstructed later without re-deriving it (this is the section that should name real bugs
    found, real things verified live, not just "implemented X").
  - **Decisions made** — the small number of judgment calls worth surfacing on their own,
    separated out from the narrative above so they're skimmable.
  - **Current state** — where things stand right now, stated plainly enough that `ROADMAP.md`'s
    checkboxes and this line should never contradict each other.
  - **Next steps** — the actual next thing to do, not a vague direction. This is the line a
    cold-started next session reads to know where to pick up.
  - **Loose ends / reminders** — anything that doesn't fit the above but shouldn't be lost — a
    place these don't silently vanish between sessions.
- **Write it at a natural stopping point**, not only at the literal end of a session — a long
  session that crosses a real milestone mid-way benefits from a checkpoint entry rather than
  one giant entry trying to cover two different arcs of work.

## Keeping the roadmap

`docs/ROADMAP.md` answers "which phase are we in, and what's actually left before we can call
it done" — deliberately *not* a day-by-day calendar. Phases 1–3 are the direct implementation of
`docs/scoping.md` §10's rollout plan (same milestones, M0–M7), with the roadmap tracking *built*
against the scoping doc's *designed*.

What makes a roadmap entry worth writing (not just "task: done"):

- **A checkbox only gets checked when its gate is actually, verifiably met** — not when time
  allotted for it runs out, and not on the strength of a plan that hasn't been run. "Verified
  live" (a real test run, a real command executed against real output) is the bar, not "the code
  looks right." A concrete example from this project: a full doc-staleness audit found that
  `docs/resume_project_doc.md` had described function signatures (`fetch_metric_data`,
  `format_anomaly_summary`) that never existed in `detection/anomaly_detector.py` — the doc had
  drifted from the code without anyone re-verifying it against a real function list. The fix
  wasn't just correcting the doc; it's the reminder that "documented" and "verified against
  current code" are different claims.
- **Real bugs found along the way get named**, not smoothed over — e.g. the `metric_by_payment`
  double-count bug (joining order_items × payments produced N×M rows per order; fixed by
  pre-aggregating revenue in a CTE first) is named directly in `docs/resume_project_doc.md`
  rather than silently disappearing from history once fixed.
- **Deliberately-skipped work gets named as a gap, with a reason**, not silently dropped —
  `docs/ROADMAP.md`'s Phase 0 section names the CD `dbt run` placeholder, the disabled contact
  form email, and the manual-only Lambda deploy explicitly as known gaps rather than pretending
  Phase 0 has zero rough edges.
- **A phase's gate is a fixed target stated up front** (in the phase header), so "are we done
  with this phase" is a yes/no check against something written down in advance, not a retroactive
  judgment call.

`docs/project/retrospectives/` is named as a convention in `docs/ROADMAP.md` (an end-of-phase
reflection, heavier-weight than a session log entry) but doesn't exist yet — correctly so, since
no phase has actually closed through this process yet (Phase 0 was marked done retroactively as
the already-shipped core pipeline, before this roadmap discipline existed to gate it).

## Committing, merging, and GitHub Flow

We use **GitHub Flow** (`CONTRIBUTING.md` has the quick reference; the full sequence is repeated
below): `main` is always deployable, every change — however small — happens on a short-lived
branch and comes back in through a pull request. **`main` is not currently protected by GitHub
branch-protection rules** (no required-review or required-status-check enforcement is configured
on the repo) — the discipline below is followed by agreement, not enforced by GitHub. That's a
real gap, named rather than glossed over, consistent with the "name gaps" rule above.

**The cadence: commit at the end of every session's unit of work, not batched across sessions.**
Finish a piece of work, commit it, open the PR, merge it, *then* move on — never let multiple
sessions' worth of work sit uncommitted waiting for a "good moment" to package it all up.

**The actual sequence, every time:**

1. `git checkout -b <type>/<short-description>` — branch off `main` for the work about to
   happen.
2. Do the work; verify it live (tests, and — where it applies — an actual running instance, not
   just green CI).
3. `git add` specific files (never a blanket `-A`/`.` without checking what it swept up),
   commit with a message describing *why*, not just *what*.
4. `git push -u origin <branch>`, then open the PR (`gh pr create`) with a short summary and a
   test-plan checklist.
5. Wait for CI to actually report pass on every check — `lint-and-test` and `dbt-check`
   (the two jobs defined in `.github/workflows/ci.yml`) — before merging. Never merge
   speculatively.
6. `gh pr merge --squash --delete-branch` — squash so `main`'s history is one clean commit per
   unit of work regardless of how many small commits happened getting there, and delete the
   branch immediately since GitHub Flow has no long-lived branches besides `main`.

**Naming conventions** (full detail in `CONTRIBUTING.md`):

- Branch prefixes: `feat/...`, `fix/...`, `docs/...`, `chore/...`, followed by a short,
  professional description of *what changed*.
- **Never reference roadmap phase/milestone numbers in a branch name or a commit/PR subject
  line** — e.g. `feat/langgraph-investigation-agent`, not `feat/phase-1-m1-synthesis-node`.
  Those labels mean nothing to anyone reading history from outside this project. Commit *bodies*
  and PR *descriptions* can reference roadmap context freely; it's specifically the subject line
  and branch name that stay generic.
- Commit messages (and squash-merge commit titles) describe the change's purpose, with a
  `Co-Authored-By` trailer where the work was AI-paired, so history stays attributable.

**What this buys us:** `main` never carries half-finished work, every merged change already
passed the same automated checks a stranger's PR would have to pass, and — because branches are
short-lived and squash-merged — the commit history on `main` reads as one clean, purposeful
entry per unit of work rather than a scroll of in-progress fixup commits.

## What makes a session smooth and effective

Practices that have consistently paid off, independent of which file they end up written into:

- **Start cold, on purpose.** Read `SESSION_LOG.md`'s latest entries and `ROADMAP.md`'s
  checkboxes *before* touching code or asking what's next — the answer to "where did we stop"
  should come from the repo, not from re-asking the owner to remember.
- **Verify live before calling something done.** A unit test passing is necessary but not
  sufficient — a doc that "looks right" can still describe functions that don't exist (see the
  `docs/resume_project_doc.md` example above). Run the real command, hit the real endpoint, grep
  the real function signature.
- **Add to `concepts/` when a genuinely new idea shows up.** MetricPulse's `concepts/` was seeded
  in one pass rather than grown file-by-file, but the same rule applies going forward: when a new
  tool, library, or domain term shows up that's worth explaining once, write it into `concepts/`
  and add it to `concepts/INDEX.md` — chat can point to the file, it shouldn't re-explain the
  thing at length every time it comes up.
- **Name gaps instead of hiding them.** "Deferred, and here's why" shows up constantly across
  this project's `ROADMAP.md` entries and `docs/resume_project_doc.md`'s Known Limitations
  table — it's a small habit with an outsized effect on whether the written record can be
  trusted later.
- **Commit, push, PR, wait for CI, squash-merge — every session, not batched.** Work doesn't
  accumulate uncommitted across sessions.
- **The session isn't over until the log entry is written.** Not a formality — it's the actual
  deliverable that makes the next session's cold start possible at all.

## Quick reference

- **Starting a session:** read `SESSION_LOG.md` (latest entries) + `ROADMAP.md` (checkboxes).
- **New concept introduced:** write/update one file in `concepts/`, link it, add it to
  `concepts/INDEX.md`.
- **Finishing a unit of work:** verify it live, commit → push → PR → CI green
  (`lint-and-test`, `dbt-check`) → squash-merge → delete branch.
- **Ending a session (or hitting a natural checkpoint):** append a dated entry to
  `SESSION_LOG.md` — what happened, decisions made, current state, next steps, loose ends.
- **Closing a roadmap phase:** confirm the gate is actually met (not just time spent), check the
  box, and (owed, not yet practiced) write a retrospective.
