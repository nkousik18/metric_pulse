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
