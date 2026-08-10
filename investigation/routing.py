"""
Conditional-edge routing functions for the Phase 1 investigation graph
(docs/scoping.md Section 2.4, updated for Section 3.4's typed-reason
amendment to ambiguous_dimensions). Each takes the full InvestigationState
and returns the name of the next node.
"""

from investigation.state import InvestigationState

# Bounds the graph to at most this many rounds of drill-down + synthesis,
# regardless of what synthesize (M1) requests. Enforced here, not in the
# model prompt. Docs/scoping.md Section 2.6.
MAX_ITERATIONS = 2


def route_after_detection(state: InvestigationState) -> str:
    if state['detection_result']['anomaly_count'] > 0 or state['force_investigate']:
        return 'decompose_all'
    return 'finalize_skip'


def route_after_ambiguity(state: InvestigationState) -> str:
    # .get(..., []) rather than direct indexing: the very first assess_ambiguity ->
    # route_after_ambiguity transition in a real invocation has no node that's set
    # drilled_dimensions yet unless the caller pre-seeded it (M0's test fixtures always
    # did, which masked this). build_initial_state() (M2) seeds it too, but this stays
    # defensive regardless of how the graph was invoked.
    drilled = state.get('drilled_dimensions', [])
    pending = [
        a['dimension'] for a in state['ambiguous_dimensions']
        if a['reason'] == 'close_contributors' and a['dimension'] not in drilled
    ]
    if pending and state['iteration_count'] < MAX_ITERATIONS:
        return 'drill_down'
    return 'synthesize'


def route_after_synthesis(state: InvestigationState) -> str:
    if state['should_continue'] and state['iteration_count'] < MAX_ITERATIONS:
        return 'assess_ambiguity'
    return 'finalize'
