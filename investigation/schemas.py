"""
Structured-output Pydantic schemas for the `synthesize` node (docs/scoping.md
Section 3.3). The model never free-writes prose containing numbers -- it
outputs one of these, whose numeric fields are references into evidence
already in state, not typed by the model itself.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceCitation(BaseModel):
    # `str`, not Literal['geography', 'product', 'payment'] -- that Olist-specific
    # constraint was a real bug, found live (docs/ROADMAP.md M6, running the
    # unmodified Phase 1 agent against a real onboarded dataset for the first
    # time): it forced the model's structured-output call to squeeze every
    # citation into one of three hardcoded dimension names, so a real citation
    # like ('Product Container', 'Small Box') got coerced into an invalid
    # ('product', 'Small Box') and correctly-but-uselessly failed validation.
    # validate_citation() (investigation/validation.py) already checks a
    # citation's (dimension, segment) pair against real state at runtime --
    # the Literal was always redundant with that real grounding check, just an
    # implicit assumption nothing had tested past Olist's fixed 3 dimensions
    # until now.
    dimension: str
    segment: str
    source: Literal['decomposition', 'drill_down']
    claim: str


class SynthesisOutput(BaseModel):
    reasoning: str
    primary_explanation: EvidenceCitation
    supporting_citations: List[EvidenceCitation] = Field(default_factory=list, max_length=3)
    uncertainty_note: Optional[str] = None
    should_continue: bool
