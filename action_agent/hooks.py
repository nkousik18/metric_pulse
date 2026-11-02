"""
What local pipeline runs read from the Action Agent (docs/action-agent-scope.md D3, D4, F4, A4).

- D3 `pipeline_suppression()`: is this anomaly's pipeline alert suppressed? An approved
  suppress_alerts that hasn't expired or been undone means no repeat alert for that anomaly
  (anomaly_id = dataset, metric, date; D1).
- D4 `evaluate_controls()`: every active create_control watch for the dataset and metric being
  run is checked against that date's real segment value (the full per-dimension query, not the
  decomposition's top 5). A breach alerts the watch's owner once per watch per day (a UNIQUE
  constraint in actions.db) and writes a `control_breached` row on the proposal that created it.

Both are off when ACTION_PIPELINE_HOOKS is false (the default inside Lambda, which has no
actions.db and stays unchanged, D9), and both do nothing when actions.db doesn't exist yet.
Callers wrap them in the pipeline's never-raise convention.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.identity import anomaly_id as make_anomaly_id  # noqa: E402
from action_agent.store import ActionStore  # noqa: E402
from config import settings  # noqa: E402
from config.logging_config import setup_logger  # noqa: E402

logger = setup_logger(__name__)

SYSTEM_ACTOR = 'action_agent'


def _store(actions_db) -> Optional[ActionStore]:
    if not settings.ACTION_PIPELINE_HOOKS:
        return None
    path = Path(actions_db or settings.ACTIONS_DB_PATH)
    return ActionStore(path) if path.exists() else None


def pipeline_suppression(dataset_id: str, metric: str, anomaly_date: str, *, actions_db=None,
                         now: Optional[datetime] = None) -> Optional[Dict]:
    """The active suppression for this anomaly, or None."""
    store = _store(actions_db)
    if store is None:
        return None
    try:
        return store.active_suppression(make_anomaly_id(dataset_id, metric, anomaly_date), now)
    finally:
        store.close()


def watch_breached(control: Dict, value: float) -> bool:
    """D4: the threshold is an absolute value of the segment's daily metric."""
    if control['direction'] == 'above':
        return value > control['threshold']
    return value < control['threshold']


def segment_values_from_warehouse(metric: str, dimension_config=None, connection_factory=None
                                  ) -> Callable[[str, str, str], Dict[str, float]]:
    """{segment: current_value} for one dimension, from the same query decompose_metric runs,
    but every segment (decompose_metric keeps only the top 5)."""
    from config.db import get_connection
    from decomposition.decomposer import DIMENSION_TABLES, fetch_dimension_metrics

    def values(dimension: str, current_date: str, previous_date: str) -> Dict[str, float]:
        df = fetch_dimension_metrics(dimension, current_date, previous_date, metric,
                                     dimension_config or DIMENSION_TABLES, connection_factory or get_connection)
        return {str(row['segment']): float(row['current_value'] or 0) for _, row in df.iterrows()}
    return values


def _breach_message(control: Dict, value: float, metric_date: str, proposal_id: Optional[str]) -> Dict:
    verb = 'rose above' if control['direction'] == 'above' else 'fell below'
    subject = (f"[MetricPulse] Watch breached: {control['segment']} ({control['dimension']}) "
               f"{control['metric']} {verb} {control['threshold']:,.2f} on {metric_date}")[:100]
    body = '\n'.join([
        f"{control['segment']} ({control['dimension']}) {control['metric']} was {value:,.2f} on "
        f"{metric_date}, which {verb} the watch threshold of {control['threshold']:,.2f}.",
        '',
        f"Watch #{control['control_id']} on {control['dataset_id']}, created by an approved "
        f"create_control, expires {control['expires_at'][:10]}.",
        f"To stop this watch: python -m action_agent.cli undo {(proposal_id or '<proposal_id>')[:8]} --reason ...",
    ])
    return {'subject': subject, 'body': body}


def evaluate_controls(dataset_id: str, metric: str, current_date: str, previous_date: str, *,
                      segment_values: Optional[Callable[[str, str, str], Dict[str, float]]] = None,
                      dimension_config=None, connection_factory=None, send: bool = True,
                      actions_db=None, owners=None, outbox_dir=None,
                      now: Optional[datetime] = None) -> Dict:
    """Evaluate every active watch for (dataset_id, metric) on current_date.

    send=False (the pipeline's --dry-run) reports breaches without alerting or logging.
    Returns {'status', 'evaluated', 'breaches': [...], 'alerts_sent'}."""
    store = _store(actions_db)
    if store is None:
        return {'status': 'disabled' if not settings.ACTION_PIPELINE_HOOKS else 'no_action_store',
                'evaluated': 0, 'breaches': [], 'alerts_sent': 0}
    now = now or datetime.now(timezone.utc)
    try:
        controls = store.active_controls(dataset_id, metric, now)
        if not controls:
            return {'status': 'ok', 'evaluated': 0, 'breaches': [], 'alerts_sent': 0}
        values_fn = segment_values or segment_values_from_warehouse(metric, dimension_config, connection_factory)
        cache: Dict[str, Dict[str, float]] = {}
        breaches, sent = [], 0
        for control in controls:
            dim = control['dimension']
            if dim not in cache:
                cache[dim] = values_fn(dim, current_date, previous_date)
            value = cache[dim].get(control['segment'], 0.0)   # no rows that day = 0
            if not watch_breached(control, value):
                continue
            entry = {'control_id': control['control_id'], 'dimension': dim, 'segment': control['segment'],
                     'direction': control['direction'], 'threshold': control['threshold'], 'value': value}
            if not send:
                breaches.append({**entry, 'alert': 'dry_run'})
                continue
            if store.control_alerted(control['control_id'], current_date):
                breaches.append({**entry, 'alert': 'already_sent_today'})
                continue
            entry['alert'] = _alert_owner(store, control, value, current_date, owners, outbox_dir, now)
            sent += entry['alert'] == 'sent'
            breaches.append(entry)
        return {'status': 'ok', 'evaluated': len(controls), 'breaches': breaches, 'alerts_sent': sent}
    finally:
        store.close()


def _alert_owner(store: ActionStore, control: Dict, value: float, metric_date: str, owners,
                 outbox_dir, now: datetime) -> str:
    from action_agent.executors import owner_recipient
    from action_agent.owners import load_owners
    from alerting.notifier import send_alert

    owners = owners or load_owners()
    person = owners.people.get(control['owner'])
    owner = {'id': control['owner'], **(person.model_dump() if person else {})}
    proposal_id = store.proposal_for_key(control['idempotency_key'])
    message = _breach_message(control, value, metric_date, proposal_id)
    result = send_alert(message['subject'], message['body'], recipient=owner_recipient(owner),
                        outbox_dir=outbox_dir,
                        metadata={'action': 'control_breach', 'control_id': control['control_id'],
                                  'idempotency_key': control['idempotency_key'], 'metric_date': metric_date,
                                  'value': value})
    if result.get('status') != 'sent':
        logger.warning(f"control #{control['control_id']} breach alert not sent: {result}")
        return result.get('status') or 'error'
    message_id = f"{result.get('channel')}:{result.get('message_id')}"
    store.record_control_alert(control['control_id'], metric_date, value, message_id, now)
    if proposal_id:
        store.log(proposal_id, 'control_breached', SYSTEM_ACTOR, action_type='create_control',
                  idempotency_key=None, external_id=message_id,
                  detail=f"{control['segment']} {control['metric']} = {value:,.2f} on {metric_date} "
                         f"({control['direction']} {control['threshold']:,.2f})", now=now)
    return 'sent'
