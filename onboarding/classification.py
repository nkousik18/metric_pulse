"""
Stage B classification + validation (docs/scoping.md Sections 5.2, 5.4).
`classify_columns_with_validation` is structurally identical to
investigation/nodes.py's `_run_synthesis` -- one real LLM call, validate, one
bounded retry with the specific errors fed back, then emit regardless (never
crash, never silently trust an unvalidated answer).
"""

import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger  # noqa: E402
from onboarding.llm import get_classification_llm  # noqa: E402
from onboarding.profiling import ColumnProfile  # noqa: E402
from onboarding.prompts import build_classification_prompt  # noqa: E402
from onboarding.schemas import SchemaClassification  # noqa: E402

logger = setup_logger(__name__)

# Named constants, not magic numbers (docs/scoping.md Section 5.3).
MIN_DATE_PARSE_RATE = 0.95
# Section 5.3 doesn't pin an exact number for "low-to-moderate... bounded, not
# near-unique," but Section 5.6's own worked example does, implicitly: it
# rejects customer_id (cardinality ratio 0.164) as "too high to be a useful
# grouping dimension" while accepting plan_type/region (ratio ~0.00006) as
# obviously fine. 0.1 is chosen specifically to sit between those two real
# numbers -- calibrated against the design doc's own example, not guessed.
MAX_DIMENSION_CARDINALITY_RATIO = 0.1


def validate_classification(clf: SchemaClassification, profiles: Dict[str, ColumnProfile]) -> List[str]:
    errors = []

    if clf.date_column:
        profile = profiles.get(clf.date_column)
        if profile is None:
            errors.append(f"'{clf.date_column}' proposed as date_column but is not a real column")
        elif profile.date_parse_rate < MIN_DATE_PARSE_RATE:
            errors.append(
                f"'{clf.date_column}' proposed as date_column but only "
                f"{profile.date_parse_rate:.0%} parses as a date"
            )

    for m in clf.metric_columns:
        profile = profiles.get(m)
        if profile is None:
            errors.append(f"'{m}' proposed as a metric but is not a real column")
        elif not profile.is_numeric:
            errors.append(f"'{m}' proposed as a metric but is not numeric")

    for d in clf.dimension_columns:
        profile = profiles.get(d.column)
        if profile is None:
            errors.append(f"'{d.column}' proposed as a dimension but is not a real column")
        elif profile.cardinality_ratio > MAX_DIMENSION_CARDINALITY_RATIO:
            errors.append(
                f"'{d.column}' proposed as a dimension but cardinality ratio "
                f"{profile.cardinality_ratio:.2f} suggests an identifier, not a category"
            )

    return errors


def classify_columns_with_validation(profiles: Dict[str, ColumnProfile]) -> SchemaClassification:
    llm = get_classification_llm()

    clf = llm.invoke(build_classification_prompt(profiles))
    errors = validate_classification(clf, profiles)
    if not errors:
        return clf.model_copy(update={'requires_human_review': False, 'validation_errors': []})

    logger.info(f"classification: first attempt failed validation: {errors}")
    clf = llm.invoke(build_classification_prompt(profiles, validation_errors=errors))
    errors = validate_classification(clf, profiles)
    if not errors:
        return clf.model_copy(update={'requires_human_review': False, 'validation_errors': []})

    logger.info(f"classification: retry also failed validation: {errors}")
    return clf.model_copy(update={'requires_human_review': True, 'validation_errors': errors})
