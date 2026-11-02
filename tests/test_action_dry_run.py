"""
Unit tests for Action Agent identities, owner resolution, and the dry-run
payload builder (docs/action-agent-scope.md §4-§5, D1). Pure functions, no mocks.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from action_agent.catalog import CATALOG
from action_agent.dry_run import ActionContext, build_dry_run, evidence_table, render_dry_run
from action_agent.identity import anomaly_id, canonical_json, idempotency_key
from action_agent.owners import OwnersConfig, load_owners, resolve_owner
from action_agent.policy import policy_check
from action_agent.schemas import ActionProposal

from tests.test_action_policy import EVIDENCE, VALID_PARAMS, _proposal

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

OWNERS = OwnersConfig.model_validate({
    'default_owner': 'oncall',
    'people': {
        'oncall': {'name': 'On-Call', 'email': 'oncall@example.com'},
        'pay': {'name': 'Payments', 'email': 'pay@example.com'},
        'cc': {'name': 'Cards', 'email': 'cc@example.com'},
    },
    'segments': {'olist': {'payment': {'*': 'pay', 'Credit Card': 'cc'}}},
})

CTX = ActionContext(
    dataset_id='olist', metric='total_revenue', anomaly_date='2018-09-03', evidence=EVIDENCE,
    narrative_summary='Total Revenue decreased 80.0% on 2018-09-03.',
)


def _dry(action_type, params=None):
    proposal = ActionProposal.model_validate(_proposal(action_type, params))
    return build_dry_run(proposal, policy_check(proposal, EVIDENCE), CTX, OWNERS, now=NOW)


# --- identity ---

def test_anomaly_id_is_deterministic_and_field_sensitive():
    a = anomaly_id('olist', 'total_revenue', '2018-09-03')
    assert a == anomaly_id('olist', 'total_revenue', '2018-09-03')
    assert a != anomaly_id('olist', 'total_revenue', '2018-09-04')
    assert a != anomaly_id('olist', 'order_count', '2018-09-03')


def test_anomaly_id_no_concatenation_collision():
    assert anomaly_id('ab', 'c', 'd') != anomaly_id('a', 'bc', 'd')


def test_idempotency_key_ignores_dict_order_but_not_values():
    aid = anomaly_id('olist', 'total_revenue', '2018-09-03')
    k1 = idempotency_key(aid, 'suppress_alerts', {'days': 3, 'reason': 'x'})
    assert k1 == idempotency_key(aid, 'suppress_alerts', {'reason': 'x', 'days': 3})
    assert k1 != idempotency_key(aid, 'suppress_alerts', {'days': 4, 'reason': 'x'})   # an edit
    assert k1 != idempotency_key(aid, 'annotate_anomaly', {'days': 3, 'reason': 'x'})


def test_canonical_json_is_compact_and_sorted():
    assert canonical_json({'b': 1, 'a': [1, 2]}) == '{"a":[1,2],"b":1}'


# --- owners ---

@pytest.mark.parametrize('dataset,dimension,segment,expected,matched', [
    ('olist', 'payment', 'Credit Card', 'cc', 'segment'),
    ('olist', 'payment', 'Boleto', 'pay', 'dimension'),
    ('olist', 'geography', 'Southeast', 'oncall', 'default'),
    ('superstore', 'payment', 'Credit Card', 'oncall', 'default'),
    ('olist', 'payment', '*', 'pay', 'dimension'),   # a literal '*' segment isn't an exact match
    ('olist', None, None, 'oncall', 'default'),
])
def test_resolve_owner(dataset, dimension, segment, expected, matched):
    owner = resolve_owner(OWNERS, dataset, dimension, segment)
    assert (owner['id'], owner['matched']) == (expected, matched)


def test_owners_config_rejects_undefined_owner_id():
    with pytest.raises(ValidationError, match='ghost'):
        OwnersConfig.model_validate({
            'default_owner': 'oncall',
            'people': {'oncall': {'name': 'x', 'email': 'x@example.com'}},
            'segments': {'olist': {'payment': {'*': 'ghost'}}},
        })


def test_shipped_owners_yaml_loads():
    owners = load_owners()
    assert owners.default_owner in owners.people


# --- dry run ---

@pytest.mark.parametrize('action_type', sorted(CATALOG))
def test_dry_run_shape_for_every_action(action_type):
    dry = _dry(action_type)
    assert dry['action_type'] == action_type
    assert dry['tier'] == CATALOG[action_type].tier.value
    assert dry['reversible'] == CATALOG[action_type].reversible
    assert dry['anomaly_id'] == CTX.anomaly_id
    assert dry['idempotency_key'] == idempotency_key(CTX.anomaly_id, action_type, VALID_PARAMS[action_type])
    assert dry['target']['kind'] and dry['payload']
    assert render_dry_run(dry)


def test_dry_run_is_deterministic():
    assert _dry('open_incident') == _dry('open_incident')


def test_dry_run_refuses_rejected_policy():
    proposal = ActionProposal.model_validate(_proposal('suppress_alerts', {'days': 99, 'reason': 'x'}))
    with pytest.raises(ValueError, match='rejected'):
        build_dry_run(proposal, policy_check(proposal, EVIDENCE), CTX, OWNERS, now=NOW)


def test_notify_owner_recipient_resolved_from_owners_not_params():
    dry = _dry('notify_owner')
    assert dry['target']['owner']['email'] == 'cc@example.com'
    assert 'Total Revenue decreased 80.0%' in dry['payload']['body']
    assert '**Credit Card**' in dry['payload']['body']


def test_expiries_use_injected_clock():
    assert _dry('suppress_alerts')['payload']['expires_at'] == '2026-11-04T12:00:00+00:00'
    assert _dry('create_control')['payload']['expires_at'] == '2026-11-15T12:00:00+00:00'


def test_create_control_payload_matches_d4_watch_shape():
    payload = _dry('create_control')['payload']
    assert set(payload) == {'dataset_id', 'metric', 'dimension', 'segment', 'direction',
                            'threshold', 'owner', 'expires_at'}
    assert payload['owner'] == 'cc'


def test_unconfigured_live_targets_are_explicit_none():
    assert _dry('open_incident')['target']['repo'] is None
    notify = _dry('notify_owner')['target']
    assert notify['kind'] == 'notifier' and notify['channel'] is None


def test_evidence_table_escapes_untrusted_segment_names():
    evidence = {'dimensions': {'d': {'top_contributors': [
        {'segment': 'evil | col\nnewline', 'current_value': 1, 'previous_value': 2,
         'change': -1, 'contribution_pct': 100},
    ]}}}
    table = evidence_table(evidence, 'd')
    row = table.splitlines()[-1]
    assert 'evil \\| col newline' in row
    assert len(table.splitlines()) == 3
