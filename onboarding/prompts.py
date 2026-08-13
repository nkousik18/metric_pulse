"""
Prompt construction for Stage B classification (docs/scoping.md Sections
5.2-5.4). Mirrors investigation/prompts.py's structure.
"""

from typing import Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from onboarding.profiling import ColumnProfile

SYSTEM_PROMPT = """You are the schema-classification step of MetricPulse's dataset-onboarding \
agent. You are given a deterministic statistical profile of every column in a new, never-seen \
tabular dataset. Classify each column into exactly one role:

- `date_column`: the single column representing "when" -- pick the one column with a high \
  date_parse_rate (ideally close to 1.0) that best represents one row (or one aggregation group) \
  per time period. A column can have a high date_parse_rate AND look like an identifier \
  (is_likely_id=True, high cardinality_ratio) at the same time -- that's expected for an \
  already-daily-grain dataset (one row per day looks unique too) and does NOT disqualify it from \
  being the date_column.
- `grain`: "daily" if the date_column's cardinality is approximately equal to the row count (one \
  row already exists per date); "other" if the date_column's cardinality is much smaller than the \
  row count (multiple rows per date -- transaction-level data that needs daily aggregation).
- `metric_columns`: numeric columns (is_numeric=True) worth summing per day -- revenue-like or \
  count-like values. Never a column with is_likely_id=True.
- `dimension_columns`: categorical columns worth grouping by -- bounded, low-to-moderate \
  cardinality (NOT is_likely_id=True). For each, give a cardinality, a confidence (0-1), and a \
  short reasoning string.
- `rejected_columns`: everything else -- identifiers (is_likely_id=True), high-null free text, or \
  anything that fits no other role. EVERY rejected column must have an explicit reason string; \
  never silently omit a column from the classification entirely -- it must appear in exactly one \
  of metric_columns, dimension_columns, or rejected_columns (date_column is separate and singular).

Base every judgment on the profile statistics given -- cardinality_ratio, null_rate, \
date_parse_rate, is_numeric, is_likely_id, sample_values -- not on assumptions about what the \
column names might mean in some other dataset you've seen before."""


def _format_profile(profile: ColumnProfile) -> str:
    return (
        f"- {profile.name}: dtype={profile.dtype}, cardinality={profile.cardinality}, "
        f"cardinality_ratio={profile.cardinality_ratio:.3f}, null_rate={profile.null_rate:.3f}, "
        f"date_parse_rate={profile.date_parse_rate:.3f}, is_numeric={profile.is_numeric}, "
        f"is_likely_id={profile.is_likely_id}, sample_values={profile.sample_values}"
    )


def build_classification_prompt(
    profiles: Dict[str, ColumnProfile],
    validation_errors: Optional[List[str]] = None
) -> List[BaseMessage]:
    profile_lines = "\n".join(_format_profile(p) for p in profiles.values())
    user_content = (
        f"Column profiles ({len(profiles)} columns, referenced by name below):\n\n{profile_lines}"
        f"\n\nProduce your structured classification now."
    )

    if validation_errors:
        user_content += (
            "\n\nYour previous classification failed validation for these reasons:\n"
            + "\n".join(f"- {e}" for e in validation_errors)
            + "\n\nCorrect these issues and classify again, using only the profile facts above."
        )

    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_content)]
