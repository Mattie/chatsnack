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


@pytest.mark.asyncio
async def test_connect_async_does_not_reuse_sync_socket(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)
    sync_socket = object()
    session.sync_socket = sync_socket

    class FakeAsyncSocket:
        pass

    fake_async_socket = FakeAsyncSocket()

    async def fake_connect(*args, **kwargs):
        return fake_async_socket

    fake_websockets = types.SimpleNamespace(connect=fake_connect)
    monkeypatch.setitem(sys.modules, "websockets", fake_websockets)

    ws = await adapter._connect_async()

    assert ws is fake_async_socket
    assert session.async_socket is fake_async_socket
    assert session.sync_socket is sync_socket


def test_connect_sync_does_not_reuse_async_socket(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)
    async_socket = object()
    session.async_socket = async_socket

    class FakeSyncSocket:
        pass

    fake_sync_socket = FakeSyncSocket()
    fake_websocket = types.SimpleNamespace(create_connection=lambda *args, **kwargs: fake_sync_socket)
    monkeypatch.setitem(sys.modules, "websocket", fake_websocket)

    ws = adapter._connect_sync()

    assert ws is fake_sync_socket
    assert session.sync_socket is fake_sync_socket
    assert session.async_socket is async_socket


def test_shared_session_enforces_single_in_flight_across_adapters(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None)
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
