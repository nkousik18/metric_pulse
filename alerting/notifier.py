"""
Alert delivery with a switchable channel (docs/local-stack-scope.md §6.4, R4).

Two channels, picked by settings.ALERT_CHANNEL unless a caller passes one:
- outbox (default, active): each alert becomes one Markdown file,
      outbox/YYYY-MM-DD/<HHMMSS>_<slug>.md
  with a YAML front-matter header (message_id, sent_at, channel, recipient, subject,
  metadata), plus one JSON line appended to outbox/index.jsonl. No account, no network.
- sns (archived AWS channel): delegates to alerting/sns_publisher.py, which is kept
  unchanged (rule R1: never delete AWS code). Default inside Lambda.

Return shape matches sns_publisher's ({'status': 'sent' | 'skipped' | 'error', ...}) with
'channel' added, so run_pipeline's summary and monitoring/cloudwatch_metrics' `status == 'sent'`
check work for both channels.

    python -m alerting.notifier --test                 # write a test message to the outbox
    python -m alerting.notifier --test --channel sns   # archived: the old sns_publisher --test path
"""

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml  # noqa: E402

from config import settings  # noqa: E402
from config.logging_config import setup_logger  # noqa: E402

logger = setup_logger(__name__)

CHANNELS = ('outbox', 'sns')
INDEX_FILE = 'index.jsonl'


def resolve_channel(channel: Optional[str] = None) -> str:
    """The channel to use: the argument if given, else settings.ALERT_CHANNEL. Unknown names raise,
    so a typo in ALERT_CHANNEL fails loudly instead of silently dropping alerts."""
    name = (channel or settings.ALERT_CHANNEL).strip().lower()
    if name not in CHANNELS:
        raise ValueError(f"ALERT_CHANNEL must be one of {CHANNELS}, got {name!r}")
    return name


# --- the outbox channel ---

def _slug(subject: str, max_len: int = 60) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', subject.lower()).strip('-')
    return slug[:max_len].rstrip('-') or 'alert'


def _plain(value):
    """JSON-safe copy (numpy scalars, dates and the like become strings or plain numbers), so
    metadata from the pipeline can always be written to the front matter and the index."""
    def default(obj):
        item = getattr(obj, 'item', None)   # numpy scalar -> the matching Python int/float/bool
        return item() if callable(item) else str(obj)
    return json.loads(json.dumps(value, default=default))


def write_outbox(subject: str, body: str, *, recipient: Optional[str] = None,
                 metadata: Optional[Dict] = None, outbox_dir: Optional[Path] = None,
                 now: Optional[datetime] = None) -> Dict:
    """Write one message to the outbox. Never raises on an I/O failure: returns
    {'status': 'error', ...}, the same fail-soft contract as sns_publisher.publish_alert."""
    outbox_dir = Path(outbox_dir or settings.OUTBOX_DIR)
    now = now or datetime.now().astimezone()
    message_id = uuid.uuid4().hex
    header = {
        'message_id': message_id,
        'sent_at': now.isoformat(timespec='seconds'),
        'channel': 'outbox',
        'recipient': recipient or settings.ALERT_RECIPIENT,
        'subject': subject,
        'metadata': _plain(metadata or {}),
    }
    text = ('---\n' + yaml.safe_dump(header, sort_keys=False, allow_unicode=True) + '---\n\n'
            + f'# {subject}\n\n{body.rstrip()}\n')
    try:
        day_dir = outbox_dir / now.strftime('%Y-%m-%d')
        day_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{now.strftime('%H%M%S')}_{_slug(subject)}"
        path, n = day_dir / f'{stem}.md', 1
        while True:
            try:
                with open(path, 'x', encoding='utf-8') as f:   # 'x': never overwrite an earlier message
                    f.write(text)
                break
            except FileExistsError:
                n += 1
                path = day_dir / f'{stem}_{n}.md'
        relative = path.relative_to(outbox_dir).as_posix()
        with open(outbox_dir / INDEX_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**header, 'path': relative}, ensure_ascii=False) + '\n')
    except OSError as e:
        logger.error(f"Failed to write outbox message: {e}")
        return {'status': 'error', 'error': str(e), 'channel': 'outbox'}

    logger.info(f"Alert written to outbox: {path}")
    return {'status': 'sent', 'message_id': message_id, 'channel': 'outbox',
            'recipient': header['recipient'], 'path': str(path)}


# --- the archived SNS channel (imported lazily: boto3 is only loaded when SNS is selected) ---

def _sns_alert(subject: str, body: str, **_) -> Dict:
    from alerting.sns_publisher import publish_alert
    return {**publish_alert(subject, body), 'channel': 'sns'}


def _sns_metric_alert(narratives: Dict, **_) -> Dict:
    from alerting.sns_publisher import publish_metric_alert
    return {**publish_metric_alert(narratives), 'channel': 'sns'}


def _outbox_metric_alert(narratives: Dict, **kwargs) -> Dict:
    # Same subject/body selection as sns_publisher.publish_metric_alert. The Markdown is kept,
    # not stripped as it is for plain-text SNS email, because the outbox file is Markdown.
    subject = narratives.get('email_subject', 'MetricPulse Alert')
    body = narratives.get('full', narratives.get('summary', 'No details available'))
    return write_outbox(subject, body, **kwargs)


_ALERT_SENDERS = {'outbox': write_outbox, 'sns': _sns_alert}
_METRIC_ALERT_SENDERS = {'outbox': _outbox_metric_alert, 'sns': _sns_metric_alert}


def metric_alert_sender(channel: Optional[str] = None) -> Callable[..., Dict]:
    """The function send_metric_alert dispatches to. Split out so the dispatch is testable without
    sending anything (local-stack scope LS6: the SNS path can't be run live any more)."""
    return _METRIC_ALERT_SENDERS[resolve_channel(channel)]


# --- public API ---

def send_alert(subject: str, body: str, *, recipient: Optional[str] = None,
               metadata: Optional[Dict] = None, channel: Optional[str] = None,
               outbox_dir: Optional[Path] = None) -> Dict:
    """Send one message on the configured channel. SNS ignores recipient and metadata (it
    publishes to the SNS_TOPIC_ARN topic, as before)."""
    return _ALERT_SENDERS[resolve_channel(channel)](
        subject, body, recipient=recipient, metadata=metadata, outbox_dir=outbox_dir)


def send_metric_alert(narratives: Dict, *, metadata: Optional[Dict] = None,
                      channel: Optional[str] = None, outbox_dir: Optional[Path] = None) -> Dict:
    """The pipeline alert (run_pipeline step 5), from narrative.generator's output.
    Under channel 'sns' this calls sns_publisher.publish_metric_alert(narratives) exactly as
    run_pipeline used to."""
    return metric_alert_sender(channel)(narratives, metadata=metadata, outbox_dir=outbox_dir)


def main(argv=None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description='MetricPulse alert notifier')
    parser.add_argument('--test', action='store_true', help='Send a test alert')
    parser.add_argument('--channel', choices=CHANNELS, default=None,
                        help=f'Override ALERT_CHANNEL (currently {settings.ALERT_CHANNEL!r})')
    args = parser.parse_args(argv)

    if not args.test:
        parser.print_help()
        return
    result = send_alert(
        subject='MetricPulse Test Alert',
        body='This is a test alert from MetricPulse. If you can read this, alerting is working correctly.',
        metadata={'test': True},
        channel=args.channel,
    )
    print(f"\nTest result: {result}")


if __name__ == '__main__':
    main()
