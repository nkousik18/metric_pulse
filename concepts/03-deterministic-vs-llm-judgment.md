# Deterministic vs. LLM judgment

## The question worth asking before every new piece of agent logic

For any decision a system needs to make, ask: **can a plain rule make this decision correctly, or
does it genuinely require interpretation?** If a rule can do it — a threshold comparison, a
lookup, a statistical check — write the rule. Reach for an LLM call only for the remainder: the
part that requires understanding meaning, weighing ambiguous evidence, or producing language.

This sounds obvious stated plainly, but it's easy to get backwards in practice, especially when
building something explicitly meant to demonstrate "agentic" skills — there's a pull toward
routing everything through the model, because that's what makes a system *look* more capable.
Resisting that pull turns out to matter for reasons beyond code cleanliness.

## Why it matters: cost, speed, and — most importantly — trust

An LLM call costs real money and real latency every single time, unlike a rule, which is
effectively free. Beyond cost, a rule's output is exactly reproducible and auditable — the same
input always gives the same answer, and a person can read the rule and know exactly what it does.
A model's output is neither of those things by default. So every decision routed to the model
instead of a rule is a decision that becomes slower, costlier, and harder to fully trust — a real
cost that has to be worth paying, not a free upgrade.

## Where this project draws the line

Concretely, in the investigation agent (`docs/scoping.md` §2): is a segment's contribution
percentage outside the normal `[0, 100]` range? That's a numeric comparison — a rule. Has the
agent gathered enough evidence to explain the change, or does something warrant a closer look?
That's genuine judgment — the one place the LLM gets called. In the onboarding agent (§5): does a
column's cardinality ratio look like an identifier rather than a category? Rule. Does a column
named `region` actually represent a meaningful business dimension in a dataset the system has
never seen? Judgment.

## The test that keeps this honest

Before adding a new LLM call anywhere in this system: could a plain `if` statement or a numeric
threshold make this same decision, correctly, most of the time? If yes, that's a strong signal
it's a rule dressed up as a judgment call — and every rule that replaces an LLM call is also one
fewer thing that needs [grounding](02-grounding-llm-output.md) in the first place, since a rule's
output was never something that could be wrong in the hallucination sense to begin with.
