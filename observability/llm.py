"""
The shared LLM telemetry wrapper (docs/action-agent-scope.md N1, §13.3).

Every structured-output LLM call in all three agents goes through invoke_structured():
- Phase 1 `synthesize` (investigation/nodes.py)
- Phase 2 `classify` (onboarding/classification.py)
- Action Agent `propose_action` (action_agent/llm_proposer.py)

Per call it records stage, model, attempt, input/output tokens (from the response's usage
metadata), cost (from the dated price table in config/settings.py), latency, outcome and the
LangSmith trace id. It always appends one JSON line to settings.LLM_CALLS_LOG (the durable
record, D11), and adds the same fields as metadata on a LangSmith run when tracing is on.
Both writes are fail-open: telemetry never changes what the call returns.

The D2 token budget is charged here, from the same usage numbers that are logged, so the
budget and the telemetry can't disagree.

Callers build their model with `.with_structured_output(Schema, method='function_calling',
include_raw=True)`, so the raw message (and its token usage) survives parsing. A parse failure
or an API error is recorded and then re-raised, which is exactly what the callers saw before
they used this wrapper.
"""

import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings  # noqa: E402
from config.logging_config import setup_logger  # noqa: E402

logger = setup_logger(__name__)

# Outcomes of a single call. Retry, escalation and fallback are run-level and are told apart by
# `attempt` plus the caller's own result (e.g. the Action Agent proposer name).
GROUNDED = 'grounded'          # parsed, and validate() found no errors (or no validate given)
INVALID = 'invalid'            # parsed, but validate() returned errors
PARSE_ERROR = 'parse_error'    # the model's output didn't parse into the schema
ERROR = 'error'                # the API call raised
SKIPPED_BUDGET = 'skipped_budget'   # not sent: the token budget couldn't cover it


class TokenBudget:
    """Tokens left for one run (D2). Charged by invoke_structured from real usage."""

    def __init__(self, limit: int):
        self.limit = int(limit)
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def can_afford(self, estimate: int) -> bool:
        return estimate <= self.remaining

    def charge(self, tokens: int) -> None:
        self.used += max(0, int(tokens or 0))


@dataclass
class LLMCall:
    stage: str
    model: str
    attempt: int
    outcome: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[int] = None
    prompt_hash: Optional[str] = None
    trace_id: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    budget_remaining: Optional[int] = None
    repaired: bool = False      # the output only parsed via the caller's repair() hook
    metadata: Dict[str, Any] = field(default_factory=dict)
    ts: str = ''
    prices_as_of: str = settings.LLM_PRICES_AS_OF

    def to_dict(self) -> Dict:
        return asdict(self)


def cost_usd(model: str, input_tokens: Optional[int], output_tokens: Optional[int],
             prices: Dict = None) -> Optional[float]:
    prices = settings.LLM_PRICES_USD_PER_MTOK if prices is None else prices
    if model not in prices or input_tokens is None or output_tokens is None:
        return None
    price_in, price_out = prices[model]
    return round((input_tokens * price_in + output_tokens * price_out) / 1_000_000, 8)


def _content(message) -> str:
    content = getattr(message, 'content', message)
    return content if isinstance(content, str) else json.dumps(content, default=str, sort_keys=True)


def prompt_hash(messages: Sequence) -> str:
    joined = '\n'.join(f"{getattr(m, 'type', type(m).__name__)}:{_content(m)}" for m in messages)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()[:12]


def estimate_tokens(messages: Sequence, reserve_output: int = 0) -> int:
    """Rough pre-call size: ~4 characters per token for the prompt, plus the output the caller
    reserves. Used only to decide whether a call fits the budget; the charge is the real usage."""
    return sum(len(_content(m)) for m in messages) // 4 + int(reserve_output)


def _usage(raw) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    usage = getattr(raw, 'usage_metadata', None) or {}
    i, o = usage.get('input_tokens'), usage.get('output_tokens')
    total = usage.get('total_tokens', (i or 0) + (o or 0) if (i is not None or o is not None) else None)
    return i, o, total


def _write_line(record: LLMCall, log_path: Path) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record.to_dict(), default=str) + '\n')
    except OSError as e:
        logger.warning(f'LLM telemetry line not written ({record.stage}): {e}')


def _current_run():
    try:
        from langsmith.run_helpers import get_current_run_tree
        return get_current_run_tree()
    except Exception:
        return None


