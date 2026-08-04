"""
Tool wrappers for the investigation graph. Thin wrappers around existing,
unchanged detection/decomposition/narrative functions, per docs/scoping.md
Section 2.5 -- except tool_drill_down, which is genuinely new (wraps the new
decomposer.fetch_detail_metrics()).
"""

import sys
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent))

from decomposition.decomposer import (  # noqa: E402
    calculate_contribution,
    decompose_metric,
    fetch_detail_metrics,
    summarize_dimension,
)
from detection.anomaly_detector import run_detection  # noqa: E402
from narrative.generator import generate_narrative  # noqa: E402


def tool_run_detection(metric: str, threshold: float, lookback_days: int = 30) -> Dict:
    return run_detection(metric=metric, threshold=threshold, lookback_days=lookback_days)


def tool_decompose_all(current_date: str, previous_date: str, metric: str) -> Dict:
    return decompose_metric(current_date, previous_date, metric)


def tool_drill_down(
    dimension: str,
    segment: str,
    current_date: str,
    previous_date: str,
    metric: str
) -> Dict:
    """
    Fetch and summarize the detail-grain (detail_col) breakdown for one segment
    within a dimension. Returns the same shape as one entry of
    decompose_metric()'s 'dimensions' dict, so drill_down_results and
    decomposition_results['dimensions'] are structurally interchangeable.
    """
    df = fetch_detail_metrics(dimension, segment, current_date, previous_date, metric)

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
