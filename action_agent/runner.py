"""
ActionAgent: the runtime around the action graph. It wires the store, the
SqliteSaver checkpointer, the executors and LangSmith run config, and exposes
the operations the CLI (and, in A6, the API) need: start, decide, undo, inspect.

Every start and every decide is its own LangGraph invocation and so its own
LangSmith trace. Each trace's root run id is stamped on the action_log rows it
writes, which links log rows to traces. The first trace's id is also stored on
the proposal (§13.2).
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from action_agent.catalog import CATALOG
from action_agent.executors import default_executors
from action_agent.graph import build_action_graph, default_approver
from action_agent.owners import OwnersConfig, load_owners
from action_agent.store import ActionStore
from config import settings
from observability.tracing import flush, new_run_id, run_config


def to_plain(value):
    """Round-trip through JSON so evidence holds only plain Python types.

    decompose_metric() builds its rows with pandas' to_dict('records'), so live
    evidence carries numpy scalars (numpy.float64/int64). The checkpointer's
    msgpack serializer rejects them, as found on the first live A2 run. Normalizing
    once here also makes the stored evidence snapshot identical to what the graph saw.
    """
    def default(obj):
        if hasattr(obj, 'item'):          # numpy scalar
            return obj.item()
        if hasattr(obj, 'tolist'):        # numpy array
            return obj.tolist()
        return str(obj)
    return json.loads(json.dumps(value, default=default))


class ActionAgent:
    def __init__(
        self,
        actions_db=None,
        checkpoints_db=None,
        owners: Optional[OwnersConfig] = None,
        executors: Optional[Dict] = None,
        targets: Optional[Dict] = None,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        ttl_hours: float = settings.PROPOSAL_TTL_HOURS,
        proposer_fn=None,
        live: bool = False,
        outbox_dir=None,
        catalog=None,
    ):
        """live: allow effects outside this machine (a real GitHub issue, a non-outbox notifier
        channel). Off by default; the CLI's --live turns it on (§9)."""
        self.now_fn = now_fn
        self.store = ActionStore(actions_db or settings.ACTIONS_DB_PATH)
        if executors is None:
            executors = default_executors(self.store, live=live, outbox_dir=outbox_dir)
        self.executors = executors
        if targets is None:
            targets = {'alert_channel': settings.ALERT_CHANNEL, 'github_repo': settings.ACTION_GITHUB_REPO}
        self._cp_conn = sqlite3.connect(str(checkpoints_db or settings.CHECKPOINTS_DB_PATH),
                                        check_same_thread=False)
        self.checkpointer = SqliteSaver(self._cp_conn)
        self.graph = build_action_graph(
            self.store, self.checkpointer, owners or load_owners(),
            self.executors,
            targets=targets, now_fn=now_fn, ttl_hours=ttl_hours, proposer_fn=proposer_fn,
            catalog=catalog if catalog is not None else CATALOG,
        )

    def close(self) -> None:
        flush()
        self.store.close()
        self._cp_conn.close()

    # --- operations ---

    def start(self, *, dataset_id: str, metric: str, anomaly_date: str, evidence: Dict,
              narrative_summary: str, top_driver: Optional[Dict]) -> Dict:
        proposal_id, run_id = str(uuid.uuid4()), new_run_id()
        config = run_config(
            run_name='action_agent.start', run_id=run_id, thread_id=proposal_id,
            metadata={'proposal_id': proposal_id, 'dataset_id': dataset_id, 'metric': metric,
                      'anomaly_date': anomaly_date},
            tags=['action_agent', 'start'],
        )
        result = self.graph.invoke({
            'proposal_id': proposal_id, 'trace_id': str(run_id), 'dataset_id': dataset_id,
            'metric': metric, 'anomaly_date': anomaly_date, 'evidence': to_plain(evidence),
            'narrative_summary': narrative_summary, 'top_driver': to_plain(top_driver),
        }, config)
        return self._summarize(proposal_id, result, run_id)

    def decide(self, proposal_id: str, decision: str, *, params: Optional[Dict] = None,
               reason: Optional[str] = None, approver: Optional[str] = None) -> Dict:
        if not self.is_waiting(proposal_id):
            raise ValueError(f'proposal {proposal_id} is not awaiting a decision '
                             f'(status: {self.store.status(proposal_id)})')
        run_id = new_run_id()
        proposal = self.store.get_proposal(proposal_id)
        config = run_config(
            run_name=f'action_agent.{decision}', run_id=run_id, thread_id=proposal_id,
            metadata={'proposal_id': proposal_id, 'anomaly_id': proposal['anomaly_id'],
                      'dataset_id': proposal['dataset_id'], 'metric': proposal['metric'],
                      'decision': decision},
            tags=['action_agent', 'decision'],
        )
        payload = {'decision': decision, 'params': params, 'reason': reason,
                   'approver': approver or default_approver()}
        result = self.graph.invoke(Command(resume=payload, update={'trace_id': str(run_id)}), config)
        return self._summarize(proposal_id, result, run_id)

    def undo(self, proposal_id: str, *, reason: str, approver: Optional[str] = None) -> Dict:
        """F3: reverse an executed, reversible action with a compensating `undone` log row.

        Local effects (annotation, suppression, control) stop applying because the active-effect
        queries exclude undone keys; the effect rows themselves are never edited. An opened GitHub
        issue is closed (needs live). notify_owner can't be undone: a sent message stays sent."""
        status = self.store.status(proposal_id)
        if status != 'executed':
            raise ValueError(f'proposal {proposal_id} has nothing to undo (status: {status})')
        row = self.store.executed_row(proposal_id)
        action_type = row['action_type']
        if not CATALOG[action_type].reversible:
            raise ValueError(f'{action_type} is not reversible')
        if not reason or not reason.strip():
            raise ValueError('an undo needs a reason')
        outcome = 'effect_lifted'
        executor = self.executors.get(action_type)
        if hasattr(executor, 'undo'):
            outcome = executor.undo(row['external_id'], reason)['outcome']
        self.store.log(proposal_id, 'undone', approver or default_approver(), action_type=action_type,
                       params=row['params'], idempotency_key=row['idempotency_key'],
                       external_id=row['external_id'], detail=f'{reason.strip()} ({outcome})',
                       now=self.now_fn())
        return {'proposal_id': proposal_id, 'status': 'undone', 'outcome': outcome,
                'action_type': action_type, 'external_id': row['external_id']}

    def is_waiting(self, proposal_id: str) -> bool:
        state = self.graph.get_state({'configurable': {'thread_id': proposal_id}})
        return bool(state.next) and 'await_approval' in state.next

    def waiting_on(self, proposal_id: str) -> Optional[Dict]:
        """The interrupt payload (dry run, policy errors, expiry) the approver should see."""
        state = self.graph.get_state({'configurable': {'thread_id': proposal_id}})
        return state.interrupts[0].value if state.interrupts else None

    def pending(self) -> List[Dict]:
        """Proposals awaiting a decision and still inside their TTL. One past its TTL is
        expired in effect; the `expired` row is written when someone next tries to decide it."""
        now = self.now_fn()
        return [p for p in self.store.pending_proposals()
                if self.is_waiting(p['proposal_id']) and now <= datetime.fromisoformat(p['expires_at'])]

    def _summarize(self, proposal_id: str, result: Dict, run_id) -> Dict:
        interrupts = result.get('__interrupt__') or []
        return {
            'proposal_id': proposal_id,
            'status': 'awaiting_approval' if interrupts else result.get('status'),
            'error': result.get('error'),
            'dry_run': result.get('dry_run'),
            'policy': result.get('policy'),
            'execution': result.get('execution'),
            'waiting_on': interrupts[0].value if interrupts else None,
            'trace_id': str(run_id),
        }
