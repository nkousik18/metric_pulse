"""
Stage: codegen (docs/scoping.md Section 6). Turns a validated SchemaClassification
into queryable tables in a local DuckDB file -- 100% deterministic, no LLM call;
the model's judgment call finished at Stage B (classification.py).

File layout resolves a disagreement between Section 6.3 (a flat
onboarding/generated/<dataset_id>.duckdb) and Section 7.5 (a subfolder
onboarding/generated/<dataset_id>/ containing both the .duckdb file and
classification.json) in favor of Section 7.5's fuller structure -- it actually
needs a folder, since it colocates two files per dataset.
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger  # noqa: E402
from onboarding.schemas import SchemaClassification  # noqa: E402

logger = setup_logger(__name__)

GENERATED_DIR = Path(__file__).parent / 'generated'


def load_and_aggregate(df: pd.DataFrame, clf: SchemaClassification) -> pd.DataFrame:
    """
    Parses clf.date_column, renames it to metric_date. If grain == 'other',
    aggregates to daily grain (SUM per metric_column) with a free row_count
    bonus metric (COUNT per day). If already 'daily', a rename-only
    pass-through with row_count=1 per existing row (Section 6.3 point 2).
    """
    working = df.copy()
    working['metric_date'] = pd.to_datetime(working[clf.date_column], errors='coerce').dt.date

    unparsed = working['metric_date'].isna().sum()
    if unparsed:
        logger.warning(f"Dropping {unparsed} rows with unparseable {clf.date_column} values")
        working = working[working['metric_date'].notna()]

    if clf.grain == 'other':
        grouped = working.groupby('metric_date')[clf.metric_columns].sum()
        grouped['row_count'] = working.groupby('metric_date').size()
        return grouped.reset_index()

    daily = working[['metric_date'] + clf.metric_columns].copy()
    daily['row_count'] = 1
    return daily.reset_index(drop=True)


def write_fact_table(conn, df_daily: pd.DataFrame) -> None:
    # CREATE OR REPLACE, not CREATE: a repeat onboarding run against the same dataset_id
    # (the schema-fingerprint cache's whole point -- Section 7.5) reopens the existing
    # .duckdb file, which already has this table from the prior run. Found live: a second
    # run crashed with a CatalogException before this was OR REPLACE. Matches this
    # project's existing safe-to-rerun convention (ingestion/setup_redshift_tables.py's
    # CREATE TABLE IF NOT EXISTS).
    conn.execute("CREATE OR REPLACE TABLE fact_daily_metrics AS SELECT * FROM df_daily")


def write_dimension_tables(conn, df_daily_source: pd.DataFrame, clf: SchemaClassification) -> Dict:
    """
    One metric_by_<column> table per dimension_column: groupby([metric_date, column])
    [metric_columns].sum(). segment_col == detail_col == column for every entry --
    Section 6.4: onboarded dimensions have no dim_* taxonomy layer, so there's no
    finer grain to drill into than the dimension itself.

    Returns the generated dimension_config dict (Section 6.3 point 5).
    """
    dimension_config = {}
    for dim in clf.dimension_columns:
        table_name = f'metric_by_{dim.column}'
        grouped = (
            df_daily_source.groupby(['metric_date', dim.column])[clf.metric_columns]
            .sum()
            .reset_index()
        )
        conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM grouped")
        dimension_config[dim.column] = {
            'table': table_name,
            'segment_col': dim.column,
            'detail_col': dim.column,
        }
    return dimension_config


def generate_tables(df: pd.DataFrame, clf: SchemaClassification, dataset_id: str) -> Tuple[str, Dict]:
    """
    Orchestrates codegen end to end. Returns (duckdb_path, dimension_config).

    Dimension tables are aggregated from the *original* df (not the already-daily-
    aggregated fact table) so that grain='other' datasets' dimension breakdowns are
    also correctly summed per day, not double-aggregated.
    """
    import duckdb

    working = df.copy()
    working['metric_date'] = pd.to_datetime(working[clf.date_column], errors='coerce').dt.date
    working = working[working['metric_date'].notna()]

    output_dir = GENERATED_DIR / dataset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    duckdb_path = str(output_dir / f'{dataset_id}.duckdb')

    df_daily = load_and_aggregate(df, clf)

    conn = duckdb.connect(duckdb_path)
    try:
        write_fact_table(conn, df_daily)
        dimension_config = write_dimension_tables(conn, working, clf)
    finally:
        conn.close()

    return duckdb_path, dimension_config


def validate_generated_tables(conn, dimension_config: Dict, metric_columns: List[str]) -> List[str]:
    """
    Reconciliation check (docs/scoping.md Section 6.5): every dimension's per-date
    totals must equal the fact table's per-date totals. A failure indicates a
    codegen bug (e.g. a GROUP BY that silently dropped null-valued dimension rows),
    not a heuristic guess.
    """
    errors = []
    select_cols = ', '.join(f'SUM({m}) AS {m}' for m in metric_columns)

    # Rounded to 2 decimals before comparing, not exact float equality (Section 6.5's own
    # code block uses .equals() literally): the fact table and each dimension table sum the
    # same underlying values through a different aggregation order (one groupby vs. a
    # two-stage per-segment-then-per-date groupby), which can produce a tiny floating-point
    # discrepancy that's mathematically noise, not a real reconciliation bug. Rounding to the
    # same currency-style precision already used elsewhere in this codebase (decomposer.py's
    # round(x, 2)) avoids flagging that noise as a codegen error.
    fact_totals = conn.execute(
        f"SELECT metric_date, {select_cols} FROM fact_daily_metrics GROUP BY metric_date"
    ).df().set_index('metric_date').sort_index().round(2)

    for dim, config in dimension_config.items():
        dim_totals = conn.execute(
            f"SELECT metric_date, {select_cols} FROM {config['table']} GROUP BY metric_date"
        ).df().set_index('metric_date').sort_index().round(2)

        if not fact_totals.equals(dim_totals):
            errors.append(f"{dim}: per-date totals don't reconcile with fact_daily_metrics")

    return errors
