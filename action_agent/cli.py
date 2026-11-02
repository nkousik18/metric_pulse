"""
CLI approver for the Action Agent (docs/action-agent-scope.md §5, §10.1: CLI only).

    python -m action_agent.cli propose --dataset-id superstore_sales --metric sales
    python -m action_agent.cli pending
    python -m action_agent.cli show <proposal_id>
    python -m action_agent.cli approve <proposal_id> [--reason ...]
    python -m action_agent.cli reject  <proposal_id> --reason ...
    python -m action_agent.cli edit    <proposal_id> --params '{"days": 2, "reason": "..."}'
    python -m action_agent.cli log     [<proposal_id>]
    python -m action_agent.cli replay  <proposal_id>
    python -m action_agent.cli undo    <proposal_id> --reason ... [--live]

`propose` builds the latest anomaly's evidence and feeds it to the action graph: for an
onboarded dataset via its detect -> decompose -> narrate cycle (onboarding.investigate.run_cycle),
and for `--dataset-id olist` via action_agent.evidence (the local warehouse since local-stack L1).

`--live` (approve / edit / undo) allows effects outside this machine: a real GitHub issue for
open_incident, or a non-outbox notifier channel. Without it those are simulated (§9).
Proposal ids can be abbreviated to any unique prefix.

Approver identity is ACTION_APPROVER, falling back to the OS user (decision log).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.dry_run import render_dry_run  # noqa: E402
from action_agent.replay import replay_decisions  # noqa: E402
from action_agent.runner import ActionAgent  # noqa: E402
from observability.tracing import tracing_enabled, trace_url  # noqa: E402


def _resolve(agent: ActionAgent, prefix: str) -> str:
    rows = agent.store._conn.execute(
        'SELECT proposal_id FROM proposals WHERE proposal_id LIKE ?', (prefix + '%',)).fetchall()
    if len(rows) != 1:
        sys.exit(f"'{prefix}' matches {len(rows)} proposals; give more of the id")
    return rows[0]['proposal_id']


def _print_result(result: dict) -> None:
    print(f"proposal {result['proposal_id']}: {result['status']}")
    if result.get('error'):
        print(f"  error: {result['error']}")
    waiting = result.get('waiting_on')
    if waiting:
        for err in waiting.get('policy_errors') or []:
            print(f"  policy rejected the last edit: {err}")
        if waiting.get('dry_run'):
            print('\n' + render_dry_run(waiting['dry_run']))
        print(f"\n  expires {waiting['expires_at']}. Decide with approve / edit / reject.")
    elif result.get('execution'):
        print(f"  execution: {result['execution']}")
    elif result.get('policy') and result['policy'].get('errors'):
        print(f"  policy: {result['policy']['errors']}")
    _print_trace(result.get('trace_id'))


def _print_trace(trace_id) -> None:
    if not tracing_enabled():
        print('  trace: tracing off (set LANGSMITH_TRACING=true)')
        return
    print(f"  trace: {trace_url(trace_id) or trace_id}")


def cmd_propose(agent: ActionAgent, args) -> None:
    from action_agent.identity import OLIST_DATASET_ID
    if args.dataset_id == OLIST_DATASET_ID:
        from action_agent.evidence import build_case
        try:
            case = build_case(args.dataset_id, args.metric)
        except ValueError as e:
            sys.exit(str(e))
        _print_result(agent.start(**case))
        return
    from onboarding.investigate import run_cycle
    cycle = run_cycle(args.dataset_id, args.metric)
    result = agent.start(
        dataset_id=args.dataset_id, metric=args.metric, anomaly_date=cycle['current_date'],
        evidence=cycle['decomposition'], narrative_summary=cycle['narratives']['summary'],
        top_driver=cycle['narratives'].get('top_driver') or _top_driver(cycle['decomposition']),
    )
    _print_result(result)


def _top_driver(decomposition: dict):
    from decomposition.decomposer import get_top_driver
    return get_top_driver(decomposition)


def cmd_pending(agent: ActionAgent, args) -> None:
    pending = agent.pending()
    if not pending:
        print('no proposals awaiting a decision')
    for p in pending:
        print(f"{p['proposal_id'][:8]}  {p['action_type']:<16} {p['dataset_id']}/{p['metric']}/"
              f"{p['anomaly_date']}  expires {p['expires_at']}")


def cmd_show(agent: ActionAgent, args) -> None:
    pid = _resolve(agent, args.proposal_id)
    p = agent.store.get_proposal(pid)
    print(f"proposal {pid}  status={agent.store.status(pid)}  proposer={p['proposer']}")
    print(f"anomaly {p['dataset_id']}/{p['metric']}/{p['anomaly_date']} ({p['anomaly_id'][:12]})")
    waiting = agent.waiting_on(pid) if agent.is_waiting(pid) else None
    if waiting:
        _print_result({'proposal_id': pid, 'status': 'awaiting_approval', 'waiting_on': waiting,
                       'trace_id': p['trace_id']})
    else:
        _print_trace(p['trace_id'])


def cmd_decide(agent: ActionAgent, args) -> None:
    pid = _resolve(agent, args.proposal_id)
    params = json.loads(args.params) if getattr(args, 'params', None) else None
    try:
        result = agent.decide(pid, args.command if args.command != 'edit' else 'edit',
                              params=params, reason=args.reason)
    except ValueError as e:
        sys.exit(str(e))
    _print_result(result)


def cmd_undo(agent: ActionAgent, args) -> None:
    pid = _resolve(agent, args.proposal_id)
    try:
        result = agent.undo(pid, reason=args.reason)
    except (ValueError, RuntimeError) as e:
        sys.exit(str(e))
    print(f"proposal {pid}: undone ({result['action_type']}, {result['outcome']})")


def cmd_log(agent: ActionAgent, args) -> None:
    pid = _resolve(agent, args.proposal_id) if args.proposal_id else None
    for e in agent.store.events(pid):
        extra = e['detail'] or (e['external_id'] or '')
        print(f"{e['log_id']:>4} {e['created_at'][:19]} {e['proposal_id'][:8]} {e['event']:<20} "
              f"{e['actor']:<22} {e['action_type'] or '':<16} {extra}")


def cmd_replay(agent: ActionAgent, args) -> None:
    pid = _resolve(agent, args.proposal_id)
    results = replay_decisions(agent.store, pid)
    for r in results:
        mark = 'OK  ' if r['match'] else 'DIFF'
        print(f"{mark} log {r['log_id']} {r['event']}: logged={r['logged']} replayed={r['replayed']}")
        if not r['match']:
            print(f"     logged errors:   {r['logged_errors']}\n     replayed errors: {r['replayed_errors']}")
    if any(not r['match'] for r in results):
        sys.exit(1)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='MetricPulse Action Agent CLI approver')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('propose')
    p.add_argument('--dataset-id', required=True)
    p.add_argument('--metric', required=True)
    p.add_argument('--no-llm', action='store_true',
                   help='Use the deterministic proposer instead of the LLM (20b -> 120b -> fallback)')
    sub.add_parser('pending')
    for name in ('show', 'replay'):
        sub.add_parser(name).add_argument('proposal_id')
    for name in ('approve', 'reject', 'edit'):
        d = sub.add_parser(name)
        d.add_argument('proposal_id')
        d.add_argument('--reason', required=(name == 'reject'))
        if name == 'edit':
            d.add_argument('--params', required=True, help='JSON object of replacement params')
        d.add_argument('--live', action='store_true', help='Allow effects outside this machine')
    u = sub.add_parser('undo')
    u.add_argument('proposal_id')
    u.add_argument('--reason', required=True)
    u.add_argument('--live', action='store_true', help='Needed to close a real GitHub issue')
    lg = sub.add_parser('log')
    lg.add_argument('proposal_id', nargs='?')

    args = parser.parse_args(argv)
    handlers = {'propose': cmd_propose, 'pending': cmd_pending, 'show': cmd_show, 'log': cmd_log,
                'replay': cmd_replay, 'approve': cmd_decide, 'reject': cmd_decide, 'edit': cmd_decide,
                'undo': cmd_undo}
    proposer_fn = None
    if args.command == 'propose' and not args.no_llm:
        from action_agent.llm_proposer import make_llm_proposer
        proposer_fn = make_llm_proposer()
    agent = ActionAgent(proposer_fn=proposer_fn, live=getattr(args, 'live', False))
    try:
        handlers[args.command](agent, args)
    finally:
        agent.close()


if __name__ == '__main__':
    main()
