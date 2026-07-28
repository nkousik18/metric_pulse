# How we work: documentation and session conventions

This is a reflection on the documentation and process habits Interpose has actually used
across its sessions so far — not a new set of rules, a written-down version of what's already
been practiced (and, where useful, why it turned out that way rather than some other way).
Written because the practice itself is worth being able to explain later, not just follow.

The short version: **every session starts with total amnesia**, so anything that needs to
survive to the next session has to be written down, in the right file, in a shape a cold read
can actually use. Everything below is in service of that one constraint.

## The document map

Five files carry project state, each answering a different question and changing at a
different rate. Knowing which one to reach for is most of this discipline.

| File | Question it answers | Changes... | Audience |
|---|---|---|---|
| `README.md` | What is this, why should I care, how do I run it | rarely | an outside visitor |
| `CLAUDE.md` | How do we work together, what's non-negotiable | rarely | a fresh AI session |
| `docs/ROADMAP.md` | Which phase are we in, what's left to hit the gate | phase-by-phase | anyone tracking progress |
| `docs/project/SESSION_LOG.md` | What happened *last time*, what's next | every session | the very next session |
| `CHANGELOG.md` | What's shipped, in user-facing terms | every notable change | a user of the software |

`concepts/` sits alongside these as a sixth thing, but it's not project *state* — it's an
accumulating explainer library, one file per idea encountered while building
(`concepts/00-claude-md-files.md` is the first one, and explains why it exists as a mechanism
in its own right).

The deeper "why" behind the state-tracking four (everything but `concepts/`) is written up once,
properly, in `concepts/13-session-continuity-and-progress-logs.md` — this document doesn't
repeat that reasoning, it's the practical "how to actually write each one" companion to it.

## Writing the README

