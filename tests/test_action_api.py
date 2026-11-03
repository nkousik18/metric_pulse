"""
Tests for the Action Agent HTTP API (dashboard_api/action_views.py; scope F5, N4, D8; A6).

Requests go through Django's real URL routing, DRF and the real views, via DRF's APIClient. The
views build a real ActionAgent on tmp_path SQLite files: the agent factory is a Django setting,
swapped with override_settings, the same injection the other Action Agent tests use for their
executors and clock. Throttle counts live in Django's real local-memory cache, cleared per test.
No mocks, no network.
"""

import os
import sys
from functools import partial
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'metric_pulse_web.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings as dj_settings  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.test import override_settings  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from action_agent.graph import default_approver  # noqa: E402
from action_agent.runner import ActionAgent  # noqa: E402
from dashboard_api.action_views import default_agent_factory  # noqa: E402
from tests.test_action_graph import OWNERS, TOP_DRIVER, Clock, _proposer  # noqa: E402
from tests.test_action_policy import EVIDENCE  # noqa: E402

TOKEN = 'test-approver-token-0123456789'
AUTH = {'HTTP_AUTHORIZATION': f'Bearer {TOKEN}'}
SUPPRESS = {'days': 3, 'reason': 'Known holiday dip'}
NOTIFY = {'dimension': 'payment', 'segment': 'Credit Card'}


