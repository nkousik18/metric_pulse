"""
Tests for the eval scorecard on Investigate (observability/scorecard.py, metric_pulse_web/views.py;
docs/ui-redesign-scope.md U2). Pure functions on in-memory ledger rows, plus the real Django view
through the test client. No mocks.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'metric_pulse_web.settings')

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402

from observability.scorecard import SCORECARD, build_scorecard  # noqa: E402


def _row(metrics, ts='2026-11-12T16:21:04+00:00', sha='06a58bf'):
    return {'ts': ts, 'git_sha': sha, 'metrics': metrics}


def test_rates_show_numerator_over_denominator_and_the_percentage_only_when_partial():
    groups = build_scorecard({'investigation': _row({
        'grounding_pass_rate': {'value': 0.8333, 'num': 25, 'n': 30},
        'golden_match_rate': {'value': 1.0, 'num': 30, 'n': 30},
    })})
    rows = {r['key']: r for r in groups[0]['rows']}
    assert rows['grounding_pass_rate']['figure'] == '25/30'
    assert rows['grounding_pass_rate']['context'] == 'runs · 83%'
    assert rows['golden_match_rate']['context'] == 'runs'
    assert groups[0]['date'] == '2026-11-12' and groups[0]['git_sha'] == '06a58bf'


def test_a_score_without_a_numerator_shows_its_n():
    groups = build_scorecard({'detection': _row({'with_freshness_f1': {'value': 0.96, 'num': None, 'n': 28}})})
    assert groups[0]['rows'][0]['figure'] == '0.96'
    assert groups[0]['rows'][0]['context'] == 'over 28 labelled days'


def test_missing_metrics_and_evals_are_skipped_never_filled_in():
    groups = build_scorecard({'action': _row({'action_match_rate': {'value': 1.0, 'num': 15, 'n': 15}})})
    assert [g['eval'] for g in groups] == ['action']
    assert [r['key'] for r in groups[0]['rows']] == ['action_match_rate']
    assert build_scorecard({}) == []


def test_zero_counts_keep_their_denominator():
    groups = build_scorecard({'action': _row({'injection_bypasses': {'value': 0, 'num': 0, 'n': 10}})})
    assert groups[0]['rows'][0]['figure'] == '0/10'


def test_every_scorecard_metric_exists_in_the_committed_ledger():
    from observability.drift import latest_rows
    from observability.evals import read_ledger
    latest = latest_rows(read_ledger())
    for eval_name, _, items in SCORECARD:
        for key, _, _ in items:
            assert key in latest[eval_name]['metrics'], f'{eval_name}.{key}'


def test_the_home_page_renders_the_scorecard_from_the_ledger():
    response = Client().get('/')
    assert response.status_code == 200
    html = response.content.decode()
    agent_rows = sum(len(items) for name, _, items in SCORECARD if name != 'detection')
    assert html.count('class="score-cell"') == agent_rows   # one score row per agent section


# --- the full eval table on How it's built ---

def test_the_eval_table_shows_a_percentage_only_for_rates_not_counts():
    from observability.scorecard import eval_table
    rows = eval_table({'detection': _row({
        'detection_precision': {'value': 0.9167, 'num': 11, 'n': 12},   # a rate
        'false_alarms': {'value': 1, 'num': 1, 'n': 28},                 # a count: value is the count
        'detection_f1': {'value': 0.9167, 'num': None, 'n': 28},
    })})
    text = {m['key']: m['text'] for m in rows[0]['metrics']}
    assert text == {'detection_precision': '11/12 (92%)', 'false_alarms': '1/28', 'detection_f1': '0.92 (n = 28)'}
    assert rows[0]['count'] == '3'


def test_the_eval_table_keeps_small_values_readable_and_skips_empty_ones():
    from observability.scorecard import eval_table
    rows = eval_table({'action': _row({'cost_per_run_usd': {'value': 0.00043, 'num': 0.006443, 'n': 15},
                                       'missing': {'value': None, 'num': None, 'n': 0}})})
    assert [(m['key'], m['text']) for m in rows[0]['metrics']] == [('cost_per_run_usd', '0.00043 (n = 15)')]
