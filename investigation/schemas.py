"""
Structured-output Pydantic schemas for the `synthesize` node (docs/scoping.md
Section 3.3). The model never free-writes prose containing numbers -- it
outputs one of these, whose numeric fields are references into evidence
already in state, not typed by the model itself.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceCitation(BaseModel):
    dimension: Literal['geography', 'product', 'payment']
    segment: str
    source: Literal['decomposition', 'drill_down']
    claim: str


class SynthesisOutput(BaseModel):
    reasoning: str
    primary_explanation: EvidenceCitation
    supporting_citations: List[EvidenceCitation] = Field(default_factory=list, max_length=3)
    uncertainty_note: Optional[str] = None
    should_continue: bool
