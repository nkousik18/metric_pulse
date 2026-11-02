"""
LangSmith tracing helpers (docs/action-agent-scope.md §13, D10, D11).

LangGraph/LangChain trace automatically when LANGSMITH_TRACING=true is in the
environment (config/settings.py loads .env). This module adds what automatic
tracing doesn't give you:
- a known root run id per invocation, so a trace can be stored on the
  action-log rows it produced and found again (§13.2)
- the standard metadata/tags every run carries (§13.2)
- fail-open feedback posting for approver decisions (§13.4)

Everything here is fail-open (N5). If LangSmith is disabled, unreachable or
rejects the key, the run proceeds and nothing raises. Traces are a mirror, never
the source of truth (D11).
"""

import subprocess
import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

from config import settings
from config.logging_config import setup_logger

logger = setup_logger(__name__)


def tracing_enabled() -> bool:
    return bool(settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY)


@lru_cache(maxsize=1)
def git_sha() -> str:
    try:
        return subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=settings.PROJECT_ROOT,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'


def new_run_id() -> uuid.UUID:
    return uuid.uuid4()


def run_config(
    *, run_name: str, run_id: uuid.UUID, thread_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None, tags: Optional[List[str]] = None,
) -> Dict:
    """A LangGraph/LangChain RunnableConfig with the §13.2 metadata attached.
    run_id becomes the root run's id, which is also the trace id."""
    config: Dict[str, Any] = {
        'run_name': run_name,
        'run_id': run_id,
        'metadata': {'git_sha': git_sha(), **(metadata or {})},
        'tags': ['metricpulse', *(tags or [])],
    }
    if thread_id:
        config['configurable'] = {'thread_id': thread_id}
    return config


@lru_cache(maxsize=1)
def _client():
    from langsmith import Client
    return Client()


@lru_cache(maxsize=1)
def _project_id():
    """Feedback without a project (session) id is deprecated in the SDK. Look it up once."""
    try:
        return _client().read_project(project_name=settings.LANGSMITH_PROJECT).id
    except Exception as e:
        logger.debug(f'LangSmith project lookup failed: {e}')
        return None


def trace_url(run_id) -> Optional[str]:
    """Best-effort UI link for a root run. None when tracing is off or the lookup fails."""
    if not tracing_enabled() or run_id is None:
        return None
    try:
        return _client().get_run_url(run=_client().read_run(str(run_id)))
    except Exception as e:
        logger.debug(f'trace_url lookup failed for {run_id}: {e}')
        return None


def feedback_kwargs(run_id, key: str, *, value=None, score=None, comment=None, correction=None,
                    session_id=None) -> Dict:
    """Arguments for Client.create_feedback, split out so their shape is testable offline.

    The project goes in `session_id`, never `project_id`: langsmith 0.10.x raises
    "project_id cannot be provided if run_id or trace_id is provided", and warns that feedback
    without a session_id is deprecated. Verified live against LangSmith on 2026-11-02 (A2)."""
    return {'run_id': str(run_id), 'trace_id': str(run_id), 'key': key, 'value': value, 'score': score,
            'comment': comment, 'correction': correction,
            'session_id': session_id if session_id is not None else _project_id()}


def post_feedback(run_id, key: str, *, value=None, score=None, comment: Optional[str] = None,
                  correction: Optional[Dict] = None) -> bool:
    """Attach a human decision to a trace (§13.4). Returns False and never raises on failure."""
    if not tracing_enabled() or run_id is None:
        return False
    try:
        _client().create_feedback(**feedback_kwargs(run_id, key, value=value, score=score,
                                                    comment=comment, correction=correction))
        return True
    except Exception as e:
        logger.warning(f'LangSmith feedback not recorded ({key} on {run_id}): {e}')
        return False


def flush() -> None:
    """Send queued traces before a short-lived CLI process exits."""
    if not tracing_enabled():
        return
    try:
        _client().flush()
    except Exception as e:
        logger.debug(f'LangSmith flush failed: {e}')
