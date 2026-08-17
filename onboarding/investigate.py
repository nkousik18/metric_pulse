"""
Bridges an onboarded dataset (Section 6's generated tables) to the rest of the
pipeline -- detection, decomposition, narrative, and (optionally) the Phase 1
investigation agent. This is where docs/ROADMAP.md M6's gate actually gets
proven: "a genuinely new, real dataset... goes from a raw CSV to a working
detect -> decompose -> narrate cycle via onboarding/... and the Phase 1
investigation agent runs against it unmodified."

    python -m onboarding.investigate --dataset-id saas_subscriptions --metric mrr_amount
    python -m onboarding.investigate --dataset-id saas_subscriptions --metric mrr_amount --run-investigation

Follows this project's CLI-first convention; costs a real Groq API call only
when --run-investigation is passed.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent))

from decomposition.decomposer import decompose_metric, get_comparison_dates  # noqa: E402
from detection.anomaly_detector import run_detection  # noqa: E402
from narrative.generator import generate_narrative  # noqa: E402
from onboarding.codegen import GENERATED_DIR, sanitize_identifier  # noqa: E402
from onboarding.schemas import SchemaClassification  # noqa: E402


def build_dataset_config(dataset_id: str, dimension_config: Dict, metric_columns: List[str]) -> Dict:
    """
    Constructs the exact dict shape investigation/'s tools expect (see
    investigation/tools.py's _dataset_kwargs). 'row_count' -- codegen.py's free
    bonus metric, not one of Stage B's classified metric_columns -- is included
    so it's a valid investigable metric too (e.g. detecting an anomaly in daily
    transaction volume, not just in a classified revenue-like column).
    """
    duckdb_path = str(GENERATED_DIR / dataset_id / f'{dataset_id}.duckdb')
    return {
        'dimension_config': dimension_config,
        'connection_factory': lambda: duckdb.connect(duckdb_path),
        'table_name': 'fact_daily_metrics',
        'metric_columns': metric_columns + ['row_count'],
    }


def load_dataset_config(dataset_id: str) -> Tuple[Dict, SchemaClassification]:
    """
    Reads the confirmed classification.json onboard.py already writes.
    dimension_config isn't persisted separately -- it's deterministically
    derivable from clf.dimension_columns, the same logic
    codegen.write_dimension_tables() uses (segment_col == detail_col ==
    sanitize_identifier(column), table == f'metric_by_{sanitize_identifier(column)}').
    Both the table/column values here and metric_columns must be the
    *sanitized* names -- classification.json stores the original,
    human-readable names the user actually confirmed, but the real DuckDB
    tables' columns are sanitize_identifier()'d (docs/ROADMAP.md M6: a real
    dataset's column names, e.g. "Order Priority", aren't valid bare SQL
    identifiers).
    """
    classification_path = GENERATED_DIR / dataset_id / 'classification.json'
    if not classification_path.exists():
        raise FileNotFoundError(
            f"No confirmed classification for '{dataset_id}' -- run "
            f"'python -m onboarding.onboard --file <path>' first."
        )

    stored = json.loads(classification_path.read_text())
    clf = SchemaClassification.model_validate(stored['classification'])

    dimension_config = {
        d.column: {
            'table': f'metric_by_{sanitize_identifier(d.column)}',
            'segment_col': sanitize_identifier(d.column),
            'detail_col': sanitize_identifier(d.column),
        }
        for d in clf.dimension_columns
    }
    sanitized_metric_columns = [sanitize_identifier(m) for m in clf.metric_columns]

    return build_dataset_config(dataset_id, dimension_config, sanitized_metric_columns), clf


def run_cycle(
    dataset_id: str,
    metric: str,
    threshold: Optional[float] = None,
    run_investigation: bool = False
) -> Dict:
    """
    Proves the "detect -> decompose -> narrate cycle" half of the Phase 2 gate
    by calling the exact same, unchanged pipeline functions the Olist path
    uses -- just with the onboarded dataset's config instead of the Redshift
    defaults. When run_investigation=True, also proves the "Phase 1 agent runs
    against it unmodified" half: the graph, nodes, routing, and prompts are
    completely untouched -- only investigation/state.py's optional
    dataset_config field (M6) carries the difference.
    """
    dataset_config, clf = load_dataset_config(dataset_id)

    current_date, previous_date = get_comparison_dates(
        table_name=dataset_config['table_name'], connection_factory=dataset_config['connection_factory']
    )
    detection_result = run_detection(
        metric=metric, threshold=threshold,
        metric_columns=dataset_config['metric_columns'],
        table_name=dataset_config['table_name'],
        connection_factory=dataset_config['connection_factory'],
    )
    decomposition_results = decompose_metric(
        current_date, previous_date, metric,
        dimension_config=dataset_config['dimension_config'],
        connection_factory=dataset_config['connection_factory'],
    )
    narratives = generate_narrative(decomposition_results)

    result = {
        'current_date': current_date,
        'previous_date': previous_date,
        'detection': detection_result,
        'decomposition': decomposition_results,
        'narratives': narratives,
    }

    if run_investigation:
        from investigation.graph import investigation_graph
        from investigation.state import build_initial_state

        # Pre-seeded with detection_result/decomposition_results already fetched
        # above -- detect()/decompose_all() are idempotent (Section 4.3) and no-op
        # when these are already present, avoiding a second round of DuckDB
        # queries for data this function already has. Matches
        # orchestration/run_pipeline.py's Step 4.5 pre-seeding pattern exactly;
        # found live -- an early version of this function omitted these two
        # arguments and every query ran twice.
        initial_state = build_initial_state(
            metric=metric,
            threshold=threshold,
            force_investigate=True,
            current_date=current_date,
            previous_date=previous_date,
            detection_result=detection_result,
            decomposition_results=decomposition_results,
            dataset_config=dataset_config,
        )
        final_state = investigation_graph.invoke(initial_state)
        result['investigation'] = {
            'status': final_state['status'],
            'investigation_summary': final_state.get('investigation_summary'),
            'grounding_failed': final_state.get('grounding_failed', False),
        }

    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Run detect -> decompose -> narrate (and optionally the investigation agent) '
                    'against an onboarded dataset'
    )
    parser.add_argument('--dataset-id', required=True)
    parser.add_argument('--metric', required=True)
    parser.add_argument('--threshold', type=float, default=None)
    parser.add_argument('--run-investigation', action='store_true')
    args = parser.parse_args()

    result = run_cycle(args.dataset_id, args.metric, args.threshold, args.run_investigation)

    print(f"Period: {result['previous_date']} -> {result['current_date']}")
    print(f"Anomaly count: {result['detection']['anomaly_count']}")
    print(f"\nSummary: {result['narratives']['summary']}")

    if 'investigation' in result:
        inv = result['investigation']
        print(f"\nInvestigation status: {inv['status']}")
        if inv.get('investigation_summary'):
            print(f"Investigation summary:\n{inv['investigation_summary']}")
        if inv.get('grounding_failed'):
            print("(fell back to deterministic summary -- grounding failed)")
