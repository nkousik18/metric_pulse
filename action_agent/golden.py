"""
The Action Agent's golden set (docs/action-agent-scope.md D6, §7): 15 real anomalies from Olist
and Superstore. The agent picks the candidates; Kousik writes the labels (expected action and
owner). The candidates file never contains the model's own proposal, so the labels aren't
anchored to it.

    python -m action_agent.golden            # writes evals/action/golden.yaml (refuses to overwrite labels)
    python -m action_agent.golden --check    # validates the labels
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml  # noqa: E402

from action_agent.catalog import CATALOG  # noqa: E402
from config import settings  # noqa: E402

GOLDEN_PATH = settings.PROJECT_ROOT / 'evals' / 'action' / 'golden.yaml'

# (dataset_id, metric, how many top-|z| dates). 15 in total once duplicates are dropped.
PLAN = [('olist', 'total_revenue', 5), ('olist', 'order_count', 3),
        ('superstore_sales', 'sales', 3), ('superstore_sales', 'profit', 2),
        ('superstore_sales', 'order_quantity', 1), ('superstore_sales', 'shipping_cost', 1)]
ALWAYS = [('olist', 'total_revenue', '2018-09-03')]     # the scoping doc's Golden Case #1 date
TARGET = 15

HEADER = """\
# Action Agent golden set (docs/action-agent-scope.md D6, §7). 15 real anomalies.
#
# FOR KOUSIK TO LABEL. For each case, fill in:
#   expected_action: the action you'd want proposed. One of:
#       notify_owner | open_incident | create_control | annotate_anomaly | suppress_alerts
#     or a list of acceptable ones, e.g. [notify_owner, open_incident].
#   expected_owner: the owner id who should receive it (from action_agent/owners.yaml:
#       analytics-oncall | payments-team | regional-sales), or null when the action names
#       no segment (annotate_anomaly, suppress_alerts).
#   notes: optional, why.
#
# The agent chose the cases (the detector's strongest real anomalies) but did not label them,
# and this file deliberately doesn't show what the model proposes. "owner_if_top_driver" is
# only what owners.yaml would resolve for the biggest segment, for reference.
#
# A case counts as a match when the proposed action is (one of) expected_action, and, if
# expected_owner is set, the owner resolved for the proposed segment equals it.
"""


def _segments(evidence: Dict, per_dim: int = 3) -> Dict[str, List[str]]:
    out = {}
    for dim, data in (evidence.get('dimensions') or {}).items():
        if 'error' in data:
            continue
        out[dim] = [f"{c['segment']}: {c['contribution_pct']:+.1f}% of change "
                    f"({c['previous_value']:,.2f} -> {c['current_value']:,.2f})"
                    for c in data.get('top_contributors', [])[:per_dim]]
    return out


def build_candidates() -> List[Dict]:
    from action_agent.evidence import build_case, top_anomaly_dates
    from action_agent.owners import load_owners, resolve_owner

    owners = load_owners()
    targets = list(ALWAYS)
    for dataset_id, metric, n in PLAN:
        targets += [(dataset_id, metric, day) for day in top_anomaly_dates(dataset_id, metric, n + 2)][:n]
    seen, cases = set(), []
    for dataset_id, metric, day in targets:
        if (dataset_id, metric, day) in seen or len(cases) >= TARGET:
            continue
        seen.add((dataset_id, metric, day))
        case = build_case(dataset_id, metric, day)
        top = case['top_driver']
        if not top:
            continue
        first = next(iter(case['evidence']['dimensions'].values()))
        owner = resolve_owner(owners, dataset_id, top['dimension'], top['segment'])
        cases.append({
            'id': f'g{len(cases) + 1:02d}',
            'dataset_id': dataset_id, 'metric': metric,
            'anomaly_date': case['anomaly_date'], 'previous_date': case['evidence']['previous_date'],
            'total_change_pct': round(float(first.get('total_change_pct') or 0), 2),
            'summary': case['narrative_summary'],
            'top_segments': _segments(case['evidence']),
            'owner_if_top_driver': f"{owner['id']} ({top['dimension']} / {top['segment']})",
            'expected_action': None, 'expected_owner': None, 'notes': None,
        })
    return cases


def load_golden(path: Path = GOLDEN_PATH) -> List[Dict]:
    return yaml.safe_load(Path(path).read_text()) or []


def label_errors(cases: List[Dict]) -> List[str]:
    from action_agent.owners import load_owners
    owner_ids = set(load_owners().people)
    errors = []
    for c in cases:
        expected = c.get('expected_action')
        actions = expected if isinstance(expected, list) else [expected]
        if expected is None:
            errors.append(f"{c['id']}: expected_action is not labelled yet")
            continue
        bad = [a for a in actions if a not in CATALOG]
        if bad:
            errors.append(f"{c['id']}: not catalog actions: {bad}")
        owner = c.get('expected_owner')
        if owner is not None and owner not in owner_ids:
            errors.append(f"{c['id']}: expected_owner {owner!r} is not in owners.yaml ({sorted(owner_ids)})")
    return errors


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Action Agent golden set')
    parser.add_argument('--check', action='store_true', help='Validate the labels')
    parser.add_argument('--path', type=Path, default=GOLDEN_PATH)
    args = parser.parse_args(argv)

    if args.check:
        errors = label_errors(load_golden(args.path))
        print('\n'.join(errors) if errors else f'{len(load_golden(args.path))} cases, all labelled.')
        sys.exit(1 if errors else 0)

    if args.path.exists() and any(c.get('expected_action') for c in load_golden(args.path)):
        sys.exit(f'{args.path} already has labels; not overwriting it.')
    cases = build_candidates()
    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(HEADER + '\n' + yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=110))
    print(f'Wrote {len(cases)} candidate cases to {args.path}. Label expected_action / expected_owner, '
          f'then: python -m action_agent.golden --check')


if __name__ == '__main__':
    main()
