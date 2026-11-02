"""
Live model probe for the Action Agent proposer (docs/action-agent-scope.md D2: "A3 live-tests 20b
on real proposals first and records the result in the decision log before routing is built on it").

It builds real cases, runs the proposer on each, and prints a per-case table plus totals:
grounded rate, escalation rate, fallback rate, tokens, cost and latency. Every call is also in
logs/llm_calls.jsonl through the telemetry wrapper. Real Groq calls, real (small) cost.

Cases are real anomalies, chosen deterministically: for each (dataset, metric) the detector's
z-score over the full history, the top-|z| dates, each compared with the day before it exactly
as the pipeline does (get_comparison_dates), plus Olist's golden case (2018-09-03).

    python -m action_agent.probe --small-only            # D2's first step: gpt-oss-20b alone
    python -m action_agent.probe                         # the full routing: 20b -> 120b -> fallback
    python -m action_agent.probe --json out.json         # also write the per-case results
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.llm_proposer import make_llm_proposer  # noqa: E402
from action_agent.policy import policy_check  # noqa: E402
from action_agent.runner import to_plain  # noqa: E402
from config import settings  # noqa: E402
from config.db import get_connection  # noqa: E402

# (dataset_id, metric, how many top-|z| dates). Olist is the local DuckDB warehouse (L1);
# superstore_sales is the onboarded Phase 2 dataset.
DEFAULT_PLAN = [('olist', 'total_revenue', 4), ('olist', 'order_count', 2),
                ('superstore_sales', 'sales', 3), ('superstore_sales', 'profit', 2)]
GOLDEN = [('olist', 'total_revenue', '2018-09-03')]


def _dataset(dataset_id: str) -> Dict:
    if dataset_id == 'olist':
        return {'metric_columns': None, 'table_name': 'staging.fact_daily_metrics',
                'connection_factory': get_connection, 'dimension_config': None}
    from onboarding.investigate import load_dataset_config
    config, _ = load_dataset_config(dataset_id)
    return config


def top_anomaly_dates(dataset_id: str, metric: str, n: int) -> List[str]:
    from detection.anomaly_detector import detect_anomalies, fetch_daily_metrics
    cfg = _dataset(dataset_id)
    df = fetch_daily_metrics(100_000, cfg['metric_columns'], cfg['table_name'], cfg['connection_factory'])
    df = detect_anomalies(df, metric)
    df = df[df['is_anomaly']].assign(absz=lambda d: d['zscore'].abs())
    df = df.sort_values(['absz', 'metric_date'], ascending=[False, True])
    return [str(d)[:10] for d in df['metric_date'].head(n)]


def build_case(dataset_id: str, metric: str, target_date: str) -> Dict:
    from decomposition.decomposer import decompose_metric, get_comparison_dates, get_top_driver
    from narrative.generator import generate_narrative
    cfg = _dataset(dataset_id)
    current, previous = get_comparison_dates(target_date, table_name=cfg['table_name'],
                                             connection_factory=cfg['connection_factory'])
    kwargs = {'connection_factory': cfg['connection_factory']}
    if cfg['dimension_config'] is not None:
        kwargs['dimension_config'] = cfg['dimension_config']
    evidence = to_plain(decompose_metric(current, previous, metric, **kwargs))
    return {'dataset_id': dataset_id, 'metric': metric, 'anomaly_date': current,
            'evidence': evidence, 'narrative_summary': generate_narrative(evidence)['summary'],
            'top_driver': to_plain(get_top_driver(evidence))}


def build_cases(plan=DEFAULT_PLAN, golden=GOLDEN) -> List[Dict]:
    seen, cases = set(), []
    targets = [(d, m, day) for d, m, day in golden]
    for dataset_id, metric, n in plan:
        targets += [(dataset_id, metric, day) for day in top_anomaly_dates(dataset_id, metric, n)]
    for dataset_id, metric, day in targets:
        if (dataset_id, metric, day) in seen:
            continue
        seen.add((dataset_id, metric, day))
        case = build_case(dataset_id, metric, day)
        if case['top_driver']:
            cases.append(case)
    return cases


def run(cases: List[Dict], escalate: bool) -> List[Dict]:
    proposer = make_llm_proposer(escalate=escalate)
    rows = []
    for case in cases:
        start = time.perf_counter()
        proposal, name, trail = proposer(case)
        allowed = policy_check(proposal, case['evidence']).allowed if proposal else False
        rows.append({
            'case': f"{case['dataset_id']}/{case['metric']}/{case['anomaly_date']}",
            'proposer': name, 'action': (proposal or {}).get('action_type'),
            'segment': ((proposal or {}).get('params') or {}).get('segment'),
            'proposal': proposal,
            'top_driver': case['top_driver'].get('segment'),
            'policy_allowed': allowed, 'escalated': trail['escalated'],
            'fell_back': bool(trail.get('fell_back')), 'tokens': trail.get('tokens_used', 0),
            'seconds': round(time.perf_counter() - start, 1), 'attempts': trail['attempts'],
        })
    return rows


def report(rows: List[Dict], escalate: bool) -> None:
    n = len(rows)
    print(f"\n{'case':<44} {'proposer':<26} {'action':<16} {'segment':<22} {'tokens':>6} {'s':>5}")
    for r in rows:
        print(f"{r['case']:<44} {r['proposer']:<26} {str(r['action']):<16} {str(r['segment'])[:22]:<22} "
              f"{r['tokens']:>6} {r['seconds']:>5}")
        for a in r['attempts']:
            if a['outcome'] != 'grounded':
                print(f"    attempt {a['attempt']} {a['model']}: {a['outcome']} {a['errors'][:2]}")
    small_ok = sum(1 for r in rows if r['attempts'] and r['attempts'][0]['outcome'] == 'grounded')
    print(f"\nn = {n}  ({'20b -> 120b -> fallback' if escalate else '20b only, no escalation'})")
    print(f"  small model grounded on the first attempt: {small_ok}/{n}")
    if escalate:
        print(f"  escalated: {sum(r['escalated'] for r in rows)}/{n}")
    print(f"  fell back to deterministic: {sum(r['fell_back'] for r in rows)}/{n}")
    print(f"  proposals that pass policy_check: {sum(r['policy_allowed'] for r in rows)}/{n}")
    print(f"  action types: {dict(sorted(_count(r['action'] for r in rows).items()))}")
    print(f"  segment = top driver: {sum(r['segment'] == r['top_driver'] for r in rows)}/{n}")
    tokens = [r['tokens'] for r in rows]
    print(f"  tokens per run: median {statistics.median(tokens):,.0f}, max {max(tokens):,} "
          f"(budget {settings.ACTION_TOKEN_BUDGET:,})")
    print(f"  seconds per run: median {statistics.median(r['seconds'] for r in rows)}")
    print(f"  per-call cost and tokens: {settings.LLM_CALLS_LOG}")


def _count(values) -> Dict:
    out: Dict = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Live-test the Action Agent proposer on real anomalies')
    parser.add_argument('--small-only', action='store_true', help='Small model only (no escalation)')
    parser.add_argument('--json', type=Path, help='Also write the per-case results here')
    args = parser.parse_args(argv)

    cases = build_cases()
    print(f'{len(cases)} real anomaly cases built')
    rows = run(cases, escalate=not args.small_only)
    report(rows, escalate=not args.small_only)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1, default=str))


if __name__ == '__main__':
    main()
