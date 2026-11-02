"""
Unit tests for actions.db invariants (docs/action-agent-scope.md D1, D5, §5):
append-only action_log triggers, one proposal per anomaly, one execution per
idempotency key. Real SQLite on pytest's tmp_path, no mocks.
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.store import ActionStore, DuplicateAnomalyError  # noqa: E402

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
PROPOSAL = {'action_type': 'notify_owner', 'params': {'dimension': 'd', 'segment': 's'},
            'rationale_citations': []}


@pytest.fixture
def store(tmp_path):
    s = ActionStore(tmp_path / 'actions.db')
    yield s
    s.close()


def _create(store, proposal_id='p1', anomaly_id='a1'):
    return store.create_proposal(
        proposal_id=proposal_id, anomaly_id=anomaly_id, dataset_id='ds', metric='m',
        anomaly_date='2012-12-30', proposal=PROPOSAL, evidence={'dimensions': {}}, narrative='n',
        proposer='test', trace_id=None, created_at=NOW, expires_at=NOW + timedelta(hours=24))


def test_action_log_rejects_update(store):
    _create(store)
    store.log('p1', 'proposed', 'test')
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        store._conn.execute("UPDATE action_log SET event = 'executed'")


def test_action_log_rejects_delete(store):
    _create(store)
    store.log('p1', 'proposed', 'test')
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        store._conn.execute('DELETE FROM action_log')
    assert len(store.events('p1')) == 1


def test_triggers_survive_reopen(tmp_path):
    path = tmp_path / 'actions.db'
    s = ActionStore(path)
    _create(s)
    s.log('p1', 'proposed', 'test')
    s.close()
    raw = sqlite3.connect(path)   # a plain connection, bypassing ActionStore entirely
    with pytest.raises(sqlite3.DatabaseError, match='append-only'):
        raw.execute('DELETE FROM action_log')
    raw.close()


def test_one_proposal_per_anomaly(store):
    _create(store, 'p1', 'a1')
    with pytest.raises(DuplicateAnomalyError):
        _create(store, 'p2', 'a1')
    assert store.find_by_anomaly('a1')['proposal_id'] == 'p1'


def test_one_executed_row_per_idempotency_key(store):
    _create(store)
    store.log('p1', 'executed', 'test', idempotency_key='k1')
    with pytest.raises(sqlite3.IntegrityError):
        store.log('p1', 'executed', 'test', idempotency_key='k1')
    store.log('p1', 'duplicate_skipped', 'test', idempotency_key='k1')   # other events may repeat


def test_status_is_latest_terminal_event(store):
    _create(store)
    assert store.status('p1') == 'pending'
    store.log('p1', 'proposed', 'test')
    store.log('p1', 'policy_passed', 'test')
    assert store.status('p1') == 'pending'
    store.log('p1', 'rejected', 'approver')
    assert store.status('p1') == 'rejected'


def test_has_approval_is_key_specific(store):
    _create(store)
    store.log('p1', 'approved', 'approver', idempotency_key='k1')
    assert store.has_approval('p1', 'k1')
    assert not store.has_approval('p1', 'k2')


def test_proposal_round_trips_evidence_snapshot(store):
    _create(store)
    p = store.get_proposal('p1')
    assert p['proposal'] == PROPOSAL and p['evidence'] == {'dimensions': {}}
    assert p['thread_id'] == 'p1'


def test_insert_effect_rejects_unknown_table(store):
    with pytest.raises(ValueError):
        store.insert_effect('proposals', {'x': 1})
