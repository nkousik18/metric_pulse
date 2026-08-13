"""
Unit tests for the generated-tables reconciliation check (docs/scoping.md
Section 6.5). Real in-memory DuckDB, no mocking.
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.codegen import validate_generated_tables


def _connection_with(fact_df: pd.DataFrame, dim_tables: dict) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(':memory:')
    conn.execute("CREATE TABLE fact_daily_metrics AS SELECT * FROM fact_df")
    for table_name, df in dim_tables.items():
        conn.register('_tmp', df)
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM _tmp")
        conn.unregister('_tmp')
    return conn


class TestValidateGeneratedTables:
    """Confirms the reconciliation check both passes a good case and catches a broken one."""

    def test_correctly_reconciling_tables_pass(self):
        fact_df = pd.DataFrame({'metric_date': ['2026-01-01'], 'mrr_amount': [128.0]})
        dim_df = pd.DataFrame({
            'metric_date': ['2026-01-01', '2026-01-01'],
            'plan_type': ['Starter', 'Growth'],
            'mrr_amount': [29.0, 99.0],
        })
        conn = _connection_with(fact_df, {'metric_by_plan_type': dim_df})
        try:
            errors = validate_generated_tables(
                conn, {'plan_type': {'table': 'metric_by_plan_type'}}, ['mrr_amount']
            )
            assert errors == []
        finally:
            conn.close()

    def test_deliberately_corrupted_table_is_caught(self):
        fact_df = pd.DataFrame({'metric_date': ['2026-01-01'], 'mrr_amount': [128.0]})
        # Deliberately wrong: 999.0 instead of the 128.0 that should reconcile.
        dim_df = pd.DataFrame({'metric_date': ['2026-01-01'], 'plan_type': ['Starter'], 'mrr_amount': [999.0]})
        conn = _connection_with(fact_df, {'metric_by_plan_type': dim_df})
        try:
            errors = validate_generated_tables(
                conn, {'plan_type': {'table': 'metric_by_plan_type'}}, ['mrr_amount']
            )
            assert len(errors) == 1
            assert 'plan_type' in errors[0]
        finally:
            conn.close()

    def test_multiple_dimensions_each_checked_independently(self):
        fact_df = pd.DataFrame({'metric_date': ['2026-01-01'], 'mrr_amount': [128.0]})
        good_dim = pd.DataFrame({'metric_date': ['2026-01-01'], 'region': ['NA'], 'mrr_amount': [128.0]})
        bad_dim = pd.DataFrame({'metric_date': ['2026-01-01'], 'plan_type': ['Starter'], 'mrr_amount': [1.0]})
        conn = _connection_with(fact_df, {'metric_by_region': good_dim, 'metric_by_plan_type': bad_dim})
        try:
            errors = validate_generated_tables(
                conn,
                {'region': {'table': 'metric_by_region'}, 'plan_type': {'table': 'metric_by_plan_type'}},
                ['mrr_amount'],
            )
            assert len(errors) == 1
            assert 'plan_type' in errors[0]
        finally:
            conn.close()
