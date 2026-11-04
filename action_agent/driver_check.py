"""
Is there one segment worth paging its owner about? (docs/action-agent-scope.md §14.8)

A segment's `contribution_pct` alone can't answer that: on Olist, Credit Card is ~80% of the volume, so
it is ~80% of almost every change, including Black Friday and every Monday. The proposer read that as
"one segment clearly drives the change" and notified payments-team (the A5 misses g03, g05, g08).
This compares each contributor's share of the change with its share of the previous day:

    share_of_previous_pct = previous_value / dimension total_previous * 100
    excess_pct            = contribution_pct - share_of_previous_pct

A segment that moved with everything else has an excess near 0. A clear driver is a segment that is
most of the change AND moved out of proportion to its size:

    contribution_pct >= MIN_CONTRIBUTION_PCT and excess_pct >= MIN_EXCESS_PCT

and no driver is reported for a dimension whose net change is under MIN_NET_CHANGE_PCT, where
contribution percentages divide by a near-zero total and offsetting segments look like drivers (g09:
+3.4%, 11 orders, South +138% vs. Southeast -131%).

The thresholds (50 / 15 / 10) were set with the golden set in view and approved by Kousik before the
re-run (§14.8); they are not tuned after it. Pure functions, computed in code, never by the model.
"""

from typing import Dict, List, Optional

MIN_CONTRIBUTION_PCT = 50.0
MIN_EXCESS_PCT = 15.0
MIN_NET_CHANGE_PCT = 10.0


def share_of_previous(contributor: Dict, total_previous) -> Optional[float]:
    """The segment's share of the dimension's previous-day total, in percent. None when the total
    isn't positive (e.g. a profit that was negative the day before), where a share means nothing."""
    try:
        total = float(total_previous)
        previous = float(contributor.get('previous_value') or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return round(previous / total * 100, 1)


def annotate_contributors(dimension: Dict) -> List[Dict]:
    """The dimension's top contributors, each with `share_of_previous_pct` and `excess_pct` added
    (None when the share is undefined)."""
    out = []
    for c in dimension.get('top_contributors') or []:
        share = share_of_previous(c, dimension.get('total_previous'))
        contribution = c.get('contribution_pct')
        excess = None if share is None or contribution is None else round(float(contribution) - share, 1)
        out.append({**c, 'share_of_previous_pct': share, 'excess_pct': excess})
    return out


def driver_check(evidence: Dict) -> Dict:
    """{'clear_driver': {dimension, segment, contribution_pct, share_of_previous_pct, excess_pct} | None,
        'reason': 'driver' | 'proportional' | 'small_net_change' | 'no_evidence',
        'thresholds': {...}}

    Among the qualifying segments of every dimension, the clear driver is the one with the largest
    excess (then the largest contribution)."""
    thresholds = {'min_contribution_pct': MIN_CONTRIBUTION_PCT, 'min_excess_pct': MIN_EXCESS_PCT,
                  'min_net_change_pct': MIN_NET_CHANGE_PCT}
    dims = {name: d for name, d in (evidence.get('dimensions') or {}).items() if 'error' not in d}
    if not dims:
        return {'clear_driver': None, 'reason': 'no_evidence', 'thresholds': thresholds}

    candidates, sized = [], 0
    for name, d in dims.items():
        net = d.get('total_change_pct')
        if net is None or abs(float(net)) < MIN_NET_CHANGE_PCT:
            continue
        sized += 1
        for c in annotate_contributors(d):
            excess, contribution = c['excess_pct'], c.get('contribution_pct')
            if excess is None or contribution is None:
                continue
            if float(contribution) >= MIN_CONTRIBUTION_PCT and excess >= MIN_EXCESS_PCT:
                candidates.append({'dimension': name, 'segment': c['segment'],
                                   'contribution_pct': round(float(contribution), 1),
                                   'share_of_previous_pct': c['share_of_previous_pct'], 'excess_pct': excess})
    if not sized:
        return {'clear_driver': None, 'reason': 'small_net_change', 'thresholds': thresholds}
    if not candidates:
        return {'clear_driver': None, 'reason': 'proportional', 'thresholds': thresholds}
    best = max(candidates, key=lambda c: (c['excess_pct'], c['contribution_pct']))
    return {'clear_driver': best, 'reason': 'driver', 'thresholds': thresholds}
