"""
State schema for the Phase 1 investigation graph.

Mirrors the dict shapes the existing detection/decomposition/narrative modules
already produce, extended with the graph's working memory. See docs/scoping.md
Section 2.2 (base schema) and Section 3.4 (ambiguous_dimensions typed-reason
amendment).
"""

from typing import Dict, List, Optional, TypedDict


class AmbiguousDimension(TypedDict):
    dimension: str
    reason: str  # 'close_contributors' | 'offsetting_segments'


class InvestigationState(TypedDict):
    # --- Inputs (set once, at graph invocation) ---
    metric: str
    current_date: Optional[str]
    previous_date: Optional[str]
    threshold: float
    force_investigate: bool

    # --- Evidence gathered (populated as the graph runs) ---
    detection_result: Optional[Dict]
    decomposition_results: Optional[Dict]
    ambiguous_dimensions: List[AmbiguousDimension]
    drill_down_results: Dict[str, Dict]
    drilled_dimensions: List[str]

    # --- Reasoning trace ---
    investigation_log: List[str]
    iteration_count: int
    should_continue: bool

    # --- Output ---
    top_driver: Optional[Dict]
    investigation_summary: Optional[str]
    narratives: Optional[Dict]
    grounding_failed: Optional[bool]  # True if synthesize fell back to the deterministic summary

    # --- Control (mirrors orchestration/run_pipeline.py's status/error convention) ---
    status: str
    error: Optional[str]


def build_initial_state(
    metric: str,
    threshold: Optional[float] = None,
    force_investigate: bool = False,
    current_date: Optional[str] = None,
    previous_date: Optional[str] = None,
    detection_result: Optional[Dict] = None,
    decomposition_results: Optional[Dict] = None,
) -> InvestigationState:
    """
    Builds a fully-defaulted InvestigationState for a fresh graph invocation
    (docs/scoping.md Section 4). Every node already reads its own inputs
    defensively via .get(key, default), but a caller invoking the graph needs
    every collection field seeded up front -- otherwise a node/routing
    function that reads one of these before anything has written it (e.g.
    route_after_ambiguity's drilled_dimensions) has nothing to fall back on
    unless it's also defensive. Centralizing the defaults here means every
    call site (orchestration's pre-seeded path, the dashboard's standalone
    path) gets this right by construction rather than each remembering the
    full field list by hand.

    detection_result / decomposition_results are the two pre-seedable fields
    (Section 4.3) -- passing them makes detect()/decompose_all() no-ops.
    """
    return {
        'metric': metric,
        'current_date': current_date,
        'previous_date': previous_date,
        'threshold': threshold,
        'force_investigate': force_investigate,
        'detection_result': detection_result,
        'decomposition_results': decomposition_results,
        'ambiguous_dimensions': [],
        'drill_down_results': {},
        'drilled_dimensions': [],
        'investigation_log': [],
        'iteration_count': 0,
        'should_continue': False,
        'top_driver': None,
        'investigation_summary': None,
        'narratives': None,
        'grounding_failed': None,
        'status': 'running',
        'error': None,
    }
