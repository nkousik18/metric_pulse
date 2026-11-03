"""
The investigation golden set (docs/action-agent-scope.md §7.1, §7.3; milestone A7): real
anomalies, frozen as the exact InvestigationState the synthesis step would see, for Kousik to
label with the expected primary explanation.

    python -m investigation.golden            # writes evals/investigation/golden.yaml + states.json
                                              # (refuses to overwrite labels)
    python -m investigation.golden --check    # validates the labels

Each case is built the way a pipeline run on that day would build it: detection replayed on the
LOOKBACK_DAYS rows ending at the date (detection/eval.py's replay), decompose_all, the ambiguity
rules, and a drill-down where the routing would take one. The state is frozen (states.json) so
the eval never depends on the warehouse again. The agent chooses the cases to cover §7.1's kinds
(a clear driver, close contributors, offsetting segments, an onboarded dataset); it does not
label them, and the file never shows the model's synthesis (D6's rule).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml  # noqa: E402

from config import settings  # noqa: E402
from observability import evals as shared  # noqa: E402

GOLDEN_PATH = shared.EVALS_DIR / 'investigation' / 'golden.yaml'
STATES_PATH = shared.EVALS_DIR / 'investigation' / 'states.json'
SOURCES = [('olist', 'total_revenue'), ('superstore_sales', 'sales'), ('olist', 'order_count'),
           ('superstore_sales', 'profit')]
QUOTA = {'clear_driver': 3, 'close_contributors': 3, 'offsetting_segments': 3}
MIN_ONBOARDED = 1
MIN_CASES = 9            # plus the illustrative Golden Case #1 in investigation/eval.py = 10

HEADER = """\
# Investigation golden set (docs/action-agent-scope.md §7.1, §7.3). Real anomalies from Olist and Superstore.
#
# FOR KOUSIK TO LABEL. For each case, fill in:
#   expected_primary: the explanation a good analyst would lead with, as
#       {dimension: <dimension>, segment: <segment>}
#     The segment can be a top contributor, or a drill-down detail where one is shown
#     (Golden Case #1's answer is geography / SP, from its drill-down). For more than one
#     acceptable answer, give a list of them.
#   requires_uncertainty_note: true if the honest summary has to say the cause is uncertain
#     (e.g. close contributors or offsetting segments make the lead explanation debatable),
#     false if one explanation is clearly right.
#   notes: optional, why.
#
# The agent chose the cases and grouped them by what the ambiguity rules flagged ("kind"), but
# didn't label them, and the model's own synthesis isn't shown. The full frozen state each case
# is graded on is in states.json, under the same id.
"""


def _plain(value):
    from action_agent.runner import to_plain
    return to_plain(value)


def replayed_detection(series, metric: str, date: str, threshold: float) -> Dict:
    """A run_detection-shaped result for the LOOKBACK_DAYS rows ending at `date`: what a pipeline run
    that day would hand the investigation (synthesis reads all_anomalies as the recent history)."""
    from detection.anomaly_detector import detect_anomalies
    window = series[series['metric_date'] <= date].tail(settings.LOOKBACK_DAYS)
    df = detect_anomalies(window, metric, threshold)
    flagged = df[df['is_anomaly']]
    all_anomalies = [{'metric_date': r['metric_date'], 'metric_value': float(r[metric]),
                      'zscore': round(float(r['zscore']), 3), 'anomaly_direction': r['anomaly_direction'],
                      'change_pct': None if r['change_pct'] != r['change_pct'] else float(r['change_pct'])}
                     for _, r in flagged.iterrows()]
    return {'status': 'completed', 'metric': metric, 'lookback_days': settings.LOOKBACK_DAYS,
            'total_days_analyzed': len(df), 'anomaly_count': len(all_anomalies), 'all_anomalies': all_anomalies}


def kind_of(ambiguous: List[Dict]) -> str:
    reasons = {a['reason'] for a in ambiguous}
    if 'offsetting_segments' in reasons:
        return 'offsetting_segments'
    if 'close_contributors' in reasons:
        return 'close_contributors'
    return 'clear_driver'


def build_state(dataset_id: str, metric: str, date: str, series, threshold: float) -> Optional[Dict]:
    """The pre-synthesis InvestigationState for one anomaly, built by the graph's own nodes."""
    from decomposition.decomposer import get_comparison_dates
    from investigation.nodes import assess_ambiguity, decompose_all, drill_down
    from investigation.routing import route_after_ambiguity
    from investigation.state import build_initial_state
    from action_agent.evidence import dataset_config as evidence_config

    cfg = evidence_config(dataset_id)
    dataset_config = None
    if dataset_id != 'olist':
        from onboarding.investigate import load_dataset_config
        dataset_config, _ = load_dataset_config(dataset_id)
    current, previous = get_comparison_dates(date, table_name=cfg['table_name'],
                                             connection_factory=cfg['connection_factory'])
    state = build_initial_state(metric, threshold=threshold, force_investigate=True, current_date=current,
                                previous_date=previous,
                                detection_result=replayed_detection(series, metric, date, threshold),
                                dataset_config=dataset_config)
    for node in (decompose_all, assess_ambiguity):
        state = {**state, **node(state)}
        if state.get('status') == 'failed':
            return None
    if route_after_ambiguity(state) == 'drill_down':
        state = {**state, **drill_down(state)}
        if state.get('status') == 'failed':
            return None
    dims = state['decomposition_results'].get('dimensions') or {}
    if not dims or all('error' in d for d in dims.values()):
        return None
    state['dataset_config'] = None          # frozen: synthesis reads only the state, never the warehouse
    return _plain(state)


