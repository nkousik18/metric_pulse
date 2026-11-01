"""
Pydantic schemas for Action Agent proposals and per-action params
(docs/action-agent-scope.md §4-§5).

ActionProposal.action_type is a plain `str` and params a plain `dict` on
purpose: an out-of-catalog action or malformed params must reach policy_check
and be *rejected with a logged reason*, not blow up as a parse error before
the gate ever sees it. Each params model is strict about shape
(extra='forbid'), so a tampered payload with an injected extra field fails
validation instead of being silently dropped.
"""

import math
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from investigation.schemas import EvidenceCitation

# Hard cap on suppress_alerts' N days (decision log, docs/action-agent-scope.md §12).
SUPPRESS_MAX_DAYS = 7
# D4/§10.2: a create_control watch must expire, and within 30 days.
CONTROL_MAX_EXPIRY_DAYS = 30


class _StrictParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


class _SegmentParams(_StrictParams):
    """Params that target one decomposition segment. policy_check grounds the
    (dimension, segment) pair against the investigation's real evidence."""
    dimension: str = Field(min_length=1, max_length=100)
    segment: str = Field(min_length=1, max_length=200)


class AnnotateAnomalyParams(_StrictParams):
    category: Literal['holiday', 'promotion', 'seasonal', 'data_issue', 'other']
    cause: str = Field(min_length=1, max_length=200)


class SuppressAlertsParams(_StrictParams):
    days: int = Field(strict=True, ge=1, le=SUPPRESS_MAX_DAYS)
    reason: str = Field(min_length=1, max_length=200)


class NotifyOwnerParams(_SegmentParams):
    pass


class OpenIncidentParams(_SegmentParams):
    title: str = Field(min_length=1, max_length=120)
    severity: Literal['low', 'medium', 'high']


class CreateControlParams(_SegmentParams):
    direction: Literal['above', 'below']
    threshold: float = Field(strict=True, gt=0)
    expires_in_days: int = Field(strict=True, ge=1, le=CONTROL_MAX_EXPIRY_DAYS)

    @field_validator('threshold')
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError('threshold must be a finite number')
        return v


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')

    action_type: str
    params: dict
    rationale_citations: List[EvidenceCitation] = Field(min_length=1, max_length=3)
