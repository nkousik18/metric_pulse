"""
The fixed action catalog (docs/action-agent-scope.md §4). Adding an action
means adding an entry here with a tier -- there is no other path to a new
action type (§9, scope-creep mitigation).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Type

from pydantic import BaseModel

from action_agent.schemas import (
    AnnotateAnomalyParams,
    CreateControlParams,
    NotifyOwnerParams,
    OpenIncidentParams,
    SuppressAlertsParams,
)


class Tier(str, Enum):
    T0 = 'T0'  # executes automatically
    T1 = 'T1'  # requires human approval
    T2 = 'T2'  # data mutation -- always rejected by policy_check


# Tiers policy_check lets through. T2 is deliberately absent.
PERMITTED_TIERS = frozenset({Tier.T0, Tier.T1})


@dataclass(frozen=True)
class ActionSpec:
    name: str
    tier: Tier
    reversible: bool
    params_model: Type[BaseModel]
    targets_segment: bool  # params carry a (dimension, segment) that must be grounded
    description: str


CATALOG: Dict[str, ActionSpec] = {
    spec.name: spec for spec in [
        ActionSpec(
            'annotate_anomaly', Tier.T0, True, AnnotateAnomalyParams, False,
            'Tag an anomaly with a known cause. Tag only -- no effect on alerting.',
        ),
        ActionSpec(
            'suppress_alerts', Tier.T1, True, SuppressAlertsParams, False,
            'Suppress repeat pipeline alerts for this anomaly for N days.',
        ),
        ActionSpec(
            'notify_owner', Tier.T1, False, NotifyOwnerParams, True,
            'Send the narrative and evidence to the segment owner.',
        ),
        ActionSpec(
            'open_incident', Tier.T1, True, OpenIncidentParams, True,
            'Open a GitHub Issue with the evidence table and citations.',
        ),
        ActionSpec(
            'create_control', Tier.T1, True, CreateControlParams, True,
            'Register a segment-level watch with a threshold, owner and expiry.',
        ),
    ]
}
