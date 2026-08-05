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
