"""
Offline tests for observability/tracing.py (docs/action-agent-scope.md §13.1, N5):
with tracing disabled, nothing touches the network and nothing raises.
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings  # noqa: E402
from observability import tracing  # noqa: E402


def test_tracing_is_off_in_tests():
    assert not settings.LANGSMITH_TRACING
    assert not tracing.tracing_enabled()


def test_helpers_are_no_ops_when_tracing_is_off():
    run_id = uuid.uuid4()
    assert tracing.post_feedback(run_id, 'approval', value='approve') is False
    assert tracing.trace_url(run_id) is None
    tracing.flush()   # must not raise


def test_run_config_carries_metadata_tags_and_thread():
    run_id = uuid.uuid4()
    config = tracing.run_config(run_name='x', run_id=run_id, thread_id='t1',
                                metadata={'anomaly_id': 'a1'}, tags=['action_agent'])
    assert config['run_id'] == run_id and config['run_name'] == 'x'
    assert config['configurable'] == {'thread_id': 't1'}
    assert config['metadata']['anomaly_id'] == 'a1' and config['metadata']['git_sha']
    assert config['tags'] == ['metricpulse', 'action_agent']


def test_run_config_without_thread_has_no_configurable():
    assert 'configurable' not in tracing.run_config(run_name='x', run_id=uuid.uuid4())


def test_feedback_names_the_project_as_session_id_not_project_id():
    # Regression (A2 live verification, 2026-11-02): langsmith 0.10.x rejects project_id together
    # with run_id/trace_id, so every approval's feedback was silently dropped.
    import inspect

    from langsmith import Client

    kwargs = tracing.feedback_kwargs('run-1', 'approval', value='approved', score=1, session_id='proj-1')
    assert 'project_id' not in kwargs
    assert kwargs['session_id'] == 'proj-1' and kwargs['run_id'] == kwargs['trace_id'] == 'run-1'
    inspect.signature(Client.create_feedback).bind(None, **kwargs)   # every key is a real parameter
