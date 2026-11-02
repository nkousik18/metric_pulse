"""
Tests for observability/llm.py, the shared LLM telemetry wrapper (docs/action-agent-scope.md N1,
§13.3). The "model" is a small injected stand-in with a real .invoke() that returns what a
LangChain structured-output runnable built with include_raw=True returns. No mocks, no network,
tracing off (CI never sets LANGSMITH_*).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from observability import llm as telemetry  # noqa: E402

MESSAGES = [SystemMessage(content='rules'), HumanMessage(content='x' * 400)]
NOW = lambda: datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)   # noqa: E731


class Out(BaseModel):
    answer: str


class CannedModel:
    """Returns the given responses in order; records every call it receives."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def invoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def raw(parsed=None, tokens=(1000, 200), parsing_error=None):
    message = AIMessage(content='', usage_metadata={'input_tokens': tokens[0], 'output_tokens': tokens[1],
                                                    'total_tokens': sum(tokens)})
    return {'raw': message, 'parsed': parsed, 'parsing_error': parsing_error}


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _call(model, tmp_path, **kwargs):
    return telemetry.invoke_structured(model, MESSAGES, stage='test_stage', model='openai/gpt-oss-20b',
                                       log_path=tmp_path / 'llm.jsonl', now_fn=NOW, **kwargs)


def test_grounded_call_records_tokens_cost_latency_and_prompt_hash(tmp_path):
    parsed, record = _call(CannedModel(raw(Out(answer='ok'))), tmp_path, metadata={'anomaly_id': 'a1'})
    assert parsed == Out(answer='ok')
    assert (record.outcome, record.input_tokens, record.output_tokens, record.total_tokens) == (
        'grounded', 1000, 200, 1200)
    # 1000 * 0.075 / 1M + 200 * 0.30 / 1M (the dated price table in config/settings.py)
    assert record.cost_usd == pytest.approx(0.000135)
    assert record.latency_ms is not None and record.trace_id is None   # tracing off in tests
    [line] = _lines(tmp_path / 'llm.jsonl')
    assert line['stage'] == 'test_stage' and line['metadata'] == {'anomaly_id': 'a1'}
    assert line['prompt_hash'] == telemetry.prompt_hash(MESSAGES) and line['prices_as_of'] == '2026-11-02'


def test_validation_errors_make_the_outcome_invalid_but_still_return_the_output(tmp_path):
    parsed, record = _call(CannedModel(raw(Out(answer='bad'))), tmp_path, validate=lambda o: ['wrong segment'])
    assert parsed.answer == 'bad'
    assert record.outcome == 'invalid' and record.errors == ['wrong segment']


def test_parse_error_is_recorded_then_reraised_with_its_record(tmp_path):
    with pytest.raises(ValueError, match='bad json') as info:
        _call(CannedModel(raw(parsing_error=ValueError('bad json'))), tmp_path)
    assert info.value.llm_call.outcome == 'parse_error' and info.value.llm_call.total_tokens == 1200
    assert _lines(tmp_path / 'llm.jsonl')[0]['outcome'] == 'parse_error'


def test_api_error_is_recorded_then_reraised(tmp_path):
    with pytest.raises(ConnectionError):
        _call(CannedModel(ConnectionError('groq down')), tmp_path)
    [line] = _lines(tmp_path / 'llm.jsonl')
    assert line['outcome'] == 'error' and 'groq down' in line['errors'][0] and line['total_tokens'] is None


def test_budget_is_charged_from_the_logged_usage(tmp_path):
    budget = telemetry.TokenBudget(10_000)
    _, record = _call(CannedModel(raw(Out(answer='ok'))), tmp_path, budget=budget)
    assert budget.used == record.total_tokens == 1200
    assert record.budget_remaining == 8_800


def test_a_call_that_might_not_fit_the_budget_is_never_sent(tmp_path):
    model = CannedModel(raw(Out(answer='ok')))
    budget = telemetry.TokenBudget(500)
    parsed, record = _call(model, tmp_path, budget=budget, reserve_output=400)
    assert parsed is None and record.outcome == 'skipped_budget'
    assert model.calls == [] and budget.used == 0
    assert _lines(tmp_path / 'llm.jsonl')[0]['outcome'] == 'skipped_budget'


def test_estimate_counts_prompt_characters_plus_the_reserved_output():
    assert telemetry.estimate_tokens(MESSAGES, reserve_output=100) == (5 + 400) // 4 + 100


def test_unknown_model_has_no_cost_rather_than_a_guess():
    assert telemetry.cost_usd('some/other-model', 1000, 200) is None
    assert telemetry.cost_usd('openai/gpt-oss-120b', 1_000_000, 1_000_000) == pytest.approx(0.75)


def test_a_model_built_without_include_raw_still_works_with_no_usage(tmp_path):
    parsed, record = _call(CannedModel(Out(answer='plain')), tmp_path)
    assert parsed.answer == 'plain' and record.outcome == 'grounded' and record.total_tokens is None


def test_an_unwritable_log_never_changes_the_result(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('not a directory')
    parsed, record = telemetry.invoke_structured(
        CannedModel(raw(Out(answer='ok'))), MESSAGES, stage='s', model='m', log_path=blocker / 'llm.jsonl')
    assert parsed.answer == 'ok' and record.outcome == 'grounded'
