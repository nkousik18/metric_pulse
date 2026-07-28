# narrative/

Converts a decomposition result into plain-English text, in four output formats, using inline Jinja2 templates. This is the **third stage** of the analytics pipeline — pure text rendering, no I/O, no external calls.

## Files

| File | Purpose |
|------|---------|
| `generator.py` | Everything — templates, custom Jinja2 filters, `generate_narrative()`. |
| `__init__.py` | Empty — makes the folder an importable package. |
| `templates/` | **Empty directory.** No `.jinja2` files live here — confirmed by directory listing. All templates are inline Python triple-quoted strings inside `generator.py` (`METRIC_CHANGE_TEMPLATE`, `SLACK_TEMPLATE`, `EMAIL_SUBJECT_TEMPLATE`). This matches `docs/analytics_pipeline.md`, which notes a dead `narrative/templates/metric_drop.jinja2` file was already deleted. If you're looking for the actual template source, it's in `generator.py`, not this directory. |

## Templates & filters

| Template constant | Renders to output key | Notes |
|---|---|---|
| `METRIC_CHANGE_TEMPLATE` | `full` | Multi-paragraph markdown, emoji header, per-dimension breakdown loop. |
| `SLACK_TEMPLATE` | `slack` | Slack mrkdwn, `:chart_with_upwards/downwards_trend:` chosen by `direction`. |
| `EMAIL_SUBJECT_TEMPLATE` | `email_subject` | One-liner. |
| *(no template — built with an f-string)* | `summary` | Plain sentence, built directly in Python, not via Jinja2. |

Custom filters registered on the module-level `jinja_env`:
- `format_currency(value)` — `None → "0.00"`; otherwise `f"{abs(float(value)):,.2f}"` (always absolute value — sign is handled separately by `direction`/`direction_verb` in the surrounding text).
- `abs` — pass-through to Python's builtin, used e.g. as `{{ top_driver.contribution_pct | abs }}` since `contribution_pct` can be negative (see `decomposition/README.md`).

## `generate_narrative()`

```python
generate_narrative(decomposition_results: Dict, anomaly_info: Optional[Dict] = None, format_type: str = 'all') -> Dict[str, str]
```

- Takes `decompose_metric()`'s return dict directly (reads `.current_date`, `.previous_date`, `.metric`, `.dimensions`).
- **`current_value`/`previous_value`/`change_value`/`change_pct` are pulled from the *first* dimension in `decomposition_results['dimensions']`** (`list(...values())[0]`), on the assumption all three dimensions' totals agree (they should, since they're all slicing the same metric on the same two dates). If a dimension is missing or errored, this silently uses whichever dimension happens to be first in dict order.
- Independently re-scans every dimension's `top_contributors` to find the single highest `abs(contribution_pct)` — this duplicates `decomposition.decomposer.get_top_driver()`'s logic rather than calling it.
- `anomaly_info` parameter is accepted but **not used anywhere in the function body** — dead parameter as of the current code.
- `format_type` actually filters output now: `'all'` (default) returns all 4 keys; `'full'`/`'slack'`/`'summary'` return `{that_key: value}`; `'email'` is special-cased to map to the `email_subject` key; anything else raises `ValueError`. (Previously this parameter was accepted but ignored — see `docs/analytics_pipeline.md` Issues Fixed table — that bug is not present in the current code.)

### Return shape (`format_type='all'`)

```python
{
    'full': '📊 **MetricPulse Alert: Total Revenue decrease**\n\n...',
    'slack': ':chart_with_downwards_trend: *MetricPulse Alert*\n\n...',
    'email_subject': 'MetricPulse: Total Revenue decrease 90.6% on 2018-09-03',
    'summary': 'Total Revenue decreased 90.6% on 2018-09-03. Primary driver: Credit Card (payment) contributed 106.6% of the change.'
}
```

## Running standalone

```bash
python -m narrative.generator
```

This imports `decomposition.decomposer` directly (`from decomposition.decomposer import decompose_metric, get_comparison_dates`), runs a real decomposition against Redshift using the latest 2 dates, then prints the `full`, `slack`, and `email_subject` outputs. Requires a live Redshift connection — this is not a pure offline demo.

## Config / env vars

None. No `load_dotenv()` call in this module (removed — see Issues Fixed in `docs/analytics_pipeline.md`) and no environment reads. Purely a function of its inputs.

## Upstream / downstream

- **Upstream:** `decomposition/decomposer.py`'s `decompose_metric()` output is the required input shape.
- **Downstream:** `alerting/sns_publisher.py`'s `publish_metric_alert()` reads `narratives['email_subject']` and `narratives['full']` (falling back to `narratives['summary']`). `orchestration/run_pipeline.py` calls `generate_narrative()` as step 4. `dashboard_api/views.py` exposes it via `/api/narrative/`.

## Gotchas

- `top_driver` can be `None` if every dimension in `decomposition_results` has an `'error'` key or empty `top_contributors` — the templates then render `top_driver.dimension`/`.segment` against `None`, which Jinja2 renders as empty string rather than raising, so a broken decomposition silently produces a narrative with blank driver info instead of failing loudly.
- `anomaly_info` is a vestigial parameter — passing it does nothing currently.

## Tests

Covered by `tests/test_narrative.py` — 6 tests: 4 on `format_currency` (basic, large numbers, `None`, negative/absolute-value handling) and 2 on `generate_narrative` (all 4 keys present for `format_type='all'`; `summary` contains the metric name and top driver segment). Uses a hand-built mock decomposition dict, no Redshift needed.

```bash
pytest tests/test_narrative.py -v
```

Note: the `format_type` filtering branches (`'full'`, `'slack'`, `'email'`, invalid value → `ValueError`) are **not** exercised by this test file — only the `'all'` path is tested.
