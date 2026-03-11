import pytest
from types import SimpleNamespace

from chatsnack.runtime import (
    ChatCompletionsAdapter,
    EVENT_SCHEMA_VERSION,
    RESERVED_EVENT_TYPES,
)


class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


def test_reserved_event_types_are_defined():
    assert RESERVED_EVENT_TYPES == {
        "text_delta",
        "tool_call_delta",
        "tool_result",
        "phase",
        "usage",
        "completed",
        "error",
    }


def test_normalizes_non_stream_completion_with_tool_calls():
    response = _FakeObj(
        {
            "model": "gpt-test",
            "usage": {"total_tokens": 4},
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "get_weather", "arguments": '{"city":"Boston"}'},
                            }
                        ],
                    },
                }
            ],
        }
    )

    ai = SimpleNamespace(
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
    )
    adapter = ChatCompletionsAdapter(ai)

    result = adapter.create_completion(messages=[{"role": "user", "content": "weather?"}])

    assert result.model == "gpt-test"
    assert result.finish_reason == "tool_calls"
    assert result.usage == {"total_tokens": 4}
    assert result.message.tool_calls[0].id == "call_1"
    assert result.message.tool_calls[0].function.name == "get_weather"


def test_normalizes_sync_stream_events_with_completed_terminal():
    chunks = iter(
        [
            _FakeObj({"model": "gpt-test", "choices": [{"finish_reason": None, "delta": {"content": "Hi"}}]}),
            _FakeObj({"model": "gpt-test", "choices": [{"finish_reason": None, "delta": {"tool_calls": [{"id": "tc1"}]}}]}),
            _FakeObj({"model": "gpt-test", "usage": {"total_tokens": 3}, "choices": [{"finish_reason": "stop", "delta": {"content": "!"}}]}),
        ]
    )
    ai = SimpleNamespace(
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: chunks)))
    )
    adapter = ChatCompletionsAdapter(ai)

    events = list(adapter.stream_completion(messages=[]))

    assert [e.type for e in events] == ["text_delta", "tool_call_delta", "text_delta", "usage", "completed"]
    assert all(e.schema_version == EVENT_SCHEMA_VERSION for e in events)
    assert events[-1].data["terminal"]["response_text"] == "Hi!"
    assert events[-1].data["terminal"]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_normalizes_async_stream_errors_into_error_event():
    class _BadAsyncStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("boom")

    async def create(**kwargs):
        return _BadAsyncStream()

    ai = SimpleNamespace(
        aclient=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )
    adapter = ChatCompletionsAdapter(ai)

    events = []
    async for event in adapter.stream_completion_a(messages=[]):
        events.append(event)

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].schema_version == EVENT_SCHEMA_VERSION
    assert events[0].data["error"]["message"] == "boom"
