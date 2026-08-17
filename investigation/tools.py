"""
Tool wrappers for the investigation graph. Thin wrappers around existing,
unchanged detection/decomposition/narrative functions, per docs/scoping.md
Section 2.5 -- except tool_drill_down, which is genuinely new (wraps the new
decomposer.fetch_detail_metrics()).

Each wrapper (except tool_generate_narrative, already dataset-agnostic)
accepts an optional dataset_config (M6, docs/ROADMAP.md) -- the same
{dimension_config, connection_factory, table_name, metric_columns} dict
onboarding/investigate.py builds for an onboarded dataset. Omitting it (the
default) means every call falls through to today's exact Olist/Redshift
behavior -- this is the literal, minimal-diff resolution of "the Phase 1
agent works against onboarded data unmodified beyond the two [decomposer/
anomaly_detector] parameters" (docs/scoping.md Section 6.2): no new nodes, no
routing changes, no prompt changes, only additive optional plumbing.
"""

import sys
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from decomposition.decomposer import (  # noqa: E402
    calculate_contribution,
    decompose_metric,
    fetch_detail_metrics,
    summarize_dimension,
)
from detection.anomaly_detector import run_detection  # noqa: E402
from narrative.generator import generate_narrative  # noqa: E402


def _dataset_kwargs(dataset_config: Optional[Dict], *keys: str) -> Dict:
    """
    Extracts only the requested keys actually present in dataset_config, as
    kwargs ready to **-splat into a decomposer.py/anomaly_detector.py call.
    None (or a dataset_config missing a key) means "let that function's own
    Olist/Redshift default apply" -- this never fabricates a value.
    """
    if not dataset_config:
        return {}
    return {k: dataset_config[k] for k in keys if k in dataset_config}


def tool_run_detection(
    metric: str, threshold: float, lookback_days: int = 30, dataset_config: Optional[Dict] = None
) -> Dict:
    return run_detection(
        metric=metric, threshold=threshold, lookback_days=lookback_days,
        **_dataset_kwargs(dataset_config, 'metric_columns', 'table_name', 'connection_factory')
    )


def tool_decompose_all(
    current_date: str, previous_date: str, metric: str, dataset_config: Optional[Dict] = None
) -> Dict:
    return decompose_metric(
        current_date, previous_date, metric,
        **_dataset_kwargs(dataset_config, 'dimension_config', 'connection_factory')
    )


def tool_drill_down(
    dimension: str,
    segment: str,
    current_date: str,
    previous_date: str,
    metric: str,
    dataset_config: Optional[Dict] = None
) -> Dict:
    """
    Fetch and summarize the detail-grain (detail_col) breakdown for one segment
    within a dimension. Returns the same shape as one entry of
    decompose_metric()'s 'dimensions' dict, so drill_down_results and
    decomposition_results['dimensions'] are structurally interchangeable.
    """
    df = fetch_detail_metrics(
        dimension, segment, current_date, previous_date, metric,
        **_dataset_kwargs(dataset_config, 'dimension_config', 'connection_factory')
    )

    if df.empty:
        return {
            'total_current': 0,
            'total_previous': 0,
            'total_change': 0,
            'total_change_pct': 0,
            'top_contributors': [],
            'segment_count': 0
        }

    df_analyzed = calculate_contribution(df)
    return summarize_dimension(df_analyzed)


def tool_generate_narrative(decomposition_results: Dict) -> Dict:
    return generate_narrative(decomposition_results)
