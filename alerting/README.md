# alerting/

Publishes narrative output to AWS SNS, which fans it out by email to confirmed subscribers. This is the **fourth and final stage** of the analytics pipeline.

## Files

| File | Purpose |
|------|---------|
| `sns_publisher.py` | Everything — SNS client, topic/subscription setup, publish, CLI. |
| `__init__.py` | Empty — makes the folder an importable package. |

`docs/analytics_pipeline.md` notes a `slack_webhook.py` dead file existed here and was deleted — confirmed not present in the current folder; SNS/email is the only delivery mechanism implemented today (the Slack narrative format exists in `narrative/generator.py` but nothing in this folder sends it anywhere).

## Functions

| Function | Signature | What it does |
|----------|-----------|---------------|
| `get_sns_client` | `() -> boto3.client` | Builds a boto3 SNS client from `AWS_REGION`/`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` env vars. Called fresh by every other function in this module — no client reuse/caching. |
| `create_topic_if_not_exists` | `(topic_name='metric-pulse-alerts') -> str` | `boto3`'s `create_topic` is natively idempotent — calling it again on an existing topic name just returns the existing ARN, no error. |
| `subscribe_email` | `(topic_arn, email) -> str` | Adds an email subscription; AWS requires the recipient to click a confirmation link before they'll actually receive anything. |
| `publish_alert` | `(subject, message, topic_arn=None) -> Dict` | Core publish call. `topic_arn=None` → reads `SNS_TOPIC_ARN` env var; if that's also unset, **returns early without calling AWS** (`{'status': 'skipped', 'reason': 'no_topic_arn'}`) rather than raising. `subject` is hard-truncated to 100 chars (`subject[:100]`) — SNS's hard limit. |
| `publish_metric_alert` | `(narratives: Dict, topic_arn=None) -> Dict` | Convenience wrapper around `publish_alert`. `subject = narratives.get('email_subject', 'MetricPulse Alert')`, `message = narratives.get('full', narratives.get('summary', 'No details available'))`, then strips `**` and `*` markdown characters (both, unconditionally — see Gotchas) before sending, since SNS email is plain text. |
| `setup_sns` | `(email=None) -> Dict` | One-time setup helper: creates the topic, optionally subscribes an email, and prints the ARN to copy into `.env`. Not called by the pipeline — this is a manual bootstrap step. |

### Return values from `publish_alert` / `publish_metric_alert`

| Scenario | Return |
|----------|--------|
| Sent successfully | `{'status': 'sent', 'message_id': '<uuid>', 'topic_arn': '...'}` |
| No `SNS_TOPIC_ARN` and no `topic_arn` arg | `{'status': 'skipped', 'reason': 'no_topic_arn'}` |
| `boto3.ClientError` (bad ARN, permissions, etc.) | `{'status': 'error', 'error': '<message>'}` — caught, not re-raised |

## Running standalone

```bash
# First-time setup — creates the SNS topic and subscribes an email
python -m alerting.sns_publisher --setup --email your@email.com

# Send a canned test message to whatever SNS_TOPIC_ARN is configured
python -m alerting.sns_publisher --test
```

With neither flag, it just prints usage and exits 0 (no error).

## Config / env vars

| Var | Required | Used by |
|-----|----------|---------|
| `AWS_REGION` | yes | `get_sns_client()` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | yes | `get_sns_client()` |
| `SNS_TOPIC_ARN` | only if `topic_arn` isn't passed explicitly | `publish_alert()` |

Loaded via `load_dotenv()` at module import time.

## Upstream / downstream

- **Upstream:** `narrative/generator.py`'s `generate_narrative()` output — specifically the `email_subject` and `full` (or `summary`) keys.
- **Downstream:** nothing consumes this module's output programmatically. `orchestration/run_pipeline.py` calls `publish_metric_alert()` as the final step (only when an anomaly was detected or `force_alert=True`, and skipped entirely when `dry_run=True`). `monitoring/cloudwatch_metrics.py` separately records whether an alert was sent (`AlertsSent` metric) by reading the pipeline's own results dict — it does not call back into this module.

## Gotchas

- `publish_metric_alert`'s markdown-stripping (`message.replace('**', '').replace('*', '')`) is a blunt find-and-replace, not markdown-aware — any literal `*` in a segment name (unlikely but possible) would also get stripped.
- `create_topic_if_not_exists` and `subscribe_email` catch `ClientError` and log-then-`raise` — unlike `publish_alert`, a setup failure here **is** propagated to the caller, not swallowed into a status dict. Don't assume every function in this module fails soft.
- No retry logic anywhere — a transient SNS API failure just returns `{'status': 'error', ...}` once.

## Tests

**No dedicated test file.** `tests/` (top-level) has no `test_alerting.py` / `test_sns_publisher.py` — this is the one module in the analytics pipeline (detection/decomposition/narrative all have coverage) without unit tests. Testing it would require mocking `boto3.client('sns')`.
