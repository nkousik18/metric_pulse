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
        pct = '' if num in (0, n) else f' · {value:.0%}'
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
