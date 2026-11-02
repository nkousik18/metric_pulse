"""
Load the raw Olist CSVs into the local DuckDB warehouse (docs/local-stack-scope.md §6.2).

This is the local replacement for the archived three-step AWS ingestion
(upload_to_s3 -> setup_redshift_tables -> s3_to_redshift), which stays in this
folder unchanged. It reuses that path's two sources of truth rather than
copying them, so the two can't drift:
- the file -> table mapping: s3_to_redshift.FILE_TABLE_MAPPING
- the table schemas: infrastructure/redshift_setup.sql, the same DDL Redshift ran

Columns are loaded by position, exactly as Redshift's COPY ... IGNOREHEADER 1
does, so the DDL's names win over the CSV headers. That matters: Olist's
products CSV spells two headers `product_name_lenght` /
`product_description_lenght`, and the DDL (and so every downstream dbt model)
uses `..._length`.

Idempotent: each run replaces the raw_data tables, and nothing else in the file.

    python -m ingestion.load_local
    python -m ingestion.load_local --raw-dir data/fixtures/olist_sample --warehouse-path /tmp/w.duckdb
"""

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb  # noqa: E402

from config import settings  # noqa: E402
from config.logging_config import setup_logger  # noqa: E402
from ingestion.s3_to_redshift import FILE_TABLE_MAPPING  # noqa: E402

logger = setup_logger(__name__)

DDL_PATH = settings.PROJECT_ROOT / 'infrastructure' / 'redshift_setup.sql'

# Phase 0's documented total for these 7 tables (docs/MetricPulse_resume_project_doc.md §1).
EXPECTED_FULL_ROW_TOTAL = 451_535

_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+\.\w+)\s*\((.*?)\)\s*;', re.IGNORECASE | re.DOTALL)
_COLUMN = re.compile(r'^\s*(\w+)\s+([A-Za-z]+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)')


def _split_columns(body: str) -> List[str]:
    """Split a column list on top-level commas only, so DECIMAL(10,2) stays whole and the
    result doesn't depend on whether the DDL puts one column per line."""
    parts, depth, current = [], 0, ''
    for ch in body:
        if ch == ',' and depth == 0:
            parts.append(current)
            current = ''
            continue
        depth += (ch == '(') - (ch == ')')
        current += ch
    parts.append(current)
    return [p for p in (x.strip() for x in parts) if p]


def parse_ddl(sql: str) -> Dict[str, List[Tuple[str, str]]]:
    """{'raw_data.orders': [('order_id', 'VARCHAR(50)'), ...]} from the Redshift setup DDL."""
    sql = re.sub(r'--[^\n]*', '', sql)
    tables = {}
    for name, body in _CREATE_TABLE.findall(sql):
        columns = []
        for part in _split_columns(body):
            match = _COLUMN.match(part)
            if match:
                columns.append((match.group(1), re.sub(r'\s+', '', match.group(2)).upper()))
        tables[name.lower()] = columns
    return tables


def _csv_header(path: Path) -> List[str]:
    with open(path, newline='', encoding='utf-8-sig') as f:   # utf-8-sig: the translation CSV has a BOM
        return next(csv.reader(f))


def load_raw(raw_dir: Path, warehouse_path: Path, ddl_path: Path = DDL_PATH) -> Dict[str, int]:
    """Loads every FILE_TABLE_MAPPING file from raw_dir. Returns {table: row_count}."""
    raw_dir, warehouse_path = Path(raw_dir), Path(warehouse_path)
    schemas = parse_ddl(Path(ddl_path).read_text())
    missing = [f for f in FILE_TABLE_MAPPING if not (raw_dir / f).exists()]
    if missing:
        raise FileNotFoundError(f"Missing raw files in {raw_dir}: {', '.join(missing)}")

    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    conn = duckdb.connect(str(warehouse_path))
    try:
        conn.execute('CREATE SCHEMA IF NOT EXISTS raw_data')
        for filename, table in FILE_TABLE_MAPPING.items():
            columns = schemas.get(table)
            if not columns:
                raise ValueError(f"{table} has no CREATE TABLE in {ddl_path}")
            path = raw_dir / filename
            header = _csv_header(path)
            if len(header) != len(columns):
                raise ValueError(f"{filename} has {len(header)} columns but the {table} DDL has {len(columns)}")
            renamed = [(h, c) for h, (c, _) in zip(header, columns) if h != c]
            if renamed:
                logger.info(f"{table}: CSV header -> DDL name (positional, as Redshift COPY): {renamed}")

            col_defs = ', '.join(f'{c} {t}' for c, t in columns)
            col_map = '{' + ', '.join(f"'{c}': '{t}'" for c, t in columns) + '}'
            conn.execute(f'CREATE OR REPLACE TABLE {table} ({col_defs})')
            # header=true skips the header row; columns=... assigns DDL names/types by position.
            # nullstr='' mirrors COPY's BLANKSASNULL/EMPTYASNULL for unquoted empty fields.
            conn.execute(
                f"INSERT INTO {table} SELECT * FROM read_csv(?, header=true, delim=',', quote='\"', "
                f"nullstr='', columns={col_map})", [str(path)])
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            logger.info(f"Loaded {filename} -> {table}: {counts[table]:,} rows")
    finally:
        conn.close()
    return counts


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Load raw Olist CSVs into the local DuckDB warehouse')
    parser.add_argument('--raw-dir', type=Path, default=settings.RAW_DATA_DIR)
    parser.add_argument('--warehouse-path', type=Path, default=settings.WAREHOUSE_PATH)
    args = parser.parse_args(argv)

    counts = load_raw(args.raw_dir, args.warehouse_path)
    total = sum(counts.values())
    print(f"\nLoaded {len(counts)} tables into {args.warehouse_path} (schema raw_data):")
    for table, n in counts.items():
        print(f"  {table:<32} {n:>9,}")
    print(f"  {'total':<32} {total:>9,}")
    if args.raw_dir.resolve() == Path(settings.RAW_DATA_DIR).resolve():
        status = 'matches' if total == EXPECTED_FULL_ROW_TOTAL else 'DOES NOT MATCH'
        print(f"  Phase 0 documented total {EXPECTED_FULL_ROW_TOTAL:,}: {status}")
    print("\nNext: cd dbt_project && dbt build --target local --profiles-dir .")


if __name__ == '__main__':
    main()
