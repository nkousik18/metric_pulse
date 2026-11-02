"""
The action graph (docs/action-agent-scope.md §5):

    START -> check_existing -> propose -> register -> policy
          policy -> {execute (T0, or an approver's edit that passed),
                     await_approval (T1, or an edit that failed policy),
                     record (rejected)}
          await_approval (interrupt) -> {execute (approved), policy (edited),
                                         record (rejected / expired)}
          execute -> record -> END

It is a separate graph run after the Phase 1 investigation finishes, not
nodes added to the Phase 1 graph. That keeps the Phase 1 graph and its
no-checkpointer compile path byte-for-byte unchanged (§5). This graph is
compiled with a SqliteSaver, so a pending approval survives a restart.

Each node writes its own action_log row as it acts, rather than one final
`record` node writing everything. A crash between executing and recording
must not let a replay execute twice. `record` only settles the final status.

`await_approval` re-runs from its first line when resumed (LangGraph
semantics), so nothing before `interrupt()` has side effects. The only
exception is the expiry check, which ends the run without interrupting.
"""

import getpass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Mapping, Optional, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from action_agent.catalog import CATALOG, Tier
from action_agent.dry_run import ActionContext, build_dry_run
from action_agent.executors import Executor
from action_agent.identity import anomaly_id as make_anomaly_id
from action_agent.owners import OwnersConfig
from action_agent.policy import REJECTED, policy_check
from action_agent.proposer import FALLBACK_PROPOSER, fallback_proposal
from action_agent.schemas import ActionProposal
from action_agent.store import ActionStore, DuplicateAnomalyError
from config import settings
from config.logging_config import setup_logger
from observability.tracing import post_feedback

logger = setup_logger(__name__)

SYSTEM_ACTOR = 'action_agent'
DECISIONS = ('approve', 'reject', 'edit')


class ActionState(TypedDict, total=False):
    # --- inputs ---
    proposal_id: str          # also the checkpointer thread_id
    trace_id: Optional[str]   # root run id of the *current* invocation (start or resume)
    dataset_id: str
    metric: str
    anomaly_date: str
    evidence: Dict            # decompose_metric()'s return shape, snapshotted into proposals
    narrative_summary: str
    top_driver: Optional[Dict]

    # --- working state ---
    anomaly_id: str
    proposal: Optional[Dict]
    proposer: str
    proposer_trail: Optional[Dict]   # LLM proposer only: attempts, escalation, tokens (A3)
    policy: Optional[Dict]
    dry_run: Optional[Dict]
    edited: bool
    decision: Optional[Dict]
    execution: Optional[Dict]

    # --- control ---
    status: str
    error: Optional[str]


def default_approver() -> str:
    return settings.ACTION_APPROVER or getpass.getuser()


