"""
Unit tests for the schema-fingerprint cache mechanism (docs/scoping.md
Section 7.5).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.fingerprint import schema_fingerprint
from onboarding.profiling import ColumnProfile


def _profile(name, dtype='object'):
    return ColumnProfile(
        name=name, dtype=dtype, cardinality=10, cardinality_ratio=0.1, null_rate=0.0,
        sample_values=['a'], date_parse_rate=0.0, is_numeric=False, is_likely_id=False,
    )


class TestSchemaFingerprint:
    """Tests for order-independence and sensitivity to real schema changes."""

    def test_deterministic_for_identical_input(self):
        profiles = {'a': _profile('a'), 'b': _profile('b')}
        assert schema_fingerprint(profiles) == schema_fingerprint(profiles)

    def test_order_independent(self):
        profiles_1 = {'a': _profile('a'), 'b': _profile('b'), 'c': _profile('c')}
        profiles_2 = {'c': _profile('c'), 'a': _profile('a'), 'b': _profile('b')}
        assert schema_fingerprint(profiles_1) == schema_fingerprint(profiles_2)

    def test_renamed_column_changes_fingerprint(self):
        original = {'event_date': _profile('event_date'), 'amount': _profile('amount')}
        renamed = {'order_date': _profile('order_date'), 'amount': _profile('amount')}
        assert schema_fingerprint(original) != schema_fingerprint(renamed)

    def test_retyped_column_changes_fingerprint(self):
        original = {'amount': _profile('amount', dtype='float64')}
        retyped = {'amount': _profile('amount', dtype='int64')}
        assert schema_fingerprint(original) != schema_fingerprint(retyped)

    def test_added_column_changes_fingerprint(self):
        original = {'a': _profile('a')}
        added = {'a': _profile('a'), 'b': _profile('b')}
        assert schema_fingerprint(original) != schema_fingerprint(added)

    def test_removed_column_changes_fingerprint(self):
        original = {'a': _profile('a'), 'b': _profile('b')}
        removed = {'a': _profile('a')}
        assert schema_fingerprint(original) != schema_fingerprint(removed)
