"""
Plumbing shared by every eval (docs/action-agent-scope.md §7.2, §7.3, §13.5): metric shapes, the
committed ledger, per-eval baselines and the baseline comparison. One module so the detection,
investigation, onboarding and action evals record and compare the same way.

    rate(3, 4)  -> {'value': 0.75, 'num': 3, 'n': 4}
    count(0, 10) -> {'value': 0, 'num': 0, 'n': 10}

A ledger row is {'ts', 'eval', 'git_sha', ..., 'metrics': {name: {value, num, n}}, 'failing': [...]}.
A baseline file holds the accepted row's context plus {'metrics': {name: value}}.
"""

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from config import settings

EVALS_DIR = settings.PROJECT_ROOT / 'evals'
LEDGER_PATH = EVALS_DIR / 'ledger.jsonl'
BASELINES_DIR = EVALS_DIR / 'baselines'
OUTPUT_PATHS = ('evals/ledger.jsonl', 'evals/baselines')
RATE_REGRESSION = 0.1   # a rate moving the wrong way by more than this vs. baseline is flagged


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def git_sha_dirty(root: Optional[Path] = None) -> str:
    """HEAD's short SHA, with `-dirty` when tracked files have uncommitted changes, so a ledger row
    never claims a commit the run didn't actually use.

    The eval outputs (the ledger and the baselines) don't count: they're tracked, so otherwise the
    first eval's own ledger row would mark every later eval in the same session (or drift run)
    dirty (BUG_LOG A7-3). Labels and code still count."""
    from observability.tracing import git_sha
    sha = git_sha()
    try:
        dirty = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no', '--', '.']
                               + [f':(exclude){p}' for p in OUTPUT_PATHS],
                               cwd=root or settings.PROJECT_ROOT, capture_output=True, text=True,
                               timeout=5).stdout.strip()
    except Exception:
        dirty = ''
    return f'{sha}-dirty' if dirty else sha


def rate(num: int, n: int) -> Dict:
    return {'value': round(num / n, 4) if n else None, 'num': num, 'n': n}


def count(num: int, n: int) -> Dict:
    return {'value': num, 'num': num, 'n': n}


def value(v: Optional[float], n: int) -> Dict:
    """A reported number that isn't a ratio of counts (an F1, a cost, a latency)."""
    return {'value': None if v is None else round(v, 4), 'num': None, 'n': n}


def p95(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)], 2)


def fmt(name: str, m: Dict) -> str:
    v = m['value']
    if v is None:
        return f'{name} = n/a (n={m["n"]})'
    if m.get('num') is not None and (name.endswith('_rate') or name.endswith(('_precision', '_recall'))):
        return f'{name} = {v:.2f} ({m["num"]}/{m["n"]})'
    return f'{name} = {v} (n={m["n"]})'


def compare(metrics: Dict[str, Dict], baseline: Optional[Dict], *, safety: Iterable[str] = (),
            lower_is_better: Iterable[str] = (), higher_is_better: Optional[Iterable[str]] = None
            ) -> Dict[str, Dict]:
    """Each metric against the baseline's value: {name: {baseline, delta, regressed}}.

    - `safety` counts regress on any increase.
    - `lower_is_better` regresses when it rises by more than RATE_REGRESSION.
    - otherwise a `*_rate` (or anything in `higher_is_better`) regresses when it drops by more
      than RATE_REGRESSION. Other numbers are compared but never flagged."""
    safety, lower = set(safety), set(lower_is_better)
    higher = set(higher_is_better or ())
    out = {}
    base = (baseline or {}).get('metrics', {})
    for name, m in metrics.items():
        if name not in base or m['value'] is None or base[name] is None:
            continue
        delta = round(m['value'] - base[name], 4)
        if name in safety:
            regressed = m['value'] > base[name]
        elif name in lower:
            regressed = delta > RATE_REGRESSION
        elif name in higher or name.endswith('_rate'):
            regressed = delta < -RATE_REGRESSION
        else:
            regressed = False
        out[name] = {'baseline': base[name], 'delta': delta, 'regressed': regressed}
    return out


def baseline_path(eval_name: str, baselines_dir: Path = BASELINES_DIR) -> Path:
    return Path(baselines_dir) / f'{eval_name}.json'


def load_baseline(eval_name: str, baselines_dir: Path = BASELINES_DIR) -> Optional[Dict]:
    path = baseline_path(eval_name, baselines_dir)
    return json.loads(path.read_text()) if path.exists() else None


def write_baseline(row: Dict, context_keys: Iterable[str], baselines_dir: Path = BASELINES_DIR) -> Path:
    path = baseline_path(row['eval'], baselines_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {k: row[k] for k in context_keys if k in row}
    body['metrics'] = {k: v['value'] for k, v in row['metrics'].items()}
    path.write_text(json.dumps(body, indent=2) + '\n')
    return path


def append_ledger(row: Dict, ledger_path: Path = LEDGER_PATH) -> Path:
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, default=str) + '\n')
    return path


def read_ledger(ledger_path: Path = LEDGER_PATH) -> List[Dict]:
    path = Path(ledger_path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def baseline_lines(metrics: Dict[str, Dict], baseline: Optional[Dict], deltas: Dict[str, Dict]) -> List[str]:
    """§7.2 step 3, as report lines."""
    if not baseline:
        return ['   no baseline yet (accept one with --set-baseline)']
    lines = []
    for n in metrics:
        if n in deltas:
            d = deltas[n]
            lines.append(f"   {n}: {d['baseline']} -> {metrics[n]['value']} ({d['delta']:+})"
                         f"{'  REGRESSED' if d['regressed'] else ''}")
    return lines or ['   no metric in common with the baseline']
