"""
Tests for detection/freshness.py and its wiring (docs/action-agent-scope.md §15): a day is stale when
its record volume is under 25% of the previous 28 rows' median, and the check is off for a sparse
dataset. Plain DataFrames and dicts; no mocks, no warehouse.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd  # noqa: E402

from action_agent.llm_proposer import SYSTEM_PROMPT, build_messages  # noqa: E402
from config import settings  # noqa: E402
from detection.anomaly_detector import detect_anomalies  # noqa: E402
from detection.freshness import check_freshness, stale_note, volume_column  # noqa: E402
from orchestration.run_pipeline import _with_freshness  # noqa: E402
from tests.test_llm_proposer import STATE  # noqa: E402


def days(volumes, col='order_count', start='2018-07-01'):
    return pd.DataFrame({'metric_date': pd.date_range(start, periods=len(volumes)).strftime('%Y-%m-%d'),
                         col: volumes})


def test_the_approved_values():
    assert (settings.FRESHNESS_MIN_VOLUME_RATIO, settings.FRESHNESS_WINDOW,
            settings.FRESHNESS_MIN_BASE_VOLUME) == (0.25, 28, 50)


def test_a_collapsed_day_is_stale():
    # Olist's 2018-09-03: 1 order against a median of ~250.
    f = check_freshness(days([250] * 28 + [1]))
    assert f['status'] == 'stale' and f['median'] == 250 and f['volume'] == 1 and f['ratio'] == 0.004
    assert 'incomplete' in f['reason'] and f['volume_column'] == 'order_count'


def test_a_low_but_real_day_is_fresh():
    # Christmas Eve 2017: ~27% of the median, a real quiet day, just above the line.
    assert check_freshness(days([250] * 28 + [68]))['status'] == 'fresh'
    assert check_freshness(days([250] * 28 + [62]))['status'] == 'stale'


def test_the_window_is_the_rows_before_the_day_not_including_it():
    # 28 earlier rows at 100, older rows at 10_000 outside the window: the median is 100.
    f = check_freshness(days([10_000] * 10 + [100] * 28 + [20]))
    assert f['median'] == 100 and f['status'] == 'stale' and f['window_rows'] == 28


def test_a_sparse_dataset_is_not_applicable_not_fresh():
    # Superstore: a few orders a day, so a near-empty day is normal.
    f = check_freshness(days([5] * 28 + [0], col='row_count'))
    assert f['status'] == 'not_applicable' and 'sparse' in f['reason'] and f['volume_column'] == 'row_count'


def test_short_history_missing_column_and_missing_date():
    assert 'earlier rows' in check_freshness(days([250] * 10 + [1]))['reason']
    assert check_freshness(days([250] * 29, col='revenue'))['reason'] == 'no record-volume column'
    assert check_freshness(days([250] * 29), date='1999-01-01')['reason'] == 'date not in the data'


def test_a_date_inside_the_series_is_judged_on_the_rows_up_to_it():
    df = days([250] * 28 + [1] + [250] * 5)
    assert check_freshness(df, date=df['metric_date'].iloc[28])['status'] == 'stale'
    assert check_freshness(df)['status'] == 'fresh'


def test_volume_column_prefers_orders_then_rows():
    assert volume_column(['metric_date', 'order_count', 'row_count']) == 'order_count'
    assert volume_column(['metric_date', 'row_count']) == 'row_count'
    assert volume_column(['metric_date', 'sales']) is None


def test_the_z_score_misses_a_slow_slide_that_freshness_catches():
    # The pipeline's 30-row window: ten normal days, then a 20-day slide to 1 record. The slide is
    # inside the window, so the last day's z is only ~-1.9; its volume is under 1% of the median.
    values = [250] * 10 + [240, 227, 215, 202, 190, 177, 165, 152, 139, 127, 114, 102, 89, 76, 64, 51, 39, 26, 14, 1]
    df = days(values)
    assert not bool(detect_anomalies(df, 'order_count', 2.0)['is_anomaly'].iloc[-1])
    assert check_freshness(df)['status'] == 'stale'


def test_alert_narratives_lead_with_the_note_only_when_stale():
    narratives = {'full': 'Revenue fell.', 'slack': 'Revenue fell.', 'summary': 'Revenue fell.',
                  'email_subject': 'MetricPulse: revenue'}
    stale = check_freshness(days([250] * 28 + [1]))
    out = _with_freshness(narratives, stale)
    assert out['full'].startswith('Data looks incomplete') and out['full'].endswith('Revenue fell.')
    assert out['summary'].startswith('Data looks incomplete') and out['email_subject'].startswith('[Data incomplete]')
    assert _with_freshness(narratives, check_freshness(days([250] * 29))) == narratives
    assert stale_note(None) is None and narratives['full'] == 'Revenue fell.'      # input not modified


def test_the_proposer_sees_freshness_and_rule_3_reads_it_first():
    stale = check_freshness(days([250] * 28 + [1]))
    _, human = build_messages({**STATE, 'evidence': {**STATE['evidence'], 'freshness': stale}})
    block = json.loads(human.content.split('<data>\n', 1)[1].rsplit('\n</data>', 1)[0])['EVIDENCE']
    assert block['freshness']['status'] == 'stale' and 'thresholds' not in block['freshness']
    assert SYSTEM_PROMPT.index('freshness') < SYSTEM_PROMPT.index('driver_check')
    assert 'data_issue' in SYSTEM_PROMPT
    _, human = build_messages(STATE)                                    # no freshness in the evidence
    assert '"status": "not_applicable"' in human.content
