# Concepts Index

One file per idea, written for someone new to it. Not project state (that's `docs/ROADMAP.md`
and `docs/project/SESSION_LOG.md`) — an accumulating explainer library. See
`docs/WORKING_CONVENTIONS.md` for how and when this folder gets added to.

| File | What it explains |
|---|---|
| [00-claude-md-files.md](00-claude-md-files.md) | What a `CLAUDE.md` file is and why it exists as its own mechanism, separate from a README |
| [01-state-graphs-and-langgraph.md](01-state-graphs-and-langgraph.md) | What a state graph is, why one over a single prompt or a fixed pipeline, and what LangGraph specifically adds |
| [02-grounding-llm-output.md](02-grounding-llm-output.md) | Why LLM output needs "grounding" at all, and the structured-citation-plus-validation pattern used to enforce it here |
| [03-deterministic-vs-llm-judgment.md](03-deterministic-vs-llm-judgment.md) | The recurring design question "does this decision need a model, or does a rule already answer it" |
| [04-human-in-the-loop-design.md](04-human-in-the-loop-design.md) | What "human-in-the-loop" means concretely, and why it's a UX design problem as much as a safety one |
