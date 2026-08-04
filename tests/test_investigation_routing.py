"""
Unit tests for investigation graph routing functions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investigation.routing import (
    MAX_ITERATIONS,
    route_after_ambiguity,
    route_after_detection,
    route_after_synthesis,
)


class TestRouteAfterDetection:
    """Tests for routing after the detect node."""

    def test_anomaly_detected_routes_to_decompose(self):
        state = {'detection_result': {'anomaly_count': 1}, 'force_investigate': False}
        assert route_after_detection(state) == 'decompose_all'

    def test_no_anomaly_routes_to_finalize_skip(self):
        state = {'detection_result': {'anomaly_count': 0}, 'force_investigate': False}
        assert route_after_detection(state) == 'finalize_skip'

    def test_force_investigate_overrides_no_anomaly(self):
        state = {'detection_result': {'anomaly_count': 0}, 'force_investigate': True}
        assert route_after_detection(state) == 'decompose_all'


class TestRouteAfterAmbiguity:
    """Tests for routing after the assess_ambiguity node."""

    def test_pending_close_contributors_routes_to_drill_down(self):
        state = {
            'ambiguous_dimensions': [{'dimension': 'geography', 'reason': 'close_contributors'}],
            'drilled_dimensions': [],
            'iteration_count': 0,
        }
        assert route_after_ambiguity(state) == 'drill_down'

    def test_no_ambiguous_dimensions_routes_to_synthesize(self):
        state = {'ambiguous_dimensions': [], 'drilled_dimensions': [], 'iteration_count': 0}
        assert route_after_ambiguity(state) == 'synthesize'

    def test_offsetting_segments_only_never_routes_to_drill_down(self):
        state = {
            'ambiguous_dimensions': [{'dimension': 'payment', 'reason': 'offsetting_segments'}],
            'drilled_dimensions': [],
            'iteration_count': 0,
        }
        assert route_after_ambiguity(state) == 'synthesize'

    def test_already_drilled_dimension_routes_to_synthesize(self):
        state = {
            'ambiguous_dimensions': [{'dimension': 'geography', 'reason': 'close_contributors'}],
            'drilled_dimensions': ['geography'],
            'iteration_count': 0,
        }
        assert route_after_ambiguity(state) == 'synthesize'

    def test_iteration_cap_forces_synthesize_despite_pending(self):
        state = {
            'ambiguous_dimensions': [{'dimension': 'geography', 'reason': 'close_contributors'}],
            'drilled_dimensions': [],
            'iteration_count': MAX_ITERATIONS,
        }
        assert route_after_ambiguity(state) == 'synthesize'


class TestRouteAfterSynthesis:
    """Tests for routing after the (future) synthesize node."""

    def test_should_continue_true_routes_to_assess_ambiguity(self):
        state = {'should_continue': True, 'iteration_count': 0}
        assert route_after_synthesis(state) == 'assess_ambiguity'

    def test_should_continue_false_routes_to_finalize(self):
        state = {'should_continue': False, 'iteration_count': 0}
        assert route_after_synthesis(state) == 'finalize'

    def test_iteration_cap_forces_finalize_despite_should_continue(self):
        state = {'should_continue': True, 'iteration_count': MAX_ITERATIONS}
        assert route_after_synthesis(state) == 'finalize'
