from copy import deepcopy

import pytest

from chatsnack import CallUsage, ResponseUsage, UsageCounts
from chatsnack.runtime import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
)
from chatsnack.runtime.usage import _CallUsageLedger


def _completion(usage, *, response_id="resp_1", model="gpt-test"):
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(content="done"),
        model=model,
        usage=usage,
        metadata={
            "response_id": response_id,
            "previous_response_id": "resp_previous",
        },
    )


@pytest.mark.parametrize(
    ("provider_shape", "usage"),
    [
        (
            "openai_responses_http",
            {
                "input_tokens": 11,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens": 7,
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "openai_responses_websocket",
            {
                "input_tokens": 11,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens": 7,
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "openrouter_responses_http",
            {
                "input_tokens": 11,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens": 7,
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "azure_responses_http",
            {
                "input_tokens": 11,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens": 7,
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "azure_responses_websocket",
            {
                "input_tokens": 11,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens": 7,
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "openai_chat_completions",
            {
                "prompt_tokens": 11,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens": 7,
                "completion_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "openrouter_chat_completions",
            {
                "prompt_tokens": 11,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens": 7,
                "completion_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
        (
            "azure_chat_completions",
            {
                "prompt_tokens": 11,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens": 7,
                "completion_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 18,
            },
        ),
    ],
)
def test_normalizes_usage_by_response_shape(provider_shape, usage):
    ledger = _CallUsageLedger()

    ledger.record(_completion(usage, response_id=f"resp_{provider_shape}"))

    response = ledger.snapshot().responses[0]
    assert response.input_tokens == 11
    assert response.cached_input_tokens == 4
    assert response.output_tokens == 7
    assert response.reasoning_tokens == 3
    assert response.total_tokens == 18
    assert response.model == "gpt-test"
    assert response.provider_usage == usage


def test_missing_zero_and_empty_usage_payloads_remain_distinct():
    ledger = _CallUsageLedger()
    ledger.record(_completion(None, response_id="resp_missing"))
    ledger.record(
        _completion(
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            response_id="resp_zero",
        )
    )
    ledger.record(_completion({}, response_id="resp_empty"))

    call = ledger.snapshot()

    assert call.response_count == 3
    assert call.usage_response_count == 2
    assert call.is_complete is False
    assert call.missing_usage_sequences == (1,)
    assert call.responses[0].usage_reported is False
    assert call.responses[0].provider_usage is None
    assert call.responses[1].usage_reported is True
    assert call.responses[1].input_tokens == 0
    assert call.responses[1].output_tokens == 0
    assert call.responses[1].total_tokens == 0
    assert call.responses[2].usage_reported is True
    assert call.responses[2].provider_usage == {}
    assert call.total == UsageCounts(
        input_tokens=0,
        cached_input_tokens=None,
        output_tokens=0,
        reasoning_tokens=None,
        total_tokens=0,
    )


def test_malformed_preferred_alias_falls_back_to_valid_compatible_alias():
    ledger = _CallUsageLedger()
    ledger.record(
        _completion(
            {
                "input_tokens": "unknown",
                "prompt_tokens": 11,
                "input_tokens_details": {"cached_tokens": False},
                "prompt_tokens_details": {"cached_tokens": 4},
                "output_tokens": None,
                "completion_tokens": 7,
                "output_tokens_details": {"reasoning_tokens": "unknown"},
                "completion_tokens_details": {"reasoning_tokens": 3},
            }
        )
    )

    response = ledger.snapshot().responses[0]
    assert response.input_tokens == 11
    assert response.cached_input_tokens == 4
    assert response.output_tokens == 7
    assert response.reasoning_tokens == 3


def test_ledger_sequences_responses_and_detaches_raw_provider_usage():
    usage = {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
        "vendor": {"credits": ["one"]},
    }
    original = deepcopy(usage)
    ledger = _CallUsageLedger()

    ledger.record(_completion(usage, response_id="resp_one"))
    ledger.record(_completion({"total_tokens": 7}, response_id="resp_two"))
    usage["vendor"]["credits"].append("mutated")

    call = ledger.snapshot()
    assert isinstance(call, CallUsage)
    assert isinstance(call.responses[0], ResponseUsage)
    assert call.responses[0].sequence == 1
    assert call.responses[1].sequence == 2
    assert call.responses[0].provider_usage == original
    assert call.total.input_tokens == 2
    assert call.total.output_tokens == 3
    assert call.total.total_tokens == 12


def test_empty_call_snapshot_is_incomplete_and_immutable():
    call = _CallUsageLedger().snapshot()

    assert call.responses == ()
    assert call.response_count == 0
    assert call.usage_response_count == 0
    assert call.is_complete is False
    assert call.missing_usage_sequences == ()
    assert call.total == UsageCounts()

    with pytest.raises(AttributeError):
        call.responses = ()
