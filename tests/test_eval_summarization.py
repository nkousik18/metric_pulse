"""
Unit tests for the deterministic aggregation half of the Phase 1 eval suite
(docs/scoping.md Section 8.5). No LLM calls -- summarize_results() operates
on already-graded per-trial result dicts, the shape run_investigation_eval()
produces from a real _run_synthesis() call.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investigation.eval import summarize_results


def _trial(outcome, golden_match=True, uncertainty_ok=True):
    return {
        'case': 'test_case',
        'run_index': 0,
        'outcome': outcome,
        'grounded': outcome in ('grounded_first_attempt', 'grounded_after_retry'),
        'golden_match': golden_match,
        'uncertainty_ok': uncertainty_ok,
        'primary_explanation': None,
        'uncertainty_note': None,
        'log': [],
    }


class TestSummarizeResults:
    """Tests for the pure aggregation function backing Section 8.5's named metrics."""

    def test_all_first_attempt_grounded(self):
        results = [_trial('grounded_first_attempt') for _ in range(4)]
        summary = summarize_results(results)

        assert summary['grounding_pass_rate'] == 1.0
        assert summary['fallback_rate'] == 0.0
        assert summary['golden_match_rate'] == 1.0
        assert summary['uncertainty_ok_rate'] == 1.0

    def test_grounded_after_retry_excluded_from_grounding_pass_rate(self):
        # grounding_pass_rate is specifically "first attempt, before the retry" --
        # a retry-grounded trial is not a pass for this metric, even though it's
        # still grounded and can still count toward golden_match_rate.
        results = [
            _trial('grounded_first_attempt'),
            _trial('grounded_after_retry'),
        ]
        summary = summarize_results(results)

        assert summary['grounding_pass_rate'] == 0.5
        assert summary['fallback_rate'] == 0.0
        assert summary['golden_match_rate'] == 1.0

    def test_fallback_trial_counted_correctly(self):
        results = [
            _trial('grounded_first_attempt'),
            _trial('fallback_validation_failed', golden_match=False, uncertainty_ok=False),
            _trial('fallback_exception', golden_match=False, uncertainty_ok=False),
        ]
        summary = summarize_results(results)

        assert summary['grounding_pass_rate'] == 1 / 3
        assert summary['fallback_rate'] == 2 / 3
        assert summary['golden_match_rate'] == 1 / 3
        assert summary['uncertainty_ok_rate'] == 1 / 3

    def test_empty_results_no_division_by_zero(self):
        summary = summarize_results([])

        assert summary['grounding_pass_rate'] == 0
        assert summary['fallback_rate'] == 0
        assert summary['golden_match_rate'] == 0
        assert summary['uncertainty_ok_rate'] == 0
        assert summary['results'] == []
