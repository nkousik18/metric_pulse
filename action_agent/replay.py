"""
Exact decision replay (docs/action-agent-scope.md §13.6).

Every policy decision in action_log is re-run against the evidence snapshot
stored with its proposal, using today's code. A mismatch means a code change
has altered a decision already made. That can be legitimate, but it must be
deliberate and recorded in the decision log, never silent.

    python -m action_agent.cli replay <proposal_id>
"""

from typing import Dict, List

from action_agent.policy import policy_check
from action_agent.store import ActionStore

POLICY_EVENTS = ('policy_passed', 'policy_rejected', 'edit_policy_rejected')


def replay_decisions(store: ActionStore, proposal_id: str) -> List[Dict]:
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise ValueError(f'unknown proposal {proposal_id}')

    results = []
    for event in store.events(proposal_id):
        if event['event'] not in POLICY_EVENTS:
            continue
        logged = event['policy']
        # The params that were checked: a passed/edit-rejected row carries them; an original
        # rejection is the proposal as first written.
        params = event['params'] if event['params'] is not None else proposal['params']
        replayed = policy_check({**proposal['proposal'], 'params': params}, proposal['evidence']).to_dict()
        match = (replayed['decision'], replayed['params'], replayed['errors']) == \
                (logged['decision'], logged['params'], logged['errors'])
        results.append({'log_id': event['log_id'], 'event': event['event'], 'match': match,
                        'logged': logged['decision'], 'replayed': replayed['decision'],
                        'logged_errors': logged['errors'], 'replayed_errors': replayed['errors']})
    return results
