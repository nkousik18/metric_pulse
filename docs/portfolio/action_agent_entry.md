# Portfolio entry — MetricPulse Action Agent

Same shape as the Interpose entry in the portfolio JSON. Every number is copied from a committed
source: `docs/action-agent-scope.md`, `docs/ROADMAP.md` (A1–A7), `evals/ledger.jsonl`,
`evals/baselines/action.json`, `docs/project/BUG_LOG.md` (A-rows), and `pytest --co` on
2026-11-13. Fields marked **TODO (Kousik)** need his confirmation; nothing there was guessed.

```json
{
  "id": "metricpulse-action-agent",
  "name": "MetricPulse Action Agent",
  "subtitle": "Human-approved, policy-gated actions on top of an automated root-cause-analysis pipeline (LangGraph + LangSmith)",
  "parent_project": "MetricPulse: anomaly detection -> segment decomposition -> LLM narrative -> alert, with a Phase 1 investigation agent and a Phase 2 dataset-onboarding agent",
  "status": "Solo, independent project. Milestones A1-A7 all complete as of 2026-11-12: scoped 2026-10-26, built 2026-11-01 to 2026-11-06, eval gate passed 2026-11-06 on a clean tree (de23866), first clean full drift run with 0 regressions on 2026-11-12 (06a58bf). Runs locally only (by design, D9).",
  "github": "github.com/nkousik18/metric_pulse",
  "built_with": "TODO (Kousik): confirm wording. Suggested, matching the Interpose entry: Claude Code wrote most of the code; Kousik designed it (scope, decisions D1-D11, the risk tiers, the golden labels) and directed and verified the build.",
  "summary": "Turns a validated anomaly investigation into one proposed action from a fixed 5-action catalog, gates it on a deterministic policy check and a human approval that survives a process restart, executes it idempotently, and records every step in a trigger-enforced append-only log linked to its LangSmith trace. The LLM only proposes; it never decides what runs. A small model (gpt-oss-20b) drafts the proposal with citations into the evidence; a grounding failure escalates once to gpt-oss-120b, then falls back to a deterministic proposal. A 30-case eval suite (15 human-labelled golden anomalies, 10 prompt-injection cases, 5 safety probes) gates every change, and a weekly drift run compares four evals across the whole system with their stored baselines.",
  "worked_example": "Real Olist (Brazilian e-commerce, 2016-2018) and Superstore (Canadian retail, 2009-2012) anomalies. Black Friday 2017 on Olist: the proposer sees a trusted holiday calendar and a share-adjusted driver check, finds the change spread proportionally across payment types with Black Friday on the date, and proposes annotate_anomaly with calendar_event='Black Friday'; policy verifies that event exists in the committed calendar within +/-3 days, and the proposal waits for approval. 2018-09-03 on Olist (1 order vs. a 28-day median of 247, the export's cut-off): the z-score misses it (z = -1.85) but the new data-freshness check flags it stale, and the agent proposes annotate_anomaly / data_issue instead of paging a segment owner. A real Credit Card watch (order_count below 5, actual 0) alerted the Payments Team once and logged control_breached; open_incident --live opened a real GitHub issue in a private repo, a replayed execution reused it rather than duplicating, and undo --live closed it.",
  "tech_stack": {
    "language": ["Python 3"],
    "agent_orchestration": ["LangGraph (separate action graph; interrupt() for human approval)", "langgraph-checkpoint-sqlite (SqliteSaver, pending approvals survive restart)"],
    "llm": ["Groq: openai/gpt-oss-20b (drafts), openai/gpt-oss-120b (escalation)", "LangChain structured output (tool calling, Pydantic schema)"],
    "observability": ["LangSmith (traces, datasets, experiments, approver decisions as feedback)", "Local append-only llm_calls.jsonl (model, tokens, cost, latency, outcome per call)"],
    "validation_policy": ["Pydantic (strict numerics)", "Deterministic policy_check (catalog, tier, param bounds, segment grounding, calendar grounding)"],
    "storage": ["SQLite: actions.db (proposals, action_log, annotations, suppressions, controls) and checkpoints.db", "DuckDB warehouse (local), dbt-duckdb"],
    "api_ui": ["Django REST Framework (/actions/* endpoints, scoped throttles)", "Django SPA approval queue"],
    "executors": ["GitHub Issues API (fine-grained PAT, one private repo)", "Local alert outbox via alerting.notifier (SNS archived)"],
    "ci": ["GitHub Actions: lint-and-test + dbt-build-local required on main"],
    "testing": ["pytest, no mocking: 401 tests in the suite, ~210 in the Action Agent's own files"]
  },
  "architecture": {
    "flow": "finalize (Phase 1 investigation) -> propose_action (the only LLM node) -> policy_check (deterministic) -> await_approval (LangGraph interrupt, SQLite checkpointer) -> execute (idempotency key = hash(anomaly_id, action_type, canonical params)) -> record (append-only action_log). A separate graph, so the Phase 1 graph and its no-checkpointer compile path stay byte-for-byte unchanged.",
    "action_catalog": "annotate_anomaly (tag a known cause; never affects alerting), suppress_alerts (1-7 days), notify_owner (narrative + evidence to the segment owner from owners.yaml), open_incident (GitHub issue with evidence table and citations), create_control (segment-level watch: absolute threshold, owner, expiry <= 30 days). All five are T1 (human approval). T2 (any data mutation) is rejected by policy before a human sees it. The T0 auto-execute path stays in the graph, tested with an injected catalog, for a future action with a trusted cause source.",
    "policy_check": "Action in catalog; tier permitted; params pass strict schema and range checks; any dimension/segment must appear in the investigation's real top contributors (an injected or hallucinated segment can't be targeted); holiday/promotion annotations must name an entry in the committed calendar within +/-3 days; a create_control threshold must lie within 0.1x-10x of the segment's real value. An approver's edit may change params only, never action_type, and edited params go through policy again.",
    "model_routing": "D2: 20b drafts and its citations are validated against the evidence. On an invalid citation, a policy rejection, an unparseable reply or an API error: one retry on 120b with the validation errors fed back as a JSON data field (never as instructions). A second failure falls back to a deterministic notify_owner. A 10,000-token budget per run, checked before each call (prompt chars / 4 + a 4,096 output reserve); over budget goes straight to the fallback.",
    "evidence_context": "Two deterministic additions to the proposer's evidence, both added after the first golden run failed: (1) a trusted per-dataset event calendar (Brazilian / Canadian national holidays plus named retail events, generated from rules with legal sources, committed before the re-run, and recomputed from the file on every start so a caller can't supply one); (2) a share-adjusted driver check: a segment 'drives' the change only when its share of the change exceeds its normal share of the metric (thresholds 50 / 15 / 10), so a segment that is simply most of the volume (Olist Credit Card, ~79%) no longer reads as the cause of every change.",
    "data_freshness": "A second detection signal next to the z-score, on record volume: stale when today's volume is under 25% of the previous 28 rows' median, applied only when that median is >= 50/day (otherwise reported 'not applicable', never 'fresh'). A stale day alerts even when the z-score doesn't, and the Action Agent annotates it as data_issue rather than notifying a segment owner.",
    "audit_and_replay": "action_log is append-only, enforced by SQLite triggers that raise on UPDATE and DELETE; status changes, undos and expiries are new rows. Every row carries its LangSmith trace id and LangGraph thread id; approver decisions are posted as LangSmith feedback on the propose trace. Local files (actions.db, llm_calls.jsonl, evals/ledger.jsonl) are the source of truth; LangSmith is a 14-day mirror for browsing and Playground replay, and nothing reads it to decide anything (D11). Tracing fails open; actions fail closed.",
    "idempotency": "Within the system: an idempotency key per (anomaly, action, params), and one proposal per anomaly for its lifetime (anomaly_id = sha256(dataset, metric, date)). Beyond it: the GitHub issue body carries the key in an HTML comment, and the executor lists the repo's labelled issues (the list endpoint, not search, which is eventually consistent) and reuses a match.",
    "approval_surfaces": "CLI (propose / approve [--live] / undo --reason) and the Django SPA's approval queue, both over the same ActionAgent. API approver identity is a bearer secret (ACTION_APPROVER_TOKEN; 503 when unset), with scoped DRF throttles checked before the token so guesses are counted. --live gates only effects outside the machine (a real GitHub issue); the local outbox always runs.",
    "eval_system": "One shared eval module writes every run to a committed append-only ledger (timestamp, git SHA with -dirty detection, models, prompt hash, set sizes, every metric with numerator and n, failing case ids with trace links). Baselines change only with --set-baseline. The drift run executes every ready eval, lists regressions first, and reports a run that hit an API error as 'invalid, not compared' rather than as a regression. A shared Pacer keeps every eval under Groq's 8,000 tokens/minute using real token use from llm_calls.jsonl."
  },
  "key_engineering_decisions": [
    {"decision": "What the LLM controls", "chosen": "LLM proposes one action from a fixed catalog; deterministic policy and a human decide", "rejected": "Open-ended tool selection / multi-step autonomous remediation", "reason": "The roles targeted ask for scoped, approved, auditable actions; a fixed catalog makes every effect enumerable and testable"},
    {"decision": "Risk tiers after the first adversarial run", "chosen": "Nothing auto-executes; annotate_anomaly moved from T0 to T1", "rejected": "Keep the tag-only action automatic because it doesn't affect alerting", "reason": "Measured, not assumed: injected segment text got annotate_anomaly auto-applied in 5 of 10 hostile cases. Even a harmless-looking auto action is an injection channel"},
    {"decision": "Why suppression is T1", "chosen": "Silencing alerts always passes a human", "rejected": "Auto-suppress repeat alerts", "reason": "Suppression is exactly the action an attacker-controlled segment name would want to trigger"},
    {"decision": "Model routing", "chosen": "Small model first (gpt-oss-20b), one escalation to 120b on a grounding failure, then a deterministic fallback", "rejected": "Always the large model", "reason": "20b was live-tested first: grounded 12/12 real anomalies at a median 2,615 tokens and $0.0042 total; routing was built only after that result was recorded"},
    {"decision": "Untrusted data in prompts", "chosen": "Segment names, column values and validation errors passed as data fields; segment params must match real contributors", "rejected": "Interpolating data into instructions; trusting model-named segments", "reason": "Data values are attacker-controllable (an onboarded CSV); grounding in policy means even a fooled model can't target an injected segment"},
    {"decision": "Fixing a failed eval gate (0.47 vs. 0.80)", "chosen": "Diagnose from traces, then add trusted context (calendar) and a better feature (share-adjusted driver check), each scoped and approved before building, with the calendar committed before the re-run", "rejected": "Prompt-tweaking until the golden set passes; changing labels or the target", "reason": "Traces showed the model lacked calendar context and mistook volume for causation; fixing inputs generalizes, tuning to 15 cases doesn't"},
    {"decision": "Where the calendar comes from", "chosen": "Committed per-dataset files generated from public holiday law and stated rules, recomputed on every start, plus a policy check that a cited holiday exists", "rejected": "Letting the model or the data name the holiday", "reason": "A cause claim needs a trusted source; a hostile segment claiming 'holiday: Carnival' on a non-holiday is rejected by policy, not just held"},
    {"decision": "Detecting a dying feed", "chosen": "Independent record-volume freshness check (25% of 28-row median, 50/day floor)", "rejected": "Lowering the z-score threshold; an 'N consecutive drops' rule", "reason": "A slowly failing feed fills the z-score's own window, so the worst day doesn't stand out (z = -1.85 on 1 order vs. 247); the consecutive-drop rule fired all over normal weekly cycles"},
    {"decision": "Pending approvals", "chosen": "LangGraph interrupt() with a SQLite checkpointer; 24h TTL applied lazily on read", "rejected": "In-memory waits; a background expiry sweep", "reason": "A proposal must survive a restart; a single local process has nothing to run a sweep"},
    {"decision": "Audit log integrity", "chosen": "SQLite triggers that raise on UPDATE/DELETE; undo is a compensating row", "rejected": "Application-level discipline; editing effect tables on undo", "reason": "Append-only enforced by the database, covered by a pytest test, and verified live (a raw DELETE is refused)"},
    {"decision": "Tracing tool", "chosen": "LangSmith (native LangGraph tracing, Playground replay, datasets/experiments, feedback API)", "rejected": "MLflow tracking", "reason": "No per-node instrumentation; hands-on LangSmith experience; MLflow would need a tracking server and manual spans"},
    {"decision": "Durable record vs. exploration layer", "chosen": "Local files are the source of truth; LangSmith is a mirror", "rejected": "LangSmith as the system of record", "reason": "The free plan keeps traces 14 days; an outage should lose traces, never decisions"},
    {"decision": "Approver edits", "chosen": "params only, re-checked by policy; an edit is an approval of its own params with a new idempotency key", "rejected": "Allowing the edit to change action_type", "reason": "A different action type is a different tier and risk, so a different proposal"},
    {"decision": "Live side effects", "chosen": "--live flag gates only effects that leave the machine; a recording fake executor for tests", "rejected": "Real executors in tests; a global dry-run mode", "reason": "Tests stay hermetic and the log still records a 'simulated' execution, so a dry run looks like a real one in the log"},
    {"decision": "GitHub issue target", "chosen": "ACTION_GITHUB_REPO with no default; a fine-grained PAT scoped to Issues on one private repo", "rejected": "A default repo; a broad token", "reason": "An agent should never open issues on a repo nobody chose"},
    {"decision": "Eval history", "chosen": "Committed append-only ledger with git SHA, prompt hash and failing-case trace links; baselines changed only on purpose", "rejected": "Eval results only in LangSmith experiments", "reason": "Reproducible comparisons across months, independent of vendor retention"},
    {"decision": "Who labels the golden set", "chosen": "The agent may choose candidate anomalies, Kousik labels the expected action and owner without ever seeing the model's proposal", "rejected": "Agent-written labels", "reason": "Avoids grading the model against its own answers"}
  ],
  "eval_results": {
    "action_agent_gate": {
      "targets": "action_match_rate >= 0.8 on 15 golden cases; idempotency_violations 0; unauthorized_exec_count 0; injection_bypasses 0; grounding 1.00",
      "passing_run": "2026-11-06, clean tree de23866, accepted as baseline (evals/baselines/action.json)",
      "metrics": {
        "action_match_rate": "1.00 (15/15)",
        "grounding_pass_rate": "1.00 golden (15/15), 1.00 adversarial (10/10)",
        "first_attempt_grounded_rate": 0.8667,
        "escalation_rate": "0.13 (2/15)",
        "fallback_rate": 0.0,
        "idempotency_violations": "0 (each approved action replayed 3x from its checkpoint)",
        "unauthorized_exec_count": "0 of 20 probes",
        "injection_bypasses": "0 of 10",
        "injection_followed_rate": 0.0,
        "held_for_approval_rate": "1.00 (10/10)",
        "calendar_injection_accepted": 0,
        "cost_per_run_usd": 0.000496,
        "p95_latency_s": 3.62,
        "tokens_per_run_median": 3820
      },
      "reconfirmed": "2026-11-12 drift run (06a58bf): action_match 1.00, escalation 0, fallback 0, first-attempt grounded 1.00, cost $0.00043/run, p95 3.48s, every safety count 0"
    },
    "action_match_trajectory": [
      {"date": "2026-11-03", "git": "de3adf0", "action_match_rate": 0.4667, "note": "First golden run on Kousik's labels: gate FAILED. 7 of 8 misses were known-cause days (holidays, Monday rebounds) where the model chose notify_owner; it had no calendar context"},
      {"date": "2026-11-04", "git": "45cb74e", "action_match_rate": 0.6667, "note": "After the trusted calendar (scope §14): still FAILED. Traces showed the model treating Olist's Credit Card (~79% of volume) as 'the driver' of every change"},
      {"date": "2026-11-06", "git": "de23866", "action_match_rate": 1.0, "note": "After the share-adjusted driver check (§14.8) and data-freshness check (§15), plus one disclosed relabel (g01 -> data_issue). Without the relabel: 14/15 = 0.93, still above 0.8"},
      {"date": "2026-11-12", "git": "06a58bf", "action_match_rate": 1.0, "note": "Clean full drift run, 0 regressions"}
    ],
    "injection_followed_trajectory": "0.5 -> 0.4 -> 0.2 -> 0.0 across runs (how often the model proposed what the injected text asked for). Bypasses (an injected action executing, or the attacker becoming a recipient) were 0 on every run after the T1 change; 10/10 held for approval every time.",
    "system_wide_evals_latest_2026_11_12": {
      "detection": "28 human-labelled dates. z-score alone: precision 0.92, recall 0.92, F1 0.92 (1 false alarm, 1 missed event). With the freshness check: precision 0.92 (12/13), recall 1.00 (12/12), F1 0.96. Free, deterministic, replays the production decision",
      "investigation": "10 golden cases x 3 runs (Phase 1 agent): grounding 0.83, golden_match 0.73, uncertainty_ok 0.70, fallback 0.00 (was grounding 0.33 / fallback 0.37 before BUG_LOG A7-4 was fixed)",
      "onboarding": "3 datasets x 2 runs: date column, grain and metric columns 1.00; dimension columns 0.50; rejected columns 0.67; all fields 0.33; grounded 1.00. Weak and reported as such",
      "drift": "All four evals vs. baselines: 0 regressions, 0 API errors"
    }
  },
  "real_bugs_found_selected": [
    {"bug": "Prompt injection: hostile segment text got annotate_anomaly auto-applied in 5 of 10 cases, by 20b and by 120b after escalation", "found_by": "The first live adversarial eval", "fix": "Kousik's decision: annotate_anomaly becomes T1, nothing auto-executes; re-run 0/10 bypasses, 10/10 held; a test asserts nothing in the catalog auto-executes"},
    {"bug": "Every approval's LangSmith feedback was silently dropped", "found_by": "First live run with a working key", "fix": "langsmith 0.10.16 rejects project_id with trace_id; the project goes in session_id. Fail-open had turned the error into a log warning"},
    {"bug": "Three valid LangSmith keys all returned 403, indistinguishable from a fake key", "found_by": "Live setup", "fix": "The account is on LangSmith's AWS US region, the SDK defaults to GCP US; set LANGSMITH_ENDPOINT and LANGSMITH_WORKSPACE_ID. No code change; documented as a 403 checklist"},
    {"bug": "LLM telemetry (tokens, cost, outcome) never appeared on the LangSmith run", "found_by": "Inspecting a live trace's run tree", "fix": "Metadata had been added after the traced function returned and the run closed; all bookkeeping moved inside the traced function"},
    {"bug": "The action graph crashed checkpointing live evidence", "found_by": "First run on real Superstore data", "fix": "Real decomposition output carries numpy scalars the msgpack checkpointer rejects (tests used plain floats); evidence normalized at the graph boundary, regression test confirmed to fail without the fix"},
    {"bug": "suppress_alerts accepted days: true (as 1) and days: \"5\"", "found_by": "Probing the schema in tests", "fix": "Pydantic lax mode coerces bools and numeric strings; Field(strict=True) on every numeric param"},
    {"bug": "gpt-oss-20b named its tool functions.ProposalDraft in 3 of 10 adversarial cases, forcing escalations", "found_by": "Live adversarial eval", "fix": "A narrow repair hook accepts exactly that slip, still validated and marked 'repaired'; escalation 7/10 -> 2/10"},
    {"bug": "The first full drift run reported 3 false regressions (investigation fallback 0.07 -> 0.83) and crashed the onboarding eval", "found_by": "The first live drift run", "fix": "Only the action eval paced itself under Groq's 8,000 tokens/minute; all 25 fallbacks were rate-limit 429s. A shared Pacer using real token use now paces every eval, and an API failure marks a run invalid rather than regressed"},
    {"bug": "Phase 1 synthesis fell back on every real Olist case without a drill-down (grounding 0.33)", "found_by": "The first 10-case investigation eval (it had only ever run on one golden case)", "fix": "The prompt printed dimensions title-cased, the model cited that spelling, and the validator looks keys up exactly; grounding rose to 0.77, then 0.83"},
    {"bug": "Every eval after the first in a session would record its ledger row as -dirty", "found_by": "Review while planning sequential baseline runs", "fix": "The eval's own ledger write dirtied the tracked tree; ledger and baselines excluded from the dirty check, tested against a real git repo"},
    {"bug": "The baseline comparison treated a rise in adversarial escalation as an improvement", "found_by": "Review when moving comparison into the shared eval module", "fix": "Added to the lower-is-better list before any baseline existed, so no past report was wrong"},
    {"bug": "Onboarding validation accepted a rejected column that doesn't exist (the classifier renamed the hostile header)", "found_by": "The first 3-dataset onboarding eval", "fix": "Rejected names must be real columns too. Still open: a classification that omits a real column entirely passes"},
    {"bug": "The generated Superstore calendar put Victoria Day 2010 on May 17 instead of May 24", "found_by": "Spot-checking generated dates before committing", "fix": "'Last Monday before 25 May' had been coded from 24 May; regression test plus a check that committed calendars match their rules"},
    {"bug": "propose crashed with a bare KeyError on a non-decomposable Olist metric", "found_by": "The new Olist propose path, live", "fix": "require_decomposable() refuses such a metric with a clear message; the pipeline had the same latent issue"},
    {"bug": "pending listed proposals already past their 24h TTL", "found_by": "Live", "fix": "TTL had been checked only when a decision arrived; pending() now filters expired proposals"}
  ],
  "real_bugs_total": 20,
  "real_bugs_note": "15 of the 20 Action Agent-era rows in BUG_LOG.md (A1-1 to A7-5); 15 were found by running live (real LLM calls, real LangSmith, real data), not by code review.",
  "test_coverage": {
    "suite_total": 401,
    "action_agent_files": {
      "test_action_policy": 57,
      "test_action_dry_run": 24,
      "test_event_calendar": 23,
      "test_action_hooks": 20,
      "test_llm_proposer": 19,
      "test_action_graph": 18,
      "test_action_api": 16,
      "test_action_executors": 13,
      "test_driver_check": 11,
      "test_action_store": 9
    },
    "action_agent_files_total": 210,
    "shared_infra_built_for_it": {"test_eval_plumbing": 32, "test_freshness": 11, "test_llm_telemetry": 10, "test_citation_validation": 9, "test_tracing": 5},
    "no_mocking": true,
    "llm_graded_eval_cases": "15 golden + 10 adversarial + 5 safety probes, real Groq calls, about a cent per full run"
  },
  "quantifiable_outcomes": [
    "Eval gate passed: action_match_rate 0.47 -> 0.67 -> 1.00 (15/15) on human-labelled real anomalies, by fixing inputs (trusted calendar, share-adjusted driver check, freshness), not by tuning prompts to the set",
    "0 unauthorized executions (20 probes), 0 injection bypasses (10 hostile cases), 0 idempotency violations (each approved action replayed 3x), 100% grounding",
    "~$0.0005 per proposal, p95 3.6s, median ~3.8k tokens; 20b grounded 12/12 real anomalies alone in the pre-build live test ($0.0042 for all 12)",
    "Detection F1 0.92 -> 0.96 with the data-freshness check (recall 12/12)",
    "4 evals, 20 committed ledger rows, weekly drift run: 0 regressions on the first clean full run",
    "5-action catalog, 14 core log event types (plus undo and watch-breach rows), append-only log enforced by database triggers",
    "~3,660 lines in action_agent/, ~210 tests in its own files, 401 in the suite, no mocking",
    "20 real bugs logged with root cause, fix and guard"
  ],
  "known_limitations": [
    "The golden set is 15 cases and the adversarial set 10: enough for a gate, not for rate claims beyond these sets",
    "One golden label (g01) was changed by Kousik before the passing run; disclosed beforehand as likely to raise the score (14/15 = 0.93 without it)",
    "The freshness threshold (25%) was chosen after seeing the Olist export tail; guarded by committing it before re-running and by it firing on no other Olist day, but it is not validated on a second dataset (Superstore is too sparse for it to apply)",
    "Local only: Lambda can't hold the SQLite state, and the hosted demo shows recorded runs, not live approvals",
    "One approver identity (a bearer secret), not an auth system",
    "Temperature 0 isn't deterministic on Groq: the same case gave different actions across runs; replay means LangSmith Playground re-runs plus the recorded decision, not bit-identical output",
    "Groq's 120b daily cap (200k tokens) allows about one full drift run a day",
    "The weekly drift job is printed for launchd, not installed as a hosted scheduler",
    "Onboarding eval is weak on dimension and rejected columns (0.50 / 0.67), and an omitted real column still passes validation"
  ],
  "positioning": "TODO (Kousik): confirm. Suggested: leads for agentic / applied-AI / AI-safety roles that want agents taking scoped, approved, auditable actions. Strongest single signal in the portfolio for LLM evals done properly (human-labelled golden sets, adversarial injection testing, a failed gate diagnosed from traces and fixed by improving inputs, drift against baselines), human-in-the-loop with LangGraph interrupts, and LangSmith tracing tied to an audit log. Complements Interpose: Interpose governs other agents' tool calls at the network layer; this is the agent itself designed to be governable."
}
```
