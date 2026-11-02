"""
Executors: the only code that has an effect (docs/action-agent-scope.md §5, §9).

Each executor takes a dry run (build_dry_run's output, which is exactly what the
approver saw) and performs it. Idempotency and F1 approval checks happen in the
graph's `execute` node before an executor is ever called. Executors don't
decide anything.

As of A2:
- annotate_anomaly / suppress_alerts / create_control write their local effect
  tables in actions.db. Reading those tables during pipeline runs (D3
  suppression, D4 control evaluation) is A4.
- notify_owner / open_incident are *simulated*: the dry-run payload is
  recorded, nothing is sent. The live SNS/GitHub executors arrive in A4 behind
  `--live`.
"""

from typing import Dict, List, Protocol

from action_agent.store import ActionStore


class Executor(Protocol):
    def execute(self, dry_run: Dict) -> Dict:
        """Returns {'outcome': 'applied' | 'simulated', 'external_id': str | None}."""
        ...


class LocalStoreExecutor:
    def __init__(self, store: ActionStore):
        self.store = store

    def execute(self, dry_run: Dict) -> Dict:
        action_type, payload, key = dry_run['action_type'], dry_run['payload'], dry_run['idempotency_key']
        if action_type == 'annotate_anomaly':
            table = 'annotations'
            row = {'anomaly_id': payload['anomaly_id'], 'category': payload['category'],
                   'cause': payload['cause']}
        elif action_type == 'suppress_alerts':
            table = 'suppressions'
            row = {'anomaly_id': payload['anomaly_id'], 'reason': payload['reason'],
                   'expires_at': payload['expires_at']}
        elif action_type == 'create_control':
            table = 'controls'
            row = {k: payload[k] for k in ('dataset_id', 'metric', 'dimension', 'segment',
                                           'direction', 'threshold', 'owner', 'expires_at')}
        else:
            raise ValueError(f'LocalStoreExecutor cannot run {action_type}')
        rowid = self.store.insert_effect(table, {**row, 'idempotency_key': key})
        return {'outcome': 'applied', 'external_id': f'{table}:{rowid}'}


class SimulatedExecutor:
    """Stand-in for the live SNS/GitHub executors until A4. It sends nothing."""

    def execute(self, dry_run: Dict) -> Dict:
        return {'outcome': 'simulated', 'external_id': None}


class RecordingExecutor:
    """Test double from §9's risk table: records each call and has no side effects."""

    def __init__(self):
        self.calls: List[Dict] = []

    def execute(self, dry_run: Dict) -> Dict:
        self.calls.append(dry_run)
        return {'outcome': 'recorded', 'external_id': f"recorded:{len(self.calls)}"}


def default_executors(store: ActionStore) -> Dict[str, Executor]:
    local = LocalStoreExecutor(store)
    simulated = SimulatedExecutor()
    return {
        'annotate_anomaly': local,
        'suppress_alerts': local,
        'create_control': local,
        'notify_owner': simulated,
        'open_incident': simulated,
    }
