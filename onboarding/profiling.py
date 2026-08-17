"""
Stage A: deterministic column profiling (docs/scoping.md Section 5.2). No LLM
call here -- pure pandas over a single flat dataset, scales with column count
not row count. Every fact Stage B's classification prompt is built from comes
from this module.
"""

from typing import Dict, List

import pandas as pd
from pydantic import BaseModel

# Named constant, not a magic number (docs/scoping.md Section 5.2's own suggested value).
ID_CARDINALITY_THRESHOLD = 0.9


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    cardinality: int
    cardinality_ratio: float
    null_rate: float
    sample_values: List[str]
    date_parse_rate: float
    is_numeric: bool
    is_likely_id: bool


def _date_parse_rate(series: pd.Series, is_numeric: bool) -> float:
    """
    Fraction of a bounded sample that pd.to_datetime() parses successfully.

    Numeric columns are never date candidates and are short-circuited to 0.0:
    pandas coerces plain numbers into "successfully parsed" nanosecond-epoch
    timestamps (e.g. pd.to_datetime(pd.Series([100.5])) succeeds with 100%
    non-null rate) -- without this guard, every metric column would look like
    a perfect date column. A genuine date column in this system's intended
    input shape is object/string (or already-parsed datetime64, which
    pd.to_datetime() passes through as a harmless no-op) -- never bare numeric.
    """
    if is_numeric:
        return 0.0

    sample = series.dropna().head(1000)
    if len(sample) == 0:
        return 0.0

    parsed = pd.to_datetime(sample, errors='coerce')
    return float(parsed.notna().mean())


def profile_column(name: str, series: pd.Series) -> ColumnProfile:
    n_rows = len(series)
    non_null = series.dropna()

    cardinality = int(series.nunique())
    cardinality_ratio = (cardinality / n_rows) if n_rows else 0.0
    null_rate = 1.0 - (len(non_null) / n_rows) if n_rows else 0.0
    sample_values = [str(v) for v in non_null.head(5)]
    is_numeric = bool(pd.api.types.is_numeric_dtype(series))
    # Float columns are exempt from the cardinality-based ID check. Found live
    # (docs/ROADMAP.md M6, a real sales dataset): a genuine revenue column
    # ("Sales", ratio 0.971) and a genuine profit column ("Profit", ratio
    # 0.930) both cleared ID_CARDINALITY_THRESHOLD purely because continuous
    # dollar amounts are almost all naturally unique across thousands of rows
    # -- that's normal for a measurement, not an identifier signal. Integer
    # columns stay eligible: a genuinely sequential ID (e.g. "Row ID",
    # ratio 1.0) is still caught, and an integer *metric* (e.g. "Order
    # Quantity") already has naturally low cardinality on its own, so it was
    # never at risk of this false positive the way a continuous float is.
    is_float = bool(pd.api.types.is_float_dtype(series))
    is_likely_id = cardinality_ratio > ID_CARDINALITY_THRESHOLD and not is_float

    return ColumnProfile(
        name=name,
        dtype=str(series.dtype),
        cardinality=cardinality,
        cardinality_ratio=cardinality_ratio,
        null_rate=null_rate,
        sample_values=sample_values,
        date_parse_rate=_date_parse_rate(series, is_numeric),
        is_numeric=is_numeric,
        is_likely_id=is_likely_id,
    )


def profile_columns(df: pd.DataFrame) -> Dict[str, ColumnProfile]:
    return {column: profile_column(column, df[column]) for column in df.columns}
