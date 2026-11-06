"""
Detection eval (docs/action-agent-scope.md §7.1, §7.3; milestone A7): does MetricPulse alarm at
the right times?

It grades the production decision, replayed. The pipeline judges the latest day against the
LOOKBACK_DAYS rows ending at it (fetch_daily_metrics' LIMIT), so for a labelled date D this
rebuilds exactly that window ending at D, runs the unchanged detect_anomalies, and reads D's
flag. No LLM: the run is free and deterministic.

    python -m detection.eval --candidates   # write evals/detection/labels.yaml (refuses to overwrite labels)
    python -m detection.eval --check        # are the labels complete?
    python -m detection.eval                # grade, print the §7.2 report, append to evals/ledger.jsonl
    python -m detection.eval --set-baseline # also accept this run as evals/baselines/detection.json

The agent picks the candidates; Kousik labels them (D6's rule). The candidates file shows each
date's value against its prior week, never the detector's z-score or flag.
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from config import settings  # noqa: E402
from detection.anomaly_detector import detect_anomalies  # noqa: E402
from observability import evals as shared  # noqa: E402

LABELS_PATH = shared.EVALS_DIR / 'detection' / 'labels.yaml'
QUESTION = 'Does it alarm at the right times?'
SWEEP = [round(1.5 + 0.25 * i, 2) for i in range(9)]   # 1.5 .. 3.5
MIN_LABELS = 20

# (dataset_id, metric, strongest, near-threshold, ordinary). Calendar dates are added on top.
PLAN = [('olist', 'total_revenue', 3, 2, 2), ('olist', 'order_count', 2, 1, 1),
        ('superstore_sales', 'sales', 3, 2, 2), ('superstore_sales', 'profit', 2, 1, 1)]
CALENDAR = {'olist': ['2017-11-24', '2017-12-25', '2018-01-01'],          # Black Friday, Christmas, New Year
            'superstore_sales': ['2011-11-25', '2011-12-25', '2012-01-01']}
CALENDAR_METRICS = {'olist': 'total_revenue', 'superstore_sales': 'sales'}
ALWAYS = [('olist', 'total_revenue', '2018-09-03')]   # the scoping doc's Golden Case #1 date
NEAR_BAND = (1.5, 2.5)
ORDINARY_MAX = 1.0
SEED = 7

HEADER = """\
# Detection eval labels (docs/action-agent-scope.md §7.1, §7.3). Real dates from Olist and Superstore.
#
# FOR KOUSIK TO LABEL. For each case, set:
#   is_event: true   if you'd want MetricPulse to alert on this metric that day
#             false  if an alert that day would be noise
#   notes:    optional, why.
#
# Judge from the numbers shown: the day's value, the day before, and the 7 rows before it.
# The agent chose the dates (strong moves, borderline ones, ordinary days and calendar dates)
# but didn't label them, and this file deliberately doesn't show what the detector decided.
# Rows are trading days present in the data, so "the day before" can be several calendar days
# earlier where the data has a gap.
"""


# --------------------------------------------------------------------------- the replayed decision

def load_series(dataset_id: str, metric: str) -> pd.DataFrame:
    """Every row of the dataset's daily fact table, oldest first, with metric_date as a string."""
    from action_agent.evidence import dataset_config
    from detection.anomaly_detector import fetch_daily_metrics
    cfg = dataset_config(dataset_id)
    df = fetch_daily_metrics(1_000_000, cfg['metric_columns'], cfg['table_name'], cfg['connection_factory'])
    df = df[['metric_date', metric]].copy()
    df['metric_date'] = df['metric_date'].astype(str).str[:10]
    return df.sort_values('metric_date').reset_index(drop=True)


def load_volume(dataset_id: str) -> pd.DataFrame:
    """Every row's record volume (order_count / row_count) for the §15 freshness check."""
    from action_agent.evidence import dataset_config
    from detection.anomaly_detector import fetch_daily_metrics
    from detection.freshness import volume_column
    cfg = dataset_config(dataset_id)
    df = fetch_daily_metrics(1_000_000, cfg['metric_columns'], cfg['table_name'], cfg['connection_factory'])
    col = volume_column(df.columns)
    return df[['metric_date'] + ([col] if col else [])].copy()


def replay(series: pd.DataFrame, metric: str, date: str, threshold: float,
           lookback: int = settings.LOOKBACK_DAYS) -> Optional[Dict]:
    """The pipeline's decision on `date`, had it been the latest day: the `lookback` rows ending at
    it, through the unchanged detect_anomalies. None if the date isn't in the data."""
    upto = series[series['metric_date'] <= date]
    if upto.empty or upto['metric_date'].iloc[-1] != date:
        return None
    window = upto.tail(lookback)
    out = detect_anomalies(window, metric, threshold).iloc[-1]
    z = out['zscore']
    return {'zscore': None if pd.isna(z) else round(float(z), 3), 'flagged': bool(out['is_anomaly']),
            'window_rows': len(window)}


