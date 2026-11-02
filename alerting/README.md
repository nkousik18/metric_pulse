# alerting/

Delivers the pipeline's alert. This is the **final stage** of the analytics pipeline. Since 2026-11-02 (`docs/local-stack-scope.md` §6.4), alerts go to a **local outbox** by default. The original **AWS SNS** publisher is kept intact as an archived channel (rule R1: never delete AWS code).

## Files

| File | Status | Purpose |
|------|--------|---------|
| `notifier.py` | **Active** | Channel switch (`ALERT_CHANNEL`), the outbox writer, `send_alert` / `send_metric_alert`, and the `--test` CLI. `orchestration/run_pipeline.py` step 5 calls this. |
| `sns_publisher.py` | Archived (AWS), unchanged | SNS client, topic/subscription setup, publish, CLI. Reached only through `notifier` with `ALERT_CHANNEL=sns`, or directly. |
| `__init__.py` | | Empty; makes the folder an importable package. |

`docs/analytics_pipeline.md` notes a `slack_webhook.py` dead file existed here and was deleted — confirmed not present in the current folder. The Slack narrative format exists in `narrative/generator.py`, but nothing sends it anywhere.

## Channels (`ALERT_CHANNEL`)

| `ALERT_CHANNEL` | Status | What a send does |
|---|---|---|
| `outbox` (default) | **Active** | Writes one Markdown file, appends one line to `outbox/index.jsonl`. No account, no network. |
| `sns` | Archived | Calls `sns_publisher.publish_alert` / `publish_metric_alert`, exactly as `run_pipeline` used to. |

- **Inside AWS Lambda** (`AWS_LAMBDA_FUNCTION_NAME` set) the default is `sns`, via `settings.backend_default()`, so the archived image behaves as before.
- An unknown channel name raises `ValueError` (it does not silently drop the alert). Names are case-insensitive.
- `OUTBOX_DIR` (default `<repo>/outbox`, gitignored) and `ALERT_RECIPIENT` (default `metric-pulse-alerts`, named after the old SNS topic) are in `config/settings.py`.

## Outbox layout

```
outbox/
├── index.jsonl                         # one JSON line per message, oldest first
└── 2026-11-02/
    ├── 145939_metricpulse-total-revenue-decrease-90-6-on-2018-09-03.md
    └── 145948_metricpulse-test-alert.md
```

Each `.md` file is YAML front matter, then the message:

```markdown
---
message_id: c31689a16df64e3791cd7f3f3f8ba673
sent_at: '2026-11-02T14:59:39-05:00'
channel: outbox
recipient: metric-pulse-alerts
subject: 'MetricPulse: Total Revenue decrease 90.6% on 2018-09-03'
metadata:
  metric: total_revenue
  current_date: '2018-09-03'
  previous_date: '2018-08-29'
  anomaly_count: 0
  force_alert: true
---

# MetricPulse: Total Revenue decrease 90.6% on 2018-09-03

(narratives['full'], Markdown kept)
```

The `index.jsonl` line is the same header plus `path` (relative to the outbox). To read the latest alerts: `tail -n 5 outbox/index.jsonl`, or open the newest folder.

- **File name:** local time `HHMMSS` + a slug of the subject (lowercase, non-alphanumerics → `-`, at most 60 chars, `alert` if empty). A second message in the same second with the same subject gets `_2`, `_3`, …; files are opened with mode `x`, so an earlier message is never overwritten.
- **Metadata** is made JSON-safe first (numpy scalars → plain numbers, anything else unknown → string), because live pipeline values arrive as numpy types.
- **Markdown is kept** in the outbox body. SNS strips `*` for plain-text email; the outbox file is Markdown, so it doesn't.

## `notifier.py` functions

| Function | Signature | What it does |
|---|---|---|
| `send_metric_alert` | `(narratives, *, metadata=None, channel=None, outbox_dir=None) -> Dict` | The pipeline alert. Same subject/body selection as `publish_metric_alert`: `email_subject` (default `MetricPulse Alert`), then `full` → `summary` → `No details available`. Under `sns` it calls `publish_metric_alert(narratives)` unchanged; `metadata` is outbox-only. |
| `send_alert` | `(subject, body, *, recipient=None, metadata=None, channel=None, outbox_dir=None) -> Dict` | One arbitrary message. This is what Action Agent `notify_owner` (A4) will use, with the owner as `recipient`. SNS ignores `recipient` and `metadata`. |
| `write_outbox` | `(subject, body, *, recipient, metadata, outbox_dir, now) -> Dict` | The outbox writer. `now` is injectable for tests. |
| `resolve_channel` / `metric_alert_sender` | `(channel=None)` | The dispatch, split out so the archived SNS path can be tested without sending (scope LS6). |

**Return values** keep `sns_publisher`'s shape, plus `channel`, so `run_pipeline`'s summary and `monitoring/cloudwatch_metrics.py`'s `status == 'sent'` check work for both:

| Scenario | Return |
|---|---|
| Outbox written | `{'status': 'sent', 'message_id', 'channel': 'outbox', 'recipient', 'path'}` |
| Outbox I/O failure | `{'status': 'error', 'error', 'channel': 'outbox'}` (logged, not raised) |
| SNS | whatever `sns_publisher` returns, plus `'channel': 'sns'` |

