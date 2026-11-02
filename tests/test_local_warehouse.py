"""
Unit tests for the local stack's warehouse layer (docs/local-stack-scope.md §6.1-6.2, LS5, LS6):
backend dispatch, the Lambda default, DDL parsing, and the CSV -> DuckDB loader. Real DuckDB
files and real CSVs in tmp_path. No mocks, no network, no Redshift.
"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import db  # noqa: E402
from config.settings import backend_default  # noqa: E402
from ingestion.load_local import DDL_PATH, load_raw, parse_ddl  # noqa: E402
from ingestion.s3_to_redshift import FILE_TABLE_MAPPING  # noqa: E402

DDL = """
-- a comment with CREATE TABLE inside it must be ignored
CREATE TABLE IF NOT EXISTS raw_data.orders (
    order_id VARCHAR(50),
    order_purchase_timestamp TIMESTAMP
);
CREATE TABLE IF NOT EXISTS raw_data.order_items (
    order_id VARCHAR(50),
    order_item_id INTEGER,
    price DECIMAL(10,2)
);
CREATE TABLE IF NOT EXISTS raw_data.customers (customer_id VARCHAR(50), customer_zip_code_prefix VARCHAR(10));
CREATE TABLE IF NOT EXISTS raw_data.products (product_id VARCHAR(50), product_name_length INTEGER);
CREATE TABLE IF NOT EXISTS raw_data.sellers (seller_id VARCHAR(50));
CREATE TABLE IF NOT EXISTS raw_data.payments (order_id VARCHAR(50), payment_value DECIMAL(10,2));
CREATE TABLE IF NOT EXISTS raw_data.category_translation (product_category_name VARCHAR(100));
"""

CSVS = {
    'olist_orders_dataset.csv': '"order_id","order_purchase_timestamp"\n"o1","2018-09-03 10:00:00"\n"o2",\n',
    'olist_order_items_dataset.csv': '"order_id","order_item_id","price"\n"o1",1,58.90\n',
    'olist_customers_dataset.csv': '"customer_id","customer_zip_code_prefix"\n"c1","01037"\n',
    # Olist's real header typo: loaded positionally, so the DDL's name wins.
    'olist_products_dataset.csv': '"product_id","product_name_lenght"\n"p1",40\n',
    'olist_sellers_dataset.csv': '"seller_id"\n"s1"\n',
    'olist_order_payments_dataset.csv': '"order_id","payment_value"\n"o1",99.33\n',
    # The real translation CSV starts with a UTF-8 BOM.
    'product_category_name_translation.csv': '﻿product_category_name\nbeleza_saude\n',
}


@pytest.fixture
def raw(tmp_path):
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    for name, body in CSVS.items():
        (raw_dir / name).write_text(body, encoding='utf-8')
    ddl = tmp_path / 'ddl.sql'
    ddl.write_text(DDL)
    return raw_dir, ddl, tmp_path / 'warehouse.duckdb'


# --- dispatch (LS6: the archived path is selected correctly without connecting) ---

def test_redshift_backend_selects_the_archived_connection_function():
    assert db.connection_factory('redshift') is db._redshift_connection


def test_unknown_backend_is_rejected():
    with pytest.raises(ValueError, match='WAREHOUSE must be one of'):
        db.connection_factory('snowflake')


def test_missing_local_warehouse_names_the_setup_commands(tmp_path):
    with pytest.raises(RuntimeError, match='ingestion.load_local'):
        db._duckdb_connection(tmp_path / 'absent.duckdb')


def test_local_connection_is_read_only(tmp_path):
    path = tmp_path / 'w.duckdb'
    duckdb.connect(str(path)).close()
    conn = db._duckdb_connection(path)
    with pytest.raises(duckdb.Error):
        conn.execute('CREATE TABLE t (x INT)')
    conn.close()


@pytest.mark.parametrize('environ,expected', [
    ({}, 'duckdb'),
    ({'AWS_LAMBDA_FUNCTION_NAME': 'metricpulse'}, 'redshift'),
])
def test_backend_default_keeps_lambda_on_aws(environ, expected):
    assert backend_default('duckdb', 'redshift', environ=environ) == expected


# --- DDL parsing ---

def test_parse_ddl_ignores_comments_and_keeps_decimal_precision():
    tables = parse_ddl(DDL)
    assert set(tables) == set(FILE_TABLE_MAPPING.values())
    assert tables['raw_data.order_items'] == [
        ('order_id', 'VARCHAR(50)'), ('order_item_id', 'INTEGER'), ('price', 'DECIMAL(10,2)')]


def test_real_redshift_ddl_covers_every_mapped_table():
    tables = parse_ddl(DDL_PATH.read_text())
    assert set(FILE_TABLE_MAPPING.values()) <= set(tables)
    assert ('product_name_length', 'INTEGER') in tables['raw_data.products']


# --- loading ---

def test_load_raw_counts_and_redshift_equivalent_semantics(raw):
    raw_dir, ddl, warehouse = raw
    counts = load_raw(raw_dir, warehouse, ddl_path=ddl)
    assert counts['raw_data.orders'] == 2 and sum(counts.values()) == 8

    conn = duckdb.connect(str(warehouse), read_only=True)
    q = lambda sql: conn.execute(sql).fetchall()   # noqa: E731
    assert q('SELECT customer_zip_code_prefix FROM raw_data.customers') == [('01037',)]          # leading zero kept
    # empty field -> NULL, as COPY's EMPTYASNULL
    assert q("SELECT order_purchase_timestamp FROM raw_data.orders WHERE order_id = 'o2'") == [(None,)]
    assert q('SELECT product_name_length FROM raw_data.products') == [(40,)]  # DDL name, not the CSV typo
    assert q('SELECT product_category_name FROM raw_data.category_translation') == [('beleza_saude',)]  # BOM ignored
    assert str(q('SELECT price FROM raw_data.order_items')[0][0]) == '58.90'                     # DECIMAL(10,2)
    conn.close()


def test_load_raw_is_idempotent(raw):
    raw_dir, ddl, warehouse = raw
    first = load_raw(raw_dir, warehouse, ddl_path=ddl)
    assert load_raw(raw_dir, warehouse, ddl_path=ddl) == first


def test_column_count_mismatch_is_an_error(raw):
    raw_dir, ddl, warehouse = raw
    (raw_dir / 'olist_sellers_dataset.csv').write_text('"seller_id","extra"\n"s1","x"\n')
    with pytest.raises(ValueError, match='olist_sellers_dataset.csv has 2 columns'):
        load_raw(raw_dir, warehouse, ddl_path=ddl)


def test_missing_raw_file_is_an_error(raw):
    raw_dir, ddl, warehouse = raw
    (raw_dir / 'olist_sellers_dataset.csv').unlink()
    with pytest.raises(FileNotFoundError, match='olist_sellers_dataset.csv'):
        load_raw(raw_dir, warehouse, ddl_path=ddl)
