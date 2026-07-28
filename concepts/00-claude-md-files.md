# What is a `CLAUDE.md` file?

A `CLAUDE.md` is a plain Markdown file that an AI coding assistant (Claude Code, in this case)
automatically loads into its context at the start of every session in this repository — before
it's read a single line of actual code, before it's been told what today's task is. Nothing has
to ask for it; it's just there, every time.

## Why it's a separate file from the README

A `README.md` is written for a human visitor deciding whether to keep reading — a recruiter, a
stranger who found the repo. A `CLAUDE.md` is written for a fresh AI session with zero memory of
anything that happened before it, whose job is to be immediately useful inside the codebase, not
to be persuaded to care about the project. Mixing those two audiences into one file tends to make
both jobs worse: the README gets cluttered with command references a human visitor doesn't need,
or the AI-facing file gets padded with marketing language that wastes space it doesn't have.

## The one hard constraint

`CLAUDE.md` gets loaded into *every* session automatically, whether or not anything in it is
relevant to that session's actual task. That means every line in it has a permanent, repeated
cost — it has to earn its keep at the top of the context window, every single time, forever. The
practical consequence: it should hold commands and conventions that are *genuinely* commonly
needed, plus short pointers into `docs/` or a folder's own `README.md` for anything that needs
more than a sentence or two — not a copy of that deeper material. If a `CLAUDE.md` starts
explaining architecture at length, that's usually a sign the explanation belongs in a `docs/`
file instead, with just a pointer left behind.

## What it isn't

It's not an enforcement mechanism. Nothing technically stops a session from ignoring it or
drifting from it over a long conversation — it works because it's read in good faith at the start
of every session, the same way an onboarding doc doesn't physically stop a new hire from cutting
a corner. When behavior drifts from what it says, the fix is updating the file (or a direct
correction in the moment), not building a guardrail around it.

## In this project

MetricPulse's `CLAUDE.md` (repo root) holds: a two-sentence description of what the project is,
pointers to `docs/README.md` and `docs/resume_project_doc.md` for the real depth, a short list of
codebase conventions worth knowing before editing (stated as pointers to the relevant folder
`README.md`, not payloads), and the commands actually used day to day (setup, tests, dbt, the
pipeline CLI). It's kept short on purpose, per the constraint above.
