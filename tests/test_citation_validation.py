"""
Unit tests for investigation graph citation validation (docs/scoping.md
Section 3.5).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investigation.schemas import EvidenceCitation
from investigation.validation import validate_citation, validate_synthesis_output
from investigation.schemas import SynthesisOutput


def _state():
    return {
        'decomposition_results': {
            'dimensions': {
                'geography': {
                    'top_contributors': [
                        {'segment': 'Southeast', 'contribution_pct': 45, 'abs_contribution': 45},
                        {'segment': 'Northeast', 'contribution_pct': 38, 'abs_contribution': 38},
                    ]
                },
                'payment': {
                    'top_contributors': [
                        {'segment': 'Credit Card', 'contribution_pct': 107.1, 'abs_contribution': 107.1},
                    ]
                },
            }
        },
        'drill_down_results': {
            'geography': {
                'top_contributors': [
                    {'segment': 'SP', 'contribution_pct': 88.9, 'abs_contribution': 88.9},
                ]
            }
        },
        'ambiguous_dimensions': [
            {'dimension': 'geography', 'reason': 'close_contributors'},
            {'dimension': 'payment', 'reason': 'offsetting_segments'},
        ],
    }


class TestValidateCitation:
    """Tests for validate_citation against decomposition_results/drill_down_results."""

    def test_valid_segment_from_decomposition_source(self):
        state = _state()
        citation = EvidenceCitation(
            dimension='geography', segment='Southeast', source='decomposition', claim='the driver'
        )
        assert validate_citation(citation, state) is True

    def test_valid_segment_from_drill_down_source(self):
        state = _state()
        citation = EvidenceCitation(
            dimension='geography', segment='SP', source='drill_down', claim='the concentrated driver'
        )
        assert validate_citation(citation, state) is True

    def test_invalid_unknown_segment(self):
        state = _state()
        citation = EvidenceCitation(
            dimension='geography', segment='Rio Grande do Sul', source='decomposition', claim='the driver'
        )
        assert validate_citation(citation, state) is False

    def test_segment_valid_for_wrong_source(self):
        # 'SP' only exists in drill_down_results, not decomposition_results['dimensions']['geography'].
        state = _state()
        citation = EvidenceCitation(
            dimension='geography', segment='SP', source='decomposition', claim='the driver'
        )
        assert validate_citation(citation, state) is False

    def test_segment_valid_for_wrong_dimension(self):
        # 'Southeast' exists under geography, not payment.
        state = _state()
        citation = EvidenceCitation(
            dimension='payment', segment='Southeast', source='decomposition', claim='the driver'
        )
        assert validate_citation(citation, state) is False


class TestValidateSynthesisOutput:
    """Tests for the broader structural validation, including the uncertainty_note rule."""

    def test_valid_output_with_required_uncertainty_note_passes(self):
        state = _state()
        output = SynthesisOutput(
            reasoning='test',
            primary_explanation=EvidenceCitation(
                dimension='geography', segment='SP', source='drill_down', claim='the driver'
            ),
            supporting_citations=[],
            uncertainty_note='Payment mix is offsetting.',
            should_continue=False,
        )
        assert validate_synthesis_output(output, state) == []

    def test_missing_required_uncertainty_note_fails(self):
        state = _state()
        output = SynthesisOutput(
            reasoning='test',
            primary_explanation=EvidenceCitation(
                dimension='geography', segment='SP', source='drill_down', claim='the driver'
            ),
            supporting_citations=[],
            uncertainty_note=None,
            should_continue=False,
        )
        errors = validate_synthesis_output(output, state)
        assert len(errors) == 1
        assert 'uncertainty_note' in errors[0]

    def test_invalid_citation_produces_error_with_valid_segments_listed(self):
        state = _state()
        output = SynthesisOutput(
            reasoning='test',
            primary_explanation=EvidenceCitation(
                dimension='geography', segment='Rio Grande do Sul', source='decomposition', claim='the driver'
            ),
            supporting_citations=[],
            uncertainty_note='required note present',
            should_continue=False,
        )
        errors = validate_synthesis_output(output, state)
        assert len(errors) == 1
        assert 'Southeast' in errors[0] and 'Northeast' in errors[0]


def test_the_prompt_names_every_dimension_exactly_as_validation_accepts_it():
    # BUG_LOG A7-4: the prompt showed `geography` as "Geography", the model cited "Geography",
    # and validate_citation (exact key match) rejected it twice -> fallback on every real case
    # without a drill-down. The prompt must spell each dimension the way validation looks it up.
    import re
    from investigation.prompts import build_synthesis_prompt
    from investigation.schemas import EvidenceCitation
    from investigation.validation import validate_citation

    state = {
        'decomposition_results': {'dimensions': {
            'geography': {'total_change': 29, 'total_change_pct': 35.8, 'top_contributors': [
                {'segment': 'Southeast', 'change': 29, 'contribution_pct': 100.0}]},
            'Order Priority': {'total_change': 5, 'total_change_pct': 2.0, 'top_contributors': [
                {'segment': 'High', 'change': 5, 'contribution_pct': 100.0}]}}},
        'drill_down_results': {}, 'ambiguous_dimensions': [], 'detection_result': None,
    }
    prompt = build_synthesis_prompt(state)[1].content
    shown = set(re.findall(r"source='decomposition', dimension='([^']+)'", prompt))
    assert shown == {'geography', 'Order Priority'}
    assert 'Geography' not in prompt
    for dim, seg in (('geography', 'Southeast'), ('Order Priority', 'High')):
        assert validate_citation(EvidenceCitation(source='decomposition', dimension=dim, segment=seg,
                                                  claim='x'), state)