def _rates(**overrides):
    rates = {**dj_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'], **overrides}
    return {**dj_settings.REST_FRAMEWORK, 'DEFAULT_THROTTLE_RATES': rates}


@pytest.fixture
def api(tmp_path):
    """(client, propose, factory_calls). propose(action_type, params, date) makes a real
    proposal through the agent's graph; the API then sees it in the same tmp databases."""
    clock, opened, factory_calls = Clock(), [], []

    def make_agent(live=False, proposer_fn=None):
        agent = ActionAgent(actions_db=tmp_path / 'actions.db', checkpoints_db=tmp_path / 'cp.db',
                            owners=OWNERS, now_fn=clock, proposer_fn=proposer_fn,
                            outbox_dir=tmp_path / 'outbox', live=live)
        opened.append(agent)
        return agent

    def factory(live=False):
        factory_calls.append(live)
        return make_agent(live=live)

    def propose(action_type, params, date='2018-09-03'):
        agent = make_agent(proposer_fn=_proposer(action_type, params))
        started = agent.start(dataset_id='olist', metric='total_revenue', anomaly_date=date,
                              evidence=EVIDENCE, narrative_summary='Revenue fell.', top_driver=TOP_DRIVER)
        agent.store.close()
        agent._cp_conn.close()
        return started['proposal_id']

    cache.clear()
    with override_settings(ACTION_APPROVER_TOKEN=TOKEN, ACTION_AGENT_FACTORY=factory):
        yield APIClient(), propose, factory_calls
    cache.clear()
    for agent in opened:   # the views close theirs; closing twice is harmless for sqlite3
        agent.store.close()
        agent._cp_conn.close()


def _post(client, path, body=None, auth=AUTH):
    return client.post(path, body or {}, format='json', **auth)


# --- D8: the approver token ---

def test_every_endpoint_refuses_everything_when_no_token_is_configured(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    with override_settings(ACTION_APPROVER_TOKEN=None):
        assert client.get('/api/actions/pending/', **AUTH).status_code == 503
        assert client.get('/api/actions/log/', **AUTH).status_code == 503
        for verb in ('approve', 'edit', 'reject', 'undo'):
            assert _post(client, f'/api/actions/{pid}/{verb}/', {'reason': 'x'}).status_code == 503
    with override_settings(ACTION_APPROVER_TOKEN='too-short'):
        assert client.get('/api/actions/pending/', **AUTH).status_code == 503


def test_a_missing_or_wrong_token_is_refused_and_decides_nothing(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    assert client.get('/api/actions/pending/').status_code == 401
    assert client.get('/api/actions/pending/', HTTP_AUTHORIZATION=f'Token {TOKEN}').status_code == 401
    wrong = {'HTTP_AUTHORIZATION': 'Bearer ' + TOKEN[:-1] + 'X'}
    assert _post(client, f'/api/actions/{pid}/approve/', auth=wrong).status_code == 401
    pending = client.get('/api/actions/pending/', **AUTH)
    assert pending.status_code == 200
    assert [p['proposal_id'] for p in pending.json()['data']] == [pid]   # still undecided


# --- F5: pending, approve, reject, edit, log, undo ---

def test_pending_shows_the_dry_run_and_approve_executes_it(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    item = client.get('/api/actions/pending/', **AUTH).json()['data'][0]
    assert item['action_type'] == 'suppress_alerts'
    assert item['waiting_on']['dry_run']['payload']['days'] == 3
    assert item['rationale_citations']

    r = _post(client, f'/api/actions/{pid}/approve/', {'reason': 'holiday week'})
    assert r.status_code == 200 and r.json()['data']['status'] == 'executed'
    assert client.get('/api/actions/pending/', **AUTH).json()['data'] == []

    approved = [e for e in client.get(f'/api/actions/log/?proposal_id={pid}', **AUTH).json()['data']['events']
                if e['event'] == 'approved']
    assert approved and approved[0]['actor'] == default_approver()


def test_a_decided_proposal_cannot_be_decided_again(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    assert _post(client, f'/api/actions/{pid}/reject/', {'reason': 'not a holiday'}).json()['data']['status'] \
        == 'rejected'
    second = _post(client, f'/api/actions/{pid}/approve/')
    assert second.status_code == 409 and 'not awaiting a decision' in second.json()['message']


def test_reject_needs_a_reason_and_edit_needs_params(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    assert _post(client, f'/api/actions/{pid}/reject/').status_code == 400
    assert _post(client, f'/api/actions/{pid}/reject/', {'reason': '   '}).status_code == 400
    assert _post(client, f'/api/actions/{pid}/edit/', {'params': '{"days": 2}'}).status_code == 400
    assert _post(client, f'/api/actions/{pid}/approve/', {'reason': 5}).status_code == 400


def test_an_edit_goes_back_through_policy(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    bad = _post(client, f'/api/actions/{pid}/edit/', {'params': {'days': 30, 'reason': 'too long'}})
    assert bad.status_code == 200
    assert bad.json()['data']['status'] == 'awaiting_approval'
    assert bad.json()['data']['waiting_on']['policy_errors']
    good = _post(client, f'/api/actions/{pid}/edit/', {'params': {'days': 2, 'reason': 'shorter'}})
    assert good.json()['data']['status'] == 'executed'
    assert good.json()['data']['dry_run']['params']['days'] == 2


def test_unknown_and_malformed_ids_are_404(api):
    client, _, _ = api
    assert _post(client, '/api/actions/not-a-uuid/approve/').status_code == 404
    assert _post(client, '/api/actions/00000000-0000-0000-0000-000000000000/approve/').status_code == 404
    assert _post(client, '/api/actions/00000000-0000-0000-0000-000000000000/undo/',
                 {'reason': 'x'}).status_code == 404
    assert client.get('/api/actions/log/?proposal_id=abc', **AUTH).status_code == 400


def test_undo_writes_an_undone_row_with_a_trace_id_and_only_once(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    _post(client, f'/api/actions/{pid}/approve/')
    log = client.get('/api/actions/log/', **AUTH).json()['data']
    assert log['proposals'][0]['undoable'] is True

    assert _post(client, f'/api/actions/{pid}/undo/').status_code == 400          # needs a reason
    r = _post(client, f'/api/actions/{pid}/undo/', {'reason': 'wrong anomaly'})
    assert r.status_code == 200 and r.json()['data']['status'] == 'undone'
    undone = [e for e in client.get(f'/api/actions/log/?proposal_id={pid}', **AUTH).json()['data']['events']
              if e['event'] == 'undone']
    assert len(undone) == 1 and undone[0]['trace_id'] == r.json()['data']['trace_id']
    assert _post(client, f'/api/actions/{pid}/undo/', {'reason': 'again'}).status_code == 409


def test_an_irreversible_action_cannot_be_undone(api):
    client, propose, _ = api
    pid = propose('notify_owner', NOTIFY)
    assert _post(client, f'/api/actions/{pid}/approve/').json()['data']['status'] == 'executed'
    assert client.get('/api/actions/log/', **AUTH).json()['data']['proposals'][0]['undoable'] is False
    r = _post(client, f'/api/actions/{pid}/undo/', {'reason': 'oops'})
    assert r.status_code == 409 and 'not reversible' in r.json()['message']


def test_log_is_newest_first_and_limited(api):
    client, propose, _ = api
    propose('suppress_alerts', SUPPRESS, date='2018-09-03')
    propose('notify_owner', NOTIFY, date='2018-09-04')
    events = client.get('/api/actions/log/', **AUTH).json()['data']['events']
    assert [e['log_id'] for e in events] == sorted((e['log_id'] for e in events), reverse=True)
    assert len(client.get('/api/actions/log/?limit=1', **AUTH).json()['data']['events']) == 1


def test_live_is_on_only_for_a_json_true(api):
    client, propose, factory_calls = api
    a = propose('suppress_alerts', SUPPRESS, date='2018-09-03')
    b = propose('suppress_alerts', SUPPRESS, date='2018-09-04')
    factory_calls.clear()
    _post(client, f'/api/actions/{a}/approve/', {'live': 'true'})
    _post(client, f'/api/actions/{b}/approve/', {'live': True})
    assert factory_calls == [False, True]


def test_the_api_never_creates_actions_db(tmp_path):
    missing = tmp_path / 'actions.db'
    factory = partial(default_agent_factory, actions_db=missing, checkpoints_db=tmp_path / 'cp.db')
    cache.clear()
    with override_settings(ACTION_APPROVER_TOKEN=TOKEN, ACTION_AGENT_FACTORY=factory):
        client = APIClient()
        assert client.get('/api/actions/pending/', **AUTH).json()['data'] == []
        assert client.get('/api/actions/log/', **AUTH).json()['data'] == {'events': [], 'proposals': []}
        pid = '00000000-0000-0000-0000-000000000000'
        assert _post(client, f'/api/actions/{pid}/approve/').status_code == 404
    assert not missing.exists()
    assert not (tmp_path / 'cp.db').exists()


# --- N4: throttling ---

def test_wrong_tokens_count_toward_the_limit(api):
    client, _, _ = api
    with override_settings(REST_FRAMEWORK=_rates(actions_read='2/min')):
        wrong = {'HTTP_AUTHORIZATION': 'Bearer wrong-token-wrong-token'}
        assert client.get('/api/actions/pending/', **wrong).status_code == 401
        assert client.get('/api/actions/pending/', **wrong).status_code == 401
        # The right token doesn't reset the count: the third request is refused before the check.
        assert client.get('/api/actions/pending/', **AUTH).status_code == 429


def test_decisions_have_their_own_limit(api):
    client, propose, _ = api
    pid = propose('suppress_alerts', SUPPRESS)
    with override_settings(REST_FRAMEWORK=_rates(actions_decide='1/min')):
        assert _post(client, f'/api/actions/{pid}/reject/').status_code == 400   # counted
        assert _post(client, f'/api/actions/{pid}/approve/').status_code == 429
        assert client.get('/api/actions/pending/', **AUTH).status_code == 200    # reads unaffected


@pytest.mark.parametrize('path,scope', [('/api/investigate/', 'investigate'), ('/api/pipeline/', 'pipeline')])
def test_investigation_and_pipeline_endpoints_are_throttled(path, scope):
    # GET is not allowed on either view (405), but DRF counts the request before choosing the
    # handler, so this exercises the real throttle without running an investigation or pipeline.
    cache.clear()
    client = APIClient()
    with override_settings(REST_FRAMEWORK=_rates(**{scope: '2/min'})):
        assert [client.get(path).status_code for _ in range(3)] == [405, 405, 429]
    cache.clear()
