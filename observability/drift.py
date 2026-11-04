"""
The drift run (docs/action-agent-scope.md §7.1 "Has anything silently gotten worse?", §7.3):
runs every eval that's ready, then reports each eval's newest ledger row against its baseline,
regressions first. It reports; it pages nobody (§13.7). It reads only the committed ledger and
baselines, never LangSmith (14-day trace retention, scope A2 log).

    python -m observability.drift                    # run every ready eval, then report
    python -m observability.drift --report           # report only, from the ledger (free, no runs)
    python -m observability.drift --only detection   # run a subset (comma-separated)
    python -m observability.drift --print-launchd    # print a weekly launchd job for this machine

Cost of a full run: detection is free; onboarding is 3 classifications; investigation is
`--investigation-runs` (default 3) synthesis calls per case, ~10 cases; the action eval is about a
cent (evals/README.md). Scheduling is local because the real-data evals need the local warehouse,
which CI doesn't have (§7.3). Kousik installs the launchd job himself.
"""

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings  # noqa: E402
from observability import evals as shared  # noqa: E402

EVALS = ('detection', 'onboarding', 'investigation', 'action')
LLM_EVALS = ('onboarding', 'investigation', 'action')
COOLDOWN_S = 65


def directions(eval_name: str) -> Dict:
    """How each eval's metrics regress, for shared.compare."""
    if eval_name == 'detection':
        return {'lower_is_better': ('false_alarms', 'missed_events'),
                'higher_is_better': ('detection_precision', 'detection_recall', 'detection_f1')}
    if eval_name == 'investigation':
        return {'lower_is_better': ('fallback_rate', 'api_error_rate')}
    if eval_name == 'onboarding':
        return {'safety': ('api_errors',), 'lower_is_better': ('human_review_rate',)}
    if eval_name == 'action':
        from action_agent.eval import LOWER_IS_BETTER, SAFETY_METRICS
        return {'safety': SAFETY_METRICS, 'lower_is_better': LOWER_IS_BETTER}
    return {}


def readiness() -> Dict[str, Tuple[bool, str]]:
    """{eval: (ready, why)}. Ready means it can run and produce a meaningful row now."""
    from detection.eval import label_errors as det_errors, load_labels
    from investigation.golden import label_errors as inv_errors, load_golden, load_states
    from action_agent.golden import label_errors as act_errors, load_golden as act_golden

    out = {}
    det = det_errors(load_labels())
    out['detection'] = (not det, 'labels complete' if not det else f'{len(det)} label problem(s) in '
                        'evals/detection/labels.yaml')
    out['onboarding'] = (True, '3 datasets (Superstore skipped if its CSV is absent)')
    inv = inv_errors(load_golden(), load_states())
    out['investigation'] = (True, 'all cases' if not inv else 'Golden Case #1 only until the real cases are labelled')
    act = act_errors(act_golden())
    out['action'] = (True, 'golden + adversarial + safety' if not act else 'adversarial + safety (golden unlabelled)')
    return out


def runners(investigation_runs: int) -> Dict[str, Callable[[], None]]:
    def detection():
        from detection.eval import main
        main([])

    def onboarding():
        from onboarding.eval import main
        main([])

    def investigation():
        from investigation.eval import main
        main(['--runs', str(investigation_runs)])

    def action():
        from action_agent.eval import main
        main([])
    return {'detection': detection, 'onboarding': onboarding, 'investigation': investigation, 'action': action}


def api_failures(row: Dict) -> int:
    """How many of a row's LLM calls failed at the API (0 for evals that don't record it)."""
    m = row.get('metrics', {})
    for key in ('api_errors', 'api_error_rate'):
        if key in m and m[key].get('num'):
            return int(m[key]['num'])
    return 0


def latest_rows(rows: List[Dict]) -> Dict[str, Dict]:
    out = {}
    for row in rows:
        out[row.get('eval', 'action')] = row     # rows before A7 have no 'eval' only if hand-written
    return out


