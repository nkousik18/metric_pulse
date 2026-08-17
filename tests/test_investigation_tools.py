"""
Unit tests for investigation/tools.py's _dataset_kwargs() (docs/ROADMAP.md M6).
Pure function, no I/O, no LLM calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from investigation.tools import _dataset_kwargs


class TestDatasetKwargs:
    """Tests for the dataset_config -> kwargs extraction helper."""

    def test_none_dataset_config_returns_empty_dict(self):
        assert _dataset_kwargs(None, 'table_name', 'connection_factory') == {}

    def test_empty_dataset_config_returns_empty_dict(self):
        assert _dataset_kwargs({}, 'table_name', 'connection_factory') == {}

    def test_only_present_keys_are_returned(self):
        dataset_config = {'table_name': 'fact_daily_metrics'}
        result = _dataset_kwargs(dataset_config, 'table_name', 'connection_factory')
        assert result == {'table_name': 'fact_daily_metrics'}

    def test_all_requested_keys_present_are_all_returned(self):
        factory = object()
        dataset_config = {'table_name': 'fact_daily_metrics', 'connection_factory': factory}
        result = _dataset_kwargs(dataset_config, 'table_name', 'connection_factory')
        assert result == {'table_name': 'fact_daily_metrics', 'connection_factory': factory}

    def test_keys_not_requested_are_excluded(self):
        dataset_config = {'table_name': 'fact_daily_metrics', 'metric_columns': ['mrr_amount']}
        result = _dataset_kwargs(dataset_config, 'table_name')
        assert result == {'table_name': 'fact_daily_metrics'}