def replay_all(series: pd.DataFrame, metric: str, threshold: float,
               lookback: int = settings.LOOKBACK_DAYS) -> pd.DataFrame:
    """replay() for every date with a full window."""
    rows = []
    for i in range(lookback - 1, len(series)):
        d = series['metric_date'].iloc[i]
        r = replay(series.iloc[:i + 1], metric, d, threshold, lookback)
        rows.append({'metric_date': d, **r})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- grading (pure)

def confusion(cases: List[Dict], flagged: Dict[str, bool]) -> Dict[str, int]:
    """cases carry 'id' and 'is_event'; flagged maps id -> the replayed flag."""
    c = {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0}
    for case in cases:
        f, e = flagged[case['id']], bool(case['is_event'])
        c['tp' if f and e else 'fp' if f else 'fn' if e else 'tn'] += 1
    return c


def scores(c: Dict[str, int]) -> Dict[str, Dict]:
    flagged, events = c['tp'] + c['fp'], c['tp'] + c['fn']
    precision = shared.rate(c['tp'], flagged)
    recall = shared.rate(c['tp'], events)
    p, r = precision['value'], recall['value']
    f1 = 2 * p * r / (p + r) if p is not None and r is not None and (p + r) > 0 else (0.0 if p is not None
                                                                                        and r is not None else None)
    n = sum(c.values())
    return {'detection_precision': precision, 'detection_recall': recall,
            'detection_f1': shared.value(f1, n),
            'false_alarms': shared.count(c['fp'], n), 'missed_events': shared.count(c['fn'], n)}


def with_freshness(cases: List[Dict], zscores: Dict[str, Optional[float]], stale: Dict[str, bool],
                   threshold: float) -> Dict:
    """§15: the pipeline's alert decision once the freshness check exists: flagged by the z-score OR
    stale. Reported next to the z-score-only headline (which stays comparable with its baseline)."""
    flagged = {cid: (z is not None and abs(z) > threshold) or bool(stale.get(cid)) for cid, z in zscores.items()}
    c = confusion(cases, flagged)
    s = scores(c)
    metrics = {'with_freshness_precision': s['detection_precision'], 'with_freshness_recall': s['detection_recall'],
               'with_freshness_f1': s['detection_f1']}
    failing = [k['id'] for k in cases if flagged[k['id']] != bool(k['is_event'])]
    return {'confusion': c, 'metrics': metrics, 'failing': failing,
            'stale': sorted(cid for cid, v in stale.items() if v)}


def grade(cases: List[Dict], zscores: Dict[str, Optional[float]], threshold: float) -> Dict:
    """Flags at `threshold` from each case's replayed z (strictly above, as detect_anomalies), the
    headline scores, the per-threshold sweep and the failing cases."""
    def flags(t):
        return {cid: z is not None and abs(z) > t for cid, z in zscores.items()}
    c = confusion(cases, flags(threshold))
    sweep = []
    for t in SWEEP:
        ct = confusion(cases, flags(t))
        s = scores(ct)
        sweep.append({'threshold': t, **ct, 'precision': s['detection_precision']['value'],
                      'recall': s['detection_recall']['value'], 'f1': s['detection_f1']['value']})
    at = flags(threshold)
    failing = [{'id': k['id'], 'expected': 'event' if k['is_event'] else 'no event',
                'actual': f"{'flagged' if at[k['id']] else 'not flagged'} (z={zscores[k['id']]})",
                'case': f"{k['dataset_id']}/{k['metric']}/{k['date']}", 'trace': None}
               for k in cases if at[k['id']] != bool(k['is_event'])]
    return {'confusion': c, 'metrics': scores(c), 'sweep': sweep, 'failing': failing}


# --------------------------------------------------------------------------- candidates

def _context(series: pd.DataFrame, metric: str, date: str) -> Dict:
    upto = series[series['metric_date'] <= date]
    val = float(upto[metric].iloc[-1])
    prior = upto.iloc[-8:-1]
    prev_date, prev = None, None
    if len(prior):
        prev_date, prev = str(prior['metric_date'].iloc[-1]), float(prior[metric].iloc[-1])
    median7 = float(prior[metric].median()) if len(prior) else None

    def pct(a, b):
        return None if b in (None, 0) else round((a - b) / abs(b) * 100, 1)
    return {'value': round(val, 2),
            'previous_row': {'date': prev_date, 'value': None if prev is None else round(prev, 2)},
            'change_vs_previous_pct': pct(val, prev), 'median_prior_7': None if median7 is None else round(median7, 2),
            'change_vs_median_pct': pct(val, median7),
            'prior_7': [round(float(v), 2) for v in prior[metric]]}


