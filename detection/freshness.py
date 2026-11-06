"""
The data-freshness check (docs/action-agent-scope.md §15): a second detection signal, next to the
z-score, for a feed that is failing rather than a business that is changing.

The z-score compares a day with its own trailing window, so a slow slide fills the window and the
worst day doesn't stand out (Olist's export tail: 1 order on 2018-09-03, replayed z only -1.85).
This compares the day's record volume with the median of the rows before it:

    stale  when  volume(day) < FRESHNESS_MIN_VOLUME_RATIO x median(previous FRESHNESS_WINDOW rows)
    not applicable when that median < FRESHNESS_MIN_BASE_VOLUME (too sparse to judge: Superstore's
    ~6 orders/day would be "stale" on 240 of 1,390 days)

Volume, not the alerted metric: a revenue dip can be real business (Christmas Eve), a collapse in the
number of records is what missing data looks like. Pure functions; the caller passes the rows.

    {'status': 'stale' | 'fresh' | 'not_applicable', 'date', 'volume_column', 'volume', 'median',
     'ratio', 'window_rows', 'reason'}
"""

import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd  # noqa: E402

from config import settings  # noqa: E402

VOLUME_COLUMNS = ('order_count', 'row_count')   # Olist's fact table; an onboarded dataset's (codegen)


def volume_column(columns: Iterable[str]) -> Optional[str]:
    """The record-volume column of a daily fact table, or None if it has none."""
    columns = set(columns)
    return next((c for c in VOLUME_COLUMNS if c in columns), None)


def check_freshness(df: pd.DataFrame, volume_col: Optional[str] = None, date: Optional[str] = None,
                    ratio: float = None, window: int = None, min_base: float = None) -> Dict:
    """Freshness of `date` (default: the latest row) from the daily rows in df (metric_date plus the
    volume column; any order)."""
    ratio = settings.FRESHNESS_MIN_VOLUME_RATIO if ratio is None else ratio
    window = settings.FRESHNESS_WINDOW if window is None else window
    min_base = settings.FRESHNESS_MIN_BASE_VOLUME if min_base is None else min_base
    volume_col = volume_col or volume_column(df.columns)
    out = {'status': 'not_applicable', 'date': date, 'volume_column': volume_col, 'volume': None,
           'median': None, 'ratio': None, 'window_rows': 0,
           'thresholds': {'min_volume_ratio': ratio, 'window': window, 'min_base_volume': min_base}}
    if volume_col is None or volume_col not in df.columns or df.empty:
        return {**out, 'reason': 'no record-volume column'}

    rows = df[['metric_date', volume_col]].copy()
    rows['metric_date'] = rows['metric_date'].astype(str).str[:10]
    rows = rows.sort_values('metric_date')
    if date is not None:
        rows = rows[rows['metric_date'] <= str(date)[:10]]
    if rows.empty or (date is not None and rows['metric_date'].iloc[-1] != str(date)[:10]):
        return {**out, 'reason': 'date not in the data'}

    day = rows.iloc[-1]
    prior = pd.to_numeric(rows[volume_col].iloc[:-1].tail(window), errors='coerce').dropna()
    volume = float(day[volume_col])
    out.update({'date': day['metric_date'], 'volume': volume, 'window_rows': len(prior)})
    if len(prior) < window:
        return {**out, 'reason': f'only {len(prior)} earlier rows (needs {window})'}
    median = float(prior.median())
    out['median'] = median
    if median < min_base:
        return {**out, 'reason': f'too sparse to judge (median {median:g} < {min_base:g} records/day)'}
    share = round(volume / median, 3)
    out['ratio'] = share
    if share < ratio:
        return {**out, 'status': 'stale',
                'reason': f'{volume:g} {_records(volume)} vs. a median of {median:g} over the previous {window} rows '
                          f'({share:.0%}, under {ratio:.0%}): the data looks incomplete'}
    return {**out, 'status': 'fresh', 'reason': f'{share:.0%} of the {window}-row median'}


def _records(n: float) -> str:
    return 'record' if n == 1 else 'records'


def stale_note(freshness: Optional[Dict]) -> Optional[str]:
    """One line for an alert when the day is stale, else None."""
    if not freshness or freshness.get('status') != 'stale':
        return None
    return (f"Data looks incomplete on {freshness['date']}: {freshness['volume']:g} {_records(freshness['volume'])} "
            f"vs. a typical "
            f"{freshness['median']:g} ({freshness['ratio']:.0%}). The segment breakdown below is likely "
            f"an artefact of missing data, not a business change.")
