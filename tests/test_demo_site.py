"""
Tests for the static replay site (demo/; docs/hosting-scope.md §6.1-6.3, H1).

They run against the committed recordings in demo/recordings/ (real outputs, recorded by
`python -m demo.record`), so CI checks that the recordings answer every request the SPA can make
and that the site builds from them. The JavaScript side (demo/static/replay.js) runs under Node,
unmocked, on the same inputs as the Python side. No network, no LLM.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from demo import build as site  # noqa: E402
from demo.keys import request_key  # noqa: E402
from demo.record import (CASES, METRICS, METRICS_DAYS, THRESHOLDS, compare_deterministic,  # noqa: E402
                         edited_params)

ROOT = Path(__file__).parent.parent
REC = ROOT / 'demo' / 'recordings'
REPLAY_JS = ROOT / 'demo' / 'static' / 'replay.js'
NODE = shutil.which('node')
needs_node = pytest.mark.skipif(NODE is None, reason='node is not installed')


def _json(rel):
    return json.loads((REC / rel).read_text())


def _node(script: str, payload) -> object:
    """Run `script` under Node with `replay` = demo/static/replay.js and `input` = payload."""
    program = (f'const replay = require({json.dumps(str(REPLAY_JS))});\n'
               'const input = JSON.parse(require("fs").readFileSync(0, "utf8"));\n'
               f'{script}\n')
    out = subprocess.run([NODE, '-e', program], input=json.dumps(payload), capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout)


# --- request keys ---

KEY_CASES = [
    ('GET', '/api/metrics/?days=60', None),
    ('GET', '/api/anomalies/?threshold=2', None),
    ('GET', '/api/anomalies/?threshold=1.7000000000000002', None),
    ('GET', '/api/decomposition/', None),
    ('GET', '/api/narrative/?previous_date=2018-08-29&current_date=2018-09-03', None),
    ('POST', '/api/investigate/', {'metric': 'order_count', 'current_date': '2018-08-25', 'previous_date': '2018-08-24'}),
    ('POST', '/api/pipeline/', {'metric': 'total_revenue', 'force_alert': False, 'dry_run': True}),
]


def test_request_keys_normalize_the_threshold_and_sort_params():
    assert request_key('GET', '/api/anomalies/?threshold=2') == 'GET /api/anomalies/?threshold=2.0'
    assert (request_key('GET', '/api/narrative/?previous_date=b&current_date=a')
            == 'GET /api/narrative/?current_date=a&previous_date=b')
    assert (request_key('POST', '/api/pipeline/', {'metric': 'm', 'force_alert': True})
            == 'POST /api/pipeline/?force_alert=true&metric="m"')


@needs_node
def test_replay_js_builds_the_same_keys_as_python():
    js = _node('console.log(JSON.stringify(input.map(([m, u, b]) => replay.requestKey(m, u, b))));', KEY_CASES)
    assert js == [request_key(m, u, b) for m, u, b in KEY_CASES]


# --- the recordings answer every request the SPA makes ---

def test_every_index_entry_points_at_a_recorded_file():
    index = _json('index.json')
    assert index
    for key, entry in index.items():
        assert (REC / entry['file']).exists(), key


def test_the_recordings_cover_every_default_and_consecutive_request():
    index = _json('index.json')
    dates = [row['metric_date'] for row in _json(f'metrics/days-{METRICS_DAYS}.json')['data']]
    assert len(dates) == METRICS_DAYS
    expected = [request_key('GET', f'/api/metrics/?days={METRICS_DAYS}')]
    expected += [request_key('GET', f'/api/anomalies/?threshold={t}') for t in THRESHOLDS]
    for endpoint in ('decomposition', 'narrative'):
        expected.append(request_key('GET', f'/api/{endpoint}/'))
        expected += [request_key('GET', f'/api/{endpoint}/?current_date={c}&previous_date={p}')
                     for c, p in zip(dates, dates[1:])]
    expected += [request_key('POST', '/api/investigate/', {'metric': c['metric'], 'current_date': c['current_date'],
                                                          'previous_date': c['previous_date']}) for c in CASES]
    expected += [request_key('POST', '/api/pipeline/', {'metric': m, 'force_alert': f, 'dry_run': not f})
                 for m in METRICS for f in (False, True)]
    missing = [k for k in expected if k not in index]
    assert not missing


def test_recorded_investigations_are_real_runs_inside_the_dashboard_window():
    manifest = _json('manifest.json')
    dates = {row['metric_date'] for row in _json(f'metrics/days-{METRICS_DAYS}.json')['data']}
    assert [c['id'] for c in manifest['investigations']] == [c['id'] for c in CASES]
    for case in manifest['investigations']:
        assert {case['current_date'], case['previous_date']} <= dates
        assert case['status'] != 'failed'
    assert manifest['llm_calls']['count'] >= len(CASES)
    assert manifest['live_effects'] is False
    assert not manifest['git_sha'].endswith('-dirty')


def test_the_actions_walkthrough_is_approve_edit_reject_undo_with_live_off():
    flow = _json('actions/flow.json')
    assert [s['verb'] for s in flow['steps']] == ['approve', 'edit', 'reject', 'undo']
    assert all(s['body']['live'] is False for s in flow['steps'])
    assert all(s['response']['status'] == 200 for s in flow['steps'])
    pending = {p['proposal_id'] for p in flow['initial']['pending']['data']}
    assert {s['proposal_id'] for s in flow['steps']} <= pending
    assert flow['steps'][0]['proposal_id'] == flow['steps'][3]['proposal_id']   # undo reverses the approval
    assert flow['steps'][-1]['after']['pending']['data'] == []
    assert {v['status'] for v in flow['validation'].values()} == {400}


def test_the_recordings_publish_no_local_paths():
    for path in REC.rglob('*.json'):
        text = path.read_text()
        for marker in ('/Users/', '/private/', '/var/folders/', '/tmp/', 'kousiknandury'):
            assert marker not in text, f'{marker} in {path.relative_to(ROOT)}'


# --- the replay of the actions walk-through (Node) ---

@needs_node
def test_action_replay_refuses_out_of_order_live_and_unrecorded_steps_and_plays_the_recording():
    flow = _json('actions/flow.json')
    results = _node('''
        const r = replay.createActionReplay(input);
        const first = input.steps[0], second = input.steps[1];
        const out = {};
        out.outOfOrder = r.handle('POST', `/api/actions/${second.proposal_id}/${second.verb}/`, second.body);
        out.live = r.handle('POST', `/api/actions/${first.proposal_id}/approve/`, {...first.body, live: true});
        out.noReason = r.handle('POST', `/api/actions/${first.proposal_id}/reject/`, {reason: '', live: false});
        out.played = input.steps.map(s => r.handle('POST', `/api/actions/${s.proposal_id}/${s.verb}/`, s.body).status);
        out.pendingAfter = r.handle('GET', '/api/actions/pending/');
        out.finished = r.handle('POST', `/api/actions/${first.proposal_id}/approve/`, first.body);
        console.log(JSON.stringify(out));
    ''', flow)
    assert 'Next recorded step' in results['outOfOrder']['notRecorded']
    assert 'live effects off' in results['live']['notRecorded']
    assert results['noReason']['status'] == 400
    assert results['played'] == [200, 200, 200, 200]
    assert results['pendingAfter'] == flow['steps'][-1]['after']['pending']
    assert 'complete' in results['finished']['notRecorded']


# --- the build ---

def test_the_site_builds_from_the_recordings_with_replay_loaded_before_the_spa(tmp_path):
    out = site.build(REC, tmp_path / 'site')
    page = (out / 'index.html').read_text()
    assert page.index('<script src="replay.js"></script>') < page.index('// Tab switching')
    assert _json('manifest.json')['git_sha'] in page
    assert 'id="content-recorded"' in page and 'id="tab-recorded"' in page
    assert '{%' not in page and '{{' not in page
    assert (out / 'replay.js').exists() and (out / '.nojekyll').exists()
    assert (out / 'data' / 'index.json').read_text() == (REC / 'index.json').read_text()


def test_the_build_fails_loudly_when_an_anchor_moves():
    with pytest.raises(site.BuildError):
        site.insert_once('<html></html>', site.NAV_ANCHOR, 'x')


# --- recorder helpers ---

def test_q2_comparison_masks_only_the_narrative_generation_stamp(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    for root, stamp, value in ((a, '2026-11-12 10:00:00', 1), (b, '2026-11-13 11:11:11', 1)):
        (root / 'narrative').mkdir(parents=True)
        (root / 'narrative' / 'x.json').write_text(f'{{"full": "*Generated by MetricPulse at {stamp}*", "v": {value}}}')
    assert compare_deterministic(a, b) == []
    (b / 'narrative' / 'x.json').write_text('{"full": "*Generated by MetricPulse at 2026-11-13 11:11:11*", "v": 2}')
    assert compare_deterministic(a, b) == ['narrative/x.json: differs']


def test_edited_params_stay_inside_the_policy_limits():
    assert edited_params('suppress_alerts', {'days': 7, 'reason': 'x'})['days'] == 6
    assert edited_params('suppress_alerts', {'days': 3, 'reason': 'x'})['days'] == 4
    assert edited_params('create_control', {'expires_in_days': 28})['expires_in_days'] == 21
    assert edited_params('open_incident', {'severity': 'high'})['severity'] == 'medium'
    assert edited_params('notify_owner', {'dimension': 'd', 'segment': 's'}) is None
