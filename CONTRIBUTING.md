# Contributing

This project uses **GitHub Flow**: `main` is always deployable, every change happens on a
short-lived branch and comes back in through a pull request. See `docs/WORKING_CONVENTIONS.md`
for the full reasoning; this file is the quick reference.

## Branch naming

`<type>/<short-description>`, describing *what changed*:

- `feat/` — a new capability
- `fix/` — a bug fix
- `docs/` — documentation only
- `chore/` — tooling, config, cleanup, no behavior change

Never reference internal roadmap phase/milestone numbers in a branch name or a commit/PR subject
line (e.g. `feat/langgraph-investigation-agent`, not `feat/phase-1-m1-synthesis-node`) — those
labels mean nothing to anyone reading history from outside this project. Commit *bodies* and PR
*descriptions* can reference roadmap context freely; it's specifically the subject line and
branch name that stay generic.

## The sequence, every time

1. `git checkout -b <type>/<short-description>` off `main`.
2. Do the work. Verify it live before considering it done — a passing test is necessary, not
   sufficient (run the actual command, hit the actual endpoint).
3. `git add` specific files — never a blanket `-A`/`.` without checking what it swept up. Commit
   with a message describing *why*, not just *what*.
4. `git push -u origin <branch>`, then `gh pr create` with a short summary and a test-plan
   checklist.
5. Wait for CI to actually report pass on every check (`lint-and-test`, `dbt-check`) before
   merging. Never merge speculatively.
6. `gh pr merge --squash --delete-branch` — squash so `main`'s history is one clean commit per
   unit of work, and delete the branch immediately (no long-lived branches besides `main`).

Commit at the end of every unit of work — don't let multiple sessions' worth of changes sit
uncommitted waiting for a "good moment" to package them up.

## Commit messages

Describe the change's purpose. AI-paired work gets a `Co-Authored-By` trailer and session link,
so history stays attributable:

```
docs: fix stale test count in resume_project_doc.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
```
