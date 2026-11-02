"""
Tests for ingestion/make_olist_sample.py and the committed CI fixture data/fixtures/olist_sample/
(docs/local-stack-scope.md §6.5). Real CSVs in tmp_path and a real DuckDB file; no mocks.
"""

import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DATA_DIR  # noqa: E402
from ingestion.load_local import load_raw  # noqa: E402
from ingestion.make_olist_sample import make_sample  # noqa: E402

SAMPLE_DIR = DATA_DIR / 'fixtures' / 'olist_sample'

# Mixed quoting on purpose: the real files quote some fields and not others, and the sample must
# keep each line exactly as it was.
RAW = {
    'olist_orders_dataset.csv': (
        '"order_id","customer_id","order_purchase_timestamp"\n'
        'o_old,"c_old",2018-07-31 23:59:59\n'
        'o_new,"c_new",2018-08-01 00:00:00\n'
        'o_late,"c_late",2018-10-17 10:00:00\n'),
    'olist_order_items_dataset.csv': (
        '"order_id","order_item_id","product_id","seller_id"\n'
        '"o_old",1,"p_old","s_old"\n'
        '"o_new",1,"p_new","s_shared"\n'
        '"o_late",1,"p_new","s_shared"\n'),
    'olist_order_payments_dataset.csv': (
        'order_id,payment_sequential,payment_type\n'
        'o_old,1,boleto\no_new,1,credit_card\no_new,2,voucher\n'),
    'olist_customers_dataset.csv': (
        '"customer_id","customer_zip_code_prefix"\n'
        '"c_old","01037"\n"c_new","14409"\n"c_late","99999"\n"c_unused","00000"\n'),
    'olist_products_dataset.csv': (
        '"product_id","product_category_name"\n"p_old",perfumaria\n"p_new",beleza_saude\n'),
    'olist_sellers_dataset.csv': '"seller_id","seller_zip_code_prefix"\n"s_old","1"\n"s_shared","2"\n',
    'product_category_name_translation.csv': (
        '﻿product_category_name,product_category_name_english\n'
        'beleza_saude,health_beauty\nperfumaria,perfumery\n'),
}


@pytest.fixture
def raw_dir(tmp_path):
    d = tmp_path / 'raw'
    d.mkdir()
    for name, body in RAW.items():
        (d / name).write_text(body, encoding='utf-8')
    return d


def _lines(path):
    return Path(path).read_text(encoding='utf-8').splitlines()


def test_window_and_referenced_rows_only(raw_dir, tmp_path):
    out = tmp_path / 'sample'
    counts = make_sample(raw_dir, out, start='2018-08-01')
    assert counts == {
        'olist_orders_dataset.csv': 2,            # o_new (the boundary day is included), o_late
        'olist_order_items_dataset.csv': 2,
        'olist_order_payments_dataset.csv': 2,    # both payments of o_new; o_late has none
        'olist_customers_dataset.csv': 2,         # c_new, c_late; never c_old or c_unused
        'olist_products_dataset.csv': 1,          # p_new only
        'olist_sellers_dataset.csv': 1,           # s_shared only
        'product_category_name_translation.csv': 2,   # always the whole table
    }
    assert 'o_old' not in (out / 'olist_orders_dataset.csv').read_text()


def test_lines_are_copied_byte_for_byte(raw_dir, tmp_path):
    out = tmp_path / 'sample'
    make_sample(raw_dir, out, start='2018-08-01')
    for name in RAW:
        source = _lines(raw_dir / name)
        kept = _lines(out / name)
        assert kept[0] == source[0]                      # header, including the BOM
        assert all(line in source for line in kept)      # no line rewritten or requoted
        assert kept[1:] == [s for s in source[1:] if s in kept[1:]]   # source order kept


def test_output_is_deterministic(raw_dir, tmp_path):
    make_sample(raw_dir, tmp_path / 'a')
    make_sample(raw_dir, tmp_path / 'b')
    for name in RAW:
        assert (tmp_path / 'a' / name).read_bytes() == (tmp_path / 'b' / name).read_bytes()


def test_a_record_spanning_lines_is_refused(raw_dir, tmp_path):
    (raw_dir / 'olist_sellers_dataset.csv').write_text(
        '"seller_id","seller_zip_code_prefix"\n"s_shared","2\n3"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='spans lines'):
        make_sample(raw_dir, tmp_path / 'sample')


# --- the committed fixture itself ---

def test_committed_sample_loads_and_is_referentially_complete(tmp_path):
    counts = load_raw(SAMPLE_DIR, tmp_path / 'sample.duckdb')
    assert sum(counts.values()) == 32_749     # the figure in data/fixtures/olist_sample/README.md
    conn = duckdb.connect(str(tmp_path / 'sample.duckdb'), read_only=True)
    orphans = {
        'items without an order': 'SELECT COUNT(*) FROM raw_data.order_items i '
                                  'LEFT JOIN raw_data.orders o USING (order_id) WHERE o.order_id IS NULL',
        'payments without an order': 'SELECT COUNT(*) FROM raw_data.payments p '
                                     'LEFT JOIN raw_data.orders o USING (order_id) WHERE o.order_id IS NULL',
        'orders without a customer': 'SELECT COUNT(*) FROM raw_data.orders o '
                                     'LEFT JOIN raw_data.customers c USING (customer_id) WHERE c.customer_id IS NULL',
        'items without a product': 'SELECT COUNT(*) FROM raw_data.order_items i '
                                   'LEFT JOIN raw_data.products p USING (product_id) WHERE p.product_id IS NULL',
        'items without a seller': 'SELECT COUNT(*) FROM raw_data.order_items i '
                                  'LEFT JOIN raw_data.sellers s USING (seller_id) WHERE s.seller_id IS NULL',
    }
    assert {name: conn.execute(sql).fetchone()[0] for name, sql in orphans.items()} == dict.fromkeys(orphans, 0)
    first = conn.execute('SELECT MIN(order_purchase_timestamp)::DATE FROM raw_data.orders').fetchone()[0]
    assert str(first) == '2018-08-01'
    conn.close()
