# Grounding LLM output

## The problem

An LLM generates text one plausible-sounding token at a time. It has no built-in mechanism that
distinguishes "this number is something I was actually given" from "this number is something
that sounds right in context" — both come out the same way, as fluent text. In a system whose
entire purpose is reporting *why a real metric changed*, that's a serious problem: a wrong number
stated confidently is worse than no explanation at all, because it looks just as trustworthy as a
correct one.

**Grounding** is the general term for making sure a model's output is actually tied to real,
checkable data — as opposed to "hallucinated," the term for fluent-but-fabricated output.

## The weak version: just ask nicely

The obvious first attempt is a system prompt that says "only state facts you were given, don't
make anything up." This helps, but it's not a guarantee — it reduces the *rate* of the problem,
it doesn't make it structurally impossible. The model can still, occasionally, misstate a number
or reference something that wasn't in its input, and a prompt instruction has no way to catch
that after the fact.

## The pattern used in this project: structured citation + deterministic validation

Instead of letting the model write final prose directly, it's asked for a small structured object
— which segment, which dimension, which data source a claim comes from — plus a short interpretive
phrase, but **not** the numbers themselves. Plain code then checks: does that segment actually
exist in the data the model was given? If yes, the claim is trusted; if no, it's rejected before
it ever reaches a user. Only after that check passes does a template (not the model) fill in the
actual numbers into the final sentence. See `docs/scoping.md` §3 for the full design, including a
worked example and the exact retry/fallback behavior when validation fails.

The key property this gives: **a factually wrong claim can't reach output, even if the model is
confidently, fluently wrong** — because the numbers a reader sees are never typed by the model in
the first place, only chosen by it from a pre-verified set.

## Grounding isn't only about numbers

The same idea applies to a subtler failure: technically-true-but-misleadingly-incomplete output.
If two segments moved in *opposite* directions, picking just one as "the driver" without
mentioning the other is still a form of ungrounded output, even though no number was invented —
it's an incomplete picture presented as a complete one. `docs/scoping.md` §3.4 handles this by
requiring an explicit uncertainty note whenever the underlying data shows this pattern, enforced
by the output schema, not left to the model to remember on its own.

## Why this matters beyond this project

"How do you keep an LLM from hallucinating in a production system" is one of the most commonly
asked, still-unsolved-in-general questions in applied LLM engineering right now. This project
doesn't solve it in general — it solves a *specific, bounded* version of it (the model's job is
narrow: pick a citation from a fixed set, not generate arbitrary claims), which is exactly what
makes the solution tractable. A system that tried to ground genuinely open-ended generation would
need a fundamentally different, harder approach.
