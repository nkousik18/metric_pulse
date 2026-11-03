"""
Onboarding eval (docs/scoping.md Section 5.6; docs/action-agent-scope.md §7.1, §7.3): can it
understand an unseen dataset? Real LLM calls (one classification per dataset per run).

    python -m onboarding.eval [--runs 2]       # all three datasets, report + ledger row
    python -m onboarding.eval --set-baseline

Three datasets, each graded field by field against a confirmed classification:
1. saas_subscriptions: the synthetic Golden Case #2 (Section 5.6), expectations written in code.
2. superstore_sales: data/samples/superstore_sales.csv (gitignored, so local only; skipped
   when absent), against the classification Kousik confirmed in M6
   (evals/onboarding/superstore_sales.expected.json).
3. adversarial_injection: the A5 hostile CSV, against the classification he confirmed in A5
   (evals/action/adversarial/classification.json).
2 and 3 were confirmed after the model proposed them, so they're anchored to its output in a way
D6's labels aren't (§7.3); the report says so.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.classification import classify_columns_with_validation, validate_classification  # noqa: E402
from onboarding.profiling import profile_columns  # noqa: E402
from observability import evals as shared  # noqa: E402
from config import settings  # noqa: E402

# --- Golden Case #2 (docs/scoping.md Section 5.6): a synthetic SaaS-subscription
# dataset, not literally 50,000 rows, but reproducing the worked example's
# *qualitative* profile shape per column closely enough that Stage A/B's real
# output should match Section 5.6's expected classification. Fixed seed for
# reproducibility.

_N_ROWS = 500
_N_DATES = 40          # cardinality << n_rows -> grain='other', matches original's 412/50,000
_N_CUSTOMERS = 80       # ratio 0.16, matches original's 8,200/50,000 -- explicitly "too high" per 5.6


def _build_golden_case_2_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)

    dates = pd.date_range('2026-01-01', periods=_N_DATES).astype(str)
    plan_types = ['Starter', 'Growth', 'Enterprise']
    regions = ['NA', 'EMEA', 'APAC']

    notes_pool = [
        'customer requested upgrade', 'billing inquiry', 'churn risk flagged',
        'renewed early', 'requested downgrade', 'support escalation',
    ]
    notes = rng.choice(notes_pool, size=_N_ROWS).astype(object)
    notes[rng.random(_N_ROWS) < 0.4] = None  # ~40% null, matching Section 5.6

    plan_choices = rng.choice(plan_types, size=_N_ROWS)
    # Plan-tier-correlated base price + small noise, rounded to whole dollars --
    # realistic revenue data repeats at common price points (unlike continuous
    # rng.uniform(), which is ~100% unique by chance and would misleadingly
    # flag this metric column as is_likely_id).
    base_price = {'Starter': 29, 'Growth': 99, 'Enterprise': 299}
    mrr_amount = np.array([base_price[p] for p in plan_choices]) + rng.integers(-5, 6, size=_N_ROWS)

    return pd.DataFrame({
        'subscription_id': [f'SUB{i}' for i in range(_N_ROWS)],
        'event_date': rng.choice(dates, size=_N_ROWS),
        'customer_id': rng.choice([f'CUST{i}' for i in range(_N_CUSTOMERS)], size=_N_ROWS),
        'plan_type': plan_choices,
        'region': rng.choice(regions, size=_N_ROWS),
        'mrr_amount': mrr_amount.astype(float),
        'seats': rng.integers(1, 50, size=_N_ROWS),
        'notes': notes,
    })


GOLDEN_CASE_2 = {
    'name': 'saas_subscriptions',
    'df': _build_golden_case_2_df(),
    'expected_date_column': 'event_date',
    'expected_grain': 'other',
    'expected_metric_columns': {'mrr_amount', 'seats'},
    'expected_dimension_columns': {'plan_type', 'region'},
    'expected_rejected_columns': {'subscription_id', 'customer_id', 'notes'},
}


FIELDS = ('date_column', 'grain', 'metric_columns', 'dimension_columns', 'rejected_columns')
ANCHORED = 'confirmed after seeing the model proposal (anchored, §7.3)'


def expected_from_classification(name: str, classification: dict) -> dict:
    """The expectation shape GOLDEN_CASE_2 uses, from a confirmed SchemaClassification dict."""
    return {
        'name': name,
        'expected_date_column': classification.get('date_column'),
        'expected_grain': classification['grain'],
        'expected_metric_columns': set(classification.get('metric_columns') or []),
        'expected_dimension_columns': {d['column'] for d in classification.get('dimension_columns') or []},
        'expected_rejected_columns': {r['column'] for r in classification.get('rejected_columns') or []},
    }


def _csv_case(name: str, csv_path: Path, expected_path: Path) -> dict:
    stored = json.loads(Path(expected_path).read_text())
    case = expected_from_classification(name, stored['classification'])
    case['csv'] = Path(csv_path)
    case['provenance'] = ANCHORED
    return case


def all_cases() -> list:
    root = settings.PROJECT_ROOT
    return [
        {**GOLDEN_CASE_2, 'provenance': 'written in code from Section 5.6 (unanchored)'},
        _csv_case('superstore_sales', root / 'data' / 'samples' / 'superstore_sales.csv',
                  shared.EVALS_DIR / 'onboarding' / 'superstore_sales.expected.json'),
        _csv_case('adversarial_injection', shared.EVALS_DIR / 'action' / 'adversarial' / 'adversarial_injection.csv',
                  shared.EVALS_DIR / 'action' / 'adversarial' / 'classification.json'),
    ]


def grade_classification(case: dict, clf, errors) -> dict:
    """Field-by-field match of a SchemaClassification against a case's expectations. Pure."""
    dimension_names = {d.column for d in clf.dimension_columns}
    rejected_names = {r.column for r in clf.rejected_columns}
    return {
        'case': case['name'],
        'classification': clf,
        'validation_errors': errors,
        'grounded': not errors,
        'requires_human_review': bool(clf.requires_human_review),
        'date_column_match': clf.date_column == case['expected_date_column'],
        'grain_match': clf.grain == case['expected_grain'],
        'metric_columns_match': set(clf.metric_columns) == case['expected_metric_columns'],
        'dimension_columns_match': dimension_names == case['expected_dimension_columns'],
        'rejected_columns_match': rejected_names == case['expected_rejected_columns'],
        'diff': {
            'metric_columns': _set_diff(set(clf.metric_columns), case['expected_metric_columns']),
            'dimension_columns': _set_diff(dimension_names, case['expected_dimension_columns']),
            'rejected_columns': _set_diff(rejected_names, case['expected_rejected_columns']),
        },
    }