def _evidence(state: Dict) -> Dict:
    out = {}
    for dim, data in state['decomposition_results']['dimensions'].items():
        if 'error' in data:
            continue
        out[dim] = [f"{c['segment']}: {c['contribution_pct']:+.1f}% of change "
                    f"({c['previous_value']:,.2f} -> {c['current_value']:,.2f})"
                    for c in data.get('top_contributors', [])[:3]]
    return out


def _drill(state: Dict) -> Dict:
    return {dim: [f"{c['segment']}: {c['contribution_pct']:+.1f}% of change "
                  f"({c['previous_value']:,.2f} -> {c['current_value']:,.2f})"
                  for c in data.get('top_contributors', [])[:3]]
            for dim, data in (state.get('drill_down_results') or {}).items()}


def build_candidates(threshold: float = settings.ANOMALY_THRESHOLD_ZSCORE):
    from detection.eval import load_series, replay_all

    pools = {k: [] for k in QUOTA}
    for dataset_id, metric in SOURCES:
        series = load_series(dataset_id, metric)
        flagged = replay_all(series, metric, threshold)
        flagged = flagged[flagged['flagged']].assign(absz=lambda d: d['zscore'].abs())
        for date in flagged.sort_values(['absz', 'metric_date'], ascending=[False, True])['metric_date'].head(8):
            state = build_state(dataset_id, metric, date, series, threshold)
            if state is not None:
                pools[kind_of(state['ambiguous_dimensions'])].append((dataset_id, metric, date, state))

    chosen = []
    for kind, n in QUOTA.items():
        # Round-robin over sources, so no kind is all one dataset.
        by_source: Dict = {}
        for item in pools[kind]:
            by_source.setdefault((item[0], item[1]), []).append(item)
        while len([c for c in chosen if c[4] == kind]) < n and any(by_source.values()):
            for key in list(by_source):
                if by_source[key] and len([c for c in chosen if c[4] == kind]) < n:
                    chosen.append((*by_source[key].pop(0), kind))
    if sum(c[0] != 'olist' for c in chosen) < MIN_ONBOARDED:
        extra = next((item for k in QUOTA for item in pools[k] if item[0] != 'olist'
                      and all(item[2] != c[2] or item[1] != c[1] for c in chosen)), None)
        if extra:
            chosen.append((*extra, kind_of(extra[3]['ambiguous_dimensions'])))

    cases, states = [], {}
    for i, (dataset_id, metric, date, state, kind) in enumerate(chosen, start=2):   # case 1 is the illustrative one
        cid = f'i{i:02d}'
        states[cid] = state
        cases.append({
            'id': cid, 'dataset_id': dataset_id, 'metric': metric,
            'current_date': state['current_date'], 'previous_date': state['previous_date'], 'kind': kind,
            'ambiguity': [f"{a['dimension']}: {a['reason']}" for a in state['ambiguous_dimensions']] or ['none'],
            'top_segments': _evidence(state), 'drill_down': _drill(state) or None,
            'expected_primary': None, 'requires_uncertainty_note': None, 'notes': None,
        })
    return cases, states


