"""
The Action Agent's HTTP API (docs/action-agent-scope.md F5, N4, D8; milestone A6).

    GET  /api/actions/pending/              proposals awaiting a decision, with their dry runs
    POST /api/actions/<id>/approve/         {"reason"?, "live"?}
    POST /api/actions/<id>/edit/            {"params": {...}, "reason"?, "live"?}
    POST /api/actions/<id>/reject/          {"reason"}
    GET  /api/actions/log/                  ?proposal_id=&limit=  the action log, newest first
    POST /api/actions/<id>/undo/            {"reason", "live"?}

A thin adapter over action_agent.runner.ActionAgent, the same object the CLI approver uses, so
the API can't decide anything the CLI wouldn't: policy, F1's fail-closed execution, TTL expiry
and idempotency all live in the graph, not here.

Approver identity (D8): every endpoint, reads included, requires
`Authorization: Bearer <ACTION_APPROVER_TOKEN>`. With no token configured the endpoints refuse
everything (503), so a deployment that never set one exposes nothing. The approver recorded on
decision rows is ACTION_APPROVER (else the OS user), exactly as for the CLI. Throttles are
checked before the token, so wrong guesses are rate limited too (N4).

`live` (default false) has the CLI's --live meaning: allow effects outside this machine (a real
GitHub issue, a non-outbox notifier channel). Only a JSON `true` turns it on.

The API never creates actions.db. Its existence is what switches the pipeline hooks on (D3, D4),
so with no database the reads return empty lists and decisions return 404.
"""

import hmac
import logging
import uuid
from typing import Optional

from django.conf import settings
from django.utils.module_loading import import_string
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from dashboard_api.throttling import ScopedThrottle, ThrottleFirstMixin

logger = logging.getLogger(__name__)

MIN_TOKEN_LENGTH = 16
MAX_LOG_LIMIT = 500


def default_agent_factory(live: bool = False, actions_db=None, checkpoints_db=None):
    """The real ActionAgent on ACTIONS_DB_PATH/CHECKPOINTS_DB_PATH (or the paths given), or None
    if actions.db doesn't exist yet (no proposal has ever been made on this machine)."""
    from pathlib import Path
    from action_agent.runner import ActionAgent
    from config import settings as mp_settings
    actions_db = Path(actions_db or mp_settings.ACTIONS_DB_PATH)
    if not actions_db.exists():
        return None
    return ActionAgent(actions_db=actions_db, checkpoints_db=checkpoints_db, live=live)


def _make_agent(live: bool = False):
    factory = settings.ACTION_AGENT_FACTORY
    if isinstance(factory, str):
        factory = import_string(factory)
    return factory(live=live)


