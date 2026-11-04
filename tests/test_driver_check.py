"""
Tests for action_agent/driver_check.py (docs/action-agent-scope.md §14.8): a segment is a clear
driver only when it is most of the change AND moved out of proportion to its normal share, and no
driver is reported for a near-zero net change. Plain dicts in the decompose_metric shape; no mocks.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.driver_check import (  # noqa: E402
    MIN_CONTRIBUTION_PCT, MIN_EXCESS_PCT, MIN_NET_CHANGE_PCT, annotate_contributors, driver_check,
    share_of_previous,
)
from action_agent.llm_proposer import SYSTEM_PROMPT, build_messages  # noqa: E402
from tests.test_llm_proposer import STATE  # noqa: E402


def dim(total_previous, total_change_pct, *contributors):
    return {'total_previous': total_previous, 'total_change_pct': total_change_pct,
            'top_contributors': [{'segment': s, 'previous_value': p, 'contribution_pct': c}
                                 for s, p, c in contributors]}


# g03's payment numbers (Olist, the day after Black Friday): Credit Card is 77.5% of the change
# and ~81.5% of the previous day, so it moved with everything else.
PROPORTIONAL = {'dimensions': {'payment': dim(178_357, -59.72, ('Credit Card', 145_446, 77.5),
                                              ('Boleto', 31_930, 22.3))}}
# g04's: Credit Card is 103.5% of the change but ~79% of the previous day.
OVER_INDEXED = {'dimensions': {'payment': dim(49_350, 30.87, ('Credit Card', 39_107, 103.5),
                                              ('Voucher', 1_074, -6.5), ('Boleto', 8_888, 4.5))}}


def test_thresholds_are_the_approved_ones():
    assert (MIN_CONTRIBUTION_PCT, MIN_EXCESS_PCT, MIN_NET_CHANGE_PCT) == (50.0, 15.0, 10.0)


def test_share_and_excess_per_contributor():
    rows = annotate_contributors(OVER_INDEXED['dimensions']['payment'])
    assert rows[0]['share_of_previous_pct'] == 79.2 and rows[0]['excess_pct'] == 24.3
    assert rows[0]['segment'] == 'Credit Card' and rows[0]['previous_value'] == 39_107


def test_a_big_segment_moving_with_everything_else_is_not_a_driver():
    result = driver_check(PROPORTIONAL)
    assert result['clear_driver'] is None and result['reason'] == 'proportional'


def test_a_segment_out_of_proportion_to_its_size_is_the_driver():
    result = driver_check(OVER_INDEXED)
    assert result['reason'] == 'driver'
    assert result['clear_driver'] == {'dimension': 'payment', 'segment': 'Credit Card', 'contribution_pct': 103.5,
                                      'share_of_previous_pct': 79.2, 'excess_pct': 24.3}


def test_over_indexing_but_a_minority_of_the_change_is_not_a_driver():
    # g05's Auto & Tools: ~5% of the previous day, 30% of the change.
    evidence = {'dimensions': {'product': dim(42_071, 50.03, ('Auto & Tools', 2_292, 30.0),
                                              ('Other', 14_221, 29.0))}}
    assert driver_check(evidence)['clear_driver'] is None


def test_offsetting_segments_on_a_small_net_change_are_not_drivers():
    # g09: +3.4% net; South +138.5% and Southeast -130.8% of an 11-order change.
    evidence = {'dimensions': {'geography': dim(381, 3.36, ('South', 53, 138.5), ('Southeast', 287, -130.8)),
                               'payment': dim(381, 3.36, ('Boleto', 49, 107.7), ('Credit Card', 330, -23.1))}}
    result = driver_check(evidence)
    assert result['clear_driver'] is None and result['reason'] == 'small_net_change'


def test_undefined_share_never_makes_a_driver():
    # A profit that was negative the day before: no share, so no excess.
    evidence = {'dimensions': {'Region': dim(-1_972, -2026.86, ('Atlantic', -72, 72.3))}}
    assert share_of_previous({'previous_value': -72}, -1_972) is None
    assert driver_check(evidence)['reason'] == 'proportional'
    assert share_of_previous({'previous_value': 5}, 0) is None


def test_the_largest_excess_wins_across_dimensions():
    evidence = {'dimensions': {
        'payment': OVER_INDEXED['dimensions']['payment'],
        'geography': dim(1_000, 40.0, ('North', 100, 90.0)),          # 10% share, 90% of the change
        'broken': {'error': 'query failed'}}}
    assert driver_check(evidence)['clear_driver']['segment'] == 'North'


def test_no_usable_dimension():
    assert driver_check({'dimensions': {'x': {'error': 'boom'}}})['reason'] == 'no_evidence'


def _data(state):
    _, human = build_messages(state)
    return json.loads(human.content.split('<data>\n', 1)[1].rsplit('\n</data>', 1)[0])['EVIDENCE']


def test_the_evidence_block_carries_driver_check_and_shares():
    data = _data({**STATE, 'evidence': {**STATE['evidence'], **OVER_INDEXED}})
    assert data['driver_check']['clear_driver']['segment'] == 'Credit Card'
    row = data['dimensions']['payment']['top_contributors'][0]
    assert row['share_of_previous_pct'] == 79.2 and row['excess_pct'] == 24.3
    assert 'driver_check' in SYSTEM_PROMPT and 'Never notify an owner only because' in SYSTEM_PROMPT


def test_wide_datasets_send_three_contributors_but_check_them_all():
    five = [(f's{i}', 100, 10.0) for i in range(4)] + [('late', 10, 60.0)]
    wide = {f'd{n}': dim(410, 50.0, *five) for n in range(4)}
    data = _data({**STATE, 'evidence': {**STATE['evidence'], 'dimensions': wide}})
    assert all(len(d['top_contributors']) == 3 for d in data['dimensions'].values())
    # 'late' is 5th in its dimension, so not sent, but driver_check still sees it.
    assert data['driver_check']['clear_driver']['segment'] == 'late'
    narrow = {f'd{n}': dim(410, 50.0, *five) for n in range(3)}
    data = _data({**STATE, 'evidence': {**STATE['evidence'], 'dimensions': narrow}})
    assert all(len(d['top_contributors']) == 5 for d in data['dimensions'].values())