Audience: someone who has never seen this project and is deciding whether to keep reading —
a recruiter, an interviewer, a stranger who found the repo. It is *not* written for the next
work session (that's what `SESSION_LOG.md` is for) and it is not written for the AI (that's
`CLAUDE.md`'s job) — mixing those audiences into one file is how READMEs turn into unreadable
kitchen-sink documents.

What ours does, in order, and why each piece is there:

1. **One paragraph: what it is.** No preamble, no "in today's world of AI agents..." — what
   the thing does, stated plainly, in the first sentence if possible.
2. **A status line, stated honestly.** `"Status: early build, learning-in-public."` — a reader
   should never have to infer maturity from vibes or dig through commits to find out how far
   along something is. Overstating status is the single fastest way to lose credibility with
   the audience this file is for.
3. **Why this exists**, one short section, pointing to the full rationale (`docs/INTERPOSE_SCOPING.md`)
   rather than restating it — a README that tries to be the full design doc becomes neither
   readable nor accurate over time.
4. **Quickstart that actually runs**, copy-pasteable, both paths we support (bare `uv run` and
   the full `kind` deploy) shown as real commands, not prose describing commands. If a reader
   can't get something running from this section alone, the section has failed regardless of
   how good the prose above it is.
5. **Repo layout**, as a short annotated tree, not a paragraph — someone deciding whether to
   dig further wants a map, not a narrative.
6. **A pointer to `concepts/`**, not a copy of it — this is where "learning project" becomes
   visible to an outside reader without bloating the README itself.

The test for whether the README is doing its job: could someone with no context clone the repo
and be running it within the quickstart section alone, with no other file open?

## Writing CLAUDE.md

Audience: a fresh Claude Code session with zero memory of anything that happened before it.
This file gets loaded into *every* session's context automatically, whether or not anything in
it is relevant to that session's actual task — which sets the one hard constraint everything
else follows from: **it has to earn its keep at the top of every context window, forever, so it
stays short.**

What it holds, and — just as important — what it deliberately doesn't:

- **What this project is**, in two sentences, plus pointers to the real spec and plan
  (`docs/INTERPOSE_SCOPING.md`, `docs/ROADMAP.md`). Not the spec itself.
- **The session-start/session-end ritual**, stated as an instruction, not a suggestion — "read
  `SESSION_LOG.md` and `ROADMAP.md` before doing anything else" and "append a session log entry
  at the end" are the two lines that make every other convention in this document actually
  happen, session after session, without being re-asked.
- **How the owner wants to work** — the collaboration style itself (here: teach concepts as
  they come up, don't rush ahead of understanding, hold code to a real quality bar even though
  the pace is relaxed). This is the part that's genuinely project- and person-specific, and the
  part a generic README or wiki page could never carry.
- **Repo conventions** stated as pointers, not payloads — "module layout follows scoping doc
  Section 6.16," not a copy of that layout. If a convention needs more than a sentence to state,
  it belongs in `docs/` or `concepts/` with a one-line reference here.

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
  - **Loose ends / reminders** — anything that doesn't fit the above but shouldn't be lost (a
    credential that still needs rotating is the recurring example here) — a place these don't
    silently vanish between sessions.
- **Write it at a natural stopping point**, not only at the literal end of a session — a long
  session that crosses a real milestone mid-way benefits from a checkpoint entry rather than
  one giant entry trying to cover two different arcs of work.

## Keeping the roadmap

`docs/ROADMAP.md` answers "which phase are we in, and what's actually left before we can call
it done" — deliberately *not* a day-by-day calendar. It's adapted from the original scoping
document's fixed day-by-day plan (same phases, same sequence, same end-of-phase gates), with
one change: **paced by understanding, not by hitting a date.** A "day" in the original plan
might take a session or three here once a new concept needs explaining first, and that's
treated as correct, not as falling behind.

What makes a roadmap entry worth writing (not just "task: done"):

- **A checkbox only gets checked when its gate is actually, verifiably met** — not when time
  allotted for it runs out, and not on the strength of a plan that hasn't been run. "Verified
  live" (a real client hitting a real server, a real container run against real data) is the
  bar, not "the code looks right."
- **Real bugs found along the way get named**, not smoothed over — a roadmap entry that only
  ever says "implemented X, all green" is less useful later than one that says what actually
  broke first and why, because the second one is the part worth remembering.
- **Deliberately-skipped work gets named as a gap, with a reason**, not silently dropped. The
  difference between "we didn't get to this" and "we decided not to do this yet, because Y, and
  it's tracked here" is the difference between a roadmap you can trust and one you can't.
- **A phase's gate is a fixed target stated up front** (in the phase header), so "are we done
  with this phase" is a yes/no check against something written down in advance, not a retroactive
  judgment call.

One thing genuinely still owed here rather than actively practiced: `docs/project/retrospectives/`
exists as a convention (an end-of-phase reflection, heavier-weight than a session log entry) but
is empty so far even though a phase has closed — a real example of the "name the gap rather than
pretend it's covered" rule above, applied to this very document's own subject matter.

## Committing, merging, and GitHub Flow

We use **GitHub Flow** (`concepts/11-git-branching-and-github-flow.md` has the full reasoning
for why this over trunk-based-direct-to-main or GitFlow): `main` is always deployable, every
change — however small — happens on a short-lived branch and comes back in through a pull
request, and `main` has branch protection (PR required, `lint` + `test` CI must pass, no
force-push) so that's enforced by GitHub, not just agreed to in a doc.

**The cadence: commit at the end of every session's unit of work, not batched across sessions.**
This wasn't the original habit — the first several days of Phase 1 piled up uncommitted in one
sitting before it was flagged, and going forward the rule is: finish a piece of work, commit it,
open the PR, merge it, *then* move on — never let multiple sessions' worth of work sit
uncommitted waiting for a "good moment" to package it all up.

**The actual sequence, every time:**

1. `git checkout -b <type>/<short-description>` — branch off `main` for the work about to
   happen.
2. Do the work; verify it live (tests, and — where it applies — an actual running instance, not
   just green CI).
3. `git add` specific files (never a blanket `-A`/`.` without checking what it swept up),
   commit with a message describing *why*, not just *what*.
4. `git push -u origin <branch>`, then open the PR (`gh pr create`) with a short summary and a
   test-plan checklist.
5. Wait for CI to actually report pass on every check — `lint`, `test`, `helm` (whichever apply)
   — before merging. Never merge speculatively, and never use the admin bypass that's technically
   available, even though it exists.
6. `gh pr merge --squash --delete-branch` — squash so `main`'s history is one clean commit per
   unit of work regardless of how many small commits happened getting there, and delete the
   branch immediately since GitHub Flow has no long-lived branches besides `main`.

**Naming conventions:**

- Branch prefixes: `feat/...`, `fix/...`, `docs/...`, `chore/...` (per `CONTRIBUTING.md`),
  followed by a short, professional description of *what changed*.
- **Never reference roadmap day/phase numbers in a branch name or a commit/PR subject line** —
  e.g. `feat/transaction-graph-mcp-server`, not `feat/phase-3-day12-transaction-graph`. Those
  numbers are this project's own internal pacing labels; they mean nothing to anyone reading
  history from outside it, and early on a couple of branches were named that way before this was
  caught and corrected. Commit *bodies* and PR descriptions can still reference roadmap context
  freely (e.g. "Phase 3 Day 12" in a commit body) — it's specifically the subject line and branch
  name that stay generic.
- Commit messages (and squash-merge commit titles) describe the change's purpose, with a
  `Co-Authored-By` / session-link trailer where the work was AI-paired, so history stays
  attributable.

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
  sufficient — the sessions that caught real bugs (a case-sensitive fuzzy matcher, a DuckDB
  type-inference mismatch, an unpinned dependency that had quietly drifted to a breaking
  release) did so by actually running the thing: a real client against a real server, a real
  container against real data. Bugs found this way get written into the session log and often
  into a `concepts/` file, because they're the most durable thing a session produces.
- **Teach at the point of first use, once, in writing.** When something new shows up (a tool, a
  library, a domain term), it gets explained in chat *and* a `concepts/` file gets written or
  updated — but the explanation lives in the file, chat just points to it. Explaining the same
  thing twice, at length, in two places is waste; a link is not.
- **Name gaps instead of hiding them.** "Deferred, and here's why" shows up constantly across
  this project's `ROADMAP.md` entries and Dockerfiles and READMEs — it's a small habit with an
  outsized effect on whether the written record can be trusted later.
- **Commit, push, PR, wait for CI, squash-merge — every session, not batched.** Work doesn't
  accumulate uncommitted across sessions. Branch names describe *what changed*
  (`feat/transaction-graph-mcp-server`), never internal pacing labels like a phase or day
  number, since those aren't meaningful to anyone outside this project's own roadmap.
- **The session isn't over until the log entry is written.** Not a formality — it's the actual
  deliverable that makes the next session's cold start possible at all.

## Quick reference

- **Starting a session:** read `SESSION_LOG.md` (latest entries) + `ROADMAP.md` (checkboxes).
- **New concept introduced:** write/update one file in `concepts/`, link it, add it to
  `concepts/INDEX.md`.
- **Finishing a unit of work:** verify it live, commit → push → PR → CI green → squash-merge →
  delete branch.
- **Ending a session (or hitting a natural checkpoint):** append a dated entry to
  `SESSION_LOG.md` — what happened, decisions made, current state, next steps, loose ends.
- **Closing a roadmap phase:** confirm the gate is actually met (not just time spent), check the
  box, and (owed, not yet practiced) write a retrospective.
