# onboarding/

The Phase 2 agentic layer: given a brand-new, never-seen flat dataset, produces the same
`{date_column, metric_columns, dimension_columns, rejected_columns}` contract a human currently
hand-writes into `decomposition/decomposer.py`'s `DIMENSION_TABLES`. Design record: `docs/scoping.md`
Sections 5–7. Roadmap status: `docs/ROADMAP.md` Phase 2.

## Scope as of M4

This folder currently contains **only Section 5** — deterministic profiling (Stage A) and LLM
classification + validation (Stage B). Three things named in `docs/scoping.md` §§6–7 are
intentionally **not** here yet:

- `codegen.py` — turning a validated `SchemaClassification` into actual queryable DuckDB tables
  (§6). M5.
- The CLI confirmation flow and schema-fingerprint cache (§7) — human-in-the-loop review, and the
  mechanism that skips re-review for an already-confirmed, unchanged dataset. M5.
- A dashboard-based onboarding wizard — named but explicitly deferred as v2 (§7.7), CLI only for v1.

`requires_human_review` (below) reflects **validation outcome only** in M4 — `True` only if the
bounded retry still leaves errors. §5.6's stronger rule ("still `True` for a first-ever run
against a brand-new dataset regardless of validation success") depends on the schema-fingerprint
cache, which doesn't exist yet — that's M5's job, not claimed here.

## Files

| File | Purpose |
|------|---------|
| `profiling.py` | Stage A: `ColumnProfile`, `ID_CARDINALITY_THRESHOLD`, `profile_column()`, `profile_columns()`. 100% deterministic, no LLM call. |
| `schemas.py` | Stage B's structured-output types: `DimensionCandidate`, `RejectedColumn`, `SchemaClassification`. |
| `llm.py` | `get_classification_llm()` — same provider/method as `investigation/llm.py`'s `get_synthesis_llm()`. |
| `prompts.py` | `build_classification_prompt()` — formats profiles into the evidence bundle + system prompt. |
| `classification.py` | `MIN_DATE_PARSE_RATE`, `MAX_DIMENSION_CARDINALITY_RATIO`, `validate_classification()`, `classify_columns_with_validation()` (the bounded-retry orchestrator). |
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

## Tests

`tests/test_profiling.py` (`profile_column`/`profile_columns`, including the numeric-column date-parse
guard) and `tests/test_classification_validation.py` (`validate_classification`'s three rules,
independently and combined) — fixture-in, exact-value-out style, no mocking, no LLM calls (see
`tests/README.md`). `classify_columns_with_validation` is **not** unit-tested this way — same
deterministic-vs-LLM split as `investigation/`; it's exercised by `eval.py`'s golden case instead.

## Upstream / downstream

- **Upstream:** `config.settings.GROQ_API_KEY`/`GROQ_MODEL` (reused, no new env vars). No
  dependency on `detection`/`decomposition`/`narrative`/`investigation` — Stage A/B operate purely
  on a pandas `DataFrame`, independent of the rest of the pipeline.
- **Downstream:** nothing yet. `codegen.py` (M5) is what turns a validated `SchemaClassification`
  into tables the rest of the pipeline (and the unmodified Phase 1 investigation agent) can query.
