# onboarding/

The Phase 2 agentic layer: given a brand-new, never-seen flat dataset, produces the same
`{date_column, metric_columns, dimension_columns, rejected_columns}` contract a human currently
hand-writes into `decomposition/decomposer.py`'s `DIMENSION_TABLES`. Design record: `docs/scoping.md`
Sections 5–7. Roadmap status: `docs/ROADMAP.md` Phase 2.

## Scope as of M5

Sections 5, 6, and 7 all exist now: profiling + classification (Stage A/B), codegen (turning a
validated contract into real DuckDB tables), the CLI confirmation flow, and the schema-fingerprint
cache. One thing named in `docs/scoping.md` is intentionally **not** here yet:

- A dashboard-based onboarding wizard — named but explicitly deferred as v2 (§7.7), CLI only for v1.

**M5 does not touch `investigation/`.** §6.2's closing paragraph says the Phase 1 agent works
against onboarded data "unmodified beyond the two [decomposer/anomaly_detector] parameters," but
`investigation/tools.py`'s wrappers currently call `decompose_metric()`/`fetch_detail_metrics()`
with no config passthrough at all — *something* still needs deciding about how a dataset's
`dimension_config`/`connection_factory` actually reaches the graph. Left as an explicit open
question for M6 (the milestone that runs a real dataset through the full cycle), not resolved here.

`requires_human_review` still reflects **validation outcome only**, not §5.6's stronger "always
`True` for a first-ever run" rule — the schema-fingerprint cache (below) now exists, but that rule
would require `onboard.py` to track review *history* per dataset beyond the fingerprint match/
mismatch binary already implemented. Named as a scope boundary, not silently overclaimed.

## Files

| File | Purpose |
|------|---------|
| `profiling.py` | Stage A: `ColumnProfile`, `ID_CARDINALITY_THRESHOLD`, `profile_column()`, `profile_columns()`. 100% deterministic, no LLM call. |
| `schemas.py` | Stage B's structured-output types: `DimensionCandidate`, `RejectedColumn`, `SchemaClassification`. |
| `llm.py` | `get_classification_llm()` — same provider/method as `investigation/llm.py`'s `get_synthesis_llm()`. |
| `prompts.py` | `build_classification_prompt()` — formats profiles into the evidence bundle + system prompt. |
| `classification.py` | `MIN_DATE_PARSE_RATE`, `MAX_DIMENSION_CARDINALITY_RATIO`, `validate_classification()`, `classify_columns_with_validation()` (the bounded-retry orchestrator). |
| `codegen.py` | `load_and_aggregate()`, `write_fact_table()`, `write_dimension_tables()`, `generate_tables()`, `validate_generated_tables()` — turns a validated contract into real DuckDB tables. 100% deterministic, no LLM call. |
| `fingerprint.py` | `schema_fingerprint()` — the schema-change detector behind the confirmation cache. |
| `onboard.py` | The CLI entry point — `python -m onboarding.onboard --file <path>`. |
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

- `load_and_aggregate(df, clf) -> pd.DataFrame` — parses `clf.date_column` (`errors='coerce'`,
  dropping unparseable rows with a warning rather than crashing), renames to `metric_date`. If
  `clf.grain == 'other'`: `groupby('metric_date')[clf.metric_columns].sum()` plus a free
  `row_count` bonus metric (`.size()` per day). If already `'daily'`: a rename-only pass-through
  with `row_count=1` per existing row.
- `write_fact_table(conn, df_daily)` / `write_dimension_tables(conn, df, clf) -> dict` — the
  latter returns the generated `dimension_config`, one `metric_by_<column>` table per dimension,
  `segment_col == detail_col == column` for every entry (§6.4 — no `dim_*` taxonomy layer for
  onboarded data; there's no finer grain to drill into than the dimension itself). Both use
  `CREATE OR REPLACE TABLE`, not `CREATE TABLE` — **found live**: a second onboarding run against
  the same dataset (the schema-fingerprint cache's whole point) reopens the existing `.duckdb`
  file, which already has these tables from the first run; `CREATE TABLE` alone crashed with a
  `CatalogException` on that second run. Matches this project's existing safe-to-rerun convention
  (`ingestion/setup_redshift_tables.py`'s `CREATE TABLE IF NOT EXISTS`).
- `generate_tables(df, clf, dataset_id) -> (duckdb_path, dimension_config)` — orchestrates the
  above, writes to `onboarding/generated/<dataset_id>/<dataset_id>.duckdb`. **Resolves a real
  disagreement in the design doc**: §6.3 describes a flat `<dataset_id>.duckdb` path directly under
  `generated/`; §7.5 describes a subfolder `generated/<dataset_id>/` containing both the `.duckdb`
  file and `classification.json`. This module follows §7.5's fuller structure — it actually needs
  a folder, since it colocates two files per dataset.
- `validate_generated_tables(conn, dimension_config, metric_columns) -> List[str]` — the
  reconciliation check (§6.5): every dimension's per-date totals must equal the fact table's.
  Rounds to 2 decimals before comparing (currency-style precision, matching
  `decomposer.py`'s existing `round(x, 2)`) rather than exact float equality — the fact table and
  each dimension table sum the same values through a different aggregation order (one groupby vs.
  a two-stage per-segment-then-per-date groupby), which can produce floating-point noise that
  isn't a real reconciliation bug. **Live-verified as a real, working catch, not just a passing
  test**: two separate live runs against Golden Case #2 had the LLM propose `notes` (a 40%-null
  free-text column with a coincidentally small non-null vocabulary) as a dimension — `notes` has
  low enough cardinality to pass `validate_classification`'s cardinality-only check, but pandas'
  `groupby` silently drops null-valued dimension rows, so `metric_by_notes`'s totals don't match
  the fact table's. Reconciliation correctly caught both times, exactly the failure mode §6.5
  names as its reason to exist ("e.g., a `GROUP BY` that silently dropped null-valued dimension
  rows"). This is a genuine gap in Stage B's simpler cardinality-only validator that reconciliation
  exists precisely to backstop — a deliberate two-layer defense, not treated as a Stage-B bug to
  fix in this milestone.

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
  (new dependency, M5). No dependency on `detection`/`decomposition`/`narrative`/`investigation`.
- **Downstream:** nothing yet. `investigation/`'s tools don't accept `dimension_config`/
  `connection_factory` passthrough, so nothing currently connects an onboarded dataset's generated
  tables to the Phase 1 investigation agent — that connection is M6's open question (see Scope,
  above).
