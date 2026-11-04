"""
Tests for the Action Agent's trusted calendar (action_agent/event_calendar.py, scope §14) and the
calendar-grounding policy check. Real files on tmp_path and the committed calendars; no mocks.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.event_calendar import (  # noqa: E402
    CALENDAR_DIR, SPECS, attach_calendar, black_friday, build, calendar_context, easter, event_names,
    load_calendar, nth_weekday, render,
)
from action_agent.policy import NEEDS_APPROVAL, REJECTED, policy_check  # noqa: E402
from tests.test_action_policy import CITATION, EVIDENCE  # noqa: E402


@pytest.fixture
def cal_dir(tmp_path):
    (tmp_path / 'shop.yaml').write_text(
        "source: test\n"
        "events:\n"
        "- {date: '2017-11-24', name: Black Friday, kind: retail_event}\n"
        "- {date: '2017-11-29', name: Far Day, kind: holiday}\n"
        "- {date: '2017-11-20', name: Early Day, kind: holiday}\n")
    return tmp_path


# --------------------------------------------------------------------------- lookup

def test_day_after_black_friday_sees_it_at_minus_one(cal_dir):
    ctx = calendar_context('shop', '2017-11-25', '2017-11-24', cal_dir)
    assert ctx['events_on_date'] == []
    assert ctx['events_nearby'] == [{'date': '2017-11-24', 'name': 'Black Friday', 'kind': 'retail_event',
                                     'offset_days': -1}]
    assert ctx['weekday'] == 'Saturday' and ctx['previous_weekday'] == 'Friday'
    assert ctx['weekday_class_changed'] is True


def test_event_on_the_date_and_window_edges(cal_dir):
    ctx = calendar_context('shop', '2017-11-24', '2017-11-23', cal_dir)
    assert [e['name'] for e in ctx['events_on_date']] == ['Black Friday']
    # +5 days (Far Day) and -4 days (Early Day) are outside ±3.
    assert ctx['events_nearby'] == []
    ctx = calendar_context('shop', '2017-11-23', '2017-11-22', cal_dir)
    assert [(e['name'], e['offset_days']) for e in ctx['events_nearby']] == [('Black Friday', 1), ('Early Day', -3)]
    assert ctx['weekday_class_changed'] is False


def test_unknown_dataset_gets_an_empty_calendar_with_weekdays(cal_dir):
    ctx = calendar_context('adversarial_injection', '2024-02-05', '2024-02-04', cal_dir)
    assert ctx['source'] is None and ctx['events_on_date'] == [] and ctx['events_nearby'] == []
    assert ctx['weekday'] == 'Monday' and ctx['weekday_class_changed'] is True


@pytest.mark.parametrize('dataset_id', ['../shop', 'shop/../shop', '', None, 'a' * 101])
def test_dataset_id_never_becomes_a_path(cal_dir, dataset_id):
    assert load_calendar(dataset_id, cal_dir) == {'source': None, 'events': []}


def test_bad_dates_give_no_events(cal_dir):
    ctx = calendar_context('shop', 'not-a-date', None, cal_dir)
    assert ctx['weekday'] is None and ctx['events_nearby'] == [] and ctx['weekday_class_changed'] is False


def test_attach_calendar_replaces_a_supplied_one(cal_dir):
    evidence = {'previous_date': '2017-11-24', 'calendar': {'events_on_date': [{'name': 'Carnival'}]}}
    out = attach_calendar(evidence, 'shop', '2017-11-25', cal_dir)
    assert event_names(out['calendar']) == ['Black Friday']
    assert evidence['calendar'] == {'events_on_date': [{'name': 'Carnival'}]}   # input untouched


# --------------------------------------------------------------------------- rules and committed files

def test_date_rules():
    assert [easter(y) for y in (2009, 2010, 2016, 2017, 2018)] == [
        date(2009, 4, 12), date(2010, 4, 4), date(2016, 3, 27), date(2017, 4, 16), date(2018, 4, 1)]
    assert [black_friday(y) for y in (2016, 2017, 2018)] == [date(2016, 11, 25), date(2017, 11, 24),
                                                            date(2018, 11, 23)]
    assert nth_weekday(2018, 5, 6, 2) == date(2018, 5, 13)     # Brazilian Mother's Day 2018
    assert nth_weekday(2017, 8, 6, 2) == date(2017, 8, 13)     # Brazilian Father's Day 2017


def test_victoria_day_when_may_24_is_a_monday():
    events = build(*SPECS['superstore_sales'])['events']
    victoria = [e['date'] for e in events if e['name'] == 'Victoria Day']
    assert victoria == ['2009-05-18', '2010-05-24', '2011-05-23', '2012-05-21']


@pytest.mark.parametrize('dataset_id', sorted(SPECS))
def test_committed_calendars_match_their_rules(dataset_id):
    assert (CALENDAR_DIR / f'{dataset_id}.yaml').read_text() == render(dataset_id)


def test_olist_calendar_covers_the_data_and_has_no_carnival():
    events = load_calendar('olist')['events']
    years = {e['date'][:4] for e in events}
    assert years == {'2016', '2017', '2018'}
    assert not any('carnival' in e['name'].lower() for e in events)
    ctx = calendar_context('olist', '2017-11-25', '2017-11-24')
    assert ('Black Friday', -1) in [(e['name'], e['offset_days']) for e in ctx['events_nearby']]


# --------------------------------------------------------------------------- policy (§14.3)

def _annotate(**params):
    return {'action_type': 'annotate_anomaly', 'params': params, 'rationale_citations': [CITATION]}


def _evidence(**calendar):
    return {**EVIDENCE, 'calendar': {**EVIDENCE['calendar'], **calendar}}


@pytest.mark.parametrize('category', ['holiday', 'promotion'])
def test_event_category_needs_a_calendar_event(category):
    result = policy_check(_annotate(category=category, cause='x'), EVIDENCE)
    assert result.decision == REJECTED
    assert "needs calendar_event" in result.errors[0] and "'Test Festival'" in result.errors[0]


def test_calendar_event_must_be_a_real_nearby_entry():
    result = policy_check(_annotate(category='holiday', cause='Carnival', calendar_event='Carnival'), EVIDENCE)
    assert result.decision == REJECTED and "'Carnival' is not an entry" in result.errors[0]
    ok = policy_check(_annotate(category='promotion', cause='x', calendar_event='Test Festival'), EVIDENCE)
    assert ok.decision == NEEDS_APPROVAL


def test_no_calendar_in_evidence_fails_closed():
    evidence = {k: v for k, v in EVIDENCE.items() if k != 'calendar'}
    assert policy_check(_annotate(category='holiday', cause='x', calendar_event='Test Festival'),
                        evidence).decision == REJECTED


def test_seasonal_needs_a_weekday_class_change():
    assert policy_check(_annotate(category='seasonal', cause='weekend'), EVIDENCE).decision == REJECTED
    assert policy_check(_annotate(category='seasonal', cause='weekend'),
                        _evidence(weekday_class_changed=True)).decision == NEEDS_APPROVAL


@pytest.mark.parametrize('category', ['data_issue', 'other'])
def test_other_categories_need_no_calendar(category):
    assert policy_check(_annotate(category=category, cause='late load'), EVIDENCE).decision == NEEDS_APPROVAL
    # but a calendar_event, when given, is still checked
    assert policy_check(_annotate(category=category, cause='x', calendar_event='Nope'), EVIDENCE).decision == REJECTED


def test_unset_calendar_event_stays_out_of_params():
    result = policy_check(_annotate(category='other', cause='x'), EVIDENCE)
    assert result.params == {'category': 'other', 'cause': 'x'}
