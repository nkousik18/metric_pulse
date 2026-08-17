# onboarding/

The Phase 2 agentic layer: given a brand-new, never-seen flat dataset, produces the same
`{date_column, metric_columns, dimension_columns, rejected_columns}` contract a human currently
hand-writes into `decomposition/decomposer.py`'s `DIMENSION_TABLES`. Design record: `docs/scoping.md`
Sections 5–7. Roadmap status: `docs/ROADMAP.md` Phase 2.

## Scope as of M6

All of Sections 5–7 exist, and Phase 2's overall gate is met: a real, never-before-referenced
dataset ("Sample Superstore Sales") goes from a raw CSV through profiling, classification,
human confirmation, codegen, and a real `detect → decompose → narrate` cycle, with the Phase 1
investigation agent running against it — genuinely, verifiably unmodified (see
`investigation/README.md`'s M6 section for the one real fix that made "unmodified" actually true).
One thing named in `docs/scoping.md` is intentionally **not** here:

- A dashboard-based onboarding wizard — named but explicitly deferred as v2 (§7.7), CLI only for v1.

`requires_human_review` still reflects **validation outcome only**, not §5.6's stronger "always
`True` for a first-ever run" rule — the schema-fingerprint cache exists, but that rule would
require `onboard.py` to track review *history* per dataset beyond the fingerprint match/mismatch
binary it implements. Named as a scope boundary, not silently overclaimed.

## Files

| File | Purpose |
|------|---------|
| `profiling.py` | Stage A: `ColumnProfile`, `ID_CARDINALITY_THRESHOLD`, `profile_column()`, `profile_columns()`. 100% deterministic, no LLM call. |
| `schemas.py` | Stage B's structured-output types: `DimensionCandidate`, `RejectedColumn`, `SchemaClassification`. |
| `llm.py` | `get_classification_llm()` — same provider/method as `investigation/llm.py`'s `get_synthesis_llm()`. |
| `prompts.py` | `build_classification_prompt()` — formats profiles into the evidence bundle + system prompt. |
| `classification.py` | `MIN_DATE_PARSE_RATE`, `MAX_DIMENSION_CARDINALITY_RATIO`, `validate_classification()`, `classify_columns_with_validation()` (the bounded-retry orchestrator). |
| `codegen.py` | `sanitize_identifier()`, `load_and_aggregate()`, `write_fact_table()`, `write_dimension_tables()`, `generate_tables()`, `validate_generated_tables()` — turns a validated contract into real DuckDB tables. 100% deterministic, no LLM call. |
| `fingerprint.py` | `schema_fingerprint()` — the schema-change detector behind the confirmation cache. |
| `onboard.py` | The CLI entry point — `python -m onboarding.onboard --file <path>`. |
| `investigate.py` | The bridge to the rest of the pipeline — `python -m onboarding.investigate --dataset-id <id> --metric <col> [--run-investigation]` (M6). |
| `eval.py` | `GOLDEN_CASE_2` (§5.6, the SaaS fixture) — `python -m onboarding.eval`, run manually. |
| `__init__.py` | Empty — makes the folder an importable package. |

## Stage A: `ColumnProfile` (`profiling.py`)

```python
class ColumnProfile(BaseModel):
    name: str
    dtype: str
    cardinality: int
    cardinality_ratio: float   # n_unique / n_rows (total rows, including nulls)
    null_rate: float
    sample_values: List[str]   # first 5 non-null values, stringified
    date_parse_rate: float     # fraction of a bounded sample pd.to_datetime() parses
    is_numeric: bool
    is_likely_id: bool         # cardinality_ratio > ID_CARDINALITY_THRESHOLD (0.9)
```

`profile_columns(df) -> Dict[str, ColumnProfile]` applies `profile_column()` to every column.
No network call, no LLM — scales with column count, not row count (§5.2).

**A real pandas quirk this module guards against:** `pd.to_datetime()` coerces plain numbers into
"successfully parsed" nanosecond-epoch timestamps with ~100% success — without an explicit guard,
every numeric metric column would get `date_parse_rate=1.0`. `_date_parse_rate()` short-circuits to
`0.0` for any column where `is_numeric_dtype` is true; only non-numeric (or already-`datetime64`)
columns are actually run through `pd.to_datetime()`. Verified directly in a REPL before writing the
guard, not assumed — see `tests/test_profiling.py::test_numeric_column_never_looks_like_a_date`.

`date_parse_rate` is computed over a bounded sample (`.head(1000)` of non-null values, not the
whole column) per §5.2's literal "a sample" wording — deterministic (`.head()`, not `.sample()`),
so re-profiling the same file twice gives identical output.

A column can have both `is_likely_id=True` (high `cardinality_ratio`) **and** a high
`date_parse_rate` at the same time — that's expected and correct for an already-daily-grain
dataset (one row per date looks unique too). `is_likely_id` only disqualifies a column from being a
`metric_column`/`dimension_column`, never from being `date_column`; both `prompts.py`'s system
prompt and `validate_classification()` treat it that way.

**A second real gap, found live against a real dataset (M6), not a synthetic fixture:** `is_likely_id`
originally applied the cardinality threshold to every numeric column, including floats. A real
sales dataset's genuine `Sales` (cardinality ratio 0.971) and `Profit` (0.930) columns both cleared
`ID_CARDINALITY_THRESHOLD` purely because continuous dollar amounts are almost all naturally unique
across thousands of rows — normal for a measurement, not an identifier signal — and `prompts.py`'s
own system prompt explicitly tells the model "never propose a column with `is_likely_id=True` as a
metric," so the two most important metrics in the whole dataset got rejected. Fixed: float columns
are now exempt from the cardinality check entirely; integer columns stay eligible (a genuinely
sequential ID like `Row ID`, ratio 1.0, is still caught, and an integer *metric* like `Order
Quantity` already has naturally low cardinality on its own, so it was never at risk of this false
positive the way a continuous float is). Verified directly against the real data before and after
the fix, not assumed fixed.

## Stage B: classification + validation (`schemas.py`, `llm.py`, `prompts.py`, `classification.py`)

```python
class SchemaClassification(BaseModel):
    date_column: Optional[str]
    grain: Literal['daily', 'other']
    metric_columns: List[str]
    dimension_columns: List[DimensionCandidate]   # column, cardinality, confidence, reasoning
    rejected_columns: List[RejectedColumn]          # column, reason -- nothing silently dropped
    requires_human_review: bool
    validation_errors: List[str]
```

The last two fields aren't in §5.2's illustrative code block but are required by §5.4/5.6's prose
("the contract is still emitted — but with `requires_human_review=True` and the unresolved issues
attached") — the same category of doc-vs-implementation gap already corrected once for §3.5's
`validate_citation` snippet in Phase 1. **The LLM is never asked to fill these two fields in** —
`classify_columns_with_validation()` always overwrites them post-hoc based on the real validation
outcome (`clf.model_copy(update={...})`), never trusting whatever the model happened to put there.

### `classify_columns_with_validation(profiles) -> SchemaClassification`

Structurally identical to `investigation/nodes.py`'s `_run_synthesis` (§10.3 names this reuse
explicitly): one real LLM call via `get_classification_llm()`, `validate_classification()`; on
failure, one retry with the specific errors appended to the prompt; if still failing, emit the
classification anyway with `requires_human_review=True` and `validation_errors` attached — never
crash, never silently accept a wrong answer (§5.4).

### `validate_classification(clf, profiles) -> List[str]`

Three checks, per §5.4:
1. `date_column`'s `date_parse_rate >= MIN_DATE_PARSE_RATE` (`0.95`, §5.3's own suggested value).
2. Every `metric_columns` entry is `is_numeric`.
3. Every `dimension_columns` entry's `cardinality_ratio <= MAX_DIMENSION_CARDINALITY_RATIO`.

