"""
policy_check -- the deterministic gate between a proposal and execution
(docs/action-agent-scope.md §5).

Three checks, in order, each failing closed:
  1. the action is in the catalog
  2. its tier is permitted (T2 never is)
  3. its params pass schema and range checks, including grounding any
     (dimension, segment) they name against the investigation's real evidence

A proposal that passes gets decision 'auto_execute' (T0) or 'needs_approval'
(T1). Anything else gets 'rejected' with human-readable reasons. Never raises
on bad input -- a malformed proposal is a rejection, not a crash, matching
orchestration/run_pipeline.py's never-raise convention.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from pydantic import BaseModel, ValidationError

from action_agent.catalog import CATALOG, PERMITTED_TIERS, ActionSpec, Tier
from action_agent.schemas import ActionProposal

# create_control threshold must sit within this factor of the segment's
# observed scale, max(current_value, previous_value) (decision log §12).
CONTROL_THRESHOLD_FACTOR = 10.0

AUTO_EXECUTE = 'auto_execute'
NEEDS_APPROVAL = 'needs_approval'
REJECTED = 'rejected'


@dataclass
class PolicyResult:
    decision: str
    action_type: Optional[str]
    tier: Optional[Tier]
    errors: List[str] = field(default_factory=list)
    params: Optional[dict] = None  # validated, normalized params (None unless allowed)

    @property
    def allowed(self) -> bool:
        return self.decision in (AUTO_EXECUTE, NEEDS_APPROVAL)

    def to_dict(self) -> dict:
        return {
            'decision': self.decision,
            'action_type': self.action_type,
            'tier': self.tier.value if self.tier else None,
            'errors': list(self.errors),
            'params': self.params,
        }


def _reject(action_type, tier, errors) -> PolicyResult:
    return PolicyResult(REJECTED, action_type, tier, errors)


def _format_validation_error(exc: ValidationError) -> List[str]:
    return [
        f"params.{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
        for err in exc.errors()
    ]


def _find_segment(evidence: Optional[Dict], dimension: str, segment: str) -> Optional[dict]:
    dims = (evidence or {}).get('dimensions', {})
    for contributor in dims.get(dimension, {}).get('top_contributors', []):
        if contributor.get('segment') == segment:
            return contributor
    return None


def _range_checks(spec: ActionSpec, params: BaseModel, evidence: Optional[Dict]) -> List[str]:
    if not spec.targets_segment:
        return []

    contributor = _find_segment(evidence, params.dimension, params.segment)
    if contributor is None:
        return [
            f"segment '{params.segment}' in dimension '{params.dimension}' is not in this "
            f"investigation's decomposition evidence"
        ]

    if spec.name == 'create_control':
        scale = max(
            abs(float(contributor.get('current_value') or 0)),
            abs(float(contributor.get('previous_value') or 0)),
        )
        if scale == 0:
            return [f"segment '{params.segment}' has no observed volume to anchor a threshold to"]
        low, high = scale / CONTROL_THRESHOLD_FACTOR, scale * CONTROL_THRESHOLD_FACTOR
        if not (low <= params.threshold <= high):
            return [
                f"threshold {params.threshold:g} is outside the allowed range "
                f"[{low:g}, {high:g}] ({CONTROL_THRESHOLD_FACTOR:g}x either side of the "
                f"segment's observed value {scale:g})"
            ]
    return []


def policy_check(
    proposal, evidence: Optional[Dict], catalog: Mapping[str, ActionSpec] = CATALOG,
) -> PolicyResult:
    """
    proposal: an ActionProposal or a plain dict of one (e.g. an approver's edit).
    evidence: the investigation's decomposition_results (decompose_metric()'s shape).
    catalog:  injectable for tests (e.g. a catalog containing a T2 entry).
    """
    if not isinstance(proposal, ActionProposal):
        try:
            proposal = ActionProposal.model_validate(proposal)
        except ValidationError as exc:
            action_type = proposal.get('action_type') if isinstance(proposal, dict) else None
            return _reject(action_type if isinstance(action_type, str) else None, None,
                           [f"malformed proposal: {e}" for e in _format_validation_error(exc)])

    # 1. In the catalog.
    spec = catalog.get(proposal.action_type)
    if spec is None:
        return _reject(proposal.action_type, None,
                       [f"action '{proposal.action_type}' is not in the action catalog"])

    # 2. Tier permitted.
    if spec.tier not in PERMITTED_TIERS:
        return _reject(spec.name, spec.tier,
                       [f"action '{spec.name}' is tier {spec.tier.value}, which policy never permits"])

    # 3. Schema + range.
    try:
        params = spec.params_model.model_validate(proposal.params)
    except ValidationError as exc:
        return _reject(spec.name, spec.tier, _format_validation_error(exc))

    errors = _range_checks(spec, params, evidence)
    if errors:
        return _reject(spec.name, spec.tier, errors)

    decision = AUTO_EXECUTE if spec.tier == Tier.T0 else NEEDS_APPROVAL
    return PolicyResult(decision, spec.name, spec.tier, [], params.model_dump())
