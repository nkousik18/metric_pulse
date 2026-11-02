"""
Unit tests for alerting/notifier.py (docs/local-stack-scope.md §6.4, LS2, LS5, LS6): the outbox
file and index format, the narrative-to-message mapping, fail-soft errors, and channel dispatch.
A real outbox directory in tmp_path. No mocks, no network, no AWS.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from alerting import notifier  # noqa: E402
from config.settings import backend_default  # noqa: E402

NOW = datetime(2026, 11, 2, 14, 30, 5, tzinfo=timezone.utc)

NARRATIVES = {
    'email_subject': 'MetricPulse Alert: total_revenue decreased 90.6%',
    'full': '**Total revenue** decreased 90.6%.\n\n- Credit Card: 106.6% of the change',
    'summary': 'Total revenue decreased 90.6%.',
}


def _read(path):
    text = Path(path).read_text(encoding='utf-8')
    _, front, body = text.split('---\n', 2)
    return yaml.safe_load(front), body


# --- outbox format ---

def test_outbox_writes_markdown_with_front_matter_and_an_index_line(tmp_path):
    result = notifier.write_outbox('Revenue drop', 'Body text', recipient='payments-team',
                                   metadata={'metric': 'total_revenue'}, outbox_dir=tmp_path, now=NOW)

    assert result['status'] == 'sent' and result['channel'] == 'outbox'
    path = Path(result['path'])
    assert path == tmp_path / '2026-11-02' / '143005_revenue-drop.md'
    header, body = _read(path)
    assert header == {
        'message_id': result['message_id'], 'sent_at': '2026-11-02T14:30:05+00:00', 'channel': 'outbox',
        'recipient': 'payments-team', 'subject': 'Revenue drop', 'metadata': {'metric': 'total_revenue'}}
    assert body == '\n# Revenue drop\n\nBody text\n'

    lines = (tmp_path / 'index.jsonl').read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {**header, 'path': '2026-11-02/143005_revenue-drop.md'}


def test_same_second_same_subject_never_overwrites(tmp_path):
    first = notifier.write_outbox('Same', 'one', outbox_dir=tmp_path, now=NOW)
    second = notifier.write_outbox('Same', 'two', outbox_dir=tmp_path, now=NOW)
    assert Path(second['path']).name == '143005_same_2.md'
    assert _read(first['path'])[1].endswith('one\n') and _read(second['path'])[1].endswith('two\n')
    assert len((tmp_path / 'index.jsonl').read_text().splitlines()) == 2


def test_numpy_metadata_and_unsafe_subject_are_written_safely(tmp_path):
    # Live pipeline values arrive as numpy scalars; a subject can hold any characters.
    result = notifier.write_outbox('Drop: 90% / "Credit Card"\n---', 'b', outbox_dir=tmp_path, now=NOW,
                                   metadata={'anomaly_count': np.int64(3), 'z': np.float64(-2.5)})
    header, _ = _read(result['path'])
    assert header['subject'] == 'Drop: 90% / "Credit Card"\n---'
    assert header['metadata'] == {'anomaly_count': 3, 'z': -2.5}
    assert Path(result['path']).name == '143005_drop-90-credit-card.md'


def test_default_recipient_is_the_pipeline_alert_recipient(tmp_path):
    result = notifier.write_outbox('s', 'b', outbox_dir=tmp_path, now=NOW)
    assert result['recipient'] == 'metric-pulse-alerts'


def test_io_failure_returns_an_error_instead_of_raising(tmp_path):
    blocker = tmp_path / 'not_a_dir'
    blocker.write_text('a file where the outbox directory should be')
    result = notifier.write_outbox('s', 'b', outbox_dir=blocker, now=NOW)
    assert result['status'] == 'error' and result['channel'] == 'outbox'


# --- the pipeline alert ---

def test_metric_alert_uses_the_same_subject_and_body_as_sns_but_keeps_markdown(tmp_path):
    result = notifier.send_metric_alert(NARRATIVES, metadata={'metric': 'total_revenue'},
                                        channel='outbox', outbox_dir=tmp_path)
    header, body = _read(result['path'])
    assert header['subject'] == NARRATIVES['email_subject']
    assert '**Total revenue** decreased 90.6%.' in body   # Markdown kept; SNS strips it for plain-text email


def test_metric_alert_falls_back_to_summary_then_a_default(tmp_path):
    only_summary = notifier.send_metric_alert({'summary': 'just this'}, channel='outbox', outbox_dir=tmp_path)
    header, body = _read(only_summary['path'])
    assert header['subject'] == 'MetricPulse Alert' and body.endswith('just this\n')
    empty = notifier.send_metric_alert({}, channel='outbox', outbox_dir=tmp_path)
    assert _read(empty['path'])[1].endswith('No details available\n')


# --- dispatch (LS6: the archived SNS path is selected correctly without sending) ---

def test_sns_channel_dispatches_to_the_archived_publisher():
    assert notifier.metric_alert_sender('sns') is notifier._sns_metric_alert
    assert notifier.metric_alert_sender('outbox') is notifier._outbox_metric_alert


def test_sns_channel_runs_the_unchanged_publisher_and_writes_no_outbox_file(tmp_path, monkeypatch):
    # With no topic configured, sns_publisher.publish_alert returns before creating any AWS client,
    # so the real archived code runs end to end here without a network call.
    # Set it to EMPTY, never delenv: sns_publisher calls load_dotenv() on import, which refills a
    # *missing* variable from .env (and so really published once, 2026-11-02), but never overrides
    # one that is set.
    monkeypatch.setenv('SNS_TOPIC_ARN', '')
    result = notifier.send_metric_alert(NARRATIVES, channel='sns', outbox_dir=tmp_path)
    assert result == {'status': 'skipped', 'reason': 'no_topic_arn', 'channel': 'sns'}
    assert list(tmp_path.iterdir()) == []


def test_unknown_channel_is_rejected():
    with pytest.raises(ValueError, match='ALERT_CHANNEL must be one of'):
        notifier.send_alert('s', 'b', channel='slack')


def test_channel_names_are_case_insensitive(tmp_path):
    assert notifier.send_alert('s', 'b', channel=' Outbox ', outbox_dir=tmp_path)['status'] == 'sent'


@pytest.mark.parametrize('environ,expected', [
    ({}, 'outbox'),
    ({'AWS_LAMBDA_FUNCTION_NAME': 'metricpulse'}, 'sns'),
])
def test_alert_channel_default_keeps_lambda_on_sns(environ, expected):
    assert backend_default('outbox', 'sns', environ=environ) == expected