def load_golden(path: Path = GOLDEN_PATH) -> List[Dict]:
    return (yaml.safe_load(Path(path).read_text()) or []) if Path(path).exists() else []


def load_states(path: Path = STATES_PATH) -> Dict[str, Dict]:
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def _primaries(expected) -> List[Dict]:
    return expected if isinstance(expected, list) else [expected]


def segments_in(state: Dict, dimension: str) -> set:
    segs = {c['segment'] for c in (state['decomposition_results']['dimensions'].get(dimension) or {})
            .get('top_contributors', [])}
    segs |= {c['segment'] for c in ((state.get('drill_down_results') or {}).get(dimension) or {})
             .get('top_contributors', [])}
    return segs


def label_errors(cases: List[Dict], states: Dict[str, Dict]) -> List[str]:
    errors = []
    for c in cases:
        cid = c['id']
        if cid not in states:
            errors.append(f'{cid}: no frozen state in states.json')
            continue
        if c.get('expected_primary') is None:
            errors.append(f'{cid}: expected_primary is not labelled yet')
        else:
            for p in _primaries(c['expected_primary']):
                if not isinstance(p, dict) or not {'dimension', 'segment'} <= set(p):
                    errors.append(f'{cid}: expected_primary needs {{dimension, segment}}, got {p!r}')
                elif p['segment'] not in segments_in(states[cid], p['dimension']):
                    errors.append(f"{cid}: {p['dimension']} / {p['segment']} isn't in this case's evidence")
        if not isinstance(c.get('requires_uncertainty_note'), bool):
            errors.append(f'{cid}: requires_uncertainty_note must be true or false')
    if len(cases) < MIN_CASES:
        errors.append(f'only {len(cases)} cases; §7.1 needs at least {MIN_CASES} besides Golden Case #1')
    return errors


def to_eval_cases(cases: List[Dict], states: Dict[str, Dict]) -> List[Dict]:
    """investigation/eval.py's case shape."""
    return [{'name': c['id'], 'state': states[c['id']], 'expected_primary': c['expected_primary'],
             'requires_uncertainty_note': c['requires_uncertainty_note'], 'kind': c['kind'],
             'dataset_id': c['dataset_id']} for c in cases]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Investigation golden set')
    parser.add_argument('--check', action='store_true', help='Validate the labels')
    args = parser.parse_args(argv)

    if args.check:
        cases = load_golden()
        errors = label_errors(cases, load_states())
        print('\n'.join(errors) if errors else f'{len(cases)} cases, all labelled.')
        sys.exit(1 if errors else 0)

    if any(c.get('expected_primary') is not None for c in load_golden()):
        sys.exit(f'{GOLDEN_PATH} already has labels; not overwriting it.')
    cases, states = build_candidates()
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(HEADER + '\n' + yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=110))
    STATES_PATH.write_text(json.dumps(states, indent=1, sort_keys=True, default=str) + '\n')
    kinds = {k: sum(c['kind'] == k for c in cases) for k in QUOTA}
    print(f'Wrote {len(cases)} cases to {GOLDEN_PATH} ({kinds}; '
          f"{sum(c['dataset_id'] != 'olist' for c in cases)} onboarded). "
          f'Label them, then: python -m investigation.golden --check')


if __name__ == '__main__':
    main()