def _annotate_run(run, record: LLMCall) -> None:
    if run is None:
        return
    try:
        run.add_metadata({f'llm_{k}': v for k, v in record.to_dict().items()
                          if k not in ('metadata', 'errors')})
    except Exception as e:
        logger.debug(f'LangSmith metadata not added ({record.stage}): {e}')


try:
    from langsmith import traceable as _traceable
except Exception:   # pragma: no cover - langsmith is a pinned dependency
    _traceable = None


def invoke_structured(llm, messages: Sequence, *, stage: str, model: str, attempt: int = 1,
                      validate: Optional[Callable[[Any], List[str]]] = None,
                      budget: Optional[TokenBudget] = None, reserve_output: int = 0,
                      metadata: Optional[Dict] = None, log_path: Optional[Path] = None,
                      repair: Optional[Callable[[Any], Any]] = None,
                      now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
                      ) -> Tuple[Any, LLMCall]:
    """Run one structured-output call and record it. Returns (parsed or None, LLMCall).

    - budget: if given and estimate_tokens(messages, reserve_output) doesn't fit, the call is
      not sent; returns (None, record with outcome skipped_budget).
    - validate(parsed) -> list of error strings; sets the outcome to grounded or invalid and
      is stored on the record. The parsed object is returned either way; the caller decides.
    - repair(raw_message) -> parsed or None: tried only when the structured output didn't parse,
      for a known, harmless format slip (e.g. gpt-oss-20b naming its tool `functions.X`). A
      repaired call is still validated like any other and is marked `repaired=True`.
    - Raises whatever the call raised (API error, or the parse error), after recording it.
    """
    log_path = Path(log_path or settings.LLM_CALLS_LOG)
    record = LLMCall(stage=stage, model=model, attempt=attempt, outcome=ERROR,
                     prompt_hash=prompt_hash(messages), metadata=dict(metadata or {}),
                     ts=now_fn().isoformat())

    if budget is not None and not budget.can_afford(estimate_tokens(messages, reserve_output)):
        record.outcome = SKIPPED_BUDGET
        record.budget_remaining = budget.remaining
        _write_line(record, log_path)
        return None, record

    def traced(llm, messages):
        # Runs inside the LangSmith run (when tracing is on), so the metadata is added while the
        # run is still open. A raise after that marks the run as errored, as it should.
        run = _current_run()
        start = time.perf_counter()
        raised: Optional[BaseException] = None
        parsed, result = None, None
        try:
            result = llm.invoke(messages)
        except Exception as e:
            raised = e
        record.latency_ms = int((time.perf_counter() - start) * 1000)

        if isinstance(result, dict) and 'raw' in result:
            record.input_tokens, record.output_tokens, record.total_tokens = _usage(result.get('raw'))
            parsed = result.get('parsed')
            if (result.get('parsing_error') is not None or parsed is None) and repair is not None:
                try:
                    parsed = repair(result.get('raw'))
                except Exception:
                    parsed = None
                record.repaired = parsed is not None
                if record.repaired:
                    result = {**result, 'parsing_error': None}
            if result.get('parsing_error') is not None or parsed is None:
                raised = result.get('parsing_error') or ValueError('structured output did not parse')
                record.outcome = PARSE_ERROR
        elif result is not None:
            parsed = result   # a model built without include_raw: no usage to record

        if raised is not None:
            if record.outcome != PARSE_ERROR:
                record.outcome = ERROR
            record.errors = [f'{type(raised).__name__}: {str(raised)[:500]}']
        else:
            errors = list(validate(parsed)) if validate else []
            record.errors = errors
            record.outcome = INVALID if errors else GROUNDED

        record.cost_usd = cost_usd(model, record.input_tokens, record.output_tokens)
        if budget is not None:
            budget.charge(record.total_tokens)
            record.budget_remaining = budget.remaining
        if run is not None:
            record.trace_id = str(getattr(run, 'trace_id', '') or '') or None
        _annotate_run(run, record)
        if raised is not None:
            try:
                raised.llm_call = record   # so a caller that catches it still has the real record
            except Exception:
                pass
            raise raised
        return parsed

    call = traced
    if _traceable is not None and settings.LANGSMITH_TRACING:
        call = _traceable(name=f'llm.{stage}', run_type='chain',
                          metadata={'stage': stage, 'model': model, 'attempt': attempt})(traced)
    try:
        parsed = call(llm, messages)
    finally:
        _write_line(record, log_path)   # exactly one line per call, success or not
    return parsed, record