**`MAX_DIMENSION_CARDINALITY_RATIO = 0.1`** — §5.3 doesn't pin an exact number ("low-to-moderate...
bounded, not near-unique"), but §5.6's own worked example does, implicitly: it rejects
`customer_id` (cardinality ratio 0.164) as "too high to be a useful grouping dimension" while
accepting `plan_type`/`region` (ratio ~0.00006) as obviously fine. `0.1` is chosen specifically to
sit between those two real numbers from the design doc's own example — calibrated, not guessed. An
earlier draft used `0.5` (a plain midpoint against `ID_CARDINALITY_THRESHOLD`'s `0.9`) and would
have incorrectly accepted `customer_id` as a valid dimension; caught by re-checking the constant
against §5.6's numbers before running the real eval, not after.

## Golden Case #2 (`eval.py`)

```bash
python -m onboarding.eval
```

`GOLDEN_CASE_2` is a synthetic SaaS-subscription dataset (fixed `np.random.default_rng(42)` seed,
500 rows) reproducing §5.6's worked example's *qualitative* profile shape per column — not
literally 50,000 rows; "run for real" means actually executing profiling + a live LLM call against
real data, not matching an arbitrary row count. Graded as sets of column names per role (date
column, grain, metric/dimension/rejected column sets), not exact `reasoning` text, matching how
`investigation/eval.py` grades structural fields rather than prose.

This is built at the same minimal scope `investigation/eval.py` had at Phase 1's M1 — a fixture
plus a bare grading run — not Phase 1's later M3-formalized scope (`--runs N`, tracked
`grounding_pass_rate`/`fallback_rate` metrics). `docs/ROADMAP.md` never names a Phase-2 equivalent
of M3 as its own milestone; M4's actual gate is just "Golden Case #2 run for real." Formalizing
this further is optional future work, not a named blocking gate.

