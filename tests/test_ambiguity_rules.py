"""
Unit tests for the investigation graph's ambiguity classification rule.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investigation.nodes import assess_ambiguity, classify_ambiguity


class TestClassifyAmbiguity:
    """Tests for the classify_ambiguity rule applied to a single dimension."""

    def test_clear_dominant_contributor_not_ambiguous(self):
        dim_data = {
            'top_contributors': [
                {'segment': 'A', 'contribution_pct': 80, 'abs_contribution': 80},
                {'segment': 'B', 'contribution_pct': 20, 'abs_contribution': 20},
            ]
        }
        assert classify_ambiguity(dim_data) is None

    def test_close_top_two_flags_close_contributors(self):
        dim_data = {
            'top_contributors': [
                {'segment': 'Southeast', 'contribution_pct': 45, 'abs_contribution': 45},
                {'segment': 'Northeast', 'contribution_pct': 38, 'abs_contribution': 38},
            ]
        }
        assert classify_ambiguity(dim_data) == 'close_contributors'

    def test_top_contributor_over_100_flags_offsetting_segments(self):
        dim_data = {
            'top_contributors': [
                {'segment': 'Credit Card', 'contribution_pct': 107.1, 'abs_contribution': 107.1},
                {'segment': 'Boleto', 'contribution_pct': 7.1, 'abs_contribution': 7.1},
                {'segment': 'Voucher', 'contribution_pct': -14.3, 'abs_contribution': 14.3},
            ]
        }
        assert classify_ambiguity(dim_data) == 'offsetting_segments'

    def test_top_contributor_negative_flags_offsetting_segments(self):
        dim_data = {
            'top_contributors': [
                {'segment': 'A', 'contribution_pct': -10, 'abs_contribution': 10},
                {'segment': 'B', 'contribution_pct': 90, 'abs_contribution': 90},
            ]
        }
        assert classify_ambiguity(dim_data) == 'offsetting_segments'

    def test_offsetting_takes_priority_over_close_contributors(self):
        # Top is offsetting (>100) AND happens to be numerically close to #2 --
        # offsetting must win, since "how close" isn't meaningful past 100%.
        dim_data = {
            'top_contributors': [
                {'segment': 'A', 'contribution_pct': 107, 'abs_contribution': 107},
                {'segment': 'B', 'contribution_pct': 100, 'abs_contribution': 100},
            ]
        }
        assert classify_ambiguity(dim_data) == 'offsetting_segments'

    def test_single_contributor_not_ambiguous(self):
        dim_data = {
            'top_contributors': [
                {'segment': 'A', 'contribution_pct': 100, 'abs_contribution': 100},
            ]
        }
        assert classify_ambiguity(dim_data) is None

    def test_no_contributors_not_ambiguous(self):
        assert classify_ambiguity({'top_contributors': []}) is None

    def test_boundary_100_pct_not_offsetting(self):
        dim_data = {
            'top_contributors': [
                {'segment': 'A', 'contribution_pct': 100, 'abs_contribution': 100},
                {'segment': 'B', 'contribution_pct': 0, 'abs_contribution': 0},
            ]
        }
        # 100 is inside [0, 100] (inclusive) -- not offsetting. Diff is 100 > 15 -- not close either.
        assert classify_ambiguity(dim_data) is None


class TestAssessAmbiguityNode:
    """End-to-end test of the assess_ambiguity node against a full decomposition_results fixture."""

    def test_flags_correct_dimensions_and_increments_iteration(self):
        state = {
            'decomposition_results': {
                'dimensions': {
                    'geography': {
                        'top_contributors': [
                            {'segment': 'Southeast', 'contribution_pct': 45, 'abs_contribution': 45},
                            {'segment': 'Northeast', 'contribution_pct': 38, 'abs_contribution': 38},
                        ]
                    },
                    'product': {
                        'top_contributors': [
                            {'segment': 'Electronics', 'contribution_pct': 90, 'abs_contribution': 90},
                            {'segment': 'Books', 'contribution_pct': 10, 'abs_contribution': 10},
                        ]
                    },
                    'payment': {
                        'top_contributors': [
                            {'segment': 'Credit Card', 'contribution_pct': 107.1, 'abs_contribution': 107.1},
                            {'segment': 'Voucher', 'contribution_pct': -14.3, 'abs_contribution': 14.3},
                        ]
                    },
                    'broken_dim': {'error': 'query failed'},
                }
            },
            'iteration_count': 0,
            'investigation_log': [],
        }

        result = assess_ambiguity(state)

        assert result.get('status') != 'failed'
        assert {'dimension': 'geography', 'reason': 'close_contributors'} in result['ambiguous_dimensions']
        assert {'dimension': 'payment', 'reason': 'offsetting_segments'} in result['ambiguous_dimensions']
        assert len(result['ambiguous_dimensions']) == 2
        assert result['iteration_count'] == 1
        assert len(result['investigation_log']) == 1