def build_action_graph(
    store: ActionStore,
    checkpointer,
    owners: OwnersConfig,
    executors: Mapping[str, Executor],
    targets: Optional[Dict] = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ttl_hours: float = settings.PROPOSAL_TTL_HOURS,
    proposer_fn: Optional[Callable[[Dict], Tuple[Optional[Dict], str]]] = None,
):
    """Dependencies are injected (store, executors, clock, proposer) so tests use
    real SQLite on tmp_path and a RecordingExecutor. No mocks.

    proposer_fn(state) -> (proposal dict or None, proposer name[, trail dict]). It defaults to the
    deterministic fallback. The LLM proposer (llm_proposer.make_llm_proposer) also returns a trail
    of its attempts, whose `summary` line is stored on the `proposed` log row."""

    def _ctx(state: ActionState) -> ActionContext:
        return ActionContext(state['dataset_id'], state['metric'], state['anomaly_date'],
                             state['evidence'], state['narrative_summary'])

    def check_existing(state: ActionState) -> Dict:
        aid = make_anomaly_id(state['dataset_id'], state['metric'], state['anomaly_date'])
        existing = store.find_by_anomaly(aid)
        if existing:
            return {'anomaly_id': aid, 'status': 'duplicate_anomaly',
                    'error': f"anomaly already has proposal {existing['proposal_id']} (D1)"}
        return {'anomaly_id': aid, 'status': 'running', 'edited': False}

    def _default_proposer(state: Dict) -> Tuple[Optional[Dict], str]:
        return fallback_proposal(state['evidence'], state.get('top_driver')), FALLBACK_PROPOSER

    make_proposal = proposer_fn or _default_proposer

    def propose(state: ActionState) -> Dict:
        out = make_proposal(state)
        proposal, proposer = out[0], out[1]
        trail = out[2] if len(out) > 2 else None
        if proposal is None:
            return {'status': 'no_proposal', 'error': 'no top driver to act on', 'proposer_trail': trail}
        return {'proposal': proposal, 'proposer': proposer, 'proposer_trail': trail}

    def register(state: ActionState) -> Dict:
        now = now_fn()
        try:
            store.create_proposal(
                proposal_id=state['proposal_id'], anomaly_id=state['anomaly_id'],
                dataset_id=state['dataset_id'], metric=state['metric'],
                anomaly_date=state['anomaly_date'], proposal=state['proposal'],
                evidence=state['evidence'], narrative=state['narrative_summary'],
                proposer=state['proposer'], trace_id=state.get('trace_id'),
                created_at=now, expires_at=now + timedelta(hours=ttl_hours),
            )
        except DuplicateAnomalyError:
            return {'status': 'duplicate_anomaly', 'error': 'anomaly already has a proposal (D1)'}
        store.log(state['proposal_id'], 'proposed', state['proposer'],
                  action_type=state['proposal']['action_type'], params=state['proposal']['params'],
                  detail=(state.get('proposer_trail') or {}).get('summary'),
                  trace_id=state.get('trace_id'), now=now)
        return {}

    def policy(state: ActionState) -> Dict:
        result = policy_check(state['proposal'], state['evidence'])
        edited = state.get('edited', False)
        pid, trace = state['proposal_id'], state.get('trace_id')

        if not result.allowed:
            event = 'edit_policy_rejected' if edited else 'policy_rejected'
            store.log(pid, event, SYSTEM_ACTOR, action_type=result.action_type,
                      params=state['proposal'].get('params'), policy=result.to_dict(),
                      detail='; '.join(result.errors), trace_id=trace, now=now_fn())
            return {'policy': result.to_dict(), 'dry_run': state.get('dry_run') if edited else None}

        dry_run = build_dry_run(ActionProposal.model_validate(state['proposal']), result, _ctx(state),
                                owners, targets=targets, now=now_fn())
        store.log(pid, 'policy_passed', SYSTEM_ACTOR, action_type=result.action_type,
                  params=result.params, idempotency_key=dry_run['idempotency_key'],
                  policy=result.to_dict(), payload=dry_run['payload'], trace_id=trace, now=now_fn())
        if edited:
            # The approver authored these params and policy passed them. Recording that as an
            # approval of exactly this idempotency key is what lets execute() pass F1.
            approver = (state.get('decision') or {}).get('approver') or default_approver()
            store.log(pid, 'edited', approver, action_type=result.action_type, params=result.params,
                      idempotency_key=dry_run['idempotency_key'], trace_id=trace, now=now_fn())
        return {'policy': result.to_dict(), 'dry_run': dry_run}

    def route_after_policy(state: ActionState) -> str:
        if state['policy']['decision'] == REJECTED:
            return 'await_approval' if state.get('edited') else 'record'
        if state.get('edited') or state['policy']['tier'] == Tier.T0.value:
            return 'execute'
        return 'await_approval'

    def await_approval(state: ActionState) -> Dict:
        pid = state['proposal_id']
        proposal_row = store.get_proposal(pid)
        if now_fn() > datetime.fromisoformat(proposal_row['expires_at']):
            store.log(pid, 'expired', SYSTEM_ACTOR, detail=f'no decision within {ttl_hours:g}h (F2)',
                      trace_id=state.get('trace_id'), now=now_fn())
            return {'status': 'expired', 'decision': None}

        decision = interrupt({
            'proposal_id': pid,
            'dry_run': state.get('dry_run'),
            'policy_errors': state['policy']['errors'] if state['policy']['decision'] == REJECTED else [],
            'expires_at': proposal_row['expires_at'],
        })

        # --- resumed: everything below runs once, with the approver's decision ---
        decision = dict(decision or {})
        kind = decision.get('decision')
        approver = decision.get('approver') or default_approver()
        reason = decision.get('reason')
        trace = state.get('trace_id')
        first_trace = proposal_row.get('trace_id')
        dry_run = state.get('dry_run') or {}

        if kind not in DECISIONS:
            store.log(pid, 'invalid_decision', approver, detail=f'unknown decision {kind!r}',
                      trace_id=trace, now=now_fn())
            return {'decision': None}

        if kind == 'reject':
            store.log(pid, 'rejected', approver, action_type=dry_run.get('action_type'),
                      idempotency_key=dry_run.get('idempotency_key'), detail=reason,
                      trace_id=trace, now=now_fn())
            post_feedback(first_trace, 'approval', value='reject', score=0, comment=reason)
            return {'decision': decision, 'status': 'rejected'}

        if kind == 'approve':
            if state['policy']['decision'] == REJECTED:   # an edit failed policy; nothing to approve
                store.log(pid, 'invalid_decision', approver,
                          detail='approve refused: the current params failed policy; edit or reject',
                          trace_id=trace, now=now_fn())
                return {'decision': None}
            store.log(pid, 'approved', approver, action_type=dry_run['action_type'],
                      params=dry_run['params'], idempotency_key=dry_run['idempotency_key'],
                      detail=reason, trace_id=trace, now=now_fn())
            post_feedback(first_trace, 'approval', value='approve', score=1, comment=reason)
            return {'decision': decision}

        # kind == 'edit': params only. A different action_type is a different proposal (decision log).
        new_params = decision.get('params')
        changes_type = decision.get('action_type') not in (None, state['proposal']['action_type'])
        if not isinstance(new_params, dict) or changes_type:
            store.log(pid, 'invalid_decision', approver,
                      detail='edit must supply params (a dict) and cannot change action_type',
                      trace_id=trace, now=now_fn())
            return {'decision': None}
        store.log(pid, 'edit_submitted', approver, action_type=state['proposal']['action_type'],
                  params=new_params, detail=reason, trace_id=trace, now=now_fn())
        post_feedback(first_trace, 'approval', value='edit', score=0.5, comment=reason,
                      correction={'params': new_params})
        return {'decision': decision, 'edited': True,
                'proposal': {**state['proposal'], 'params': new_params}}

    def route_after_approval(state: ActionState) -> str:
        decision = state.get('decision')
        if state.get('status') in ('expired', 'rejected'):
            return 'record'
        if decision is None:                      # invalid decision: ask again
            return 'await_approval'
        return 'policy' if decision['decision'] == 'edit' else 'execute'

    def execute(state: ActionState) -> Dict:
        pid, trace, dry_run = state['proposal_id'], state.get('trace_id'), state['dry_run']
        key, action_type = dry_run['idempotency_key'], dry_run['action_type']

        # F1: fail closed. T1 needs an approval row for exactly this key.
        if CATALOG[action_type].tier != Tier.T0 and not store.has_approval(pid, key):
            store.log(pid, 'execution_blocked', SYSTEM_ACTOR, action_type=action_type,
                      idempotency_key=key, detail='no approval record for this key (F1)',
                      trace_id=trace, now=now_fn())
            return {'status': 'execution_blocked'}

        prior = store.execution_for_key(key)
        if prior:
            store.log(pid, 'duplicate_skipped', SYSTEM_ACTOR, action_type=action_type, idempotency_key=key,
                      external_id=prior['external_id'], detail=f"already executed (log {prior['log_id']})",
                      trace_id=trace, now=now_fn())
            return {'status': 'duplicate_skipped', 'execution': {'outcome': 'duplicate', **prior}}

        try:
            result = executors[action_type].execute(dry_run)
        except Exception as e:
            logger.error(f'executor failed for {action_type} ({pid}): {e}')
            store.log(pid, 'execution_failed', SYSTEM_ACTOR, action_type=action_type,
                      detail=str(e), trace_id=trace, now=now_fn())
            return {'status': 'execution_failed', 'error': str(e)}

        store.log(pid, 'executed', SYSTEM_ACTOR, action_type=action_type, params=dry_run['params'],
                  idempotency_key=key, payload=dry_run['payload'], external_id=result.get('external_id'),
                  detail=result.get('outcome'), trace_id=trace, now=now_fn())
        return {'status': 'executed', 'execution': result}

    def record(state: ActionState) -> Dict:
        if state.get('status') in ('duplicate_anomaly', 'no_proposal'):
            return {}
        return {'status': store.status(state['proposal_id'])}

    def route_after_check(state: ActionState) -> str:
        return 'record' if state.get('status') == 'duplicate_anomaly' else 'propose'

    def route_after_propose(state: ActionState) -> str:
        return 'record' if state.get('status') == 'no_proposal' else 'register'

    def route_after_register(state: ActionState) -> str:
        return 'record' if state.get('status') == 'duplicate_anomaly' else 'policy'

    graph = StateGraph(ActionState)
    for name, fn in [('check_existing', check_existing), ('propose', propose), ('register', register),
                     ('policy', policy), ('await_approval', await_approval), ('execute', execute),
                     ('record', record)]:
        graph.add_node(name, fn)

    graph.add_edge(START, 'check_existing')
    graph.add_conditional_edges('check_existing', route_after_check, ['propose', 'record'])
    graph.add_conditional_edges('propose', route_after_propose, ['register', 'record'])
    graph.add_conditional_edges('register', route_after_register, ['policy', 'record'])
    graph.add_conditional_edges('policy', route_after_policy, ['execute', 'await_approval', 'record'])
    graph.add_conditional_edges('await_approval', route_after_approval,
                                ['policy', 'execute', 'await_approval', 'record'])
    graph.add_edge('execute', 'record')
    graph.add_edge('record', END)
    return graph.compile(checkpointer=checkpointer)
