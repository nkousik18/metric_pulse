"""
The Phase 1 eval suite (docs/scoping.md Section 8.3, formalized per Section 8.6
and ROADMAP milestone M3). Reuses the exact production code path --
investigation.nodes._run_synthesis and its validators -- as the grader, rather
than a separate LLM-as-judge pipeline.

Not part of `pytest tests/` -- every run calls a real LLM API and costs real
money (Section 8.6). Run manually before merging a prompt/model change, or
periodically to catch drift:

    python -m investigation.eval --runs 5
    python -m investigation.eval --runs 3 --set-baseline

Since A7 the cases are Golden Case #1 plus the labelled real cases in
evals/investigation/golden.yaml (investigation/golden.py builds them; Kousik labels
them). Until every one is labelled, only Golden Case #1 runs. Each run prints the
§7.2 report and appends a row to evals/ledger.jsonl (eval `investigation`).
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings  # noqa: E402
from investigation.nodes import _run_synthesis  # noqa: E402
from observability import evals as shared  # noqa: E402

# --- Golden Case #1 (docs/scoping.md Section 3.8), reconstructed as real
# InvestigationState fields rather than the doc's illustrative prose. Numbers
# are self-consistent (contribution_pct/change/current/previous all agree),
# not live pipeline output -- same "illustrative but real-shaped" status the
# doc itself gives this example.

_GEOGRAPHY = {
    'total_current': 200.0, 'total_previous': 1000.0, 'total_change': -800.0, 'total_change_pct': -80.0,
    'segment_count': 3,
    'top_contributors': [
        {'segment': 'Southeast', 'current_value': 90.0, 'previous_value': 450.0,
         'change': -360.0, 'change_pct': -80.0, 'contribution_pct': 45.0, 'abs_contribution': 45.0},
        {'segment': 'Northeast', 'current_value': 76.0, 'previous_value': 380.0,
         'change': -304.0, 'change_pct': -80.0, 'contribution_pct': 38.0, 'abs_contribution': 38.0},
        {'segment': 'South', 'current_value': 34.0, 'previous_value': 170.0,
         'change': -136.0, 'change_pct': -80.0, 'contribution_pct': 17.0, 'abs_contribution': 17.0},
    ],
}

_PRODUCT = {
    'total_current': 533.0, 'total_previous': 600.0, 'total_change': -67.0, 'total_change_pct': -11.17,
    'segment_count': 2,
    'top_contributors': [
        {'segment': 'Electronics', 'current_value': 440.0, 'previous_value': 500.0,
         'change': -60.0, 'change_pct': -12.0, 'contribution_pct': 89.55, 'abs_contribution': 89.55},
        {'segment': 'Books', 'current_value': 93.0, 'previous_value': 100.0,
         'change': -7.0, 'change_pct': -7.0, 'contribution_pct': 10.45, 'abs_contribution': 10.45},
    ],
}

_PAYMENT = {
    'total_current': 1300.0, 'total_previous': 2000.0, 'total_change': -700.0, 'total_change_pct': -35.0,
    'segment_count': 3,
    'top_contributors': [
        {'segment': 'Credit Card', 'current_value': 750.0, 'previous_value': 1500.0,
         'change': -750.0, 'change_pct': -50.0, 'contribution_pct': 107.14, 'abs_contribution': 107.14},
        {'segment': 'Boleto', 'current_value': 350.0, 'previous_value': 400.0,
         'change': -50.0, 'change_pct': -12.5, 'contribution_pct': 7.14, 'abs_contribution': 7.14},
        {'segment': 'Voucher', 'current_value': 200.0, 'previous_value': 100.0,
         'change': 100.0, 'change_pct': 100.0, 'contribution_pct': -14.29, 'abs_contribution': 14.29},
    ],
}

_GEOGRAPHY_DRILL_DOWN = {
    'total_current': 90.0, 'total_previous': 450.0, 'total_change': -360.0, 'total_change_pct': -80.0,
    'segment_count': 2,
    'top_contributors': [
        {'segment': 'SP', 'current_value': 80.0, 'previous_value': 400.0,
         'change': -320.0, 'change_pct': -80.0, 'contribution_pct': 88.89, 'abs_contribution': 88.89},
        {'segment': 'RJ', 'current_value': 10.0, 'previous_value': 50.0,
         'change': -40.0, 'change_pct': -80.0, 'contribution_pct': 11.11, 'abs_contribution': 11.11},
    ],
}

GOLDEN_CASE_1: Dict = {
    'name': 'geography_close_contributors_payment_offsetting',
    'state': {
        'metric': 'total_revenue',
        'current_date': '2018-09-03',
        'previous_date': '2018-08-29',
        'threshold': 2.0,
        'force_investigate': False,
        'detection_result': {
            'anomaly_count': 1,
            'all_anomalies': [
                {'metric_date': '2018-08-15', 'anomaly_direction': 'low', 'change_pct': -22.0},
            ],
        },
        'decomposition_results': {
            'current_date': '2018-09-03', 'previous_date': '2018-08-29', 'metric': 'total_revenue',
            'dimensions': {'geography': _GEOGRAPHY, 'product': _PRODUCT, 'payment': _PAYMENT},
        },
        'ambiguous_dimensions': [
            {'dimension': 'geography', 'reason': 'close_contributors'},
            {'dimension': 'payment', 'reason': 'offsetting_segments'},
        ],
        'drill_down_results': {'geography': _GEOGRAPHY_DRILL_DOWN},
        'drilled_dimensions': ['geography'],
        'investigation_log': [],
        'iteration_count': 1,
        'should_continue': False,
        'top_driver': None,
        'investigation_summary': None,
        'narratives': None,
        'grounding_failed': None,
        'status': 'running',
        'error': None,
    },
    'expected_primary': {'dimension': 'geography', 'segment': 'SP'},
    'requires_uncertainty_note': True,
}

GOLDEN_CASES: List[Dict] = [GOLDEN_CASE_1]


def summarize_results(results: List[Dict]) -> Dict:
    """
    Pure aggregation over already-graded per-trial result dicts (docs/scoping.md
    Section 8.5's named metrics). No LLM calls here -- safe to unit-test directly.

    - grounding_pass_rate: fraction where outcome == 'grounded_first_attempt'
      ("every citation validates on the first attempt... before the retry" --
      Section 3.6/8.5. Deliberately excludes 'grounded_after_retry': this is
      the metric that shows whether the retry path is doing real work.)
    - fallback_rate: fraction where outcome starts with 'fallback' (exhausted
      the retry and fell back to the deterministic summary).
    - golden_match_rate / uncertainty_ok_rate: unchanged from the original
      per-trial grading -- a fallback trial (no model citation to check)
      always counts as a non-match, which correctly folds grounding failures
      into these end-to-end rates rather than hiding them.
    """
    total = len(results)
    if not total:
        return {
            'results': results,
            'grounding_pass_rate': 0,
            'fallback_rate': 0,
            'golden_match_rate': 0,
            'uncertainty_ok_rate': 0,
        }

    return {
        'results': results,
        'grounding_pass_rate': sum(r['outcome'] == 'grounded_first_attempt' for r in results) / total,
        'fallback_rate': sum(r['outcome'].startswith('fallback') for r in results) / total,
        'golden_match_rate': sum(r['golden_match'] for r in results) / total,
        'uncertainty_ok_rate': sum(r['uncertainty_ok'] for r in results) / total,
    }


def run_investigation_eval(golden_cases: List[Dict], runs_per_case: int = 1) -> Dict:
    """
    Runs each golden case through _run_synthesis (the real production LLM call
    path) `runs_per_case` times -- one golden case run once is an n=1 coin
    flip, not a rate; repeating it against the live API is what makes
    Section 8.5's per-call metrics statistically real rather than estimated.
    """
    results = []
    for case in golden_cases:
        for run_index in range(runs_per_case):
            output, log, outcome = _run_synthesis(case['state'])
            grounded = output is not None
            expected = case['expected_primary']
            golden_match = grounded and any(
                output.primary_explanation.dimension == e['dimension']
                and output.primary_explanation.segment == e['segment']
                for e in (expected if isinstance(expected, list) else [expected])
            )
            uncertainty_ok = (
                not case['requires_uncertainty_note']
                or (grounded and output.uncertainty_note is not None)
            )
            results.append({
                'case': case['name'],
                'kind': case.get('kind', 'illustrative'),
                'expected_primary': expected,
                'run_index': run_index,
                'outcome': outcome,
                'grounded': grounded,
                'golden_match': golden_match,
                'uncertainty_ok': uncertainty_ok,
                'primary_explanation': output.primary_explanation.model_dump() if grounded else None,
                'uncertainty_note': output.uncertainty_note if grounded else None,
                'log': log,
            })

    return summarize_results(results)


QUESTIONS = {
    'grounding_pass_rate': 'Is the agent making things up?',
    'golden_match_rate': 'Does it find the right cause?',
    'uncertainty_ok_rate': "Does it admit when it's unsure?",
    'fallback_rate': 'How often does the LLM fail outright?',
}
CONTEXT_KEYS = ('ts', 'git_sha', 'model', 'prompt_hash', 'runs_per_case', 'labels_hash')


def load_cases():
    """Golden Case #1, plus the real cases once every one is labelled. Returns (cases, note)."""
    from investigation.golden import GOLDEN_PATH, label_errors, load_golden, load_states, to_eval_cases
    labelled, states = load_golden(), load_states()
    if not labelled:
        return list(GOLDEN_CASES), 'no real cases yet (python -m investigation.golden)'
    errors = label_errors(labelled, states)
    if errors:
        return list(GOLDEN_CASES), (f'{len(errors)} label problem(s) in {GOLDEN_PATH.name}, so only Golden Case #1 '
                                    f'runs (python -m investigation.golden --check)')
    return list(GOLDEN_CASES) + to_eval_cases(labelled, states), None


def metrics_of(results: List[Dict]) -> Dict:
    n = len(results)
    return {
        'grounding_pass_rate': shared.rate(sum(r['outcome'] == 'grounded_first_attempt' for r in results), n),
        'golden_match_rate': shared.rate(sum(r['golden_match'] for r in results), n),
        'uncertainty_ok_rate': shared.rate(sum(r['uncertainty_ok'] for r in results), n),
        'fallback_rate': shared.rate(sum(r['outcome'].startswith('fallback') for r in results), n),
    }


def by_kind(results: List[Dict]) -> Dict[str, Dict]:
    out = {}
    for kind in sorted({r['kind'] for r in results}):
        rows = [r for r in results if r['kind'] == kind]
        out[kind] = shared.rate(sum(r['golden_match'] for r in rows), len(rows))
    return out


def failing(results: List[Dict]) -> List[Dict]:
    out = []
    for r in results:
        if r['golden_match'] and r['uncertainty_ok'] and r['outcome'] == 'grounded_first_attempt':
            continue
        got = r['primary_explanation']
        out.append({'id': f"{r['case']}#{r['run_index']}", 'expected': r['expected_primary'],
                    'actual': (f"{got['dimension']} / {got['segment']}" if got else 'no grounded output')
                              + f"; {r['outcome']}; uncertainty_ok={r['uncertainty_ok']}",
                    'trace': None})
    return out


def report(metrics: Dict, kinds: Dict, fails: List[Dict], baseline, context: Dict, note) -> str:
    deltas = shared.compare(metrics, baseline, lower_is_better=('fallback_rate',))
    lines = [f"Investigation eval — {context['ts']} — {context['cases']} cases x {context['runs_per_case']} runs"]
    if note:
        lines.append(f'   note: {note}')
    for name, question in QUESTIONS.items():
        lines.append(f'\n1. Question: {question}')
        lines.append(f'2. Result: {shared.fmt(name, metrics[name])}')
        if name == 'golden_match_rate':
            lines += [f'   {k}: {shared.fmt("match_rate", v)}' for k, v in kinds.items()]
    lines.append('\n3. Against baseline:')
    lines += shared.baseline_lines(metrics, baseline, deltas)
    lines.append(f"4. What changed: git {context['git_sha']}, model {context['model']}, "
                 f"prompt {context['prompt_hash']}, labels {context['labels_hash']}")
    if baseline:
        lines.append(f"   baseline: git {baseline.get('git_sha')}, model {baseline.get('model')}, "
                     f"prompt {baseline.get('prompt_hash')}, labels {baseline.get('labels_hash')}")
    lines.append(f'5. Failing runs ({len(fails)}):')
    lines += [f"   {f['id']}: expected {f['expected']}; got {f['actual']}" for f in fails]
    return '\n'.join(lines)


def _prompt_hash() -> str:
    import hashlib
    import inspect
    from investigation import prompts
    return hashlib.sha256(inspect.getsource(prompts).encode()).hexdigest()[:12]


def _labels_hash() -> str:
    import hashlib
    from investigation.golden import GOLDEN_PATH
    return hashlib.sha256(GOLDEN_PATH.read_bytes()).hexdigest()[:12] if GOLDEN_PATH.exists() else 'none'


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='MetricPulse investigation eval suite (real LLM calls)')
    parser.add_argument('--runs', type=int, default=5, help='Real LLM trials per golden case')
    parser.add_argument('--set-baseline', action='store_true', help="Accept this run's numbers as the baseline")
    parser.add_argument('--no-ledger', action='store_true', help='Do not append to evals/ledger.jsonl')
    args = parser.parse_args(argv)

    cases, note = load_cases()
    summary = run_investigation_eval(cases, runs_per_case=args.runs)
    results = summary['results']
    for r in results:
        print(f"[{r['case']} #{r['run_index']}] outcome={r['outcome']} "
              f"golden_match={r['golden_match']} uncertainty_ok={r['uncertainty_ok']}")

    metrics, kinds, fails = metrics_of(results), by_kind(results), failing(results)
    context = {'ts': shared.now_iso(), 'git_sha': shared.git_sha_dirty(), 'model': settings.GROQ_MODEL,
               'prompt_hash': _prompt_hash(), 'runs_per_case': args.runs, 'labels_hash': _labels_hash(),
               'cases': len(cases)}
    baseline = shared.load_baseline('investigation')
    print('\n' + report(metrics, kinds, fails, baseline, context, note))
    row = {**context, 'eval': 'investigation', 'sets': {'cases': len(cases), 'runs': len(results)},
           'metrics': metrics, 'by_kind': kinds, 'failing': fails}
    if not args.no_ledger:
        print(f'\nLedger: appended to {shared.append_ledger(row)}')
    if args.set_baseline:
        print(f'Baseline: written to {shared.write_baseline(row, CONTEXT_KEYS)}')


if __name__ == '__main__':
    main()