def _set_diff(got: set, expected: set) -> dict:
    return {'missing': sorted(expected - got), 'extra': sorted(got - expected)}


def run_case(case: dict) -> dict:
    if 'df' in case:
        df = case['df']
    else:
        from onboarding.onboard import _read_csv_robust
        df = _read_csv_robust(str(case['csv']))
    profiles = profile_columns(df)
    clf = classify_columns_with_validation(profiles)
    return grade_classification(case, clf, validate_classification(clf, profiles))


def metrics_of(results: list) -> dict:
    n = len(results)
    out = {f'{f}_match_rate': shared.rate(sum(r[f'{f}_match'] for r in results), n) for f in FIELDS}
    out['all_fields_match_rate'] = shared.rate(sum(all(r[f'{f}_match'] for f in FIELDS) for r in results), n)
    out['grounded_rate'] = shared.rate(sum(r['grounded'] for r in results), n)
    out['human_review_rate'] = shared.rate(sum(r['requires_human_review'] for r in results), n)
    return out


def failing(results: list) -> list:
    out = []
    for r in results:
        wrong = [f for f in FIELDS if not r[f'{f}_match']]
        if wrong:
            detail = {f: r['diff'][f] for f in wrong if f in r['diff']}
            out.append({'id': f"{r['case']}#{r.get('run_index', 0)}", 'expected': 'every field matches',
                        'actual': f'mismatch: {wrong} {detail}', 'trace': None})
    return out


