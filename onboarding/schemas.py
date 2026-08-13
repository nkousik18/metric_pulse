"""
Structured-output Pydantic schemas for Stage B classification (docs/scoping.md
Section 5.2). Mirrors investigation/schemas.py's role: the LLM never
free-writes; it emits one of these.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DimensionCandidate(BaseModel):
    column: str
    cardinality: int
    confidence: float
    reasoning: str


class RejectedColumn(BaseModel):
    column: str
    reason: str


class SchemaClassification(BaseModel):
    date_column: Optional[str] = None
    grain: Literal['daily', 'other']
    metric_columns: List[str] = Field(default_factory=list)
    dimension_columns: List[DimensionCandidate] = Field(default_factory=list)
    rejected_columns: List[RejectedColumn] = Field(default_factory=list)
    # Not in Section 5.2's illustrative code block, but required by Sections 5.4/5.6's prose
    # ("the contract is still emitted -- but with requires_human_review=True and the
    # unresolved issues attached") -- same category of doc-vs-implementation gap already
    # corrected once for Section 3.5's validate_citation snippet.
    requires_human_review: bool = False
    validation_errors: List[str] = Field(default_factory=list)
