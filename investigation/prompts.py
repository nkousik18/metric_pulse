"""
Prompt construction for the `synthesize` node (docs/scoping.md Sections
3.3-3.4, 3.6, 3.9). The evidence bundle is built entirely from real state --
nothing here is free-form; it's a formatted view of decomposition_results,
drill_down_results, ambiguous_dimensions, and detection_result's history.
"""

from typing import List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from investigation.state import InvestigationState

SYSTEM_PROMPT = """You are the synthesis step of MetricPulse, an automated root-cause-analysis \
pipeline. You are given the evidence already gathered for one metric anomaly investigation and \
must produce a structured citation object -- not free-form prose.

Rules, all structurally enforced by validation after you respond (a violation triggers a retry \
or a fallback, never silently passes):

1. Every citation's (dimension, segment) pair MUST be one that appears in the evidence below, \
   under the source you claim it came from ('decomposition' or 'drill_down'). Never cite a \
   segment that isn't listed.
2. Never put a specific number inside a `claim` field. `claim` is a short interpretive phrase \
   (e.g. "the concentrated driver of the decline"); the real numbers are injected separately \
   from the evidence data, not from your text.
3. If a dimension below is flagged `offsetting_segments`, `uncertainty_note` is REQUIRED \
   (non-null) and must describe that segments moved in opposite directions -- more granular \
   data cannot resolve this, so do not present a single clean driver for it.
4. `should_continue` must be false unless a `close_contributors` dimension remains genuinely \
   unresolved and worth another round of drill-down. Never request continuation for an \
   `offsetting_segments` dimension.
5. Never attribute the change to any real-world event, mechanism, or cause not present in the \
   evidence -- no holidays, promotions, competitor actions, weather, or news. This pipeline has \
   no data source for any of that; such a claim would be fabrication. You may compare the \
   current change to a prior anomaly listed below (a real, checkable fact), but never speculate \
   about an external cause for either.
6. If a dimension below has a "Drill-down within X/Y" section, your `primary_explanation` MUST \
   cite the drill-down's specific segment (source='drill_down'), NOT the higher-level dimension's \
   segment Y (source='decomposition'). The drill-down exists precisely because the higher-level \
   view was too ambiguous to point at one cause -- Y itself is never a valid choice for \
   `primary_explanation` when its own drill-down is present in the evidence; it may only appear, \
   if at all, as a supporting_citations entry."""


def _format_dimension(name: str, dim_data: dict, reason: Optional[str], drill_data: Optional[dict]) -> str:
    lines = [f"{name.title()}" + (f" -- ambiguous, reason: {reason}" if reason else "")]
    lines.append(
        f"  total_change: {dim_data.get('total_change')}, "
        f"total_change_pct: {dim_data.get('total_change_pct')}%"
    )
    for c in dim_data.get('top_contributors', []):
        lines.append(
            f"    {c['segment']}: change {c['change']}, contribution_pct {c['contribution_pct']}%"
        )

    if drill_data is not None:
        top_segment = dim_data['top_contributors'][0]['segment'] if dim_data.get('top_contributors') else '?'
        lines.append(
            f"  >>> {name} was drilled down because it was ambiguous at the level above. "
            f"Use THIS breakdown, not '{top_segment}' above, to name the primary driver within "
            f"{name}:"
        )
        for c in drill_data.get('top_contributors', []):
            lines.append(
                f"      {c['segment']} (source='drill_down', dimension='{name}'): "
                f"change {c['change']}, contribution_pct {c['contribution_pct']}%"
            )

    return "\n".join(lines)


def _format_evidence(state: InvestigationState) -> str:
    ambiguous_by_dim = {a['dimension']: a['reason'] for a in state.get('ambiguous_dimensions', [])}
    dimensions = state['decomposition_results']['dimensions']
    drill_down_results = state.get('drill_down_results', {})

    sections = []
    for dim_name, dim_data in dimensions.items():
        if 'error' in dim_data:
            continue
        sections.append(
            _format_dimension(dim_name, dim_data, ambiguous_by_dim.get(dim_name), drill_down_results.get(dim_name))
        )

    all_anomalies = (state.get('detection_result') or {}).get('all_anomalies', [])
    prior = [a for a in all_anomalies if a.get('metric_date') != state.get('current_date')]
    if prior:
        history_lines = ["Prior anomalies on this metric (for comparison only, not a cause):"]
        for a in prior:
            history_lines.append(
                f"    {a.get('metric_date')}: {a.get('anomaly_direction')}, {a.get('change_pct')}% change"
            )
        sections.append("\n".join(history_lines))

    return "\n\n".join(sections)


def build_synthesis_prompt(
    state: InvestigationState,
    validation_errors: Optional[List[str]] = None
) -> List[BaseMessage]:
    evidence = _format_evidence(state)
    user_content = f"Evidence:\n\n{evidence}\n\nProduce your structured citation output now."

    if validation_errors:
        user_content += (
            "\n\nYour previous response failed validation for these reasons:\n"
            + "\n".join(f"- {e}" for e in validation_errors)
            + "\n\nCorrect these issues and respond again, citing only segments listed above."
        )

    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_content)]
