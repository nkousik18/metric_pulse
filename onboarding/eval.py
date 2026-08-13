"""
Golden Case #2 (docs/scoping.md Section 5.6) -- run manually. Mirrors the
scope investigation/eval.py had at M1: a golden-case fixture plus a bare
grading run, not the formalized --runs/tracked-metrics command M3 later built
for Phase 1 (docs/ROADMAP.md never names a Phase-2 equivalent milestone for
that formalization -- M4's actual gate is just "Golden Case #2 run for real").

    python -m onboarding.eval
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from onboarding.classification import classify_columns_with_validation, validate_classification  # noqa: E402
from onboarding.profiling import profile_columns  # noqa: E402

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
    result = run_golden_case_2()
    clf = result['classification']

    print(f"case: {result['case']}")
    print(f"date_column={clf.date_column} (match={result['date_column_match']})")
    print(f"grain={clf.grain} (match={result['grain_match']})")
    print(f"metric_columns={clf.metric_columns} (match={result['metric_columns_match']})")
    print(f"dimension_columns={[d.column for d in clf.dimension_columns]} "
          f"(match={result['dimension_columns_match']})")
    print(f"rejected_columns={[(r.column, r.reason) for r in clf.rejected_columns]} "
          f"(match={result['rejected_columns_match']})")
    print(f"requires_human_review={clf.requires_human_review}")
    print(f"validation_errors={result['validation_errors']}")

    all_match = all([
        result['date_column_match'], result['grain_match'], result['metric_columns_match'],
        result['dimension_columns_match'], result['rejected_columns_match'],
    ])
    print(f"\ngrounded={result['grounded']} all_match={all_match}")
