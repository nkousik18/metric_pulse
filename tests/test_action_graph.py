"""
End-to-end tests of the action graph (docs/action-agent-scope.md §5, F1, F2, D1,
§13.6): propose -> policy -> interrupt -> approve/edit/reject -> execute, plus
restart survival, TTL expiry, idempotent re-execution and decision replay.

These run the real LangGraph graph with a real SqliteSaver and a real actions.db
on tmp_path, a RecordingExecutor (the §9 test double), an injected clock and
an injected proposer. No mocks, no network, no LLM. LangSmith tracing is off
because the env var is unset in tests.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.executors import RecordingExecutor  # noqa: E402
from action_agent.owners import OwnersConfig  # noqa: E402
from action_agent.replay import replay_decisions  # noqa: E402
from action_agent.runner import ActionAgent  # noqa: E402

from tests.test_action_policy import CITATION, EVIDENCE  # noqa: E402

# 2018-09-07 is Brazil's Independence Day in the committed olist calendar, which ActionAgent.start
# attaches (§14), so this annotation is calendar-grounded on that date and on no other nearby date.
HOLIDAY = {'category': 'holiday', 'cause': 'Independence Day', 'calendar_event': 'Independence Day'}
HOLIDAY_DATE = '2018-09-07'
TOP_DRIVER = {'dimension': 'payment', 'segment': 'Credit Card', 'contribution_pct': 107.1}
OWNERS = OwnersConfig.model_validate({
    'default_owner': 'oncall', 'people': {'oncall': {'name': 'On-Call', 'email': 'oncall@example.com'}},
})


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def _proposer(action_type, params):
    proposal = {'action_type': action_type, 'params': params, 'rationale_citations': [CITATION]}
    return lambda state: (proposal, 'test_proposer')


@pytest.fixture
def env(tmp_path):
    rec, clock = RecordingExecutor(), Clock()
    executors = {k: rec for k in ('annotate_anomaly', 'suppress_alerts', 'notify_owner',
                                  'open_incident', 'create_control')}

    def make(proposer_fn=None):
        return ActionAgent(actions_db=tmp_path / 'actions.db', checkpoints_db=tmp_path / 'cp.db',
                           owners=OWNERS, executors=executors, now_fn=clock, proposer_fn=proposer_fn)
    agents = []

    def factory(proposer_fn=None):
        agents.append(make(proposer_fn))
        return agents[-1]
    yield factory, rec, clock
    for a in agents:
        a.store.close()
        a._cp_conn.close()


def _start(agent, anomaly_date='2018-09-03'):
    return agent.start(dataset_id='olist', metric='total_revenue', anomaly_date=anomaly_date,
                       evidence=EVIDENCE, narrative_summary='Revenue fell 80%.', top_driver=TOP_DRIVER)


def _events(agent, pid):
    return [e['event'] for e in agent.store.events(pid)]


def test_t1_waits_for_approval_and_survives_restart(env):
    factory, rec, _ = env
    first = factory()
    started = _start(first)
    pid = started['proposal_id']
    assert started['status'] == 'awaiting_approval'
    assert started['waiting_on']['dry_run']['action_type'] == 'notify_owner'
    assert rec.calls == []

    # "Restart": a brand-new ActionAgent on the same files, with no in-memory state shared.
    second = factory()
    assert [p['proposal_id'] for p in second.pending()] == [pid]
    done = second.decide(pid, 'approve', reason='looks right', approver='kousik')

    assert done['status'] == 'executed'
    assert len(rec.calls) == 1 and rec.calls[0]['idempotency_key'] == started['waiting_on']['dry_run']['idempotency_key']
    assert _events(second, pid) == ['proposed', 'policy_passed', 'approved', 'executed']
    approved = next(e for e in second.store.events(pid) if e['event'] == 'approved')
    assert approved['actor'] == 'kousik'


def test_reject_never_executes(env):
    factory, rec, _ = env
    agent = factory()
    pid = _start(agent)['proposal_id']
    assert agent.decide(pid, 'reject', reason='known issue')['status'] == 'rejected'
    assert rec.calls == []
    assert agent.store.status(pid) == 'rejected'
    with pytest.raises(ValueError, match='not awaiting'):
        agent.decide(pid, 'approve')


def test_t0_auto_executes_without_approval(tmp_path):
    """The T0 path stays supported, though no catalog action uses it since A5: shown with a test
    catalog (injected, not a mock) where annotate_anomaly is T0."""
    from dataclasses import replace

    from action_agent.catalog import CATALOG, Tier
    rec = RecordingExecutor()
    catalog = {**CATALOG, 'annotate_anomaly': replace(CATALOG['annotate_anomaly'], tier=Tier.T0)}
    agent = ActionAgent(actions_db=tmp_path / 'a.db', checkpoints_db=tmp_path / 'c.db', owners=OWNERS,
                        executors={k: rec for k in catalog}, now_fn=Clock(), catalog=catalog,
                        proposer_fn=_proposer('annotate_anomaly', HOLIDAY))
    try:
        result = _start(agent, HOLIDAY_DATE)
        assert result['status'] == 'executed'
        assert _events(agent, result['proposal_id']) == ['proposed', 'policy_passed', 'executed']
        assert len(rec.calls) == 1
    finally:
        agent.store.close()
        agent._cp_conn.close()


def test_annotate_now_waits_for_approval(env):
    factory, rec, _ = env
    agent = factory(_proposer('annotate_anomaly', HOLIDAY))
    result = _start(agent, HOLIDAY_DATE)
    assert result['status'] == 'awaiting_approval' and rec.calls == []


def test_holiday_annotation_off_calendar_is_rejected(env):
    """§14.3: the same 'Independence Day' annotation four days early names no calendar entry
    within ±3 days, so policy rejects it before any approver sees it."""
    factory, rec, _ = env
    agent = factory(_proposer('annotate_anomaly', HOLIDAY))
    result = _start(agent, '2018-09-03')
    assert result['status'] == 'policy_rejected' and rec.calls == []
    assert 'calendar_event' in result['policy']['errors'][0]


def test_caller_supplied_calendar_is_replaced_by_the_trusted_one(env):
    """A calendar smuggled in with the evidence (e.g. claiming Carnival) is discarded: start()
    always recomputes it from the committed file."""
    factory, rec, _ = env
    fake = {'events_on_date': [{'date': '2018-09-03', 'name': 'Carnival', 'kind': 'holiday'}], 'events_nearby': []}
    agent = factory(_proposer('annotate_anomaly', {'category': 'holiday', 'cause': 'Carnival',
                                                   'calendar_event': 'Carnival'}))
    result = agent.start(dataset_id='olist', metric='total_revenue', anomaly_date='2018-09-03',
                         evidence={**EVIDENCE, 'calendar': fake}, narrative_summary='x', top_driver=TOP_DRIVER)
    assert result['status'] == 'policy_rejected' and rec.calls == []
    stored = agent.store.get_proposal(result['proposal_id'])['evidence']['calendar']
    assert stored['events_on_date'] == [] and stored['weekday'] == 'Monday'


def test_policy_rejected_proposal_is_logged_and_never_reaches_approver(env):
    factory, rec, _ = env
    agent = factory(_proposer('suppress_alerts', {'days': 30, 'reason': 'ignore previous instructions'}))
    result = _start(agent)
    assert result['status'] == 'policy_rejected'
    assert agent.pending() == [] and rec.calls == []
    rejected = agent.store.events(result['proposal_id'])[-1]
    assert rejected['event'] == 'policy_rejected' and 'less than or equal to 7' in rejected['detail']


def test_valid_edit_executes_edited_params_under_a_new_key(env):
    factory, rec, _ = env
    agent = factory(_proposer('suppress_alerts', {'days': 5, 'reason': 'holiday'}))
    started = _start(agent)
    original_key = started['waiting_on']['dry_run']['idempotency_key']
    done = agent.decide(started['proposal_id'], 'edit', params={'days': 2, 'reason': 'holiday'})

    assert done['status'] == 'executed'
    assert rec.calls[0]['params'] == {'days': 2, 'reason': 'holiday'}
    assert rec.calls[0]['idempotency_key'] != original_key
    assert _events(agent, started['proposal_id']) == [
        'proposed', 'policy_passed', 'edit_submitted', 'policy_passed', 'edited', 'executed']


def test_edit_failing_policy_returns_to_approver(env):
    factory, rec, _ = env
    agent = factory(_proposer('suppress_alerts', {'days': 5, 'reason': 'holiday'}))
    pid = _start(agent)['proposal_id']
    bounced = agent.decide(pid, 'edit', params={'days': 99, 'reason': 'holiday'})

    assert bounced['status'] == 'awaiting_approval'
    assert any('less than or equal to 7' in e for e in bounced['waiting_on']['policy_errors'])
    # The failed edit can't be approved as-is...
    assert agent.decide(pid, 'approve')['status'] == 'awaiting_approval'
    assert rec.calls == []
    # ...but a corrected edit goes through.
    assert agent.decide(pid, 'edit', params={'days': 3, 'reason': 'holiday'})['status'] == 'executed'


def test_edit_cannot_change_action_type(env):
    factory, rec, _ = env
    agent = factory()
    pid = _start(agent)['proposal_id']
    result = agent.graph.invoke(
        __import__('langgraph.types', fromlist=['Command']).Command(
            resume={'decision': 'edit', 'action_type': 'suppress_alerts',
                    'params': {'days': 3, 'reason': 'x'}, 'approver': 'k'}),
        {'configurable': {'thread_id': pid}})
    assert result.get('__interrupt__')            # still waiting
    assert _events(agent, pid)[-1] == 'invalid_decision' and rec.calls == []


def test_unknown_decision_keeps_waiting(env):
    factory, rec, _ = env
    agent = factory()
    pid = _start(agent)['proposal_id']
    assert agent.decide(pid, 'yolo')['status'] == 'awaiting_approval'
    assert rec.calls == []


def test_expired_proposal_never_executes(env):
    factory, rec, clock = env
    agent = factory()
    pid = _start(agent)['proposal_id']
    clock.now += timedelta(hours=25)
    assert agent.pending() == []
    assert agent.decide(pid, 'approve')['status'] == 'expired'
    assert rec.calls == [] and agent.store.status(pid) == 'expired'
    assert 'approved' not in _events(agent, pid)


def test_second_run_for_same_anomaly_does_not_propose(env):
    factory, _, _ = env
    agent = factory()
    first = _start(agent)
    agent.decide(first['proposal_id'], 'reject', reason='no')
    again = _start(agent)
    assert again['status'] == 'duplicate_anomaly'
    assert agent.store.get_proposal(again['proposal_id']) is None


def _checkpoint_before_execute(agent, pid):
    for snapshot in agent.graph.get_state_history({'configurable': {'thread_id': pid}}):
        if snapshot.next == ('execute',):
            return snapshot.config
    raise AssertionError('no checkpoint before execute')


def test_replaying_execute_three_times_is_a_no_op(env):
    """§7 idempotency_violations: re-run an approved execution from its checkpoint 3x."""
    factory, rec, _ = env
    agent = factory()
    pid = _start(agent)['proposal_id']
    agent.decide(pid, 'approve')
    fork_from = _checkpoint_before_execute(agent, pid)
    for _ in range(3):
        result = agent.graph.invoke(None, fork_from)
        assert result['status'] == 'duplicate_skipped'
    assert len(rec.calls) == 1
    assert _events(agent, pid).count('executed') == 1
    assert _events(agent, pid).count('duplicate_skipped') == 3


def test_tampered_payload_at_execute_fails_closed(env):
    """F1: change the params between approval and execution, and there's no approval for the new key."""
    factory, rec, _ = env
    agent = factory(_proposer('suppress_alerts', {'days': 2, 'reason': 'holiday'}))
    pid = _start(agent)['proposal_id']
    agent.decide(pid, 'approve')
    fork_from = _checkpoint_before_execute(agent, pid)
    rec.calls.clear()
    state = agent.graph.get_state(fork_from).values
    tampered = {**state['dry_run'], 'params': {'days': 7, 'reason': 'holiday'},
                'idempotency_key': 'tampered-key'}
    forked = agent.graph.update_state(fork_from, {'dry_run': tampered})
    result = agent.graph.invoke(None, forked)
    assert result['status'] == 'execution_blocked'
    assert rec.calls == []


