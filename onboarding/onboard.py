"""
CLI entry point for dataset onboarding (docs/scoping.md Section 7.3), following
this project's existing CLI-first convention (ingestion/upload_to_s3.py,
orchestration/run_pipeline.py, etc.):

    python -m onboarding.onboard --file data/saas_subscriptions.csv

A single synchronous confirmation prompt -- not a process. The schema-fingerprint
cache (Section 7.5, onboarding/fingerprint.py) skips straight to codegen on a
repeat run against an unchanged schema; anything new or changed always gets a
human look.
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.classification import classify_columns_with_validation, validate_classification  # noqa: E402
from onboarding.codegen import GENERATED_DIR, generate_tables, validate_generated_tables  # noqa: E402
from onboarding.fingerprint import schema_fingerprint  # noqa: E402
from onboarding.profiling import profile_columns  # noqa: E402
from onboarding.schemas import DimensionCandidate, RejectedColumn, SchemaClassification  # noqa: E402


def _print_classification(clf: SchemaClassification, profiles: dict, name: str, n_rows: int, n_cols: int) -> None:
    print(f"\nProposed classification for {name} ({n_rows} rows, {n_cols} columns):\n")

    if clf.date_column:
        rate = profiles[clf.date_column].date_parse_rate
        print(f"  Date column:   {clf.date_column}   ({rate:.1%} parse rate)")
    else:
        print("  Date column:   (none found)")
    print(f"  Grain:         {clf.grain}")
    print(f"  Metrics:       {', '.join(clf.metric_columns) or '(none)'}")

    print("  Dimensions:    ", end='')
    if clf.dimension_columns:
        for i, d in enumerate(clf.dimension_columns):
            prefix = '' if i == 0 else ' ' * 17
            print(f"{prefix}{d.column}  ({d.cardinality} values, confidence {d.confidence:.2f} -- \"{d.reasoning}\")")
    else:
        print("(none)")

    print("  Rejected:      ", end='')
    if clf.rejected_columns:
        for i, r in enumerate(clf.rejected_columns):
            prefix = '' if i == 0 else ' ' * 17
            print(f"{prefix}{r.column}  ({r.reason})")
    else:
        print("(none)")


def _edit_classification(clf: SchemaClassification, profiles: dict) -> SchemaClassification:
    print(f"\nColumns: {', '.join(profiles.keys())}")
    column = input("Column to move: ").strip()
    if column not in profiles:
        print(f"'{column}' is not a column in this dataset -- no change made.")
        return clf

    role = input(f"New role for '{column}' (metric/dimension/reject): ").strip().lower()

    metric_columns = [c for c in clf.metric_columns if c != column]
    dimension_columns = [d for d in clf.dimension_columns if d.column != column]
    rejected_columns = [r for r in clf.rejected_columns if r.column != column]
    date_column = None if clf.date_column == column else clf.date_column

    if role == 'metric':
        metric_columns.append(column)
    elif role == 'dimension':
        dimension_columns.append(DimensionCandidate(
            column=column, cardinality=profiles[column].cardinality,
            confidence=1.0, reasoning='Manually assigned by user'
        ))
    elif role == 'reject':
        rejected_columns.append(RejectedColumn(column=column, reason='Manually rejected by user'))
    else:
        print(f"Unrecognized role '{role}' -- no change made.")
        return clf

    edited = clf.model_copy(update={
        'date_column': date_column,
        'metric_columns': metric_columns,
        'dimension_columns': dimension_columns,
        'rejected_columns': rejected_columns,
    })

    # Advisory, not blocking, once a human is the one deciding (Section 7.4) -- the
    # same check that's a hard gate on the model's own output only warns here.
    errors = validate_classification(edited, profiles)
    if errors:
        print("\nWarning: this edit doesn't pass automatic validation:")
        for e in errors:
            print(f"  - {e}")
        print("(Applied anyway -- a human reviewing their own dataset can know things the profiler can't.)")

    return edited


def _interactive_confirm(clf: SchemaClassification, profiles: dict, name: str, n_rows: int, n_cols: int) -> SchemaClassification:
    while True:
        _print_classification(clf, profiles, name, n_rows, n_cols)
        choice = input("\n  [y] Confirm and proceed  [e] Edit a column's role  [n] Reject\n> ").strip().lower()

        if choice == 'y':
            return clf
        elif choice == 'n':
            print("\nOnboarding aborted.")
            sys.exit(0)
        elif choice == 'e':
            clf = _edit_classification(clf, profiles)
        else:
            print(f"Unrecognized choice '{choice}'.")


def _read_csv_robust(file_path: str) -> pd.DataFrame:
    # keep_default_na=False + na_values=[''] : pandas' default na_values list includes
    # common tokens like "NA", "N/A", "NULL", "n/a" -- which silently corrupts a real,
    # legitimate categorical value if a column happens to use one (e.g. a "region" code
    # of "NA" for North America). Only a genuinely empty cell counts as missing. Found
    # live: a "region" column with real values ['NA', 'EMEA', 'APAC'] and 0% nulls came
    # back from pd.read_csv() with every 'NA' silently turned into NaN (33.6% null),
    # which then made that dimension's reconciliation check correctly (but
    # misleadingly) fail -- the real bug was here, not in codegen.
    try:
        return pd.read_csv(file_path, keep_default_na=False, na_values=[''])
    except UnicodeDecodeError:
        # A second real, live-found gap (docs/ROADMAP.md M6): a genuinely new real dataset
        # ("Sample Superstore Sales") isn't valid UTF-8 at all -- it's legacy Windows-1252
        # encoded, which is common in older exported business CSVs. cp1252 is a superset
        # of ASCII/Latin-1 and covers the vast majority of "not-quite-UTF-8" real-world
        # files, so it's a reasonable single fallback rather than open-ended encoding
        # detection -- not proven to cover every encoding, named as a bounded best-effort.
        return pd.read_csv(file_path, keep_default_na=False, na_values=[''], encoding='cp1252')


def onboard(file_path: str) -> None:
    df = _read_csv_robust(file_path)
    dataset_id = Path(file_path).stem
    profiles = profile_columns(df)
    fingerprint = schema_fingerprint(profiles)

    output_dir = GENERATED_DIR / dataset_id
    classification_path = output_dir / 'classification.json'

    clf = None
    if classification_path.exists():
        stored = json.loads(classification_path.read_text())
        if stored.get('schema_fingerprint') == fingerprint:
            print(f"Using previously-confirmed classification for '{dataset_id}' (schema unchanged).")
            clf = SchemaClassification.model_validate(stored['classification'])

    if clf is None:
        print(f"Classifying '{dataset_id}'...")
        clf = classify_columns_with_validation(profiles)
        clf = _interactive_confirm(clf, profiles, Path(file_path).name, len(df), len(df.columns))

        output_dir.mkdir(parents=True, exist_ok=True)
        classification_path.write_text(json.dumps({
            'schema_fingerprint': fingerprint,
            'classification': clf.model_dump(mode='json'),
        }, indent=2))

    print("\nGenerating tables...")
    duckdb_path, dimension_config, sanitized_metric_columns = generate_tables(df, clf, dataset_id)

    conn = duckdb.connect(duckdb_path)
    try:
        errors = validate_generated_tables(conn, dimension_config, sanitized_metric_columns)
    finally:
        conn.close()

    if errors:
        print("\nReconciliation check FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Confirmed. Generated tables at {duckdb_path}")
    print("Reconciliation check passed.")
    print(f"\ndimension_config:\n{json.dumps(dimension_config, indent=2)}")
    print(f"\nReady to investigate -- try:\n"
          f"  python -m onboarding.investigate --dataset-id {dataset_id} --metric {sanitized_metric_columns[0]}\n"
          f"  python -m onboarding.investigate --dataset-id {dataset_id} --metric {sanitized_metric_columns[0]} --run-investigation")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='MetricPulse dataset onboarding')
    parser.add_argument('--file', required=True, help='Path to the CSV to onboard')
    args = parser.parse_args()
    onboard(args.file)