**Live-verified**, real Groq API, real result: the first attempt proposed `customer_id` as a
dimension; `validate_classification` correctly rejected it (matching §5.6's own judgment); the
retry then got every field right — `date_column=event_date`, `grain=other`,
`metric_columns=[mrr_amount, seats]`, `dimension_columns=[plan_type, region]`,
`rejected_columns=[subscription_id, customer_id, notes]`, `requires_human_review=False`. A genuine
demonstration of the retry-then-validate mechanism catching a real mistake, not just passing on the
first try.

## Codegen (`codegen.py`, Section 6)

The LLM's job is finished by this point — everything here is deterministic, mechanical code.

```
GENERATED_DIR = onboarding/generated/
```

- `sanitize_identifier(name) -> str` (M6) — lowercase, non-alphanumeric runs collapsed to a single
  underscore, no leading digit. **Found live against a real dataset, not a synthetic fixture**: a
  raw column name like `"Order Priority"` or `"Product Sub-Category"` isn't a valid unquoted SQL
  identifier — it breaks DuckDB's own `CREATE TABLE` syntax outright, and every downstream
  f-string SQL query `decomposer.py`/`anomaly_detector.py` build (matching those modules' existing
  trust model that `dimension_config`'s values are internal, not raw user input — see
  `decomposition/README.md`'s Gotchas) would break the same way the moment it was queried. Every
  metric and dimension column gets renamed to its sanitized form before being written into the
  DuckDB tables; `classification.json` still stores the original, human-readable names the user
  actually confirmed, and `dimension_config`'s dict *keys* stay human-readable too (they're only
  ever a Python-level lookup, never themselves embedded in SQL, and they flow into
  narratives/investigation summaries where the readable spelling matters) — only the `table`/
  `segment_col`/`detail_col` *values*, and the `metric` argument callers actually pass to
  `run_detection()`/`decompose_metric()`, need to be the sanitized form.
- `load_and_aggregate(df, clf) -> pd.DataFrame` — parses `clf.date_column` (`errors='coerce'`,
  dropping unparseable rows with a warning rather than crashing), renames to `metric_date`; metric
  columns renamed via `sanitize_identifier()` (a no-op for already-safe names, like every existing
  test fixture's). If `clf.grain == 'other'`: `groupby('metric_date')[...].sum()` plus a free
  `row_count` bonus metric (`.size()` per day). If already `'daily'`: a rename-only pass-through
  with `row_count=1` per existing row.
- `write_fact_table(conn, df_daily)` / `write_dimension_tables(conn, df, clf) -> dict` — the
  latter returns the generated `dimension_config`, one `metric_by_<sanitized_column>` table per
  dimension, `segment_col == detail_col == sanitize_identifier(column)` for every entry (§6.4 — no
  `dim_*` taxonomy layer for onboarded data; there's no finer grain to drill into than the
  dimension itself). Both use `CREATE OR REPLACE TABLE`, not `CREATE TABLE` — **found live**: a
  second onboarding run against the same dataset (the schema-fingerprint cache's whole point)
  reopens the existing `.duckdb` file, which already has these tables from the first run;
  `CREATE TABLE` alone crashed with a `CatalogException` on that second run. Matches this project's
  existing safe-to-rerun convention (`ingestion/setup_redshift_tables.py`'s `CREATE TABLE IF NOT
  EXISTS`).
- `generate_tables(df, clf, dataset_id) -> (duckdb_path, dimension_config, sanitized_metric_columns)`
  — orchestrates the above, writes to `onboarding/generated/<dataset_id>/<dataset_id>.duckdb`. The
  third return value is what a caller must actually pass as `metric` — `clf.metric_columns` holds
  the original names. **Resolves a real disagreement in the design doc**: §6.3 describes a flat
  `<dataset_id>.duckdb` path directly under `generated/`; §7.5 describes a subfolder
  `generated/<dataset_id>/` containing both the `.duckdb` file and `classification.json`. This
  module follows §7.5's fuller structure — it actually needs a folder, since it colocates two files
  per dataset.
- `validate_generated_tables(conn, dimension_config, metric_columns) -> List[str]` — the
  reconciliation check (§6.5): every dimension's per-date totals must equal the fact table's,
  compared with `np.allclose(atol=0.01, rtol=1e-6)`, not exact float equality (§6.5's own code
  block uses `.equals()` literally). **A real, two-stage finding, not solved on the first try**: an
  earlier version rounded both sides to 2 decimals before comparing, which was enough for
  M4/M5's small synthetic fixtures but not for this real dataset's larger, messier real sums —
  found live: rounding doesn't help when the pre-rounding values straddle a rounding boundary
  (e.g. `31997.8549999...` vs `31997.8550001...` round to two *different* cent values), which
  produced a spurious 1-cent "mismatch" even though the underlying values agreed to 10+ significant
  figures. A proper numeric tolerance, applied to the raw (unrounded) sums, fixed it without
  weakening the check's ability to catch a real bug — `atol=0.01` is generous enough to absorb real
  floating-point noise, tight enough that an actual codegen bug (a whole day's transactions
  missing) still reliably fails. **Separately, live-verified as a real, working catch, not just a
  passing test**: two live runs against Golden Case #2 had the LLM propose `notes` (a 40%-null
  free-text column with a coincidentally small non-null vocabulary) as a dimension — `notes` has
  low enough cardinality to pass `validate_classification`'s cardinality-only check, but pandas'
  `groupby` silently drops null-valued dimension rows, so `metric_by_notes`'s totals don't match
  the fact table's. Reconciliation correctly caught both times, exactly the failure mode §6.5
  names as its reason to exist. This is a genuine gap in Stage B's simpler cardinality-only
  validator that reconciliation exists precisely to backstop — a deliberate two-layer defense, not
  treated as a Stage-B bug to fix.

## Fingerprint cache (`fingerprint.py`, `onboard.py`, Section 7.5)

`schema_fingerprint(profiles) -> str` — SHA-256 of sorted `(name, dtype)` pairs, order-independent,
changes on any rename/retype/add/remove. `onboard.py` stores it alongside the confirmed contract in
`onboarding/generated/<dataset_id>/classification.json`; a later run against the same `dataset_id`
compares fingerprints and skips straight to codegen on a match (§7.2's "unchanged schema" case),
or re-runs full classification + confirmation on a mismatch (§7.2's "schema changed" case). Both
paths **live-verified**: a repeat run against an unchanged file printed "Using previously-confirmed
classification" and skipped the prompt entirely; adding one column to the same file correctly
forced re-classification instead of silently reusing the stale contract.

## The CLI (`onboard.py`, Section 7.3)

```bash
python -m onboarding.onboard --file data/saas_subscriptions.csv
```

`[y]` confirm and proceed / `[e]` edit a column's role / `[n]` reject and abort. The `[e]` edit path
is bounded (§7.3's contract philosophy) — move one named column to `metric`/`dimension`/`reject`;
can't redefine the contract's shape itself. Every edit re-runs `validate_classification()` and
*shows* any resulting warnings, but — unlike the LLM's own output, which is blocked until it
passes or exhausts the retry — a human's edit is never blocked on them (§7.4: "a human reviewing
their own dataset is allowed to know things the profiler structurally can't"). **All three paths
live-verified in the terminal**, including the edit path's advisory-not-blocking warning actually
printing and the edit actually taking effect.

A found-and-fixed bug along the way, not a hypothetical: `onboard.py` originally called plain
`pd.read_csv(file_path)`. Pandas' default `na_values` list includes common tokens like `"NA"`,
`"N/A"`, `"NULL"` — so a real, legitimate categorical value of `"NA"` (a region code for North
America, in Golden Case #2's own fixture) was silently turned into a missing value on every CSV
round-trip, corrupting that column's null rate from 0% to 33.6% and causing its dimension table to
fail reconciliation for a reason that had nothing to do with codegen. Fixed with
`pd.read_csv(file_path, keep_default_na=False, na_values=[''])` — only a genuinely empty cell
counts as missing. This surfaced only once the real CLI path (CSV → `pd.read_csv`) was
live-tested; M4's in-memory-only `eval.py` never touched a CSV file and so never hit it.

## Bridging to the pipeline (`investigate.py`, M6)

`onboard.py` stops at a confirmed, codegen'd DuckDB file — `investigate.py` is what actually proves
the Phase 2 gate's "goes from a raw CSV to a working `detect → decompose → narrate` cycle... and the
Phase 1 investigation agent runs against it *unmodified*." It lives in `onboarding/`, not
`orchestration/`, because the gate's own wording places this capability here — extending
`orchestration/run_pipeline.py` with dataset-config awareness would be new scope beyond what M6
actually asks for.

```bash
python -m onboarding.investigate --dataset-id superstore_sales --metric sales
python -m onboarding.investigate --dataset-id superstore_sales --metric sales --run-investigation
```

- `build_dataset_config(dataset_id, dimension_config, metric_columns) -> dict` — constructs the
  exact `{dimension_config, connection_factory, table_name, metric_columns}` shape
  `investigation/tools.py`'s `_dataset_kwargs()` expects (see `investigation/README.md`'s
  `dataset_config (M6)` section). `metric_columns` includes codegen's free `row_count` bonus metric
  alongside the classified ones, so daily transaction volume is a valid investigable metric too.
- `load_dataset_config(dataset_id) -> (dict, SchemaClassification)` — reads the confirmed
  `classification.json` `onboard.py` already writes and deterministically reconstructs
  `dimension_config` from `clf.dimension_columns` (same `sanitize_identifier()` logic
  `codegen.write_dimension_tables()` used to build the real tables — not re-persisted separately,
  since it's cheap to derive and keeping one source of truth avoids the two ever drifting apart).
- `run_cycle(dataset_id, metric, threshold=None, run_investigation=False) -> dict` — calls
  `get_comparison_dates`, `run_detection`, `decompose_metric`, `generate_narrative` directly,
  unmodified, with the onboarded dataset's config instead of the Redshift defaults; when
  `run_investigation=True`, also builds an `InvestigationState` via `build_initial_state(...,
  dataset_config=...)` and invokes the completely untouched `investigation_graph`. Pre-seeds
  `detection_result`/`decomposition_results` into `build_initial_state` so the graph's `detect`/
  `decompose_all` nodes short-circuit rather than re-querying DuckDB a second time for data this
  function already has (matches `orchestration/run_pipeline.py`'s own pre-seeding pattern) — found
  live: an early version omitted these two arguments and every query visibly ran twice in the logs.

**Real, live-verified output** against the Superstore dataset (2009-12-30 vs. the prior comparison
date, `sales` metric):

```
python -m onboarding.investigate --dataset-id superstore_sales --metric sales
Summary: Sales decreased 83.2% on 2012-12-30. Primary driver: Small Box (Product Container)
contributed 89.4% of the change.

python -m onboarding.investigate --dataset-id superstore_sales --metric sales --run-investigation
Investigation status: completed
Investigation summary:
Dominant decline driven by medium priority orders: **Medium** (Order Priority) contributed
**81.83%** of the change ($12,866.43 -> $14.15). Contributing factors: - major contribution from
Express Air shipping: Express Air (76.31%) - large drop among customers in Quebec: Quebec (81.95%)
```

No `fallback_validation_failed`, no `grounding_failed` — real grounded citations against real
Superstore dimension names, across multiple separate live runs, from the completely unmodified
Phase 1 graph. This is only possible because of the `EvidenceCitation.dimension` fix documented in
`investigation/README.md`'s M6 section — before that fix, every citation against this dataset's real
(non-Olist) dimension names failed validation and every run fell back.

## Tests

`tests/test_profiling.py`, `tests/test_classification_validation.py` (Stage A/B, from M4),
`tests/test_codegen.py` (`load_and_aggregate` plus `write_fact_table`/`write_dimension_tables`
against a real **in-memory** DuckDB connection — `duckdb.connect(':memory:')`, genuinely exercising
real DuckDB behavior with no disk I/O, no mocking), `tests/test_reconciliation.py`
(`validate_generated_tables`, including a deliberately-corrupted fixture confirming it actually
catches a broken case), `tests/test_schema_fingerprint.py` (`schema_fingerprint`'s order-
independence and sensitivity to rename/retype/add/remove) — all fixture-in, exact-value-out, no
mocking, no LLM calls (see `tests/README.md`). `classify_columns_with_validation` and the
interactive CLI loop are **not** unit-tested this way — same deterministic-vs-LLM/interactive split
as `investigation/`; both are exercised by real, live runs instead (`eval.py`'s golden case for the
former, manual terminal verification for the latter).

## Upstream / downstream

- **Upstream:** `config.settings.GROQ_API_KEY`/`GROQ_MODEL` (reused, no new env vars). `duckdb`
  (new dependency, M5). `profiling.py`/`schemas.py`/`llm.py`/`prompts.py`/`classification.py`/
  `codegen.py`/`fingerprint.py`/`onboard.py` have no dependency on `detection`/`decomposition`/
  `narrative`/`investigation` — only `investigate.py` (M6) does, deliberately isolating the one
  module whose whole job is bridging to the rest of the pipeline.
- **Downstream (M6):** `investigate.py` calls `detection.anomaly_detector.run_detection`,
  `decomposition.decomposer.decompose_metric`/`get_comparison_dates`, and
  `narrative.generator.generate_narrative` directly with an onboarded dataset's
  `dimension_config`/`connection_factory`/`table_name`/`metric_columns` — the exact same additive
  parameters those modules gained in M5, now actually exercised end to end for the first time
  against real, non-Olist data. With `--run-investigation`, it also feeds a `dataset_config` into
  `investigation.state.build_initial_state`, connecting an onboarded dataset to the completely
  unmodified Phase 1 `investigation_graph` — see `investigation/README.md`'s `dataset_config (M6)`
  section for the mechanism, and this file's "Bridging to the pipeline" section above for real
  verified output. This resolves what M5 left as an open question (see the old Scope note, now
  superseded above): Phase 2's overall gate — the Phase 1 agent running unmodified against
  onboarded data — is met as of M6.
