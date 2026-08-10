"""
Nodes for the Phase 1 investigation graph (docs/scoping.md Section 2.3). Each
node takes the full InvestigationState and returns a partial-state-update
dict -- the standard LangGraph node calling convention, so these plug into a
StateGraph.add_node() unchanged once one is assembled (M2). No compiled
StateGraph exists yet.

Every node except `synthesize` follows the try/except-never-raise convention
established by orchestration/run_pipeline.py (docs/scoping.md Section 2.7):
on failure, return {'status': 'failed', 'error': str(e)} instead of raising.
`synthesize` is a deliberate exception -- per Section 3.2's two-tier design, a
failure there fails *open* to a deterministic fallback summary rather than
marking the whole investigation failed, since a broken LLM call shouldn't
discard an otherwise-successful decomposition. `finalize` short-circuits to
`{}` if a prior node already set status='failed', per Section 2.7.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger  # noqa: E402
from decomposition.decomposer import get_comparison_dates, get_top_driver  # noqa: E402
from investigation.llm import get_synthesis_llm  # noqa: E402
from investigation.prompts import build_synthesis_prompt  # noqa: E402
from investigation.rendering import render_investigation_summary  # noqa: E402
from investigation.schemas import SynthesisOutput  # noqa: E402
from investigation.state import InvestigationState  # noqa: E402
from investigation.tools import (  # noqa: E402
    tool_decompose_all,
    tool_drill_down,
    tool_generate_narrative,
    tool_run_detection,
)
from investigation.validation import validate_synthesis_output  # noqa: E402

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
    """
    Runs anomaly detection; resolves current/previous date if not already set.

    Idempotent (docs/scoping.md Section 4.3): if detection_result is already
    present in state (pre-seeded by a caller that already ran detection, e.g.
    orchestration/run_pipeline.py's Step 4.5), this is a no-op -- avoids a
    second, redundant round of Redshift queries for data already fetched.
    """
    if state.get('detection_result') is not None:
        return {}

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
    """
    Decomposes all dimensions for the resolved date pair.

    Idempotent (docs/scoping.md Section 4.3): no-op if decomposition_results
    is already present in state (pre-seeded), same reasoning as detect().
    """
    if state.get('decomposition_results') is not None:
        return {}

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


def _run_synthesis(state: InvestigationState) -> Tuple[Optional[SynthesisOutput], List[str], str]:
    """
    The actual LLM call plus the bounded single retry from docs/scoping.md
    Section 3.6. Kept separate from the `synthesize` node so investigation/eval.py
    can call it directly and grade the raw SynthesisOutput (Section 8.3's design:
    the eval suite reuses the exact production code path and validators, not a
    separate implementation).

    Returns (validated_output_or_None, log_entries, outcome_tag). `outcome_tag`
    is one of: 'grounded_first_attempt', 'grounded_after_retry',
    'fallback_validation_failed', 'fallback_exception'.
    """
    log = []
    try:
        llm = get_synthesis_llm()

        output = llm.invoke(build_synthesis_prompt(state))
        errors = validate_synthesis_output(output, state)
        if not errors:
            log.append("synthesize: grounded on first attempt")
            return output, log, 'grounded_first_attempt'

        log.append(f"synthesize: first attempt failed validation: {errors}")
        output = llm.invoke(build_synthesis_prompt(state, validation_errors=errors))
        errors = validate_synthesis_output(output, state)
        if not errors:
            log.append("synthesize: grounded after retry")
            return output, log, 'grounded_after_retry'

        log.append(f"synthesize: retry also failed validation: {errors}")
        return None, log, 'fallback_validation_failed'
    except Exception as e:
        logger.error(f"synthesize LLM call raised: {e}")
        log.append(f"synthesize: LLM call raised, falling back: {e}")
        return None, log, 'fallback_exception'


def _fallback_summary_text(top_driver: Optional[Dict]) -> Optional[str]:
    if not top_driver:
        return None
    return (
        f"The primary driver was {top_driver['segment']} ({top_driver['dimension']}), "
        f"contributing {abs(round(top_driver['contribution_pct'], 1))}% of the change "
        f"({top_driver['change_pct']:+.1f}% change)."
    )


def synthesize(state: InvestigationState) -> Dict:
    """
    The one LLM node (docs/scoping.md Section 3). Produces a grounded
    investigation_summary via structured-output citation synthesis, or falls
    back to a deterministic summary built from decomposer.get_top_driver() if
    validation fails twice or the LLM call itself raises (Section 3.6).
    """
    if state.get('status') == 'failed':
        return {}

    output, log, outcome = _run_synthesis(state)
    investigation_log = state.get('investigation_log', []) + log

    if output is None:
        top_driver = get_top_driver(state['decomposition_results'])
        return {
            'investigation_summary': _fallback_summary_text(top_driver),
            'should_continue': False,
            'grounding_failed': True,
            'investigation_log': investigation_log + [f"synthesize: fallback summary used ({outcome})"],
        }

    return {
        'investigation_summary': render_investigation_summary(output, state),
        'should_continue': output.should_continue,
        'grounding_failed': False,
        'investigation_log': investigation_log,
    }


def finalize(state: InvestigationState) -> Dict:
    """
    Calls narrative.generate_narrative() unchanged on decomposition_results
    (Tier 1, untouched), then attaches investigation_summary (Tier 2) alongside
    it. Short-circuits if a prior node already set status='failed' (docs/scoping.md
    Section 2.7: return partial state rather than render from incomplete data).
    """
    if state.get('status') == 'failed':
        return {}

    try:
        decomposition_results = state['decomposition_results']
        narratives = tool_generate_narrative(decomposition_results)
        narratives['investigation_summary'] = state.get('investigation_summary')

        return {
            'narratives': narratives,
            'top_driver': get_top_driver(decomposition_results),
            'status': 'completed',
            'investigation_log': state.get('investigation_log', []) + ['finalize: investigation complete'],
        }
    except Exception as e:
        logger.error(f"finalize node failed: {e}")
        return {'status': 'failed', 'error': str(e)}