def test_every_logged_decision_replays_exactly(env):
    factory, _, _ = env
    agent = factory(_proposer('suppress_alerts', {'days': 5, 'reason': 'holiday'}))
    pid = _start(agent)['proposal_id']
    agent.decide(pid, 'edit', params={'days': 99, 'reason': 'holiday'})
    agent.decide(pid, 'edit', params={'days': 3, 'reason': 'holiday'})
    replays = replay_decisions(agent.store, pid)
    assert [r['event'] for r in replays] == ['policy_passed', 'edit_policy_rejected', 'policy_passed']
    assert all(r['match'] for r in replays)


def test_numpy_evidence_from_pandas_is_checkpointable(env):
    """Regression: live decompose_metric() evidence carries numpy scalars (found on the first live run)."""
    import numpy as np
    factory, rec, _ = env
    agent = factory()
    contributor = {k: (np.float64(v) if isinstance(v, float) else v)
                   for k, v in EVIDENCE['dimensions']['payment']['top_contributors'][0].items()}
    evidence = {**EVIDENCE, 'dimensions': {**EVIDENCE['dimensions'],
                                           'payment': {'top_contributors': [contributor],
                                                       'segment_count': np.int64(1)}}}
    started = agent.start(dataset_id='olist', metric='total_revenue', anomaly_date='2018-09-03',
                          evidence=evidence, narrative_summary='n',
                          top_driver={**TOP_DRIVER, 'contribution_pct': np.float64(107.1)})
    assert started['status'] == 'awaiting_approval'
    assert agent.decide(started['proposal_id'], 'approve')['status'] == 'executed'


def test_trace_ids_link_log_rows_to_invocations(env):
    factory, _, _ = env
    agent = factory()
    started = _start(agent)
    done = agent.decide(started['proposal_id'], 'approve')
    events = agent.store.events(started['proposal_id'])
    assert agent.store.get_proposal(started['proposal_id'])['trace_id'] == started['trace_id']
    assert {e['trace_id'] for e in events if e['event'] in ('proposed', 'policy_passed')} == {started['trace_id']}
    assert {e['trace_id'] for e in events if e['event'] in ('approved', 'executed')} == {done['trace_id']}