def report(results: list, skipped: list, metrics: dict, baseline, context: dict) -> str:
    deltas = shared.compare(metrics, baseline, lower_is_better=('human_review_rate',))
    lines = [f"Onboarding eval — {context['ts']} — {len(context['datasets'])} datasets x "
             f"{context['runs_per_dataset']} runs"
             + (f" ({', '.join(skipped)} skipped: input missing)" if skipped else ''),
             '\n1. Question: Can it understand an unseen dataset?', '2. Result:']
    lines += [f'   {shared.fmt(k, v)}' for k, v in metrics.items()]
    for r in results:
        fields = ', '.join(f"{f}={'ok' if r[f + '_match'] else 'MISS'}" for f in FIELDS)
        lines.append(f"   {r['case']}#{r.get('run_index', 0)}: {fields}"
                     f"; review={r['requires_human_review']}; expected {r.get('provenance', '')}")
    lines.append('3. Against baseline:')
    lines += shared.baseline_lines(metrics, baseline, deltas)
    lines.append(f"4. What changed: git {context['git_sha']}, model {context['model']}, "
                 f"prompt {context['prompt_hash']}")
    if baseline:
        lines.append(f"   baseline: git {baseline.get('git_sha')}, model {baseline.get('model')}, "
                     f"prompt {baseline.get('prompt_hash')}")
    fails = failing(results)
    lines.append(f'5. Failing cases ({len(fails)}):')
    lines += [f"   {f['id']}: {f['actual']}" for f in fails]
    return '\n'.join(lines)


def _prompt_hash() -> str:
    import hashlib
    import inspect
    from onboarding import prompts
    return hashlib.sha256(inspect.getsource(prompts).encode()).hexdigest()[:12]


CONTEXT_KEYS = ('ts', 'git_sha', 'model', 'prompt_hash', 'datasets', 'runs_per_dataset')


def main(argv=None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Onboarding eval (real LLM calls, one per dataset)')
    parser.add_argument('--runs', type=int, default=2,
                        help='Classifications per dataset. The model varies run to run, so one is a coin flip')
    parser.add_argument('--set-baseline', action='store_true')
    parser.add_argument('--no-ledger', action='store_true')
    args = parser.parse_args(argv)

    results, skipped = [], []
    for case in all_cases():
        if 'csv' in case and not case['csv'].exists():
            skipped.append(case['name'])
            continue
        for i in range(args.runs):
            print(f"classifying {case['name']} (run {i + 1}/{args.runs})...")
            r = run_case(case)
            r['provenance'] = case.get('provenance')
            r['run_index'] = i
            results.append(r)
    metrics = metrics_of(results)
    context = {'ts': shared.now_iso(), 'git_sha': shared.git_sha_dirty(), 'model': settings.GROQ_MODEL,
               'prompt_hash': _prompt_hash(), 'datasets': sorted({r['case'] for r in results}),
               'runs_per_dataset': args.runs}
    baseline = shared.load_baseline('onboarding')
    print('\n' + report(results, skipped, metrics, baseline, context))
    row = {**context, 'eval': 'onboarding',
           'sets': {'datasets': len(context['datasets']), 'runs': len(results), 'skipped': skipped},
           'metrics': metrics, 'failing': failing(results)}
    if not args.no_ledger:
        print(f'\nLedger: appended to {shared.append_ledger(row)}')
    if args.set_baseline:
        print(f'Baseline: written to {shared.write_baseline(row, CONTEXT_KEYS)}')


def run_golden_case_2() -> dict:
    case = GOLDEN_CASE_2
    profiles = profile_columns(case['df'])
    clf = classify_columns_with_validation(profiles)
    errors = validate_classification(clf, profiles)

    dimension_names = {d.column for d in clf.dimension_columns}
    rejected_names = {r.column for r in clf.rejected_columns}

    return {
        'case': case['name'],
        'classification': clf,
        'validation_errors': errors,
        'grounded': not errors,
        'date_column_match': clf.date_column == case['expected_date_column'],
        'grain_match': clf.grain == case['expected_grain'],
        'metric_columns_match': set(clf.metric_columns) == case['expected_metric_columns'],
        'dimension_columns_match': dimension_names == case['expected_dimension_columns'],
        'rejected_columns_match': rejected_names == case['expected_rejected_columns'],
    }


if __name__ == '__main__':
    main()
