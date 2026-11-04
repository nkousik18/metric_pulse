"""
Tests for the shared eval plumbing (observability/evals.py) and the detection eval's pure parts
(detection/eval.py): the replayed production decision, the confusion matrix and scores, the
sweep, candidate picking and label validation. In-memory frames and tmp_path files; no warehouse,
no LLM, no mocks.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.eval import compare as action_compare  # noqa: E402
from detection.anomaly_detector import detect_anomalies  # noqa: E402
from detection.eval import confusion, grade, label_errors, pick, replay, replay_all, run, scores  # noqa: E402
from observability import evals as shared  # noqa: E402


def _series(values, start='2018-01-01'):
    dates = pd.date_range(start, periods=len(values)).strftime('%Y-%m-%d')
    return pd.DataFrame({'metric_date': dates, 'm': [float(v) for v in values]})


# --- observability/evals.py ---

def test_rate_count_and_value_shapes():
    assert shared.rate(3, 4) == {'value': 0.75, 'num': 3, 'n': 4}
    assert shared.rate(0, 0)['value'] is None
    assert shared.count(2, 10) == {'value': 2, 'num': 2, 'n': 10}
    assert shared.value(0.123456, 5) == {'value': 0.1235, 'num': None, 'n': 5}


def test_compare_flags_the_right_direction():
    metrics = {'match_rate': shared.rate(6, 10), 'escalation_rate': shared.rate(5, 10),
               'unsafe': shared.count(1, 4), 'cost': shared.value(9.0, 1), 'quiet_rate': shared.rate(9, 10)}
    base = {'metrics': {'match_rate': 0.9, 'escalation_rate': 0.2, 'unsafe': 0, 'cost': 1.0, 'quiet_rate': 0.95}}
    d = shared.compare(metrics, base, safety=['unsafe'], lower_is_better=['escalation_rate'])
    assert d['match_rate']['regressed'] and d['escalation_rate']['regressed'] and d['unsafe']['regressed']
    assert not d['cost']['regressed']             # not a rate, not named: compared, never flagged
    assert not d['quiet_rate']['regressed']       # a 0.05 drop is inside the 0.1 tolerance


def test_action_eval_flags_a_rise_in_adversarial_escalation_not_a_fall():
    # BUG_LOG A7-1: adversarial_escalation/fallback_rate were treated as higher-is-better.
    base = {'metrics': {'adversarial_escalation_rate': 0.2, 'adversarial_fallback_rate': 0.3}}
    rose = action_compare({'adversarial_escalation_rate': shared.rate(5, 10),
                           'adversarial_fallback_rate': shared.rate(5, 10)}, base)
    fell = action_compare({'adversarial_escalation_rate': shared.rate(0, 10),
                           'adversarial_fallback_rate': shared.rate(0, 10)}, base)
    assert rose['adversarial_escalation_rate']['regressed'] and rose['adversarial_fallback_rate']['regressed']
    assert not fell['adversarial_escalation_rate']['regressed'] and not fell['adversarial_fallback_rate']['regressed']


def test_ledger_and_baseline_round_trip(tmp_path):
    row = {'ts': 't', 'eval': 'detection', 'git_sha': 'abc', 'threshold': 2.0,
           'metrics': {'detection_recall': shared.rate(3, 4)}, 'failing': []}
    shared.append_ledger(row, tmp_path / 'ledger.jsonl')
    shared.append_ledger({**row, 'ts': 't2'}, tmp_path / 'ledger.jsonl')
    assert [r['ts'] for r in shared.read_ledger(tmp_path / 'ledger.jsonl')] == ['t', 't2']
    path = shared.write_baseline(row, ('ts', 'git_sha', 'threshold'), tmp_path)
    assert json.loads(path.read_text()) == {'ts': 't', 'git_sha': 'abc', 'threshold': 2.0,
                                            'metrics': {'detection_recall': 0.75}}
    assert shared.load_baseline('detection', tmp_path)['metrics'] == {'detection_recall': 0.75}
    assert shared.load_baseline('nope', tmp_path) is None


# --- the replayed production decision ---

def test_replay_uses_only_the_lookback_rows_ending_at_the_date():
    values = [100] * 40 + [400] + [100] * 5
    s = _series(values)
    spike_date = s['metric_date'].iloc[40]
    r = replay(s, 'm', spike_date, threshold=2.0, lookback=30)
    # Identical to running the production detector on the 30 rows ending at the spike.
    expected = detect_anomalies(s.iloc[11:41], 'm', 2.0).iloc[-1]
    assert r['window_rows'] == 30 and r['flagged'] is True
    assert r['zscore'] == round(float(expected['zscore']), 3)
    # Later rows never leak in: the spike looks the same however much data follows it.
    assert replay(s.iloc[:41], 'm', spike_date, 2.0, 30) == r


def test_replay_is_none_for_a_date_not_in_the_data():
    s = _series([1, 2, 3])
    assert replay(s, 'm', '2030-01-01', 2.0) is None


def test_replay_all_starts_at_the_first_full_window():
    s = _series(range(1, 36))
    out = replay_all(s, 'm', 2.0, lookback=30)
    assert len(out) == 6 and out['metric_date'].iloc[0] == s['metric_date'].iloc[29]


# --- grading ---

CASES = [{'id': 'a', 'is_event': True, 'dataset_id': 'x', 'metric': 'm', 'date': '1'},
         {'id': 'b', 'is_event': True, 'dataset_id': 'x', 'metric': 'm', 'date': '2'},
         {'id': 'c', 'is_event': False, 'dataset_id': 'x', 'metric': 'm', 'date': '3'},
         {'id': 'd', 'is_event': False, 'dataset_id': 'x', 'metric': 'm', 'date': '4'}]


def test_confusion_and_scores():
    c = confusion(CASES, {'a': True, 'b': False, 'c': True, 'd': False})
    assert c == {'tp': 1, 'fp': 1, 'fn': 1, 'tn': 1}
    s = scores(c)
    assert s['detection_precision'] == {'value': 0.5, 'num': 1, 'n': 2}
    assert s['detection_recall'] == {'value': 0.5, 'num': 1, 'n': 2}
    assert s['detection_f1']['value'] == 0.5


def test_scores_when_nothing_is_flagged():
    s = scores({'tp': 0, 'fp': 0, 'fn': 2, 'tn': 2})
    assert s['detection_precision']['value'] is None      # no flags: precision undefined, not 0 or 1
    assert s['detection_recall']['value'] == 0.0 and s['detection_f1']['value'] is None


def test_grade_thresholds_strictly_and_sweeps():
    z = {'a': 3.0, 'b': -2.0, 'c': 2.6, 'd': None}       # None: date missing, never flagged
    g = grade(CASES, z, threshold=2.0)
    assert g['confusion'] == {'tp': 1, 'fp': 1, 'fn': 1, 'tn': 1}   # b at exactly 2.0 isn't flagged
    assert {f['id'] for f in g['failing']} == {'b', 'c'}
    at_275 = next(s for s in g['sweep'] if s['threshold'] == 2.75)
    assert (at_275['tp'], at_275['fp']) == (1, 0)


def test_run_reports_missing_dates_and_replays_each_case():
    s = _series([100] * 40 + [400])
    cases = [{'id': 'spike', 'is_event': True, 'dataset_id': 'x', 'metric': 'm', 'date': s['metric_date'].iloc[-1]},
             {'id': 'gone', 'is_event': False, 'dataset_id': 'x', 'metric': 'm', 'date': '1999-01-01'}]
    out = run(cases, 2.0, series_loader=lambda ds, m: s)
    assert out['missing'] == ['gone'] and out['confusion']['tp'] == 1


# --- candidates and labels ---

def test_pick_takes_strongest_then_near_then_ordinary_without_repeats():
    replayed = pd.DataFrame({'metric_date': [f'2018-01-{i:02d}' for i in range(1, 11)],
                             'zscore': [5, -4, 3, 2.2, 1.8, 1.6, 0.5, 0.2, -0.3, None]})
    chosen = pick(replayed, strongest=2, near=2, ordinary=2)
    whys = [w for _, w in chosen]
    assert whys == ['strongest', 'strongest', 'near', 'near', 'ordinary', 'ordinary']
    assert [d for d, _ in chosen][:2] == ['2018-01-01', '2018-01-02']
    assert len({d for d, _ in chosen}) == 6
    assert pick(replayed, 2, 2, 2) == chosen             # deterministic


def test_label_errors():
    cases = [{'id': f'd{i}', 'is_event': True} for i in range(20)]
    assert label_errors(cases) == []
    assert label_errors(cases[:19]) == ['only 19 cases; §7.1 needs at least 20']
    bad = cases[:-1] + [{'id': 'x', 'is_event': 'yes'}]
    assert label_errors(bad) == ['x: is_event must be true or false']


@pytest.mark.parametrize('flag', [None, 'true', 1])
def test_only_real_booleans_count_as_labels(flag):
    assert label_errors([{'id': 'a', 'is_event': flag}] + [{'id': str(i), 'is_event': False} for i in range(20)])


# --- investigation golden set (investigation/golden.py, investigation/eval.py) ---

from investigation.eval import failing as inv_failing, metrics_of as inv_metrics  # noqa: E402
from investigation.golden import kind_of, label_errors as inv_label_errors, segments_in  # noqa: E402

STATE = {
    'decomposition_results': {'dimensions': {
        'geography': {'top_contributors': [{'segment': 'Southeast'}, {'segment': 'South'}]},
        'payment': {'top_contributors': [{'segment': 'Credit Card'}]}}},
    'drill_down_results': {'geography': {'top_contributors': [{'segment': 'SP'}]}},
}


def test_kind_prefers_offsetting_over_close_over_clear():
    assert kind_of([]) == 'clear_driver'
    assert kind_of([{'dimension': 'a', 'reason': 'close_contributors'}]) == 'close_contributors'
    assert kind_of([{'dimension': 'a', 'reason': 'close_contributors'},
                    {'dimension': 'b', 'reason': 'offsetting_segments'}]) == 'offsetting_segments'


def test_segments_include_drill_down_details():
    assert segments_in(STATE, 'geography') == {'Southeast', 'South', 'SP'}
    assert segments_in(STATE, 'nope') == set()


def _inv_cases(n, **label):
    base = {'expected_primary': {'dimension': 'geography', 'segment': 'SP'}, 'requires_uncertainty_note': True}
    return [{'id': f'i{i}', **base, **label} for i in range(n)], {f'i{i}': STATE for i in range(n)}


def test_investigation_labels_must_be_complete_and_in_the_evidence():
    cases, states = _inv_cases(9)
    assert inv_label_errors(cases, states) == []
    listed, _ = _inv_cases(9, expected_primary=[{'dimension': 'payment', 'segment': 'Credit Card'},
                                                {'dimension': 'geography', 'segment': 'South'}])
    assert inv_label_errors(listed, states) == []
    bad, _ = _inv_cases(9, expected_primary={'dimension': 'payment', 'segment': 'Pix'})
    assert any("payment / Pix isn't in this case's evidence" in e for e in inv_label_errors(bad, states))
    unlabelled, _ = _inv_cases(9, expected_primary=None, requires_uncertainty_note=None)
    assert len(inv_label_errors(unlabelled, states)) == 18
    assert inv_label_errors(cases[:8], states)[-1].startswith('only 8 cases')
    assert inv_label_errors(cases, {})[0] == 'i0: no frozen state in states.json'


def test_investigation_metrics_and_failing_runs():
    rows = [
        {'case': 'a', 'run_index': 0, 'kind': 'clear_driver', 'outcome': 'grounded_first_attempt', 'golden_match': True,
         'uncertainty_ok': True, 'expected_primary': {}, 'primary_explanation': {'dimension': 'g', 'segment': 's'}},
        {'case': 'b', 'run_index': 0, 'kind': 'offsetting_segments', 'outcome': 'fallback_exception',
         'golden_match': False, 'uncertainty_ok': False, 'expected_primary': {'dimension': 'p', 'segment': 'x'},
         'primary_explanation': None},
    ]
    m = inv_metrics(rows)
    assert m['grounding_pass_rate'] == {'value': 0.5, 'num': 1, 'n': 2}
    assert m['fallback_rate']['value'] == 0.5
    f = inv_failing(rows)
    assert [x['id'] for x in f] == ['b#0'] and f[0]['actual'].startswith('no grounded output')


# --- onboarding eval grading (onboarding/eval.py) ---

from onboarding.eval import (all_cases, expected_from_classification, grade_classification,  # noqa: E402
                             metrics_of as onb_metrics)
from onboarding.schemas import SchemaClassification  # noqa: E402

CONFIRMED = {'date_column': 'day', 'grain': 'other', 'metric_columns': ['revenue'],
             'dimension_columns': [{'column': 'region', 'cardinality': 4, 'confidence': 0.9, 'reasoning': 'r'}],
             'rejected_columns': [{'column': 'id', 'reason': 'identifier'}]}


def test_a_matching_classification_scores_every_field():
    case = expected_from_classification('x', CONFIRMED)
    r = grade_classification(case, SchemaClassification.model_validate(CONFIRMED), [])
    assert all(r[f'{f}_match'] for f in ('date_column', 'grain', 'metric_columns', 'dimension_columns',
                                         'rejected_columns'))
    m = onb_metrics([r])
    assert m['all_fields_match_rate']['value'] == 1.0 and m['human_review_rate']['value'] == 0.0


def test_a_silently_dropped_column_is_a_miss_with_a_diff():
    # The A5 finding: a classification that omits a real column still passes validation. The eval
    # must still count it as wrong.
    case = expected_from_classification('x', CONFIRMED)
    dropped = SchemaClassification.model_validate({**CONFIRMED, 'dimension_columns': []})
    r = grade_classification(case, dropped, [])
    assert r['grounded'] and not r['dimension_columns_match']
    assert r['diff']['dimension_columns'] == {'missing': ['region'], 'extra': []}
    assert onb_metrics([r])['all_fields_match_rate']['value'] == 0.0


def test_three_onboarding_datasets_with_committed_expectations():
    cases = all_cases()
    assert [c['name'] for c in cases] == ['saas_subscriptions', 'superstore_sales', 'adversarial_injection']
    assert 'Order Date' == cases[1]['expected_date_column']
    assert cases[2]['csv'].exists()          # the adversarial CSV is committed; Superstore's is local only


# --- the drift run's report (observability/drift.py) ---

from observability.drift import LAUNCHD, drift_report  # noqa: E402


def test_drift_report_lists_regressions_first_using_each_evals_directions():
    rows = [
        {'eval': 'detection', 'ts': 'old', 'git_sha': 'a', 'metrics': {'detection_recall': shared.rate(9, 10)}},
        {'eval': 'detection', 'ts': 'new', 'git_sha': 'b', 'metrics': {'detection_recall': shared.rate(5, 10),
                                                                      'false_alarms': shared.count(1, 20)}},
        {'eval': 'action', 'ts': 't', 'git_sha': 'b', 'metrics': {'injection_bypasses': shared.count(1, 10),
                                                                 'adversarial_escalation_rate': shared.rate(0, 10)}},
    ]
    baselines = {'detection': {'git_sha': 'a', 'metrics': {'detection_recall': 0.9, 'false_alarms': 1}},
                 'action': {'git_sha': 'a', 'metrics': {'injection_bypasses': 0, 'adversarial_escalation_rate': 0.2}}}
    text, n = drift_report(rows, baselines, ran=['detection'], failed={'onboarding': 'boom'})
    assert n == 2                                    # recall fell 0.4; a bypass appeared. Escalation fell: fine.
    head = text.split('Per eval')[0]
    assert 'detection.detection_recall: 0.9 -> 0.5' in head and 'action.injection_bypasses: 0 -> 1' in head
    assert 'adversarial_escalation_rate' not in head
    assert 'onboarding: FAILED to run: boom' in text
    assert 'investigation: no ledger row yet' in text
    assert 'newest new git b' in text                # the newest row per eval is what's compared


def test_drift_report_with_no_baselines_flags_nothing():
    rows = [{'eval': 'onboarding', 'ts': 't', 'git_sha': 'a', 'metrics': {'grounded_rate': shared.rate(1, 3)}}]
    text, n = drift_report(rows, {}, ran=[], failed={})
    assert n == 0 and 'no baseline yet' in text and 'Regressions (0)' in text


def test_launchd_job_is_a_template_for_this_machine():
    plist = LAUNCHD.format(python='/x/python', root='/repo')
    assert '<string>/x/python</string>' in plist and '/repo/logs/drift.log' in plist


def test_the_eval_outputs_do_not_make_a_run_dirty(tmp_path):
    # BUG_LOG A7-3. A real git repo on tmp_path: an appended ledger row or a new baseline must not
    # mark the next eval's row -dirty; an edited label file must.
    import subprocess

    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q')
    git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', 'init')
    (tmp_path / 'evals' / 'baselines').mkdir(parents=True)
    for rel in ('evals/ledger.jsonl', 'evals/baselines/detection.json', 'evals/labels.yaml'):
        (tmp_path / rel).write_text('x\n')
    git('add', '.')
    git('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '-m', 'files')
    (tmp_path / 'evals' / 'ledger.jsonl').write_text('x\ny\n')
    (tmp_path / 'evals' / 'baselines' / 'detection.json').write_text('changed\n')
    assert not shared.git_sha_dirty(tmp_path).endswith('-dirty')
    (tmp_path / 'evals' / 'labels.yaml').write_text('relabelled\n')
    assert shared.git_sha_dirty(tmp_path).endswith('-dirty')


# --- pacing (BUG_LOG A7-5) ---

class FakeClock:
    """An injected clock: sleeping advances time. Not a mock: Pacer takes now_fn/sleep_fn by design."""

    def __init__(self):
        self.t, self.slept = 1000.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_pacer_waits_until_the_trailing_minute_has_room():
    clock = FakeClock()
    p = shared.Pacer(per_minute=7000, reserve=3000, now_fn=clock.now, sleep_fn=clock.sleep)
    assert p.wait() == 0
    p.spent(2500)
    clock.t += 10
    assert p.wait() == 0                 # 2,500 + 3,000 reserve fits in 7,000
    p.spent(2500)
    clock.t += 10
    waited = p.wait()                    # 5,000 + 3,000 doesn't: wait for the first call to age out
    assert waited == 40 and clock.slept == [40]
    assert [n for _, n in p.log] == [2500]


def test_tokens_since_reads_only_calls_logged_after_the_offset(tmp_path):
    log = tmp_path / 'llm_calls.jsonl'
    log.write_text(json.dumps({'total_tokens': 900}) + '\n')
    offset = shared.llm_log_offset(log)
    with open(log, 'a') as f:
        f.write(json.dumps({'total_tokens': 1200}) + '\n')
        f.write(json.dumps({'total_tokens': None}) + '\n')     # an API error line has no usage
        f.write('not json\n')
    assert shared.tokens_since(offset, log) == 1200
    assert shared.tokens_since(0, tmp_path / 'missing.jsonl') == 0


def test_investigation_reports_api_errors_apart_from_quality():
    rows = [{'outcome': 'fallback_exception', 'golden_match': False, 'uncertainty_ok': True},
            {'outcome': 'fallback_validation_failed', 'golden_match': False, 'uncertainty_ok': True},
            {'outcome': 'grounded_first_attempt', 'golden_match': True, 'uncertainty_ok': True}]
    m = inv_metrics(rows)
    assert m['fallback_rate']['num'] == 2 and m['api_error_rate']['num'] == 1


def test_a_run_with_api_failures_is_invalid_not_a_regression():
    rows = [{'eval': 'investigation', 'ts': 't', 'git_sha': 'b',
             'metrics': {'golden_match_rate': shared.rate(1, 30), 'api_error_rate': shared.rate(29, 30)}},
            {'eval': 'onboarding', 'ts': 't', 'git_sha': 'b', 'metrics': {'api_errors': shared.count(6, 6)}}]
    base = {'investigation': {'git_sha': 'a', 'metrics': {'golden_match_rate': 0.57}}}
    text, n = drift_report(rows, base, ran=['investigation'], failed={})
    assert 'Regressions (0)' in text and 'Invalid runs, not compared (2)' in text
    assert 'investigation: 29 API call(s) failed' in text and 'onboarding: 6 API call(s) failed' in text
    assert n == 2      # still a non-zero exit: nothing was actually checked
