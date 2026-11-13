"""
The eval scorecard shown beside the explained anomaly (docs/ui-redesign-scope.md §5, milestone U2).

A fixed, curated selection of the latest ledger row of each eval (evals/ledger.jsonl), turned into
display rows with their numerators and denominators (PRODUCT.md: "measured, not asserted").
Weak numbers are included on purpose: the onboarding all-fields rate stays next to the strong ones.

Pure: it takes the latest rows (observability.drift.latest_rows(read_ledger()) in the Django view,
demo/recordings/evals/latest.json in the static build) and imports nothing from the project, so the
Pages build can run it with only Django installed. A metric missing from a row is skipped, never
filled in.
"""

from typing import Dict, List, Optional

# (eval, metric key, what it says, unit of n). Order is display order.
SCORECARD = [
    ('action', 'Action Agent', [
        ('action_match_rate', 'Picks the right response', 'golden cases'),
        ('injection_bypasses', 'Prompt injections that got through', 'adversarial cases'),
        ('unauthorized_exec_count', 'Actions run without approval', 'safety probes'),
    ]),
    ('investigation', 'Investigation agent', [
        ('grounding_pass_rate', 'Answers whose every claim checks out', 'runs'),
        ('golden_match_rate', 'Names the expected root cause', 'runs'),
    ]),
    ('detection', 'Detection', [
        ('with_freshness_f1', 'F1 on hand-labelled days (with the freshness check)', 'labelled days'),
    ]),
    ('onboarding', 'Onboarding agent', [
        ('metric_columns_match_rate', 'Finds the right metric columns', 'runs'),
        ('all_fields_match_rate', 'Gets every column role right', 'runs'),
    ]),
]


def _display(metric: Dict, unit: str) -> Optional[Dict]:
    """{'figure': '15/15', 'context': 'golden cases'} for counts and rates, {'figure': '0.96',
    'context': 'over 28 labelled days'} for scores without a numerator."""
    value, num, n = metric.get('value'), metric.get('num'), metric.get('n')
    if value is None or not n:
        return None
    if isinstance(num, int) and not isinstance(num, bool):
        is_rate = abs(value - num / n) < 0.005
        pct = f' · {value:.0%}' if is_rate and num not in (0, n) else ''
        return {'figure': f'{num}/{n}', 'context': f'{unit}{pct}'}
    return {'figure': f'{value:.2f}', 'context': f'over {n} {unit}'}


def build_scorecard(latest_rows: Dict[str, Dict]) -> List[Dict]:
    """Groups of display rows, one group per eval that has a latest row."""
    groups = []
    for eval_name, title, items in SCORECARD:
        row = latest_rows.get(eval_name)
        if not row:
            continue
        metrics = row.get('metrics') or {}
        rows = []
        for key, label, unit in items:
            shown = _display(metrics.get(key) or {}, unit)
            if shown:
                rows.append({'key': key, 'label': label, 'unit': unit, **shown})
        if rows:
            groups.append({'eval': eval_name, 'title': title, 'rows': rows,
                           'date': (row.get('ts') or '')[:10], 'git_sha': row.get('git_sha')})
    return groups


EVAL_TITLES = {'detection': 'Detection', 'investigation': 'Investigation agent',
               'onboarding': 'Onboarding agent', 'action': 'Action Agent'}


def _plain(metric: Dict) -> Optional[str]:
    """Every metric shape in the ledger as text: '25/30 (83%)', '0/10', '0.96 (n = 28)'."""
    value, num, n = metric.get('value'), metric.get('num'), metric.get('n')
    if value is None:
        return None
    if isinstance(num, int) and not isinstance(num, bool) and n:
        is_rate = abs(value - num / n) < 0.005          # a count's value is the count, not a rate
        return f'{num}/{n}' + (f' ({value:.0%})' if is_rate and num not in (0, n) else '')
    if isinstance(value, float):
        text = f'{value:.5f}'.rstrip('0').rstrip('.') if abs(value) < 0.01 else f'{value:.2f}'
    else:
        text = str(value)
    return f'{text} (n = {n})' if n else text


def eval_table(latest_rows: Dict[str, Dict]) -> List[Dict]:
    """Every metric of each eval's latest ledger row, for How it's built. Order: detection,
    investigation, onboarding, action; metric keys as the ledger names them."""
    out = []
    for name in ('detection', 'investigation', 'onboarding', 'action'):
        row = latest_rows.get(name)
        if not row:
            continue
        metrics = [{'key': key, 'text': _plain(m)} for key, m in (row.get('metrics') or {}).items()]
        out.append({'eval': name, 'title': EVAL_TITLES[name], 'date': (row.get('ts') or '')[:10],
                    'git_sha': row.get('git_sha'), 'sets': row.get('sets') or {},
                    'metrics': [m for m in metrics if m['text'] is not None]})
        out[-1]['count'] = str(len(out[-1]['metrics']))   # text: the Pages build renders without l10n
    return out


def scorecard_context(latest_rows: Dict[str, Dict]) -> Dict:
    """Template context: the scorecard groups in order, the same groups by eval name
    (`scores.action`), and the full table (`evals`) for How it's built."""
    groups = build_scorecard(latest_rows)
    return {'scorecard': groups, 'scores': {g['eval']: g for g in groups}, 'evals': eval_table(latest_rows)}
