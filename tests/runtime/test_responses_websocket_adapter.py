import sys
import threading
import types
from types import SimpleNamespace

import pytest

from chatsnack.runtime import (
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
    RuntimeStreamEvent,
)
from chatsnack.runtime.responses_websocket_adapter import (
    ResponsesWebSocketTransportError,
    _SDK_VERSION_GUIDANCE,
)


def test_session_busy_raises_fail_fast(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    adapter.session.in_flight = True
    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert events[0].type == "error"
    assert "in-flight" in events[0].data["error"]["message"]


def test_busy_session_does_not_clear_existing_in_flight_flag():
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    adapter.session.in_flight = True
    list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert adapter.session.in_flight is True


def test_request_with_session_applies_continuation_defaults_before_building_input():
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    adapter.session.last_response_id = "resp_prev"

    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "continue"},
    ]

    request = adapter._request_with_session(messages, {"model": "gpt-4.1"}, include_prev=True)

    assert request["previous_response_id"] == "resp_prev"
    assert request["store"] is True
    assert len(request["input"]) == 1
    assert request["input"][0]["content"][0]["text"] == "continue"

def test_previous_response_not_found_retries_once_without_previous(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
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


def test_retriable_transport_error_reopens_connection_once(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    calls = []

    def fake_stream_once(messages, kwargs, include_prev=True):
        calls.append((kwargs.copy(), include_prev))
        if len(calls) == 1:
            raise ResponsesWebSocketTransportError("socket_receive_failed", code="socket_receive_failed", retriable=True)
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "ok"})

    dropped = {"count": 0}

    def drop_connection():
        dropped["count"] += 1

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream_once)
    monkeypatch.setattr(adapter, "_drop_sync_connection", drop_connection)

    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert events[0].type == "text_delta"
    assert len(calls) == 2
    assert dropped["count"] == 1


def test_non_retriable_transport_error_surfaces_structured_error(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream_fail(messages, kwargs, include_prev=True):
        raise ResponsesWebSocketTransportError("auth failed", code="auth_error", retriable=False, details={"provider_code": "unauthorized"})
        yield  # pragma: no cover

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream_fail)
    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert events[0].type == "error"
    assert events[0].data["error"]["code"] == "auth_error"
    assert events[0].data["error"]["retriable"] is False
    assert events[0].data["error"]["details"]["provider_code"] == "unauthorized"


def test_create_completion_consumes_stream_to_normalized_result(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
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
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
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
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, **kwargs):
        yield SimpleNamespace(type="error", index=0, data={"error": {"message": "busy session", "code": "session_busy"}})

    monkeypatch.setattr(adapter, "stream_completion", fake_stream)

    from chatsnack.runtime.responses_websocket_adapter import ResponsesSessionBusyError
    with pytest.raises(ResponsesSessionBusyError, match="busy session"):
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")


@pytest.mark.asyncio
async def test_stream_completion_a_busy_raises_fail_fast():
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    adapter.session.in_flight = True

    events = []
    async for event in adapter.stream_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"):
        events.append(event)

    assert events[0].type == "error"
    assert events[0].data["error"]["code"] == "session_busy"


@pytest.mark.asyncio
async def test_create_completion_a_raises_on_stream_error_event(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    async def fake_stream(messages, **kwargs):
        yield SimpleNamespace(type="error", index=0, data={"error": {"message": "busy session", "code": "session_busy"}})

    monkeypatch.setattr(adapter, "stream_completion_a", fake_stream)

    from chatsnack.runtime.responses_websocket_adapter import ResponsesSessionBusyError
    with pytest.raises(ResponsesSessionBusyError, match="busy session"):
        await adapter.create_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")


def test_shared_session_enforces_single_in_flight_across_adapters(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter_a = ResponsesWebSocketAdapter(ai, session=session)
    adapter_b = ResponsesWebSocketAdapter(ai, session=session)

    gate = threading.Event()
    proceed = threading.Event()

    def slow_stream(messages, kwargs, include_prev=True):
        gate.set()
        proceed.wait(timeout=1.0)
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "ok"})

    def fast_stream(messages, kwargs, include_prev=True):
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "nope"})

    monkeypatch.setattr(adapter_a, "_stream_sync_request", slow_stream)
    monkeypatch.setattr(adapter_b, "_stream_sync_request", fast_stream)

    first_events = []
    second_events = []

    def run_first():
        first_events.extend(adapter_a.stream_completion(messages=[{"role": "user", "content": "a"}], model="gpt-4.1"))

    t1 = threading.Thread(target=run_first)
    t1.start()
    assert gate.wait(timeout=1.0)

    second_events.extend(adapter_b.stream_completion(messages=[{"role": "user", "content": "b"}], model="gpt-4.1"))
    proceed.set()
    t1.join(timeout=1.0)

    assert any(event.type == "text_delta" for event in first_events)
    assert second_events[0].type == "error"
    assert "in-flight" in second_events[0].data["error"]["message"]


def test_sdk_version_check_raises_clear_message():
    """Adapter should fail fast with a clear message when SDK lacks responses.connect()."""
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    # client is None so responses.connect won't be available
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    # Try to connect - should raise the version guidance message
    with pytest.raises(RuntimeError, match="openai>=2.29.0"):
        adapter._connect_sync()


def test_create_kwargs_strips_transport_fields():
    """_create_kwargs should remove stream and background from the request."""
    request = {"model": "gpt-4.1", "input": [], "stream": True, "background": True, "store": False}
    result = ResponsesWebSocketAdapter._create_kwargs(request)
    assert "stream" not in result
    assert "background" not in result
    assert result["model"] == "gpt-4.1"
    assert result["store"] is False


def test_no_retry_after_partial_output_emitted(monkeypatch):
    """Retriable transport errors should NOT trigger retry if deltas have already been yielded."""
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    calls = []

    def fake_stream_with_partial_then_fail(messages, kwargs, include_prev=True):
        calls.append(len(calls) + 1)
        from chatsnack.runtime.types import RuntimeStreamEvent
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "partial"})
        raise ResponsesWebSocketTransportError("socket_receive_failed", code="socket_receive_failed", retriable=True)

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream_with_partial_then_fail)

    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    # Should have yielded the text_delta then an error - NOT retried
    assert len(calls) == 1, "Should not retry after partial output"
    assert events[0].type == "text_delta"
    assert events[1].type == "error"
