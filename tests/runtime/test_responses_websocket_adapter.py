from types import SimpleNamespace

import pytest

from chatsnack.runtime import (
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
    RuntimeStreamEvent,
)


def test_session_busy_raises_fail_fast(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    adapter.session.in_flight = True
    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert events[0].type == "error"
    assert "in-flight" in events[0].data["error"]["message"]


def test_previous_response_not_found_retries_once_without_previous(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    calls = []

    def fake_stream_once(messages, kwargs, include_prev=True):
        calls.append((kwargs.copy(), include_prev))
        if len(calls) == 1:
            raise RuntimeError("previous_response_not_found")

        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "ok"})
        adapter.session.last_response_id = "resp_new"

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream_once)

    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert events[0].type == "text_delta"
    assert len(calls) == 2
    assert calls[0][1] is True
    assert calls[1][1] is False
    assert adapter.session.last_response_id == "resp_new"


def test_create_completion_consumes_stream_to_normalized_result(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, **kwargs):
        yield SimpleNamespace(type="text_delta", index=0, data={"text": "hel"})
        yield SimpleNamespace(type="text_delta", index=1, data={"text": "lo"})
        yield SimpleNamespace(
            type="completed",
            index=2,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {"total_tokens": 5},
                    "response_text": "hello",
                    "metadata": {"response_id": "resp_1"},
                }
            },
        )

    monkeypatch.setattr(adapter, "stream_completion", fake_stream)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "hello"
    assert result.metadata["response_id"] == "resp_1"


def test_create_completion_preserves_streamed_tool_calls(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, **kwargs):
        yield SimpleNamespace(
            type="tool_call_delta",
            index=0,
            data={"tool_call": {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": '{"q"'}}},
        )
        yield SimpleNamespace(
            type="tool_call_delta",
            index=1,
            data={"tool_call": {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": ': "snack"}'}}},
        )
        yield SimpleNamespace(
            type="completed",
            index=2,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {"total_tokens": 5},
                    "response_text": "",
                    "metadata": {"response_id": "resp_1"},
                }
            },
        )

    monkeypatch.setattr(adapter, "stream_completion", fake_stream)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert len(result.message.tool_calls) == 1
    assert result.message.tool_calls[0].id == "call_1"
    assert result.message.tool_calls[0].function.name == "lookup"
    assert result.message.tool_calls[0].function.arguments == '{"q": "snack"}'


def test_create_completion_raises_on_stream_error_event(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, **kwargs):
        yield SimpleNamespace(type="error", index=0, data={"error": {"message": "busy session", "code": "session_busy"}})

    monkeypatch.setattr(adapter, "stream_completion", fake_stream)

    with pytest.raises(RuntimeError, match="session_busy"):
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")


@pytest.mark.asyncio
async def test_stream_completion_a_busy_raises_fail_fast():
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    adapter.session.in_flight = True

    events = []
    async for event in adapter.stream_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"):
        events.append(event)

    assert events[0].type == "error"
    assert events[0].data["error"]["code"] == "transport_error"


@pytest.mark.asyncio
async def test_create_completion_a_raises_on_stream_error_event(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    async def fake_stream(messages, **kwargs):
        yield SimpleNamespace(type="error", index=0, data={"error": {"message": "busy session", "code": "session_busy"}})

    monkeypatch.setattr(adapter, "stream_completion_a", fake_stream)

    with pytest.raises(RuntimeError, match="session_busy"):
        await adapter.create_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")
