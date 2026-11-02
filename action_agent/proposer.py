"""
The deterministic proposer: D2 step 3's fallback, and A2's only proposer.

It proposes notify_owner for the investigation's top driver, citing that same
segment. A3 puts the LLM proposer (20b, then 120b) in front of it. This stays
as the fallback when both LLM attempts fail or the token budget runs out.
"""

from typing import Dict, Optional

FALLBACK_PROPOSER = 'deterministic_fallback'


def fallback_proposal(evidence: Dict, top_driver: Optional[Dict]) -> Optional[Dict]:
    """Returns an ActionProposal-shaped dict, or None when there is no driver to act on."""
    if not top_driver or not top_driver.get('dimension') or not top_driver.get('segment'):
        return None
    dimension, segment = top_driver['dimension'], top_driver['segment']
    contribution = top_driver.get('contribution_pct')
    claim = (f"{segment} ({dimension}) contributed {contribution:+.1f}% of the change"
             if isinstance(contribution, (int, float)) else f"{segment} ({dimension}) is the top driver")
    return {
        'action_type': 'notify_owner',
        'params': {'dimension': dimension, 'segment': segment},
        'rationale_citations': [
            {'dimension': dimension, 'segment': segment, 'source': 'decomposition', 'claim': claim},
        ],
    }
