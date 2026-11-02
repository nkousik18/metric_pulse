"""
Tests for A4's undo (F3) and the pipeline hooks (action_agent/hooks.py: D3 suppression, D4/F4
watch evaluation), end to end through a real ActionAgent on tmp_path SQLite files, the real
executors, and a real outbox directory. The warehouse lookup is injected as a plain function of
(dimension, dates) -> {segment: value}. No mocks.
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.evidence import require_decomposable  # noqa: E402
from action_agent.hooks import evaluate_controls, pipeline_suppression, watch_breached  # noqa: E402
from action_agent.runner import ActionAgent  # noqa: E402
from tests.test_action_graph import OWNERS, TOP_DRIVER, Clock, _proposer  # noqa: E402
from tests.test_action_policy import EVIDENCE  # noqa: E402

DATE = '2018-09-03'


@pytest.fixture
def world(tmp_path):
    clock, agents = Clock(), []

    def agent(proposer_fn=None):
        a = ActionAgent(actions_db=tmp_path / 'actions.db', checkpoints_db=tmp_path / 'cp.db', owners=OWNERS,
                        now_fn=clock, proposer_fn=proposer_fn, outbox_dir=tmp_path / 'outbox')
        agents.append(a)
        return a

    yield agent, clock, tmp_path
    for a in agents:
        a.store.close()
        a._cp_conn.close()


def _approve(make_agent, action_type, params):
    agent = make_agent(_proposer(action_type, params))
    started = agent.start(dataset_id='olist', metric='total_revenue', anomaly_date=DATE, evidence=EVIDENCE,
                          narrative_summary='Revenue fell.', top_driver=TOP_DRIVER)
    pid = started['proposal_id']
    if started['status'] == 'awaiting_approval':
        assert agent.decide(pid, 'approve', reason='ok')['status'] == 'executed'
    return agent, pid


def _outbox(tmp_path):
    index = tmp_path / 'outbox' / 'index.jsonl'
    return [json.loads(line) for line in index.read_text().splitlines()] if index.exists() else []


SUPPRESS = {'days': 3, 'reason': 'Known holiday dip'}
CONTROL = {'dimension': 'payment', 'segment': 'Credit Card', 'direction': 'below',
           'threshold': 500.0, 'expires_in_days': 14}


# --- D3: suppression ---

def test_an_approved_suppression_suppresses_the_pipeline_alert(world):
    make_agent, clock, tmp_path = world
    _approve(make_agent, 'suppress_alerts', SUPPRESS)
    found = pipeline_suppression('olist', 'total_revenue', DATE, actions_db=tmp_path / 'actions.db', now=clock())
    assert found['reason'] == 'Known holiday dip'
    # Another date or metric is a different anomaly (D1), so it isn't suppressed.
    assert pipeline_suppression('olist', 'total_revenue', '2018-09-04', actions_db=tmp_path / 'actions.db',
                                now=clock()) is None
    assert pipeline_suppression('olist', 'order_count', DATE, actions_db=tmp_path / 'actions.db', now=clock()) is None


def test_a_suppression_ends_when_it_expires(world):
    make_agent, clock, tmp_path = world
    _approve(make_agent, 'suppress_alerts', SUPPRESS)
    later = clock() + timedelta(days=3, minutes=1)
    assert pipeline_suppression('olist', 'total_revenue', DATE, actions_db=tmp_path / 'actions.db', now=later) is None


def test_no_actions_db_means_nothing_is_suppressed(tmp_path):
    assert pipeline_suppression('olist', 'total_revenue', DATE, actions_db=tmp_path / 'absent.db') is None
    assert evaluate_controls('olist', 'total_revenue', DATE, '2018-08-29',
                             actions_db=tmp_path / 'absent.db')['status'] == 'no_action_store'
    assert not (tmp_path / 'absent.db').exists()     # a check must not create the database


# --- F3: undo ---

def test_undo_lifts_a_suppression_with_a_compensating_log_row(world):
    make_agent, clock, tmp_path = world
    agent, pid = _approve(make_agent, 'suppress_alerts', SUPPRESS)
    result = agent.undo(pid, reason='Not a holiday after all', approver='kousik')
    assert result['status'] == 'undone' and result['outcome'] == 'effect_lifted'
    assert pipeline_suppression('olist', 'total_revenue', DATE, actions_db=tmp_path / 'actions.db',
                                now=clock()) is None
    undone = agent.store.events(pid)[-1]
    assert (undone['event'], undone['actor'], undone['detail']) == (
        'undone', 'kousik', 'Not a holiday after all (effect_lifted)')
    assert agent.store.status(pid) == 'undone'
    assert len(agent.store.effects('suppressions')) == 1     # the effect row itself is never edited


def test_undo_twice_is_refused(world):
    make_agent, _, _ = world
    agent, pid = _approve(make_agent, 'suppress_alerts', SUPPRESS)
    agent.undo(pid, reason='r')
    with pytest.raises(ValueError, match='nothing to undo'):
        agent.undo(pid, reason='again')


def test_notify_owner_cannot_be_undone(world):
    make_agent, _, _ = world
    agent, pid = _approve(make_agent, 'notify_owner', {'dimension': 'payment', 'segment': 'Credit Card'})
    with pytest.raises(ValueError, match='not reversible'):
        agent.undo(pid, reason='r')


def test_undo_needs_a_reason_and_an_executed_action(world):
    make_agent, _, _ = world
    agent, pid = _approve(make_agent, 'suppress_alerts', SUPPRESS)
    with pytest.raises(ValueError, match='reason'):
        agent.undo(pid, reason='  ')
    waiting = make_agent(_proposer('notify_owner', {'dimension': 'payment', 'segment': 'Credit Card'}))
    pending = waiting.start(dataset_id='olist', metric='total_revenue', anomaly_date='2018-09-10',
                            evidence=EVIDENCE, narrative_summary='x', top_driver=TOP_DRIVER)
    with pytest.raises(ValueError, match='nothing to undo'):
        waiting.undo(pending['proposal_id'], reason='r')


def test_notify_owner_now_really_writes_the_owner_message(world):
    make_agent, _, tmp_path = world
    agent, pid = _approve(make_agent, 'notify_owner', {'dimension': 'payment', 'segment': 'Credit Card'})
    executed = agent.store.executed_row(pid)
    assert executed['detail'] == 'sent' and executed['external_id'].startswith('outbox:')
    [message] = _outbox(tmp_path)
    assert message['recipient'] == 'On-Call <oncall@example.com>'
    assert message['metadata']['idempotency_key'] == executed['idempotency_key']


# --- D4 / F4: watches ---

def _evaluate(tmp_path, clock, values, date=DATE, send=True):
    return evaluate_controls('olist', 'total_revenue', date, '2018-08-29', segment_values=lambda d, c, p: values,
                             actions_db=tmp_path / 'actions.db', owners=OWNERS, outbox_dir=tmp_path / 'outbox',
                             send=send, now=clock())


@pytest.mark.parametrize('direction,value,breached', [
    ('below', 499.99, True), ('below', 500.0, False), ('above', 500.01, True), ('above', 500.0, False)])
def test_watch_threshold_is_strict(direction, value, breached):
    assert watch_breached({'direction': direction, 'threshold': 500.0}, value) is breached


def test_a_breach_alerts_the_owner_once_per_day_and_is_logged(world):
    make_agent, clock, tmp_path = world
    agent, pid = _approve(make_agent, 'create_control', CONTROL)
    first = _evaluate(tmp_path, clock, {'Credit Card': 150.0})
    assert first['evaluated'] == 1 and first['alerts_sent'] == 1 and first['breaches'][0]['alert'] == 'sent'
    second = _evaluate(tmp_path, clock, {'Credit Card': 150.0})
    assert second['alerts_sent'] == 0 and second['breaches'][0]['alert'] == 'already_sent_today'
    messages = [m for m in _outbox(tmp_path) if m['metadata'].get('action') == 'control_breach']
    assert len(messages) == 1 and messages[0]['recipient'] == 'On-Call <oncall@example.com>'
    body = (tmp_path / 'outbox' / messages[0]['path']).read_text()
    assert f'cli undo {pid[:8]}' in body
    breach_rows = [e for e in agent.store.events(pid) if e['event'] == 'control_breached']
    assert len(breach_rows) == 1 and 'Credit Card total_revenue = 150.00' in breach_rows[0]['detail']
    assert agent.store.status(pid) == 'executed'      # a breach isn't a status change


def test_a_new_day_alerts_again(world):
    make_agent, clock, tmp_path = world
    _approve(make_agent, 'create_control', CONTROL)
    _evaluate(tmp_path, clock, {'Credit Card': 150.0}, date=DATE)
    assert _evaluate(tmp_path, clock, {'Credit Card': 150.0}, date='2018-09-04')['alerts_sent'] == 1


def test_no_breach_no_alert(world):
    make_agent, clock, tmp_path = world
    _approve(make_agent, 'create_control', CONTROL)
    result = _evaluate(tmp_path, clock, {'Credit Card': 900.0})
    assert result['evaluated'] == 1 and result['breaches'] == [] and _outbox(tmp_path) == []


def test_a_segment_with_no_rows_that_day_counts_as_zero(world):
    make_agent, clock, tmp_path = world
    _approve(make_agent, 'create_control', CONTROL)
    assert _evaluate(tmp_path, clock, {'Boleto': 10.0})['breaches'][0]['value'] == 0.0


def test_dry_run_reports_the_breach_but_sends_nothing(world):
    make_agent, clock, tmp_path = world
    agent, pid = _approve(make_agent, 'create_control', CONTROL)
    result = _evaluate(tmp_path, clock, {'Credit Card': 150.0}, send=False)
    assert result['breaches'][0]['alert'] == 'dry_run' and _outbox(tmp_path) == []
    assert not any(e['event'] == 'control_breached' for e in agent.store.events(pid))


def test_an_undone_watch_is_not_evaluated(world):
    make_agent, clock, tmp_path = world
    agent, pid = _approve(make_agent, 'create_control', CONTROL)
    agent.undo(pid, reason='watch no longer needed')
    assert _evaluate(tmp_path, clock, {'Credit Card': 150.0})['evaluated'] == 0


def test_an_expired_watch_is_not_evaluated(world):
    make_agent, clock, tmp_path = world
    _approve(make_agent, 'create_control', CONTROL)     # expires in 14 days
    clock.now = clock() + timedelta(days=15)
    assert _evaluate(tmp_path, clock, {'Credit Card': 150.0})['evaluated'] == 0


def test_a_metric_no_dimension_carries_is_refused_clearly():
    evidence = {'dimensions': {'payment': {'error': 'Binder Error: column customer_count not found'},
                               'product': {'error': 'Binder Error: column customer_count not found'}}}
    with pytest.raises(ValueError, match="olist/customer_count can't be decomposed"):
        require_decomposable(evidence, 'olist', 'customer_count')
    require_decomposable(EVIDENCE, 'olist', 'total_revenue')     # decomposable: no error
