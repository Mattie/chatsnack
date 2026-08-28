import asyncio

import pytest

from chatsnack import (
    CallUsage,
    Chat,
    ChatParams,
    ResponseUsage,
    UsageCounts,
    utensil,
)
from chatsnack.runtime import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
    NormalizedToolFunction,
)


class _SequenceRuntime:
    """Small adapter double that returns normalized provider responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create_completion_a(self, messages, **kwargs):
        self.requests.append({"messages": messages, "kwargs": kwargs})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _completion(
    content,
    usage,
    *,
    response_id,
    previous_response_id=None,
    tool_call=None,
    model="gpt-test",
):
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(
            content=content,
            tool_calls=[tool_call] if tool_call is not None else [],
        ),
        model=model,
        usage=usage,
        metadata={
            "response_id": response_id,
            "previous_response_id": previous_response_id,
            "assistant_phase": "incomplete" if tool_call else "completed",
            "provider_extras": {
                "status": "in_progress" if tool_call else "completed"
            },
        },
    )


def _tool_call(name):
    return NormalizedToolCall(
        id="call_snack",
        function=NormalizedToolFunction(
            name=name,
            arguments='{"name":"popcorn"}',
        ),
    )


@utensil
def aggregate_usage_snack_lookup(name: str) -> str:
    """Look up a snack for the aggregate-usage acceptance story."""
    return f"{name} is crunchy"


@pytest.mark.asyncio
async def test_chat_a_aggregates_every_auto_feed_provider_response_once():
    first_usage = {
        "input_tokens": 10,
        "input_tokens_details": {"cached_tokens": 3},
        "output_tokens": 2,
        "output_tokens_details": {"reasoning_tokens": 1},
        "total_tokens": 12,
    }
    second_usage = {
        "prompt_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens": 7,
        "completion_tokens_details": {"reasoning_tokens": 2},
        "total_tokens": 12,
    }
    runtime = _SequenceRuntime(
        [
            _completion(
                None,
                first_usage,
                response_id="resp_tool",
                tool_call=_tool_call("aggregate_usage_snack_lookup"),
            ),
            _completion(
                "Popcorn is crunchy.",
                second_usage,
                response_id="resp_final",
                previous_response_id="resp_tool",
            ),
        ]
    )
    source = Chat(
        "Use the snack tool.",
        runtime=runtime,
        utensils=[aggregate_usage_snack_lookup],
        auto_feed=True,
    )

    completed = await source.chat_a("Tell me about popcorn.")

    assert isinstance(completed, Chat)
    assert completed.response == "Popcorn is crunchy."
    assert len(runtime.requests) == 2
    call = completed.last_call_usage
    assert source.last_call_usage is call
    assert call.response_count == 2
    assert call.usage_response_count == 2
    assert call.is_complete is True
    assert [item.response_id for item in call.responses] == [
        "resp_tool",
        "resp_final",
    ]
    assert call.responses[1].previous_response_id == "resp_tool"
    assert call.total == UsageCounts(
        input_tokens=15,
        cached_input_tokens=3,
        output_tokens=9,
        reasoning_tokens=3,
        total_tokens=24,
    )
    assert call.responses[0].provider_usage == first_usage
    assert call.responses[1].provider_usage == second_usage
    assert completed._last_runtime_metadata["usage"] == second_usage


def test_chat_preserves_mixed_usage_coverage_and_reported_zero():
    runtime = _SequenceRuntime(
        [
            _completion(
                None,
                None,
                response_id="resp_missing",
                tool_call=_tool_call("aggregate_usage_snack_lookup"),
            ),
            _completion(
                "Done.",
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                response_id="resp_zero",
                previous_response_id="resp_missing",
            ),
        ]
    )
    source = Chat(
        "Use the snack tool.",
        runtime=runtime,
        utensils=[aggregate_usage_snack_lookup],
        auto_feed=True,
    )

    completed = source.chat("Tell me about popcorn.")

    call = completed.last_call_usage
    assert call.response_count == 2
    assert call.usage_response_count == 1
    assert call.is_complete is False
    assert call.missing_usage_sequences == (1,)
    assert call.responses[0].provider_usage is None
    assert call.responses[1].input_tokens == 0
    assert call.responses[1].output_tokens == 0
    assert call.responses[1].total_tokens == 0
    assert call.total == UsageCounts(
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
    )


@pytest.mark.asyncio
async def test_chat_a_failure_exposes_partial_usage_without_wrapping_exception():
    failure = RuntimeError("follow-up failed")
    runtime = _SequenceRuntime(
        [
            _completion(
                None,
                {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
                response_id="resp_tool",
                tool_call=_tool_call("aggregate_usage_snack_lookup"),
            ),
            failure,
        ]
    )
    source = Chat(
        "Use the snack tool.",
        runtime=runtime,
        utensils=[aggregate_usage_snack_lookup],
        auto_feed=True,
    )

    with pytest.raises(RuntimeError) as raised:
        await source.chat_a("Tell me about popcorn.")

    assert raised.value is failure
    assert len(runtime.requests) == 2
    partial = source.last_call_usage
    assert partial.response_count == 1
    assert partial.responses[0].response_id == "resp_tool"
    assert partial.total.total_tokens == 5
    assert failure.last_call_usage is partial


@pytest.mark.asyncio
async def test_next_call_replaces_source_usage_and_leaves_prior_result_intact():
    runtime = _SequenceRuntime(
        [
            _completion("First.", {"total_tokens": 5}, response_id="resp_first"),
            _completion("Second.", {"total_tokens": 8}, response_id="resp_second"),
        ]
    )
    source = Chat("Answer briefly.", runtime=runtime)
    first = await source.chat_a("First?")
    first_call = first.last_call_usage

    second = await source.chat_a("Second?")

    assert first.last_call_usage is first_call
    assert first.last_call_usage.total.total_tokens == 5
    assert source.last_call_usage is second.last_call_usage
    assert source.last_call_usage.response_count == 1
    assert source.last_call_usage.total.total_tokens == 8


@pytest.mark.asyncio
async def test_in_flight_call_preserves_most_recently_finished_source_usage():
    class _BlockingSecondRuntime:
        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.calls = 0

        async def create_completion_a(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return _completion(
                    "First.",
                    {"total_tokens": 5},
                    response_id="resp_first",
                )
            self.started.set()
            await self.release.wait()
            return _completion(
                "Second.",
                {"total_tokens": 8},
                response_id="resp_second",
            )

    runtime = _BlockingSecondRuntime()
    source = Chat("Answer briefly.", runtime=runtime)
    first = await source.chat_a("First?")
    first_call = first.last_call_usage

    pending = asyncio.create_task(source.chat_a("Second?"))
    await runtime.started.wait()

    assert source.last_call_usage is first_call

    runtime.release.set()
    second = await pending
    assert source.last_call_usage is second.last_call_usage
    assert source.last_call_usage.total.total_tokens == 8


def test_call_usage_is_transient_across_yaml_copy_reset_and_load(tmp_path):
    runtime = _SequenceRuntime(
        [
            _completion(
                "Saved answer.",
                {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                response_id="resp_saved",
            )
        ]
    )
    source = Chat(
        name="UsageTransient",
        params=ChatParams(
            runtime="chat_completions",
            responses={"export_state": True},
        ),
        runtime=runtime,
    )
    result = source.chat("Save this.")
    call = result.last_call_usage

    assert "last_call_usage" not in result.yaml
    assert "provider_usage" not in result.yaml
    with pytest.raises(AttributeError):
        result.last_call_usage = call
    assert result.copy().last_call_usage is None

    result.reset()
    assert result.last_call_usage is None

    result._last_call_usage = call
    path = tmp_path / "UsageTransient.yml"
    result.save(path)
    result.load(path)
    assert result.last_call_usage is None


@pytest.mark.asyncio
async def test_concurrent_calls_keep_independent_ledgers_and_source_tracks_last_finish():
    class _ConcurrentRuntime:
        async def create_completion_a(self, messages, **kwargs):
            prompt = messages[-1]["content"]
            if prompt == "slow":
                await asyncio.sleep(0.02)
                return _completion(
                    "Slow.",
                    {"total_tokens": 20},
                    response_id="resp_slow",
                )
            await asyncio.sleep(0)
            return _completion(
                "Fast.",
                {"total_tokens": 5},
                response_id="resp_fast",
            )

    source = Chat("Answer briefly.", runtime=_ConcurrentRuntime())

    slow, fast = await asyncio.gather(
        source.chat_a("slow"),
        source.chat_a("fast"),
    )

    assert slow.last_call_usage.responses[0].response_id == "resp_slow"
    assert slow.last_call_usage.total.total_tokens == 20
    assert fast.last_call_usage.responses[0].response_id == "resp_fast"
    assert fast.last_call_usage.total.total_tokens == 5
    assert source.last_call_usage is slow.last_call_usage


def test_public_usage_types_are_available_from_package_root():
    assert CallUsage.__name__ == "CallUsage"
    assert ResponseUsage.__name__ == "ResponseUsage"
    assert UsageCounts.__name__ == "UsageCounts"
