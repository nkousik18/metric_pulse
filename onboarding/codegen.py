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

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger  # noqa: E402
from onboarding.schemas import SchemaClassification  # noqa: E402

logger = setup_logger(__name__)

GENERATED_DIR = Path(__file__).parent / 'generated'


def sanitize_identifier(name: str) -> str:
    """
    Converts an arbitrary column name into a safe, unquoted SQL identifier --
    lowercase, non-alphanumeric runs collapsed to a single underscore, no
    leading digit. Found live (docs/ROADMAP.md M6, a real dataset -- not a
    synthetic fixture -- with columns like "Order Priority", "Product
    Sub-Category"): every downstream f-string SQL query built by decomposer.py/
    anomaly_detector.py assumes an unquoted bareword identifier (matches those
    modules' existing trust model that dimension_config's table/column values
    are internal, not raw user input -- see decomposition/README.md's
    Gotchas), so a raw column name with a space breaks both DuckDB's own
    CREATE TABLE syntax and every later SELECT/GROUP BY/WHERE. Sanitizing once
    here, at the codegen boundary, avoids retrofitting identifier-quoting into
    every already-tested Redshift-facing query elsewhere.
    """
    sanitized = re.sub(r'[^0-9a-zA-Z]+', '_', name.strip()).strip('_').lower()
    if not sanitized:
        sanitized = 'column'
    if sanitized[0].isdigit():
        sanitized = f'_{sanitized}'
    return sanitized


def load_and_aggregate(df: pd.DataFrame, clf: SchemaClassification) -> pd.DataFrame:
    """
    Parses clf.date_column, renames it to metric_date. Metric columns are
    renamed to sanitize_identifier()'d names (a no-op for already-safe names,
    like every existing test fixture's). If grain == 'other', aggregates to
    daily grain (SUM per metric_column) with a free row_count bonus metric
    (COUNT per day). If already 'daily', a rename-only pass-through with
    row_count=1 per existing row (Section 6.3 point 2).
    """
    working = df.copy()
    working['metric_date'] = pd.to_datetime(working[clf.date_column], errors='coerce').dt.date

    unparsed = working['metric_date'].isna().sum()
    if unparsed:
        logger.warning(f"Dropping {unparsed} rows with unparseable {clf.date_column} values")
        working = working[working['metric_date'].notna()]

    metric_rename = {m: sanitize_identifier(m) for m in clf.metric_columns}
    working = working.rename(columns=metric_rename)
    sanitized_metrics = list(metric_rename.values())

    if clf.grain == 'other':
        grouped = working.groupby('metric_date')[sanitized_metrics].sum()
        grouped['row_count'] = working.groupby('metric_date').size()
        return grouped.reset_index()

    daily = working[['metric_date'] + sanitized_metrics].copy()
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
    [metric_columns].sum(). segment_col == detail_col == the *sanitized* column
    name for every entry (see sanitize_identifier) -- Section 6.4: onboarded
    dimensions have no dim_* taxonomy layer, so there's no finer grain to
    drill into than the dimension itself.

    Returns the generated dimension_config dict (Section 6.3 point 5), keyed
    by the *original*, human-readable column name -- that key is only ever a
    Python-level lookup (and flows into narratives/investigation summaries,
    where the human-readable spelling reads better), never itself embedded in
    SQL, so it doesn't need sanitizing; only the table/segment_col/detail_col
    *values*, which do become real SQL identifiers, are sanitized.
    """
    dimension_config = {}
    metric_rename = {m: sanitize_identifier(m) for m in clf.metric_columns}

    for dim in clf.dimension_columns:
        sanitized_column = sanitize_identifier(dim.column)
        table_name = f'metric_by_{sanitized_column}'
        grouped = (
            df_daily_source.groupby(['metric_date', dim.column])[clf.metric_columns]
            .sum()
            .reset_index()
            .rename(columns={dim.column: sanitized_column, **metric_rename})
        )
        conn.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM grouped")
        dimension_config[dim.column] = {
            'table': table_name,
            'segment_col': sanitized_column,
            'detail_col': sanitized_column,
        }
    return dimension_config


def generate_tables(
    df: pd.DataFrame, clf: SchemaClassification, dataset_id: str
) -> Tuple[str, Dict, List[str]]:
    """
    Orchestrates codegen end to end. Returns (duckdb_path, dimension_config,
    sanitized_metric_columns) -- the third element is what a caller (e.g.
    onboarding/investigate.py, or onboard.py's own "ready to investigate"
    hint) must actually pass as `metric` to run_detection()/decompose_metric():
    clf.metric_columns holds the original, human-readable names, but the
    generated tables' real columns are sanitize_identifier()'d.

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
    sanitized_metric_columns = [sanitize_identifier(m) for m in clf.metric_columns]

    conn = duckdb.connect(duckdb_path)
    try:
        write_fact_table(conn, df_daily)
        dimension_config = write_dimension_tables(conn, working, clf)
    finally:
        conn.close()

    return duckdb_path, dimension_config, sanitized_metric_columns


def validate_generated_tables(conn, dimension_config: Dict, metric_columns: List[str]) -> List[str]:
    """
    Reconciliation check (docs/scoping.md Section 6.5): every dimension's per-date
    totals must equal the fact table's per-date totals. A failure indicates a
    codegen bug (e.g. a GROUP BY that silently dropped null-valued dimension rows),
    not a heuristic guess.
    """
    errors = []
    select_cols = ', '.join(f'SUM({m}) AS {m}' for m in metric_columns)

    # Compared with a numeric tolerance (np.allclose), not exact float equality (Section
    # 6.5's own code block uses .equals() literally): the fact table and each dimension
    # table sum the same underlying values through a different aggregation order (one
    # groupby vs. a two-stage per-segment-then-per-date groupby), which can produce a tiny
    # floating-point discrepancy that's mathematically noise, not a real reconciliation bug.
    # An earlier version rounded both sides to 2 decimals before comparing instead of using
    # a tolerance -- found live, against this real (not synthetic-fixture) dataset's larger,
    # messier real sums: rounding doesn't help when the pre-rounding values straddle a
    # rounding boundary (e.g. 31997.8549999... vs 31997.8550001... round to two *different*
    # cent values), which produced a spurious 1-cent "mismatch" on real data even though the
    # underlying values agree to 10+ significant figures. atol=0.01 is one cent -- generous
    # enough to absorb real floating-point noise, tight enough that an actual codegen bug
    # (e.g. a silently-dropped null-valued dimension row) still reliably fails the check.
    fact_totals = conn.execute(
        f"SELECT metric_date, {select_cols} FROM fact_daily_metrics GROUP BY metric_date"
    ).df().set_index('metric_date').sort_index()

    for dim, config in dimension_config.items():
        dim_totals = conn.execute(
            f"SELECT metric_date, {select_cols} FROM {config['table']} GROUP BY metric_date"
        ).df().set_index('metric_date').sort_index()

        if not np.allclose(fact_totals.values, dim_totals.values, atol=0.01, rtol=1e-6):
            errors.append(f"{dim}: per-date totals don't reconcile with fact_daily_metrics")

    return errors