class ApproverNotConfigured(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = ('The actions API is disabled: set ACTION_APPROVER_TOKEN '
                      f'(at least {MIN_TOKEN_LENGTH} characters) in .env and restart the server.')
    default_code = 'approver_not_configured'


class IsApprover(BasePermission):
    """D8: the single approver, identified by a shared secret. Fails closed."""

    def has_permission(self, request, view):
        expected = getattr(settings, 'ACTION_APPROVER_TOKEN', None) or ''
        if len(expected) < MIN_TOKEN_LENGTH:
            raise ApproverNotConfigured()
        header = request.META.get('HTTP_AUTHORIZATION', '')
        scheme, _, given = header.partition(' ')
        if scheme.lower() != 'bearer' or not given:
            raise AuthenticationFailed('Send the approver token as "Authorization: Bearer <token>".')
        if not hmac.compare_digest(given.strip().encode(), expected.encode()):
            raise AuthenticationFailed('Wrong approver token.')
        return True


class _ActionsView(ThrottleFirstMixin, APIView):
    authentication_classes = []   # the token check is the permission below; no session, no CSRF
    permission_classes = [IsApprover]
    throttle_classes = [ScopedThrottle]

    def get_authenticate_header(self, request):
        return 'Bearer'           # makes DRF answer a failed token with 401, not 403

    @staticmethod
    def _ok(data, code=status.HTTP_200_OK):
        return Response({'status': 'success', 'data': data}, status=code)

    @staticmethod
    def _error(message, code):
        return Response({'status': 'error', 'message': message}, status=code)

    @staticmethod
    def _proposal_id(raw: str) -> Optional[str]:
        """Full UUIDs only. The CLI's prefix matching is a typing convenience a web client doesn't
        need, and a prefix could resolve to a different proposal than the one on screen."""
        try:
            return str(uuid.UUID(raw))
        except (ValueError, TypeError):
            return None


def _summary(agent, proposal) -> dict:
    pid = proposal['proposal_id']
    return {
        'proposal_id': pid,
        'status': agent.store.status(pid),
        'dataset_id': proposal['dataset_id'],
        'metric': proposal['metric'],
        'anomaly_date': proposal['anomaly_date'],
        'anomaly_id': proposal['anomaly_id'],
        'action_type': proposal['action_type'],
        'proposer': proposal['proposer'],
        'created_at': proposal['created_at'],
        'expires_at': proposal['expires_at'],
        'trace_id': proposal['trace_id'],
    }


class PendingActionsView(_ActionsView):
    throttle_scope = 'actions_read'

    def get(self, request):
        agent = _make_agent()
        if agent is None:
            return self._ok([])
        try:
            out = []
            for p in agent.pending():
                item = _summary(agent, p)
                item['narrative'] = p['narrative']
                item['rationale_citations'] = p['proposal'].get('rationale_citations') or []
                item['waiting_on'] = agent.waiting_on(p['proposal_id'])
                out.append(item)
            return self._ok(out)
        finally:
            agent.close()


class ActionLogView(_ActionsView):
    throttle_scope = 'actions_read'

    def get(self, request):
        raw_pid = request.query_params.get('proposal_id')
        pid = self._proposal_id(raw_pid) if raw_pid else None
        if raw_pid and pid is None:
            return self._error('proposal_id must be a full proposal UUID', status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.query_params.get('limit', 200))
        except ValueError:
            return self._error('limit must be an integer', status.HTTP_400_BAD_REQUEST)
        limit = max(1, min(limit, MAX_LOG_LIMIT))

        agent = _make_agent()
        if agent is None:
            return self._ok({'events': [], 'proposals': []})
        try:
            if pid and agent.store.get_proposal(pid) is None:
                return self._error('no such proposal', status.HTTP_404_NOT_FOUND)
            events = list(reversed(agent.store.events(pid)))[:limit]
            ids = {e['proposal_id'] for e in events}
            proposals = []
            from action_agent.catalog import CATALOG
            for proposal_id in sorted(ids):
                summary = _summary(agent, agent.store.get_proposal(proposal_id))
                executed = agent.store.executed_row(proposal_id)
                executed_type = executed['action_type'] if executed else None
                summary['executed_action_type'] = executed_type
                summary['undoable'] = (summary['status'] == 'executed' and executed_type in CATALOG
                                       and CATALOG[executed_type].reversible)
                proposals.append(summary)
            return self._ok({'events': events, 'proposals': proposals})
        finally:
            agent.close()


class _DecisionView(_ActionsView):
    throttle_scope = 'actions_decide'
    decision = None   # 'approve' | 'edit' | 'reject'

    def post(self, request, proposal_id):
        pid = self._proposal_id(proposal_id)
        if pid is None:
            return self._error('not a proposal id', status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        reason = body.get('reason')
        if reason is not None and not isinstance(reason, str):
            return self._error('reason must be a string', status.HTTP_400_BAD_REQUEST)
        reason = (reason or '').strip() or None
        params = None
        if self.decision == 'edit':
            params = body.get('params')
            if not isinstance(params, dict):
                return self._error('edit needs "params": a JSON object of replacement params',
                                   status.HTTP_400_BAD_REQUEST)
        if self.decision == 'reject' and not reason:
            return self._error('a rejection needs a reason', status.HTTP_400_BAD_REQUEST)

        agent = _make_agent(live=body.get('live') is True)
        if agent is None or agent.store.get_proposal(pid) is None:
            if agent is not None:
                agent.close()
            return self._error('no such proposal', status.HTTP_404_NOT_FOUND)
        try:
            result = agent.decide(pid, self.decision, params=params, reason=reason)
        except ValueError as e:          # not awaiting a decision (already decided, expired, ...)
            return self._error(str(e), status.HTTP_409_CONFLICT)
        finally:
            agent.close()
        return self._ok(result)


class ApproveActionView(_DecisionView):
    decision = 'approve'


class EditActionView(_DecisionView):
    decision = 'edit'


class RejectActionView(_DecisionView):
    decision = 'reject'


class UndoActionView(_ActionsView):
    throttle_scope = 'actions_decide'

    def post(self, request, proposal_id):
        pid = self._proposal_id(proposal_id)
        if pid is None:
            return self._error('not a proposal id', status.HTTP_404_NOT_FOUND)
        body = request.data if isinstance(request.data, dict) else {}
        reason = body.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            return self._error('an undo needs a reason', status.HTTP_400_BAD_REQUEST)

        agent = _make_agent(live=body.get('live') is True)
        if agent is None or agent.store.get_proposal(pid) is None:
            if agent is not None:
                agent.close()
            return self._error('no such proposal', status.HTTP_404_NOT_FOUND)
        try:
            result = agent.undo(pid, reason=reason)
        except (ValueError, RuntimeError) as e:   # nothing to undo, irreversible, needs live
            return self._error(str(e), status.HTTP_409_CONFLICT)
        finally:
            agent.close()
        return self._ok(result)