```bash
python -m alerting.notifier --test                 # writes a test message to the outbox
python -m alerting.notifier --test --channel sns   # archived: same as sns_publisher --test (really publishes)
```

## Archived: `sns_publisher.py` (AWS SNS)

Publishes to AWS SNS, which fans the alert out by email to confirmed subscribers. Kept byte-for-byte (R1). Everything below describes that file.

> **Warning (found 2026-11-02, L2):** the SNS topic `metric-pulse-alerts` and the AWS credentials in `.env` **still work**. A test that removed `SNS_TOPIC_ARN` from the environment really published one message, because `sns_publisher` calls `load_dotenv()` on import and refills a *missing* variable from `.env`. To keep a test off SNS, set `SNS_TOPIC_ARN` to an empty string (dotenv never overrides a variable that is set) — see `tests/test_notifier.py`.

### Functions

| Function | Signature | What it does |
|----------|-----------|---------------|
| `get_sns_client` | `() -> boto3.client` | Builds a boto3 SNS client from `AWS_REGION`/`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars. Called fresh by every other function in this module — no client reuse/caching. |
| `create_topic_if_not_exists` | `(topic_name='metric-pulse-alerts') -> str` | `boto3`'s `create_topic` is natively idempotent — calling it again on an existing topic name just returns the existing ARN, no error. |
| `subscribe_email` | `(topic_arn, email) -> str` | Adds an email subscription; AWS requires the recipient to click a confirmation link before they'll actually receive anything. |
| `publish_alert` | `(subject, message, topic_arn=None) -> Dict` | Core publish call. `topic_arn=None` → reads `SNS_TOPIC_ARN` env var; if that's also unset, **returns early without calling AWS** (`{'status': 'skipped', 'reason': 'no_topic_arn'}`) rather than raising. `subject` is hard-truncated to 100 chars (`subject[:100]`) — SNS's hard limit. |
| `publish_metric_alert` | `(narratives: Dict, topic_arn=None) -> Dict` | Convenience wrapper around `publish_alert`. `subject = narratives.get('email_subject', 'MetricPulse Alert')`, `message = narratives.get('full', narratives.get('summary', 'No details available'))`, then strips `**` and `*` markdown characters (both, unconditionally — see Gotchas) before sending, since SNS email is plain text. |
| `setup_sns` | `(email=None) -> Dict` | One-time setup helper: creates the topic, optionally subscribes an email, and prints the ARN to copy into `.env`. Not called by the pipeline — this is a manual bootstrap step. |

#### Return values from `publish_alert` / `publish_metric_alert`

| Scenario | Return |
|----------|--------|
| Sent successfully | `{'status': 'sent', 'message_id': '<uuid>', 'topic_arn': '...'}` |
| No `SNS_TOPIC_ARN` and no `topic_arn` arg | `{'status': 'skipped', 'reason': 'no_topic_arn'}` |
| `boto3.ClientError` (bad ARN, permissions, etc.) | `{'status': 'error', 'error': '<message>'}` — caught, not re-raised |

### Running standalone

```bash
# First-time setup — creates the SNS topic and subscribes an email
python -m alerting.sns_publisher --setup --email your@email.com

# Send a canned test message to whatever SNS_TOPIC_ARN is configured
python -m alerting.sns_publisher --test
```

With neither flag, it just prints usage and exits 0 (no error).

### Config / env vars

| Var | Required | Used by |
|-----|----------|---------|
| `AWS_REGION` | yes | `get_sns_client()` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | yes | `get_sns_client()` |
| `SNS_TOPIC_ARN` | only if `topic_arn` isn't passed explicitly | `publish_alert()` |

Loaded via `load_dotenv()` at module import time.

## Upstream / downstream

- **Upstream:** `narrative/generator.py`'s `generate_narrative()` output — specifically the `email_subject` and `full` (or `summary`) keys.
- **Downstream:** `orchestration/run_pipeline.py` step 5 calls `notifier.send_metric_alert()` (only when an anomaly was detected or `force_alert=True`, and skipped entirely when `dry_run=True`), passing `metric`, both dates, `anomaly_count` and `force_alert` as metadata. Nothing reads the outbox programmatically yet; Action Agent A4's `notify_owner` will write to it too. `monitoring/cloudwatch_metrics.py` (archived, off locally) records whether an alert was sent by reading the pipeline's own results dict.

### Gotchas (SNS)

- `publish_metric_alert`'s markdown-stripping (`message.replace('**', '').replace('*', '')`) is a blunt find-and-replace, not markdown-aware — any literal `*` in a segment name (unlikely but possible) would also get stripped.
- `create_topic_if_not_exists` and `subscribe_email` catch `ClientError` and log-then-`raise` — unlike `publish_alert`, a setup failure here **is** propagated to the caller, not swallowed into a status dict. Don't assume every function in this module fails soft.
- No retry logic anywhere — a transient SNS API failure just returns `{'status': 'error', ...}` once.

## Tests

`tests/test_notifier.py` (13 tests, no mocks): the outbox file and index format, collision handling, numpy metadata, fail-soft I/O errors, the narrative → message mapping, the channel dispatch, and the Lambda default. It also runs the real, unchanged `sns_publisher` code through `ALERT_CHANNEL=sns` on its no-topic branch, which returns before any AWS client is created. The rest of `sns_publisher.py` (the actual boto3 publish) has no test; testing it would need a mock or a live topic.
