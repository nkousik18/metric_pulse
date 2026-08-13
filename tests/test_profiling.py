"""
Unit tests for Stage A column profiling (docs/scoping.md Section 5.2).
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.profiling import ID_CARDINALITY_THRESHOLD, profile_column, profile_columns


class TestProfileColumn:
    """Tests for profile_column against small, hand-computed fixture Series."""

    def test_clean_date_string_column(self):
        series = pd.Series(['2018-09-01', '2018-09-02', '2018-09-03', '2018-09-04'])
        profile = profile_column('event_date', series)

        assert profile.dtype in ('object', 'str')
        assert profile.cardinality == 4
        assert profile.cardinality_ratio == 1.0
        assert profile.null_rate == 0.0
        assert profile.date_parse_rate == 1.0
        assert profile.is_numeric is False

    def test_numeric_column_never_looks_like_a_date(self):
        # Guards against a real pandas quirk: pd.to_datetime() coerces plain
        # numbers into "successfully parsed" nanosecond-epoch timestamps with
        # ~100% success -- without an explicit guard, every metric column
        # would get date_parse_rate=1.0.
        series = pd.Series([29.99, 99.99, 299.99, 49.99, 19.99])
        profile = profile_column('mrr_amount', series)

        assert profile.is_numeric is True
        assert profile.date_parse_rate == 0.0

    def test_high_cardinality_id_like_column(self):
        series = pd.Series([f'SUB{i}' for i in range(20)])
        profile = profile_column('subscription_id', series)

        assert profile.cardinality == 20
        assert profile.cardinality_ratio == 1.0
        assert profile.cardinality_ratio > ID_CARDINALITY_THRESHOLD
        assert profile.is_likely_id is True

    def test_low_cardinality_categorical_column(self):
        series = pd.Series(['Starter', 'Growth', 'Enterprise', 'Starter', 'Growth'] * 4)
        profile = profile_column('plan_type', series)

        assert profile.cardinality == 3
        assert profile.cardinality_ratio == 3 / 20
        assert profile.is_likely_id is False

    def test_high_null_free_text_column(self):
        series = pd.Series(['a note', None, None, 'another note', None])
        profile = profile_column('notes', series)

        assert profile.null_rate == 3 / 5
        assert profile.sample_values == ['a note', 'another note']

    def test_already_datetime_dtype_parses_fully(self):
        series = pd.Series(pd.date_range('2018-01-01', periods=5))
        profile = profile_column('event_date', series)

        assert profile.is_numeric is False
        assert profile.date_parse_rate == 1.0

    def test_sample_values_capped_at_five(self):
        series = pd.Series([f'val{i}' for i in range(10)])
        profile = profile_column('col', series)

        assert len(profile.sample_values) == 5


class TestProfileColumns:
    """End-to-end test of profile_columns() against a small fixture DataFrame."""

    def test_profiles_every_column(self):
        df = pd.DataFrame({
            'id_col': [f'ID{i}' for i in range(10)],
            'metric_col': [float(i) for i in range(10)],
            'dim_col': ['A', 'B'] * 5,
        })
        profiles = profile_columns(df)

        assert set(profiles.keys()) == {'id_col', 'metric_col', 'dim_col'}
        assert profiles['id_col'].is_likely_id is True
        assert profiles['metric_col'].is_numeric is True
        assert profiles['dim_col'].cardinality == 2