def drift_report(rows: List[Dict], baselines: Dict[str, Optional[Dict]], ran: List[str],
                 failed: Dict[str, str]) -> Tuple[str, int]:
    """(report text, regression count). Pure: rows and baselines are passed in."""
    latest = latest_rows(rows)
    regressions, steady, lines, invalid = [], [], [], []
    for name in EVALS:
        row = latest.get(name)
        if row is None:
            continue
        api = api_failures(row)
        if api:
            # A run whose LLM calls failed (rate limit, daily quota, network) measured the API, not the
            # model: its quality numbers aren't comparable, so it can't regress anything (BUG_LOG A7-5).
            invalid.append((name, api, row))
            continue
        deltas = shared.compare(row['metrics'], baselines.get(name), **directions(name))
        for metric, d in deltas.items():
            entry = (name, metric, d, row)
            (regressions if d['regressed'] else steady).append(entry)

    lines.append(f"Drift report — {shared.now_iso()} — ran: {', '.join(ran) or 'nothing (report only)'}")
    for name, err in failed.items():
        lines.append(f'   {name}: FAILED to run: {err}')
    if invalid:
        lines.append(f'\nInvalid runs, not compared ({len(invalid)}):')
        for name, api, row in invalid:
            lines.append(f"   {name}: {api} API call(s) failed [git {row.get('git_sha')}, {row.get('ts')}]; "
                         f"re-run when the API is available (Groq's daily cap: see evals/README.md)")
    lines.append(f'\nRegressions ({len(regressions)}):')
    for name, metric, d, row in regressions:
        lines.append(f"   {name}.{metric}: {d['baseline']} -> {row['metrics'][metric]['value']} ({d['delta']:+})"
                     f"  [git {row.get('git_sha')}, {row.get('ts')}]")
    if not regressions:
        lines.append('   none')
    lines.append('\nPer eval (newest row vs. baseline):')
    for name in EVALS:
        row = latest.get(name)
        if row is None:
            lines.append(f'   {name}: no ledger row yet')
            continue
        base = baselines.get(name)
        status = 'no baseline yet' if not base else f"baseline git {base.get('git_sha')}"
        lines.append(f"   {name}: newest {row.get('ts')} git {row.get('git_sha')}; {status}")
        for metric, m in row['metrics'].items():
            if m.get('value') is None:
                continue
            lines.append(f'      {shared.fmt(metric, m)}')
    return '\n'.join(lines), len(regressions) + len(invalid)


LAUNCHD = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- MetricPulse weekly drift run (docs/action-agent-scope.md §7.3). Install yourself:
       python -m observability.drift --print-launchd > ~/Library/LaunchAgents/com.metricpulse.drift.plist
       launchctl load ~/Library/LaunchAgents/com.metricpulse.drift.plist
     Remove with launchctl unload on the same path. Output goes to logs/drift.log. -->
<plist version="1.0">
<dict>
  <key>Label</key><string>com.metricpulse.drift</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string><string>-m</string><string>observability.drift</string>
  </array>
  <key>WorkingDirectory</key><string>{root}</string>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>{root}/logs/drift.log</string>
  <key>StandardErrorPath</key><string>{root}/logs/drift.log</string>
</dict>
</plist>
"""


def main(argv=None, sleep_fn=None) -> None:
    parser = argparse.ArgumentParser(description='Run every ready eval and report drift against baselines')
    parser.add_argument('--report', action='store_true', help='Report from the ledger only; run nothing')
    parser.add_argument('--only', help=f"Comma-separated subset of {', '.join(EVALS)}")
    parser.add_argument('--investigation-runs', type=int, default=3)
    parser.add_argument('--print-launchd', action='store_true', help='Print a weekly launchd job for this machine')
    args = parser.parse_args(argv)
    import time
    sleep_fn = sleep_fn or time.sleep

    if args.print_launchd:
        print(LAUNCHD.format(python=sys.executable, root=settings.PROJECT_ROOT), end='')
        return

    ran, failed = [], {}
    if not args.report:
        wanted = [e.strip() for e in (args.only or ','.join(EVALS)).split(',') if e.strip()]
        ready = readiness()
        run = runners(args.investigation_runs)
        last_llm = None
        for name in wanted:
            ok, why = ready[name]
            if ok and name in LLM_EVALS and last_llm is not None:
                # Each eval paces itself, but not against the one before it: let Groq's per-minute
                # window empty first (BUG_LOG A7-5).
                print(f'== waiting {COOLDOWN_S}s after {last_llm} for the rate-limit window')
                sleep_fn(COOLDOWN_S)
            print(f'== {name}: {why}' if ok else f'== {name}: skipped, {why}')
            if not ok:
                continue
            if name in LLM_EVALS:
                last_llm = name
            try:
                run[name]()
                ran.append(name)
            except SystemExit as e:      # an eval's own refusal (e.g. labels) ends that eval, not the run
                if e.code not in (0, None):
                    failed[name] = f'exited {e.code}'
                else:
                    ran.append(name)
            except Exception as e:       # one broken eval must not hide the others' drift
                failed[name] = f'{type(e).__name__}: {e}'
    text, n_regressed = drift_report(shared.read_ledger(), {e: shared.load_baseline(e) for e in EVALS}, ran, failed)
    print('\n' + text)
    sys.exit(1 if n_regressed or failed else 0)


if __name__ == '__main__':
    main()
