# Human-in-the-loop design

## What the term actually means

"Human-in-the-loop" gets used loosely to mean anything from "a person reviews output somewhere"
to "nothing happens without sign-off." Used precisely, it means: a system pauses at a specific,
identifiable point and requires a human decision before continuing past it — the loop the system
is normally running autonomously has a deliberate gap in it, and a human closes that gap.

The precision matters because the *design* of that pause is what determines whether the safeguard
is real or theater. A review step nobody reads because it fires on every single action, or one
that's so vague nobody knows what they're actually confirming, doesn't function as a safeguard —
it just adds friction without adding safety.

## Two design questions that actually matter

**When does it fire?** Firing on every action trains people to click through without reading
(alert fatigue, a well-documented failure mode). Firing too rarely means real risk slips past
unreviewed. The useful middle: fire on specific, named conditions where the risk is actually
elevated — a new situation the system hasn't seen before, or a case where its own confidence
check failed — and skip it otherwise.

**What can the human actually see and change?** A review screen that shows a wall of raw data
isn't reviewable in any real sense; a screen that shows exactly what was decided, in plain
language, with the option to correct a specific part of it, is. The scope of what can be changed
matters too — bounded editing (pick from a fixed set of valid corrections) is easier to review
correctly than a free-form text box, precisely because bounded choices are easier to check.

## Where this project applies it

`docs/scoping.md` §7 designs exactly this for the dataset-onboarding agent. It fires on three
named conditions (a first-time dataset, a changed schema, or a failed automated check) — not on
every run — so a stable, previously-reviewed dataset doesn't get re-prompted every time. What it
shows is a short, readable summary of the proposed column classification with plain-language
reasoning for each choice, and what can be changed is bounded to moving a column between a fixed
set of roles, not arbitrary edits.

## The honest limit worth stating out loud

A human-in-the-loop step protects against the specific class of mistake it's designed to catch —
here, a column being assigned the wrong meaning. It does **not** protect against a rushed
confirmation: someone can still click "yes" without reading closely, and a review step can't tell
the difference between genuine confirmation and a reflexive one. Naming this limit explicitly
(rather than treating "there's a human in the loop" as a blanket guarantee that nothing can go
wrong) is itself part of designing the safeguard honestly.
