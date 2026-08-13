"""
Unit tests for Stage B classification validation (docs/scoping.md Section 5.4).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.classification import (
    MAX_DIMENSION_CARDINALITY_RATIO,
    MIN_DATE_PARSE_RATE,
    validate_classification,
)
from onboarding.profiling import ColumnProfile
from onboarding.schemas import DimensionCandidate, RejectedColumn, SchemaClassification


def _profile(name, **overrides):
    defaults = dict(
        name=name, dtype='object', cardinality=10, cardinality_ratio=0.1,
        null_rate=0.0, sample_values=['a', 'b'], date_parse_rate=0.0,
        is_numeric=False, is_likely_id=False,
    )
    defaults.update(overrides)
    return ColumnProfile(**defaults)


def _profiles():
    return {
        'event_date': _profile('event_date', date_parse_rate=0.998, cardinality_ratio=0.008),
        'mrr_amount': _profile('mrr_amount', is_numeric=True, cardinality_ratio=0.9),
        'seats': _profile('seats', is_numeric=True, dtype='int64', cardinality_ratio=0.1),
        'plan_type': _profile('plan_type', cardinality=3, cardinality_ratio=0.00006),
        'region': _profile('region', cardinality=3, cardinality_ratio=0.00006),
        'customer_id': _profile('customer_id', cardinality_ratio=0.164),
        'subscription_id': _profile('subscription_id', cardinality_ratio=1.0, is_likely_id=True),
        'notes': _profile('notes', null_rate=0.4, cardinality_ratio=0.012),
    }


class TestValidateClassification:
    """Tests for each of Section 5.4's three validation rules, independently."""

    def test_fully_valid_classification_has_no_errors(self):
        profiles = _profiles()
        clf = SchemaClassification(
            date_column='event_date', grain='other',
            metric_columns=['mrr_amount', 'seats'],
            dimension_columns=[
                DimensionCandidate(column='plan_type', cardinality=3, confidence=0.97, reasoning='...'),
                DimensionCandidate(column='region', cardinality=3, confidence=0.96, reasoning='...'),
            ],
            rejected_columns=[
                RejectedColumn(column='subscription_id', reason='identifier'),
                RejectedColumn(column='customer_id', reason='cardinality too high'),
                RejectedColumn(column='notes', reason='high null, free text'),
            ],
        )
        assert validate_classification(clf, profiles) == []

    def test_bad_date_column_below_min_parse_rate(self):
        profiles = _profiles()
        # 'notes' has a low date_parse_rate -- an obviously wrong date_column proposal.
        clf = SchemaClassification(date_column='notes', grain='other')
        errors = validate_classification(clf, profiles)

        assert len(errors) == 1
        assert 'notes' in errors[0]
        assert profiles['notes'].date_parse_rate < MIN_DATE_PARSE_RATE

    def test_non_numeric_metric_column(self):
        profiles = _profiles()
        clf = SchemaClassification(grain='other', metric_columns=['plan_type'])
        errors = validate_classification(clf, profiles)

        assert len(errors) == 1
        assert 'plan_type' in errors[0]
        assert 'numeric' in errors[0]

    def test_over_cardinality_dimension_column(self):
        profiles = _profiles()
        clf = SchemaClassification(
            grain='other',
            dimension_columns=[
                DimensionCandidate(column='customer_id', cardinality=80, confidence=0.5, reasoning='...'),
            ],
        )
        errors = validate_classification(clf, profiles)

        assert len(errors) == 1
        assert 'customer_id' in errors[0]
        assert profiles['customer_id'].cardinality_ratio > MAX_DIMENSION_CARDINALITY_RATIO

    def test_multiple_errors_all_reported(self):
        profiles = _profiles()
        clf = SchemaClassification(
            date_column='notes',
            grain='other',
            metric_columns=['plan_type'],
            dimension_columns=[
                DimensionCandidate(column='customer_id', cardinality=80, confidence=0.5, reasoning='...'),
            ],
        )
        errors = validate_classification(clf, profiles)

        assert len(errors) == 3

    def test_no_date_column_proposed_is_not_an_error(self):
        profiles = _profiles()
        clf = SchemaClassification(date_column=None, grain='other')
        assert validate_classification(clf, profiles) == []