def pick(replayed: pd.DataFrame, strongest: int, near: int, ordinary: int, seed: int = SEED) -> List[Tuple[str, str]]:
    """(date, why) choices from a replay_all frame. Deterministic."""
    r = replayed.dropna(subset=['zscore']).assign(absz=lambda d: d['zscore'].abs())
    chosen: List[Tuple[str, str]] = []
    taken = set()

    def add(dates, why):
        for d in dates:
            if d not in taken:
                taken.add(d)
                chosen.append((d, why))

    add(r.sort_values(['absz', 'metric_date'], ascending=[False, True])['metric_date'].head(strongest), 'strongest')
    band = r[(r['absz'] >= NEAR_BAND[0]) & (r['absz'] <= NEAR_BAND[1]) & ~r['metric_date'].isin(taken)]
    rng = np.random.default_rng(seed)
    if len(band):
        add(sorted(rng.choice(band['metric_date'].to_numpy(), size=min(near, len(band)), replace=False)), 'near')
    calm = r[(r['absz'] < ORDINARY_MAX) & ~r['metric_date'].isin(taken)]
    if len(calm):
        add(sorted(rng.choice(calm['metric_date'].to_numpy(), size=min(ordinary, len(calm)), replace=False)),
            'ordinary')
    return chosen


def build_candidates(threshold: float = settings.ANOMALY_THRESHOLD_ZSCORE) -> List[Dict]:
    picks = []   # (dataset_id, metric, date)
    series_cache = {}
    for dataset_id, metric, strongest, near, ordinary in PLAN:
        series = series_cache.setdefault((dataset_id, metric), load_series(dataset_id, metric))
        for d, _ in pick(replay_all(series, metric, threshold), strongest, near, ordinary):
            picks.append((dataset_id, metric, d))
    for dataset_id, dates in CALENDAR.items():
        metric = CALENDAR_METRICS[dataset_id]
        series = series_cache.setdefault((dataset_id, metric), load_series(dataset_id, metric))
        for d in dates:
            if d in set(series['metric_date']) and (dataset_id, metric, d) not in picks:
                picks.append((dataset_id, metric, d))
    for dataset_id, metric, d in ALWAYS:
        series_cache.setdefault((dataset_id, metric), load_series(dataset_id, metric))
        if (dataset_id, metric, d) not in picks:
            picks.append((dataset_id, metric, d))
    # Order by dataset/metric/date so a case's position reveals nothing about why it was picked.
    cases = []
    for i, (dataset_id, metric, d) in enumerate(sorted(set(picks)), start=1):
        series = series_cache[(dataset_id, metric)]
        cases.append({'id': f'd{i:02d}', 'dataset_id': dataset_id, 'metric': metric, 'date': d,
                      **_context(series, metric, d), 'is_event': None, 'notes': None})
    return cases


# --------------------------------------------------------------------------- labels

def load_labels(path: Path = LABELS_PATH) -> List[Dict]:
    return yaml.safe_load(Path(path).read_text()) or [] if Path(path).exists() else []


def label_errors(cases: List[Dict]) -> List[str]:
    errors = [f"{c['id']}: is_event must be true or false" for c in cases if not isinstance(c.get('is_event'), bool)]
    if len(cases) < MIN_LABELS:
        errors.append(f'only {len(cases)} cases; §7.1 needs at least {MIN_LABELS}')
    return errors


# --------------------------------------------------------------------------- run

def run(cases: List[Dict], threshold: float, series_loader=load_series, volume_loader=load_volume) -> Dict:
    from detection.freshness import check_freshness
    zscores, missing, stale = {}, [], {}
    cache, volumes = {}, {}
    for c in cases:
        if c['dataset_id'] not in volumes:
            volumes[c['dataset_id']] = volume_loader(c['dataset_id'])
        stale[c['id']] = check_freshness(volumes[c['dataset_id']], date=c['date'])['status'] == 'stale'
        key = (c['dataset_id'], c['metric'])
        if key not in cache:
            cache[key] = series_loader(*key)
        r = replay(cache[key], c['metric'], c['date'], threshold)
        if r is None:
            missing.append(c['id'])
        zscores[c['id']] = None if r is None else r['zscore']
    graded = grade(cases, zscores, threshold)
    graded['missing'] = missing
    graded['zscores'] = zscores
    combined = with_freshness(cases, zscores, stale, threshold)
    graded['metrics'] = {**graded['metrics'], **combined['metrics']}
    graded['with_freshness'] = combined
    return graded


