"""
Unit tests for codegen (docs/scoping.md Section 6.3). No mocking -- table
generation is tested against a real in-memory DuckDB connection
(duckdb.connect(':memory:')), genuinely exercising real DuckDB behavior with
no disk I/O, matching this project's existing no-mocking testing philosophy.
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.codegen import load_and_aggregate, write_dimension_tables, write_fact_table
from onboarding.schemas import DimensionCandidate, SchemaClassification


class TestLoadAndAggregate:
    """Tests for the pure aggregation function."""

    def test_other_grain_aggregates_by_date(self):
        df = pd.DataFrame({
            'event_date': ['2026-01-01', '2026-01-01', '2026-01-02'],
            'mrr_amount': [29.0, 99.0, 29.0],
        })
        clf = SchemaClassification(date_column='event_date', grain='other', metric_columns=['mrr_amount'])

        result = load_and_aggregate(df, clf)

        assert len(result) == 2
        assert set(result.columns) == {'metric_date', 'mrr_amount', 'row_count'}
        day1 = result[result['metric_date'] == pd.to_datetime('2026-01-01').date()]
        assert day1['mrr_amount'].iloc[0] == 128.0
        assert day1['row_count'].iloc[0] == 2

    def test_daily_grain_is_rename_only_passthrough(self):
        df = pd.DataFrame({
            'metric_date': ['2026-01-01', '2026-01-02'],
            'total_revenue': [1000.0, 2000.0],
        })
        clf = SchemaClassification(date_column='metric_date', grain='daily', metric_columns=['total_revenue'])

        result = load_and_aggregate(df, clf)

        assert len(result) == 2
        assert list(result['row_count']) == [1, 1]
        assert list(result['total_revenue']) == [1000.0, 2000.0]

    def test_unparseable_dates_are_dropped_not_raised(self):
        df = pd.DataFrame({
            'event_date': ['2026-01-01', 'not-a-date', '2026-01-02'],
            'mrr_amount': [10.0, 20.0, 30.0],
        })
        clf = SchemaClassification(date_column='event_date', grain='other', metric_columns=['mrr_amount'])

        result = load_and_aggregate(df, clf)

        assert len(result) == 2
        assert result['mrr_amount'].sum() == 40.0

    def test_multiple_metric_columns(self):
        df = pd.DataFrame({
            'event_date': ['2026-01-01', '2026-01-01'],
            'mrr_amount': [29.0, 99.0],
            'seats': [1, 5],
        })
        clf = SchemaClassification(date_column='event_date', grain='other', metric_columns=['mrr_amount', 'seats'])

        result = load_and_aggregate(df, clf)

        assert result['mrr_amount'].iloc[0] == 128.0
        assert result['seats'].iloc[0] == 6


class TestWriteTables:
    """Tests for writing fact/dimension tables into a real in-memory DuckDB connection."""

    def test_fact_table_contents(self):
        df_daily = pd.DataFrame({
            'metric_date': [pd.to_datetime('2026-01-01').date()],
            'mrr_amount': [128.0],
            'row_count': [2],
        })
        conn = duckdb.connect(':memory:')
        try:
            write_fact_table(conn, df_daily)
            result = conn.execute('SELECT * FROM fact_daily_metrics').df()
            assert result['mrr_amount'].iloc[0] == 128.0
        finally:
            conn.close()

    def test_dimension_table_split_by_segment(self):
        source = pd.DataFrame({
            'metric_date': [pd.to_datetime('2026-01-01').date()] * 2,
            'plan_type': ['Starter', 'Growth'],
            'mrr_amount': [29.0, 99.0],
        })
        clf = SchemaClassification(
            grain='other', metric_columns=['mrr_amount'],
            dimension_columns=[DimensionCandidate(column='plan_type', cardinality=2, confidence=0.9, reasoning='x')],
        )
        conn = duckdb.connect(':memory:')
        try:
            dimension_config = write_dimension_tables(conn, source, clf)

            assert dimension_config == {
                'plan_type': {'table': 'metric_by_plan_type', 'segment_col': 'plan_type', 'detail_col': 'plan_type'}
            }
            result = conn.execute('SELECT * FROM metric_by_plan_type ORDER BY plan_type').df()
            assert list(result['plan_type']) == ['Growth', 'Starter']
            assert list(result['mrr_amount']) == [99.0, 29.0]
        finally:
            conn.close()
