"""
Deterministic nodes for the Phase 1 investigation graph (docs/scoping.md
Section 2.3). Each node takes the full InvestigationState and returns a
partial-state-update dict -- the standard LangGraph node calling convention,
so these plug into a StateGraph.add_node() unchanged once one is assembled
(M1/M2). No node here calls an LLM; `synthesize` and the real `finalize` are
scoped to M1, per the milestone split in docs/ROADMAP.md.

Every node follows the try/except-never-raise convention already established
by orchestration/run_pipeline.py (docs/scoping.md Section 2.7): on failure,
return {'status': 'failed', 'error': str(e)} instead of raising.
"""

import sys
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger  # noqa: E402
from decomposition.decomposer import get_comparison_dates  # noqa: E402
from investigation.state import InvestigationState  # noqa: E402
from investigation.tools import tool_decompose_all, tool_drill_down, tool_run_detection  # noqa: E402

logger = setup_logger(__name__)

# Ambiguity rule constants (docs/scoping.md Sections 2.5, 3.4) -- named, not magic numbers.
CLOSE_CONTRIBUTORS_THRESHOLD = 15  # percentage points


def classify_ambiguity(dim_data: Dict) -> Optional[str]:
    """
    Apply the ambiguity rule to one dimension's decomposition result.

    'offsetting_segments' if the top contributor's contribution_pct is outside
    [0, 100] (segments moved in opposite directions -- checked first, since a
    top contributor already over 100% makes "how close is #2" not meaningfully
    defined). Else 'close_contributors' if the top two contributors' abs_contribution
    are within CLOSE_CONTRIBUTORS_THRESHOLD points of each other. Else None.
    """
    top_contributors = dim_data.get('top_contributors', [])
    if not top_contributors:
        return None

    top = top_contributors[0]
    if top['contribution_pct'] < 0 or top['contribution_pct'] > 100:
        return 'offsetting_segments'

    if len(top_contributors) >= 2:
        second = top_contributors[1]
        if abs(top['abs_contribution'] - second['abs_contribution']) <= CLOSE_CONTRIBUTORS_THRESHOLD:
            return 'close_contributors'

    return None


def detect(state: InvestigationState) -> Dict:
    """Runs anomaly detection; resolves current/previous date if not already set."""
    try:
        current_date = state.get('current_date')
        previous_date = state.get('previous_date')
        if not current_date or not previous_date:
            current_date, previous_date = get_comparison_dates()

        detection_result = tool_run_detection(state['metric'], state['threshold'])

        log_entry = f"detect: {detection_result['anomaly_count']} anomalies found for {state['metric']}"
        return {
            'detection_result': detection_result,
            'current_date': current_date,
            'previous_date': previous_date,
            'investigation_log': state.get('investigation_log', []) + [log_entry],
        }
    except Exception as e:
        logger.error(f"detect node failed: {e}")
        return {'status': 'failed', 'error': str(e)}


def decompose_all(state: InvestigationState) -> Dict:
    """Decomposes all dimensions for the resolved date pair."""
    try:
        decomposition_results = tool_decompose_all(
            state['current_date'], state['previous_date'], state['metric']
        )
        return {
            'decomposition_results': decomposition_results,
            'investigation_log': state.get('investigation_log', []) + [
                'decompose_all: decomposed all dimensions'
            ],
        }
    except Exception as e:
        logger.error(f"decompose_all node failed: {e}")
        return {'status': 'failed', 'error': str(e)}


def assess_ambiguity(state: InvestigationState) -> Dict:
    """Flags ambiguous dimensions and advances the iteration counter by one round."""
    try:
        dimensions = state['decomposition_results']['dimensions']
        ambiguous = []
        for dim_name, dim_data in dimensions.items():
            if 'error' in dim_data:
                continue
            reason = classify_ambiguity(dim_data)
            if reason:
                ambiguous.append({'dimension': dim_name, 'reason': reason})

        flagged = [a['dimension'] for a in ambiguous]
        return {
            'ambiguous_dimensions': ambiguous,
            'iteration_count': state.get('iteration_count', 0) + 1,
            'investigation_log': state.get('investigation_log', []) + [
                f"assess_ambiguity: flagged {flagged}"
            ],
        }
    except Exception as e:
        logger.error(f"assess_ambiguity node failed: {e}")
        return {'status': 'failed', 'error': str(e)}


def drill_down(state: InvestigationState) -> Dict:
    """
    Drills into the top contributor's segment for each not-yet-drilled
    close_contributors dimension. offsetting_segments dimensions are never
    drilled -- more granular data can't resolve an offset (docs/scoping.md
    Section 3.4).
    """
    try:
        drilled_dimensions = list(state.get('drilled_dimensions', []))
        drill_down_results = dict(state.get('drill_down_results', {}))

        pending = [
            a['dimension'] for a in state['ambiguous_dimensions']
            if a['reason'] == 'close_contributors' and a['dimension'] not in drilled_dimensions
        ]

        for dimension in pending:
            dim_data = state['decomposition_results']['dimensions'][dimension]
            top_segment = dim_data['top_contributors'][0]['segment']
            drill_down_results[dimension] = tool_drill_down(
                dimension, top_segment, state['current_date'], state['previous_date'], state['metric']
            )
            drilled_dimensions.append(dimension)

        return {
            'drill_down_results': drill_down_results,
            'drilled_dimensions': drilled_dimensions,
            'investigation_log': state.get('investigation_log', []) + [f"drill_down: drilled {pending}"],
        }
    except Exception as e:
        logger.error(f"drill_down node failed: {e}")
        return {'status': 'failed', 'error': str(e)}


def finalize_skip(state: InvestigationState) -> Dict:
    """
    Used when route_after_detection finds no anomaly and force_investigate is
    false. No decomposition, drill-down, or LLM call runs.
    """
    return {
        'status': 'skipped_no_anomaly',
        'top_driver': None,
        'investigation_summary': None,
        'narratives': None,
        'investigation_log': state.get('investigation_log', []) + [
            'finalize_skip: no anomaly detected, skipping investigation'
        ],
    }
