# tests/

Unit tests for the pure-computation parts of the analytics pipeline: z-score anomaly detection,
contribution decomposition, narrative generation, the deterministic halves of the Phase 1
investigation graph and Phase 1's eval-metric aggregation, and (as of `docs/ROADMAP.md` milestone
M4) the deterministic halves of Phase 2's dataset-onboarding profiling and classification. Run via
`pytest` and gated by CI (`.github/workflows/ci.yml`'s `lint-and-test` job).

**Correction to `docs/`:** `docs/resume_project_doc.md` and `docs/infrastructure_and_deployment.md`
both state "13 tests, 3 files" and that "Redshift is mocked in all 13 tests." Neither claim is
accurate as of the current code:

- **Actual test count is 61, not 13** — the original 3 files still total 15
  (`test_anomaly_detector.py` 5, `test_decomposer.py` 4, `test_narrative.py` 6), plus 46 more added
  across the agentic-layer initiative's M0–M4: `test_investigation_routing.py` (11),
  `test_ambiguity_rules.py` (9), `test_citation_validation.py` (8), `test_eval_summarization.py` (4),
  `test_profiling.py` (8), `test_classification_validation.py` (6). `docs/detection_layer.md`,
  `docs/analytics_pipeline.md`, and `docs/dbt_transformations.md`-adjacent per-layer docs already
  list the correct 5/4/6 breakdown for the original 3 files — only the two summary docs above have
  the stale "13" total.
- **No mocking is used at all** — not `unittest.mock`, not a fixture, not `pytest-mock`, not
  `redshift_connector` monkeypatching. Every test constructs an in-memory `pandas.DataFrame` (or
  plain dict) and calls a pure function directly. None of the tested functions perform I/O or call
  an LLM — the DB-touching functions (`fetch_daily_metrics`, `run_detection`'s Redshift fetch,
  `fetch_dimension_metrics`, `fetch_detail_metrics`, `get_comparison_dates`) and the LLM-touching
  functions (`synthesize`/`_run_synthesis`, `classify_columns_with_validation`) are simply never
  called by any test in this directory — those are exercised by `investigation/eval.py` and
  `onboarding/eval.py` instead (real API calls, run manually, not part of `pytest`). "Redshift is
  mocked" should read "Redshift-dependent and LLM-dependent code paths are untested here by design;
  only the pure functions downstream of them are covered."

## Files

| File | Test functions | Covers |
|------|----------------|--------|
| `test_anomaly_detector.py` | 5 | `calculate_zscore` (mean≈0 for median value, scaling on an outlier), `detect_anomalies` (no false positives on stable data, detects an obvious 5x spike, labels `anomaly_direction='low'` on a sharp drop) |
| `test_decomposer.py` | 4 | `calculate_contribution` (adds `change`/`contribution_pct` columns, contributions sum to ~100% when all segments move the same direction, all-negative changes handled, zero `previous_value` doesn't raise) |
| `test_narrative.py` | 6 | `format_currency` (basic, large number with commas, `None`→`"0.00"`, negative→absolute value), `generate_narrative` (all 4 format keys present, `summary` contains metric name and top driver segment) |
| `test_investigation_routing.py` | 11 | `route_after_detection`, `route_after_ambiguity`, `route_after_synthesis` (`investigation/routing.py`) — anomaly found vs. not vs. `force_investigate`; pending `close_contributors` vs. `offsetting_segments`-only vs. already-drilled vs. iteration cap; `should_continue` vs. iteration cap |
| `test_ambiguity_rules.py` | 9 | `classify_ambiguity` and `assess_ambiguity` (`investigation/nodes.py`) — clear dominant contributor, close top two, offsetting (>100%/<0%) top contributor, offsetting-takes-priority edge case, single/no contributors, the `[0,100]` boundary, and an end-to-end node run against a full `decomposition_results` fixture |
| `test_citation_validation.py` | 8 | `validate_citation`/`validate_synthesis_output` (`investigation/validation.py`) — valid/invalid segment, wrong source, wrong dimension, the required-`uncertainty_note` rule |
| `test_eval_summarization.py` | 4 | `summarize_results` (`investigation/eval.py`) — all first-attempt-grounded, retry-grounded excluded from `grounding_pass_rate`, fallback trials counted correctly, empty-list edge case |
| `test_profiling.py` | 8 | `profile_column`/`profile_columns` (`onboarding/profiling.py`) — clean date-string column, numeric column never misread as a date, high-cardinality ID-like column, low-cardinality categorical column, high-null free-text column, already-`datetime64` column, sample-value cap, full-DataFrame profiling |
| `test_classification_validation.py` | 6 | `validate_classification` (`onboarding/classification.py`) — each of the three validation rules independently, all three combined, a fully-valid case, and a `date_column=None` non-error |
| `test_action_policy.py` | 18 (57 cases, parametrized) | `policy_check` (`action_agent/policy.py`) — every catalog action's valid proposal gets the decision its tier implies; nothing in the catalog auto-executes (since A5); out-of-catalog and T2 (via an injected test catalog, not a mock) rejected; injected extra params, missing params, out-of-range/non-strict `days`/`expires_in_days`/`threshold` rejected; `(dimension, segment)` grounding against decomposition evidence, including an instruction-carrying segment name; malformed proposals rejected rather than raised |
| `test_action_dry_run.py` | 15 (24 cases) | `anomaly_id`/`idempotency_key`/`canonical_json` (`action_agent/identity.py`), `resolve_owner`/`OwnersConfig` (`action_agent/owners.py`), `build_dry_run`/`evidence_table`/`render_dry_run` (`action_agent/dry_run.py`) — deterministic hashing, edit → new key, owner precedence (segment > dimension `*` > default), dry-run shape for every action, recipient resolved from owners not params, injected-clock expiries, Markdown escaping of untrusted segment names. Reuses `test_action_policy.py`'s evidence fixture |
| `test_action_store.py` | 9 | `ActionStore` (`action_agent/store.py`) on a real SQLite file in `tmp_path`: `action_log` UPDATE/DELETE refused by triggers, also from a raw connection after reopen; one proposal per anomaly (D1); one `executed` row per idempotency key; status derivation; key-specific approval lookup; evidence snapshot round-trip |
| `test_action_graph.py` | 16 | The full action graph (`action_agent/graph.py`, `runner.py`) with a real `SqliteSaver`, a `RecordingExecutor`, an injected clock and an injected proposer: T1 waits and survives a restart, reject, T0 auto-execute (with an injected catalog, since no catalog action is T0), `annotate_anomaly` waiting for approval, policy rejection never reaching the approver, valid and invalid edits, an edit that tries to change `action_type`, an unknown decision, TTL expiry, the D1 duplicate run, re-running execute 3× from a checkpoint (one execution), a tampered payload at execute failing closed (F1), exact decision replay, trace-id linking, and numpy evidence (a live-run regression) |
| `test_tracing.py` | 4 | `observability/tracing.py` with tracing off: helpers make no network calls and don't raise; `run_config` metadata, tags and thread |
| `test_local_warehouse.py` | 12 | Local stack (`docs/local-stack-scope.md`): `config.db.connection_factory` dispatch (`redshift` selects the archived function without connecting; unknown backend rejected), missing-warehouse error, read-only DuckDB connection, `settings.backend_default` keeping Lambda on AWS, `parse_ddl` (comments, single-line tables, `DECIMAL(10,2)`, the real `infrastructure/redshift_setup.sql`), and `load_raw` on real tiny CSVs (leading zeros, empty → NULL, positional DDL names over the CSV's typo header, BOM, idempotency, column-count and missing-file errors) |
| `test_llm_telemetry.py` | 10 | `observability/llm.py` with an injected model returning canned `include_raw` results: tokens, cost from the dated price table, latency and prompt hash on a grounded call; `invalid` when validation fails; parse and API errors recorded then re-raised with the record attached; the budget charged from logged usage; a call that can't fit never sent; the estimate formula; unknown model → null cost; a model without `include_raw`; an unwritable log never changing the result |
| `test_llm_proposer.py` | 19 | `action_agent/llm_proposer.py`: validation (ungrounded citation and param, out-of-range params, unused params dropped); D2 routing (20b grounded, invalid → 120b with errors fed back, API error and parse error escalate, two failures fall back, only one retry, `--small-only`); the budget (too small for the first call, spent before the escalation); N3 (a hostile segment name and narrative stay inside the data block; the system prompt is constant and lists every action and bound); the graph storing the proposer and its trail on the `proposed` row; the A5-2 repair (a `functions.ProposalDraft` tool name repaired instead of escalating, only that slip accepted, a repaired draft still validated) |
| `test_action_executors.py` | 13 | A4 executors: `notify_owner` writing an outbox message to the resolved owner with the key in metadata, a non-outbox channel simulated without `--live`; `open_incident` against a **real local HTTP server** speaking GitHub's REST calls (simulated without live, one issue with the key marker and labels, an issue already carrying the key reused not duplicated, a new key opening a new issue, a 422 raised, undo closing with a comment, undo of a real issue needing live, undo of a simulated one), client validation, issue-number parsing |
| `test_action_hooks.py` | 20 | A4 undo and pipeline hooks through a real `ActionAgent` on tmp SQLite with the real executors and a tmp outbox: D3 suppression (applies to its own anomaly only, ends at expiry, nothing without `actions.db`, and a check never creates it); F3 undo (a compensating row with effect rows untouched, twice refused, `notify_owner` not reversible, a reason and an executed action required); `notify_owner` really writing the owner message; D4 (strict thresholds, one alert per watch per day with a `control_breached` row and the real proposal id in the message, a new day alerts again, no breach no alert, a missing segment counts as 0, dry run sends nothing, undone and expired watches skipped); a non-decomposable metric refused clearly |
| `test_action_api.py` | 16 | A6 Action Agent API through Django's real routing and DRF (`APIClient`), with a real `ActionAgent` on tmp SQLite injected via `override_settings(ACTION_AGENT_FACTORY=...)`: 503 on every endpoint with no or a short token, 401 for a missing or wrong one (and nothing decided); pending shows the dry run; approve executes and logs the `ACTION_APPROVER` actor; a second decision 409; reject needs a reason, edit needs object params; an edit that fails policy stays pending with its errors; 404 for unknown and non-UUID ids; undo writes one `undone` row carrying a trace id and is refused twice and for `notify_owner`; log newest-first with a limit; `live` only for JSON `true`; the API never creates `actions.db`; throttles: wrong tokens count toward the limit, decisions have their own limit, and `investigate` / `pipeline` are throttled (via 405s, so nothing runs) |
| `test_olist_sample.py` | 5 | `ingestion/make_olist_sample.py` on real tiny CSVs in `tmp_path`: the date window (boundary day included) and referenced-rows-only rules (unused customers, products and sellers dropped; the translation table kept whole), byte-for-byte line copying with mixed quoting and a BOM, deterministic output, a multi-line record refused; plus the **committed** `data/fixtures/olist_sample/` loaded into a real DuckDB: total 32,749 rows, no orphaned items, payments, orders, products or sellers, first order date 2018-08-01 |
| `test_notifier.py` | 13 | `alerting/notifier.py` (local-stack L2) on a real outbox directory in `tmp_path`: front matter and `index.jsonl` format, same-second collisions never overwrite, numpy metadata and an unsafe subject, default recipient, an I/O failure returned not raised, the narrative → subject/body mapping (Markdown kept) and its fallbacks, channel dispatch (`sns` selects the archived publisher), the real unchanged `sns_publisher` on its no-topic branch (`SNS_TOPIC_ARN=''`, never unset — see `alerting/README.md`), unknown/case-insensitive channel names, and the Lambda default |
| `__pycache__/` | — | pytest bytecode cache, not source |

No `conftest.py`, no `__init__.py` in this directory (each test file does its own `sys.path.insert(0, str(Path(__file__).parent.parent))` to import from the repo root).

## Functions tested (imports per file)

```python
# test_anomaly_detector.py
from detection.anomaly_detector import calculate_zscore, detect_anomalies

# test_decomposer.py
from decomposition.decomposer import calculate_contribution

# test_narrative.py
from narrative.generator import format_currency, generate_narrative

# test_investigation_routing.py
from investigation.routing import MAX_ITERATIONS, route_after_ambiguity, route_after_detection, route_after_synthesis

# test_ambiguity_rules.py
from investigation.nodes import assess_ambiguity, classify_ambiguity

# test_citation_validation.py
from investigation.validation import validate_citation, validate_synthesis_output

# test_eval_summarization.py
from investigation.eval import summarize_results

# test_profiling.py
from onboarding.profiling import ID_CARDINALITY_THRESHOLD, profile_column, profile_columns

# test_classification_validation.py
from onboarding.classification import MAX_DIMENSION_CARDINALITY_RATIO, MIN_DATE_PARSE_RATE, validate_classification

# test_action_policy.py
from action_agent.catalog import CATALOG, ActionSpec, Tier
from action_agent.policy import AUTO_EXECUTE, NEEDS_APPROVAL, REJECTED, policy_check

# test_action_dry_run.py
from action_agent.dry_run import ActionContext, build_dry_run, evidence_table, render_dry_run
from action_agent.identity import anomaly_id, canonical_json, idempotency_key
from action_agent.owners import OwnersConfig, load_owners, resolve_owner
```

## Running

```bash
# All tests, verbose
pytest tests/ -v

# Matches the CI command exactly
pytest tests/ -v --tb=short

# Single file
pytest tests/test_anomaly_detector.py -v

# Single test
pytest tests/test_narrative.py::TestFormatCurrency::test_none_value -v
```

No `pytest.ini` / `pyproject.toml` `[tool.pytest.ini_options]` section exists at the repo root — pytest runs with defaults, discovering `test_*.py` files anywhere pytest is pointed.

## Env vars / external dependencies

None. No `.env`, no AWS credentials, no live Redshift connection required — that's the point of testing only the pure functions. This is why CI can run these tests without any AWS secrets configured.

## How it connects to other folders

Imports directly from `detection/`, `decomposition/`, `narrative/`, `investigation/`, and (as of M4)
`onboarding/` (not `alerting/`, `orchestration/`, `monitoring/`, or any Django/`dashboard_api` code
— those have zero test coverage). `.github/workflows/ci.yml` runs `pytest tests/ -v --tb=short` in
the `lint-and-test` job; a failure here fails CI (previously a `|| echo ...` swallowed failures
silently — see `docs/infrastructure_and_deployment.md`'s Issues Fixed table — that swallow clause
is gone from the current `ci.yml`). No `GROQ_API_KEY` or live Redshift connection is needed to run
this directory's tests — verified explicitly each milestone by re-running the full suite with
`.env` removed entirely.

## Gotchas

- Because nothing mocks or exercises `fetch_daily_metrics`, `fetch_dimension_metrics`, `get_comparison_dates`, `run_detection`'s Redshift path, `publish_metric_alert`'s actual boto3 publish (only its no-topic branch runs, via `test_notifier.py`), or any Django view — a broken Redshift query, broken SQL, or broken SNS call would pass CI undetected. Coverage is limited to the arithmetic/formatting layer.
- `test_zscore_mean_is_zero` asserts `abs(zscores.iloc[2]) < 0.1` for the *middle* value of `[10,20,30,40,50]` — this only holds because the series is symmetric around its mean; it is not a general "median z-score is 0" guarantee.
