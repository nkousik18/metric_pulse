"""
Build the committed Olist sample used by CI's dbt-build-local job (docs/local-stack-scope.md §6.5).

A deterministic subset of data/raw/: every order purchased on or after --start (default
2018-08-01, which covers the 2018-09-03 golden case and a full 30-day detection lookback), plus
every row those orders reference:
- order_items and payments for those orders
- the customers who placed them
- the products and sellers on their items
- the whole category translation table (72 rows)

Rows are copied as the original lines, byte for byte and in source order, so the sample keeps
Olist's exact quoting and the output is identical on every run. Every Olist CSV has one record per
line (no embedded newlines; checked here), which is what makes line copying safe.

The data is CC BY-NC-SA 4.0 (Olist, via Kaggle); the folder's README.md carries the attribution.

    python -m ingestion.make_olist_sample
    python -m ingestion.make_olist_sample --start 2018-08-15 --out /tmp/olist_sample
"""

import argparse
import csv
import io
import sys
from pathlib import Path
from typing import Callable, Dict, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings  # noqa: E402
from ingestion.s3_to_redshift import FILE_TABLE_MAPPING  # noqa: E402

DEFAULT_START = '2018-08-01'
DEFAULT_OUT = settings.DATA_DIR / 'fixtures' / 'olist_sample'


def _filter(src: Path, dst: Path, keep: Callable[[Dict[str, str]], bool]) -> int:
    """Copy the header and every line whose parsed row satisfies keep(). Returns rows kept."""
    kept = 0
    with open(src, encoding='utf-8', newline='') as f, open(dst, 'w', encoding='utf-8', newline='') as out:
        header_line = f.readline()
        header = next(csv.reader([header_line.lstrip('﻿')]))
        out.write(header_line)
        for line in f:
            values = next(csv.reader(io.StringIO(line)))
            if len(values) != len(header):
                raise ValueError(f"{src.name}: a record spans lines or is malformed: {line[:80]!r}")
            if keep(dict(zip(header, values))):
                out.write(line)
                kept += 1
    return kept


def _column(path: Path, name: str, where: Callable[[Dict[str, str]], bool]) -> Set[str]:
    with open(path, encoding='utf-8', newline='') as f:
        return {row[name] for row in csv.DictReader(f) if where(row)}


def make_sample(raw_dir: Path, out_dir: Path, start: str = DEFAULT_START) -> Dict[str, int]:
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = {name: raw_dir / name for name in FILE_TABLE_MAPPING}

    def in_window(row):
        return row['order_purchase_timestamp'][:10] >= start

    order_ids = _column(src['olist_orders_dataset.csv'], 'order_id', in_window)
    customer_ids = _column(src['olist_orders_dataset.csv'], 'customer_id', in_window)
    product_ids = _column(src['olist_order_items_dataset.csv'], 'product_id', lambda r: r['order_id'] in order_ids)
    seller_ids = _column(src['olist_order_items_dataset.csv'], 'seller_id', lambda r: r['order_id'] in order_ids)

    keep = {
        'olist_orders_dataset.csv': in_window,
        'olist_order_items_dataset.csv': lambda r: r['order_id'] in order_ids,
        'olist_order_payments_dataset.csv': lambda r: r['order_id'] in order_ids,
        'olist_customers_dataset.csv': lambda r: r['customer_id'] in customer_ids,
        'olist_products_dataset.csv': lambda r: r['product_id'] in product_ids,
        'olist_sellers_dataset.csv': lambda r: r['seller_id'] in seller_ids,
        'product_category_name_translation.csv': lambda r: True,
    }
    missing = set(FILE_TABLE_MAPPING) - set(keep)
    if missing:
        raise ValueError(f"No sampling rule for {sorted(missing)}")
    return {name: _filter(src[name], out_dir / name, rule) for name, rule in keep.items()}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Build the committed Olist sample for CI')
    parser.add_argument('--raw-dir', type=Path, default=settings.RAW_DATA_DIR)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--start', default=DEFAULT_START, help='First order purchase date (YYYY-MM-DD)')
    args = parser.parse_args(argv)

    counts = make_sample(args.raw_dir, args.out, args.start)
    size = sum((args.out / name).stat().st_size for name in counts)
    print(f"Wrote the Olist sample (orders from {args.start}) to {args.out}:")
    for name, n in counts.items():
        print(f"  {name:<42} {n:>7,}")
    print(f"  {'total':<42} {sum(counts.values()):>7,} rows, {size / 1e6:.1f} MB")


if __name__ == '__main__':
    main()