def report(result: Dict, baseline: Optional[Dict], context: Dict) -> str:
    m = result['metrics']
    deltas = shared.compare(m, baseline, lower_is_better=('false_alarms', 'missed_events'),
                            higher_is_better=('detection_precision', 'detection_recall', 'detection_f1',
                                              'with_freshness_precision', 'with_freshness_recall', 'with_freshness_f1'))
    lines = [f"Detection eval — {context['ts']} — {context['n']} labelled dates, threshold {context['threshold']}, "
             f"lookback {context['lookback_days']} rows",
             f'\n1. Question: {QUESTION}', '2. Result:']
    lines += [f'   {shared.fmt(k, v)}' for k, v in m.items()]
    c = result['confusion']
    lines.append(f"   confusion: {c['tp']} caught, {c['fp']} false alarms, {c['fn']} missed, {c['tn']} correctly quiet")
    if 'with_freshness' in result:
        w = result['with_freshness']
        cw = w['confusion']
        lines.append(f"   with the §15 freshness check (z-score OR stale): {cw['tp']} caught, {cw['fp']} false alarms, "
                     f"{cw['fn']} missed; stale: {', '.join(w['stale']) or 'none'}; "
                     f"still wrong: {', '.join(w['failing']) or 'none'}")
    lines.append('   threshold sweep (z-score only; reported, not gated):')
    lines.append('     thr    tp  fp  fn  tn  precision  recall   f1')
    for s in result['sweep']:
        def f(x):
            return '  n/a' if x is None else f'{x:.2f}'
        mark = '  <- configured' if s['threshold'] == context['threshold'] else ''
        lines.append(f"     {s['threshold']:<5} {s['tp']:>3} {s['fp']:>3} {s['fn']:>3} {s['tn']:>3}   "
                     f"{f(s['precision']):>7}  {f(s['recall']):>6}  {f(s['f1']):>5}{mark}")
    lines.append('3. Against baseline:')
    lines += shared.baseline_lines(m, baseline, deltas)
    lines.append(f"4. What changed: git {context['git_sha']}, threshold {context['threshold']}, "
                 f"lookback {context['lookback_days']}, labels {context['labels_hash']}")
    if baseline:
        lines.append(f"   baseline: git {baseline.get('git_sha')}, threshold {baseline.get('threshold')}, "
                     f"lookback {baseline.get('lookback_days')}, labels {baseline.get('labels_hash')}")
    lines.append(f"5. Failing cases ({len(result['failing'])}):")
    for f_ in result['failing']:
        lines.append(f"   {f_['id']} {f_['case']}: expected {f_['expected']}; got {f_['actual']}")
    if result['missing']:
        lines.append(f"   not in the data (not graded as a pass): {', '.join(result['missing'])}")
    return '\n'.join(lines)


def labels_hash(path: Path = LABELS_PATH) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12] if Path(path).exists() else 'none'


CONTEXT_KEYS = ('ts', 'git_sha', 'threshold', 'lookback_days', 'labels_hash', 'n')


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Detection eval (no LLM calls)')
    parser.add_argument('--candidates', action='store_true', help='Write the candidate dates for labelling')
    parser.add_argument('--check', action='store_true', help='Validate the labels')
    parser.add_argument('--path', type=Path, default=LABELS_PATH)
    parser.add_argument('--threshold', type=float, default=settings.ANOMALY_THRESHOLD_ZSCORE)
    parser.add_argument('--set-baseline', action='store_true')
    parser.add_argument('--no-ledger', action='store_true')
    args = parser.parse_args(argv)

    if args.candidates:
        if any(isinstance(c.get('is_event'), bool) for c in load_labels(args.path)):
            sys.exit(f'{args.path} already has labels; not overwriting it.')
        cases = build_candidates(args.threshold)
        args.path.parent.mkdir(parents=True, exist_ok=True)
        args.path.write_text(HEADER + '\n' + yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=110))
        print(f'Wrote {len(cases)} candidate dates to {args.path}. Label is_event, then: '
              f'python -m detection.eval --check')
        return

    cases = load_labels(args.path)
    errors = label_errors(cases)
    if args.check or errors:
        print('\n'.join(errors) if errors else f'{len(cases)} cases, all labelled.')
        sys.exit(1 if errors else 0)

    result = run(cases, args.threshold)
    context = {'ts': shared.now_iso(), 'git_sha': shared.git_sha_dirty(), 'threshold': args.threshold,
               'lookback_days': settings.LOOKBACK_DAYS, 'labels_hash': labels_hash(args.path), 'n': len(cases)}
    baseline = shared.load_baseline('detection')
    print(report(result, baseline, context))
    row = {**context, 'eval': 'detection', 'sets': {'labelled': len(cases)}, 'metrics': result['metrics'],
           'sweep': result['sweep'], 'failing': result['failing']}
    if not args.no_ledger:
        print(f'\nLedger: appended to {shared.append_ledger(row)}')
    if args.set_baseline:
        print(f"Baseline: written to {shared.write_baseline(row, CONTEXT_KEYS)}")


if __name__ == '__main__':
    main()
