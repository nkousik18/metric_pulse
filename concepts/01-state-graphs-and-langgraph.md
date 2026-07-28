# State graphs, and what LangGraph adds

## The problem a single prompt can't solve

Ask an LLM one question, get one answer back — that's a single prompt call, and it's the right
tool for a huge number of problems. It stops being enough the moment the *right next step depends
on what the previous step found*: investigate a dimension only if it looks ambiguous, ask a
follow-up only if the first answer wasn't confident, stop early if the evidence already explains
everything. A single prompt can't branch or loop — it can only produce one shot of text.

## A state graph is the fix, described plainly

A **state graph** is a small program shaped like a flowchart: a set of **nodes** (each one does
something — fetch data, call an LLM, run a check) connected by **edges** that decide which node
runs next, based on the current **state** (a shared dict of everything gathered so far). Some
edges are fixed ("always go from A to B"); some are **conditional** ("go to B if X is true, else
go to C") — that's what makes branching and looping possible at all. The graph runs until it
reaches an end node, or until a loop's exit condition is met.

This isn't a new idea specific to LLMs — it's the same mental model as a state machine in any
software system. What's new is using it to sequence *decisions a model makes*, not just
deterministic code.

## What LangGraph specifically adds

LangGraph is a library for building exactly this kind of graph, with LLM calls as some of the
nodes. Concretely, it gives you: a typed way to define the shared state, a way to register nodes
as plain functions, a way to wire conditional edges with a plain routing function (input: current
state, output: the name of the next node), and — importantly — the ability to bound a loop with a
hard iteration cap, so an agent can't accidentally run forever chasing its own uncertainty.

## Why this project uses it instead of either extreme

The two easy extremes are: (a) one big prompt asking the model to "figure out the root cause,"
and (b) a fully free-form agent loop where the model picks whatever tool it wants, whenever it
wants, with no structure. This project's investigation agent (`docs/scoping.md` §2) deliberately
sits between them: the graph structure and most of the routing logic are plain, deterministic
code (cheap, fast, predictable), and the LLM is only called at the one or two specific points
where genuine interpretation is needed — see
[03-deterministic-vs-llm-judgment.md](03-deterministic-vs-llm-judgment.md) for why that split
matters.
