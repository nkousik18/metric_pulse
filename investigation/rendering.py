"""
Deterministic rendering of a validated SynthesisOutput into investigation_summary
text (docs/scoping.md Section 3.7). Numbers are looked up fresh from state using
the model's citations as keys -- never taken from the model's own output, even
though validation already confirmed the citations are real. Reuses
narrative.generator's Jinja environment (its format_currency/abs filters)
rather than duplicating one.
"""

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from narrative.generator import jinja_env  # noqa: E402

from investigation.schemas import EvidenceCitation, SynthesisOutput  # noqa: E402
from investigation.state import InvestigationState  # noqa: E402

INVESTIGATION_SUMMARY_TEMPLATE = """{{ primary.claim | capitalize }}: **{{ primary.segment }}** ({{ primary.dimension | title }}) contributed **{{ primary_value.contribution_pct | abs }}%** of the change (${{ primary_value.previous_value | format_currency }} -> ${{ primary_value.current_value | format_currency }}).
{% if supporting %}
Contributing factors:
{% for s, v in supporting %}- {{ s.claim }}: {{ s.segment }} ({{ v.contribution_pct | abs }}%)
{% endfor %}
{% endif %}
{% if uncertainty_note %}
warning: {{ uncertainty_note }}
{% endif %}"""


def _lookup_contributor(citation: EvidenceCitation, state: InvestigationState) -> Optional[dict]:
    source_data = (
        state['decomposition_results']['dimensions'] if citation.source == 'decomposition'
        else state.get('drill_down_results', {})
    )
    dim_data = source_data.get(citation.dimension, {})
    for c in dim_data.get('top_contributors', []):
        if c['segment'] == citation.segment:
            return c
    return None


def render_investigation_summary(output: SynthesisOutput, state: InvestigationState) -> str:
    primary_value = _lookup_contributor(output.primary_explanation, state)
    supporting = [
        (citation, _lookup_contributor(citation, state))
        for citation in output.supporting_citations
    ]

    template = jinja_env.from_string(INVESTIGATION_SUMMARY_TEMPLATE)
    return template.render(
        primary=output.primary_explanation,
        primary_value=primary_value,
        supporting=supporting,
        uncertainty_note=output.uncertainty_note,
    ).strip()
