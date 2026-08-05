"""
Deterministic validation of synthesize's structured output (docs/scoping.md
Section 3.5, with one correction: the doc's illustrative snippet indexes
state["decomposition_results"] directly, but the real shape nests per-dimension
data one level deeper under "dimensions" -- fixed here to match the actual
decompose_metric() return shape decomposition/decomposer.py produces.
drill_down_results has no such wrapper (matches tool_drill_down's return shape
from M0), so it's used as-is.
"""

from typing import List

from investigation.schemas import EvidenceCitation, SynthesisOutput
from investigation.state import InvestigationState


def _dimension_data(citation: EvidenceCitation, state: InvestigationState) -> dict:
    if citation.source == 'decomposition':
        return state['decomposition_results']['dimensions'].get(citation.dimension, {})
    return state.get('drill_down_results', {}).get(citation.dimension, {})


def _known_segments(citation: EvidenceCitation, state: InvestigationState) -> set:
    dim_data = _dimension_data(citation, state)
    return {c['segment'] for c in dim_data.get('top_contributors', [])}


def validate_citation(citation: EvidenceCitation, state: InvestigationState) -> bool:
    return citation.segment in _known_segments(citation, state)


def validate_synthesis_output(output: SynthesisOutput, state: InvestigationState) -> List[str]:
    """
    Returns a list of human-readable validation error strings (empty = valid).
    These strings are what feeds the retry prompt (docs/scoping.md Section 3.6).
    """
    errors = []
    all_citations = [output.primary_explanation] + list(output.supporting_citations)

    for citation in all_citations:
        if not validate_citation(citation, state):
            valid = sorted(_known_segments(citation, state))
            errors.append(
                f"'{citation.segment}' is not a valid segment for '{citation.dimension}' "
                f"(source={citation.source}); valid segments are: {', '.join(valid) or '(none)'}"
            )

    requires_uncertainty_note = any(
        a['reason'] == 'offsetting_segments' for a in state.get('ambiguous_dimensions', [])
    )
    if requires_uncertainty_note and not output.uncertainty_note:
        errors.append(
            "uncertainty_note is required because an offsetting_segments dimension "
            "is present in the evidence, but it was null"
        )

    return errors
