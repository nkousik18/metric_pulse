"""
Dry-run payload builder (docs/action-agent-scope.md §5, `await_approval`).

Turns a policy-approved proposal into exactly what execution would do: the
target, the payload, and the idempotency key. This is what the approver sees
before approving, and (A2+) what the executor runs -- so the approver approves
the real payload, not a description of it.

Every message body here is built deterministically from evidence already in
state (narrative + decomposition numbers). The LLM's only free text that
reaches a payload is the short, length-capped `cause`/`reason`/`title` params.
Untrusted data values (segment names) are escaped for the Markdown table they
land in, and never interpreted.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from action_agent.catalog import CATALOG
from action_agent.identity import anomaly_id as make_anomaly_id
from action_agent.identity import idempotency_key
from action_agent.owners import OwnersConfig, resolve_owner
from action_agent.policy import PolicyResult
from action_agent.schemas import ActionProposal


@dataclass(frozen=True)
class ActionContext:
    dataset_id: str
    metric: str
    anomaly_date: str
    evidence: Dict                     # decompose_metric()'s return shape
    narrative_summary: str             # generate_narrative()'s deterministic summary

    @property
    def anomaly_id(self) -> str:
        return make_anomaly_id(self.dataset_id, self.metric, self.anomaly_date)


def _md_cell(value) -> str:
    return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def evidence_table(evidence: Dict, dimension: str, highlight: Optional[str] = None) -> str:
    rows: List[str] = [
        '| Segment | Previous | Current | Change | Contribution |',
        '|---|---:|---:|---:|---:|',
    ]
    for c in evidence.get('dimensions', {}).get(dimension, {}).get('top_contributors', []):
        name = _md_cell(c.get('segment'))
        if highlight is not None and c.get('segment') == highlight:
            name = f'**{name}**'
        rows.append(
            f"| {name} | {float(c.get('previous_value') or 0):,.2f} | "
            f"{float(c.get('current_value') or 0):,.2f} | {float(c.get('change') or 0):+,.2f} | "
            f"{float(c.get('contribution_pct') or 0):+.1f}% |"
        )
    return '\n'.join(rows)


def _citations_block(proposal: ActionProposal) -> str:
    return '\n'.join(
        f"- {_md_cell(c.dimension)} / {_md_cell(c.segment)} ({c.source}): {_md_cell(c.claim)}"
        for c in proposal.rationale_citations
    )


def _message_body(ctx: ActionContext, proposal: ActionProposal, dimension: str, segment: str) -> str:
    return '\n\n'.join([
        ctx.narrative_summary,
        f"Evidence -- {_md_cell(dimension)}:\n\n{evidence_table(ctx.evidence, dimension, segment)}",
        f"Cited evidence:\n{_citations_block(proposal)}",
        f"Anomaly: {ctx.dataset_id} / {ctx.metric} / {ctx.anomaly_date} (id {ctx.anomaly_id[:12]})",
    ])


def build_dry_run(
    proposal: ActionProposal,
    policy: PolicyResult,
    ctx: ActionContext,
    owners: OwnersConfig,
    targets: Optional[Dict] = None,
    now: Optional[datetime] = None,
) -> Dict:
    """
    targets: live executor destinations, e.g. {'github_repo': ..., 'sns_topic_arn': ...}.
             Unset in A1 (configured with the live executors in A4); shown as None.
    now:     injectable clock so expiry timestamps are deterministic in tests.
    """
    if not policy.allowed:
        raise ValueError(f"no dry-run for a proposal policy rejected: {policy.errors}")

    targets = targets or {}
    now = now or datetime.now(timezone.utc)
    params = policy.params
    action_type = policy.action_type
    spec = CATALOG[action_type]
    aid = ctx.anomaly_id

    if action_type == 'annotate_anomaly':
        target = {'kind': 'annotation', 'store': 'actions.db:annotations'}
        payload = {'anomaly_id': aid, **params}

    elif action_type == 'suppress_alerts':
        target = {'kind': 'suppression', 'store': 'actions.db:suppressions'}
        payload = {
            'anomaly_id': aid, 'days': params['days'], 'reason': params['reason'],
            'expires_at': (now + timedelta(days=params['days'])).isoformat(),
        }

    elif action_type == 'notify_owner':
        owner = resolve_owner(owners, ctx.dataset_id, params['dimension'], params['segment'])
        target = {'kind': 'sns_email', 'owner': owner, 'topic_arn': targets.get('sns_topic_arn')}
        payload = {
            'subject': f"[MetricPulse] {ctx.metric} anomaly on {ctx.anomaly_date}: "
                       f"{params['segment']} ({params['dimension']})"[:100],
            'body': _message_body(ctx, proposal, params['dimension'], params['segment']),
        }

    elif action_type == 'open_incident':
        target = {'kind': 'github_issue', 'repo': targets.get('github_repo')}
        payload = {
            'title': params['title'],
            'labels': ['metricpulse', f"severity:{params['severity']}"],
            'body': _message_body(ctx, proposal, params['dimension'], params['segment']),
        }

    elif action_type == 'create_control':
        owner = resolve_owner(owners, ctx.dataset_id, params['dimension'], params['segment'])
        target = {'kind': 'control', 'store': 'actions.db:controls'}
        payload = {
            'dataset_id': ctx.dataset_id, 'metric': ctx.metric,
            'dimension': params['dimension'], 'segment': params['segment'],
            'direction': params['direction'], 'threshold': params['threshold'],
            'owner': owner['id'],
            'expires_at': (now + timedelta(days=params['expires_in_days'])).isoformat(),
        }

    else:  # unreachable while CATALOG and this builder agree
        raise ValueError(f"no dry-run builder for action '{action_type}'")

    return {
        'anomaly_id': aid,
        'action_type': action_type,
        'tier': spec.tier.value,
        'decision': policy.decision,
        'reversible': spec.reversible,
        'params': params,
        'idempotency_key': idempotency_key(aid, action_type, params),
        'target': target,
        'payload': payload,
    }


def render_dry_run(dry_run: Dict) -> str:
    """Plain-text view of a dry run for the CLI approver (A2)."""
    lines = [
        f"Action:    {dry_run['action_type']} ({dry_run['tier']}, {dry_run['decision']})",
        f"Anomaly:   {dry_run['anomaly_id'][:12]}",
        f"Reversible:{' yes' if dry_run['reversible'] else ' no'}",
        f"Key:       {dry_run['idempotency_key'][:12]}",
        f"Target:    {dry_run['target']}",
        'Payload:',
    ]
    for k, v in dry_run['payload'].items():
        text = str(v)
        lines.append(f"  {k}:" + ('\n    ' + text.replace('\n', '\n    ') if '\n' in text else f" {text}"))
    return '\n'.join(lines)
