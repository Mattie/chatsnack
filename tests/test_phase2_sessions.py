from types import SimpleNamespace

import pytest

from chatsnack import Chat
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime import (
    ResponsesAdapter,
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
    ResponsesSessionBusyError,
    ResponsesWebSocketTransportError,
)


# ---------------------------------------------------------------------------
# Runtime selection
# ---------------------------------------------------------------------------

def test_responses_runtime_without_session_stays_http():
    chat = Chat(params=ChatParams(runtime="responses", session=None))
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_constructor_runtime_string_selects_responses_adapter():
    chat = Chat(runtime="responses")
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_constructor_kwargs_apply_model_and_session():
    chat = Chat(runtime="responses", model="gpt-5.4", session="inherit")
    assert chat.model == "gpt-5.4"
    assert chat.session == "inherit"
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter)


# ---------------------------------------------------------------------------
# Session lineage: inherit vs new
# ---------------------------------------------------------------------------

def test_responses_runtime_with_inherit_selects_websocket_and_inherits_lineage(monkeypatch):
    chat = Chat(params=ChatParams(runtime="responses", session="inherit"))
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter)

    async def fake_create_completion_a(self, messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=[]), metadata={"response_id": "r1"})

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)
    next_chat = chat.chat("hello")

    assert isinstance(next_chat.runtime, ResponsesWebSocketAdapter)
    assert next_chat.runtime.session is chat.runtime.session


def test_responses_runtime_with_new_selects_websocket_and_descendants_get_new_session(monkeypatch):
    chat = Chat(params=ChatParams(runtime="responses", session="new"))

    async def fake_create_completion_a(self, messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="hello", tool_calls=[]), metadata={"response_id": "r1"})

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)
    next_chat = chat.chat("hello")

    assert isinstance(next_chat.runtime, ResponsesWebSocketAdapter)
    assert next_chat.runtime.session is not chat.runtime.session


def test_session_new_descendants_seeded_from_parent_session_state(monkeypatch):
    """session='new' descendants should carry lineage (last_response_id, last_model,
    last_store_value) from the parent session so continuation is preserved."""
    chat = Chat(params=ChatParams(runtime="responses", session="new"))
    parent_session = chat.runtime.session
    parent_session.last_response_id = "resp_parent_42"
    parent_session.last_model = "gpt-4.1"
    parent_session.last_store_value = True

    async def fake_create_completion_a(self, messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]), metadata={"response_id": "resp_child"})

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)
    child = chat.chat("continue")

    assert isinstance(child.runtime, ResponsesWebSocketAdapter)
    child_session = child.runtime.session
    assert child_session is not parent_session
    assert child_session.last_response_id == "resp_parent_42"
    assert child_session.last_model == "gpt-4.1"
    assert child_session.last_store_value is True


# ---------------------------------------------------------------------------
# Close methods
# ---------------------------------------------------------------------------

def test_close_session_methods_delegate_to_adapter(monkeypatch):
    chat = Chat(params=ChatParams(runtime="responses", session="inherit"))
    called = {"single": 0, "all": 0}

    monkeypatch.setattr(chat.runtime, "close_session", lambda: called.__setitem__("single", called["single"] + 1))
    monkeypatch.setattr(ResponsesWebSocketAdapter, "close_all_sessions", classmethod(lambda cls: called.__setitem__("all", called["all"] + 1)))

    chat.close_session()
    Chat.close_all_sessions()

    assert called == {"single": 1, "all": 1}


def test_close_session_via_direct_constructor_kwargs():
    """close_session() must be reachable via direct constructor kwargs
    (no ChatParams wrapper), matching the notebook style.

    Regression: older releases raised AttributeError because close_session
    was not defined on Chat.
    """
    snack = Chat("You are a concise snack expert.", runtime="responses", session="inherit")
    assert hasattr(snack, "close_session") and callable(snack.close_session)
    # Should not raise
    snack.close_session()


def test_listen_with_direct_constructor_kwargs_and_stream(monkeypatch):
    """listen() must work when runtime/session/stream are passed as direct
    constructor kwargs (no ChatParams wrapper).

    Regression: older releases crashed with
    ``AttributeError: 'NoneType' object has no attribute 'stream'``
    because listen() accessed self.params.stream directly instead of the
    guarded self.stream property.
    """
    from chatsnack.chat.mixin_query import ChatStreamListener
    from chatsnack.runtime.types import RuntimeStreamEvent

    chat = Chat("Respond tersely.", runtime="responses", session="inherit", stream=True)
    # Verify params were populated by the constructor
    assert chat.params is not None
    assert chat.stream is True

    def fake_stream(self, messages, **kwargs):
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "hi"})
        yield RuntimeStreamEvent(
            type="completed", index=1,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {},
                    "response_text": "hi",
                    "metadata": {"response_id": "resp_nb"},
                }
            },
        )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "stream_completion", fake_stream)
    listener = chat.listen("Give one sentence on reusable prompts.")
    assert isinstance(listener, ChatStreamListener)
    chunks = list(listener)
    assert "".join(chunks) == "hi"


# ---------------------------------------------------------------------------
# ask() acceptance through the WebSocket adapter
# ---------------------------------------------------------------------------

def test_ask_through_websocket_returns_text(monkeypatch):
    """ask() should return plain text when using the WebSocket runtime."""
    chat = Chat("Respond tersely.", runtime="responses", session="inherit")

    async def fake_create_completion_a(self, messages, **kwargs):
        return SimpleNamespace(
            message=SimpleNamespace(content="pong", tool_calls=[]),
            metadata={"response_id": "resp_ask"},
        )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)
    result = chat.ask("ping")

    assert result == "pong"


def test_ask_through_websocket_preserves_attachment_only_turn_metadata(monkeypatch):
    """WebSocket ask() should pass attachment-only expanded turns through to the runtime."""
    chat = Chat(runtime="responses", session="inherit")
    chat.messages = [{"user": {"files": [{"file_id": "file_phase3"}]}}]
    captured = {}

    async def fake_create_completion_a(self, messages, **kwargs):
        captured["messages"] = messages
        return SimpleNamespace(
            message=SimpleNamespace(content="ok", tool_calls=[]),
            metadata={"response_id": "resp_attach"},
        )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)

    result = chat.ask("Acknowledge the earlier attachment.")

    assert result == "ok"
    assert captured["messages"][0] == {
        "role": "user",
        "content": "",
        "files": [{"file_id": "file_phase3"}],
    }


def test_ask_through_websocket_passes_provider_native_tools(monkeypatch):
    """WebSocket ask() should forward provider-native tools unchanged."""
    chat = Chat(runtime="responses", session="inherit")
    chat.params.set_tools([{"type": "web_search"}])
    chat.params.tool_choice = "required"
    captured = {}

    async def fake_create_completion_a(self, messages, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            message=SimpleNamespace(content="tool ok", tool_calls=[]),
            metadata={"response_id": "resp_tool"},
        )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)

    result = chat.ask("Search if needed.")

    assert result == "tool ok"
    assert captured["kwargs"]["tools"] == [{"type": "web_search"}]
    assert captured["kwargs"]["tool_choice"] == "required"


# ---------------------------------------------------------------------------
# chat() acceptance through the WebSocket adapter + continuation metadata
# ---------------------------------------------------------------------------

def test_chat_continuation_propagates_metadata(monkeypatch):
    """chat() should propagate response_id via runtime metadata for continuation."""
    chat = Chat("You are helpful.", runtime="responses", session="inherit")
    call_count = {"n": 0}

    async def fake_create_completion_a(self, messages, **kwargs):
        call_count["n"] += 1
        return SimpleNamespace(
            message=SimpleNamespace(content=f"reply {call_count['n']}", tool_calls=[]),
            metadata={"response_id": f"resp_{call_count['n']}"},
        )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)

    c1 = chat.chat("first")
    assert c1._last_runtime_metadata["response_id"] == "resp_1"

    c2 = c1.chat("second")
    assert c2._last_runtime_metadata["response_id"] == "resp_2"


# ---------------------------------------------------------------------------
# listen() acceptance through the WebSocket adapter
# ---------------------------------------------------------------------------

def test_listen_returns_stream_listener(monkeypatch):
    """listen() should return a ChatStreamListener that can be iterated."""
    chat = Chat("Stream test.", runtime="responses", session="inherit", stream=True)
    from chatsnack.chat.mixin_query import ChatStreamListener
    from chatsnack.runtime.types import RuntimeStreamEvent

    chunks_produced = []

    def fake_stream(self, messages, **kwargs):
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "hel"})
        yield RuntimeStreamEvent(type="text_delta", index=1, data={"text": "lo"})
        yield RuntimeStreamEvent(
            type="completed",
            index=2,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {},
                    "response_text": "hello",
                    "metadata": {"response_id": "resp_listen"},
                }
            },
        )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "stream_completion", fake_stream)
    listener = chat.listen("stream this")

    assert isinstance(listener, ChatStreamListener)
    for chunk in listener:
        chunks_produced.append(chunk)

    assert "".join(chunks_produced) == "hello"


# ---------------------------------------------------------------------------
# copy() acceptance
# ---------------------------------------------------------------------------

def test_copy_inherits_runtime_and_metadata(monkeypatch):
    """copy() should preserve runtime type and runtime metadata."""
    chat = Chat("You are helpful.", runtime="responses", session="inherit")
    chat._last_runtime_metadata = {
        "response_id": "resp_copy",
        "usage": None,
        "assistant_phase": None,
        "provider_extras": None,
    }

    copied = chat.copy()

    assert isinstance(copied.runtime, ResponsesWebSocketAdapter)
    assert copied.runtime.session is chat.runtime.session
    assert copied._last_runtime_metadata["response_id"] == "resp_copy"


# ---------------------------------------------------------------------------
# Error taxonomy: structured errors propagate through create_completion
# ---------------------------------------------------------------------------

def test_create_completion_preserves_transport_error_metadata(monkeypatch):
    """create_completion() should raise ResponsesWebSocketTransportError with
    full metadata instead of a plain RuntimeError."""
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, **kwargs):
        yield SimpleNamespace(
            type="error",
            index=0,
            data={
                "error": {
                    "message": "rate limit exceeded",
                    "code": "rate_limit",
                    "retriable": True,
                    "details": {"retry_after": 30},
                }
            },
        )

    monkeypatch.setattr(adapter, "stream_completion", fake_stream)

    with pytest.raises(ResponsesWebSocketTransportError) as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert exc_info.value.code == "rate_limit"
    assert exc_info.value.retriable is True
    assert exc_info.value.details == {"retry_after": 30}


def test_create_completion_raises_session_busy_error(monkeypatch):
    """create_completion() should raise ResponsesSessionBusyError for busy sessions."""
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, **kwargs):
        yield SimpleNamespace(
            type="error",
            index=0,
            data={"error": {"message": "session is busy", "code": "session_busy"}},
        )

    monkeypatch.setattr(adapter, "stream_completion", fake_stream)

    with pytest.raises(ResponsesSessionBusyError, match="session is busy"):
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")


# ---------------------------------------------------------------------------
# Retry after partial output: no retry once deltas have been emitted
# ---------------------------------------------------------------------------

def test_no_retry_after_partial_output_emitted(monkeypatch):
    """Retriable transport errors should NOT trigger retry if deltas have already been yielded."""
    ai = SimpleNamespace(api_key="x", base_url=None)
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


# ---------------------------------------------------------------------------
# Async close properly awaits
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_session_a_awaits_async_connection():
    """close_session_a() should properly await the async connection close."""
    ai = SimpleNamespace(api_key="x", base_url=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    closed = {"awaited": False}

    class FakeAsyncConnection:
        async def close(self):
            closed["awaited"] = True

    adapter.session.async_connection = FakeAsyncConnection()
    await adapter.close_session_a()

    assert closed["awaited"] is True
    assert adapter.session.async_connection is None


# ---------------------------------------------------------------------------
# WebSocket + utensil acceptance (tool call through chat() path)
# ---------------------------------------------------------------------------

def test_chat_with_utensils_executes_tool_and_feeds_back(monkeypatch):
    """Chat(..., session='inherit', utensils=[...]).chat() should execute tool calls
    and feed results back to the model through the recursive tool execution path."""
    from chatsnack.utensil import utensil

    @utensil
    def snack_lookup(name: str) -> str:
        """Look up snack info by name."""
        return f"{name} has 100 calories"

    chat = Chat(
        "You are a snack expert.",
        runtime="responses",
        session="inherit",
        utensils=[snack_lookup],
    )

    call_count = {"n": 0}

    async def fake_create_completion_a(self, messages, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: model wants to call a tool
            return SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_abc",
                            type="function",
                            function=SimpleNamespace(
                                name="snack_lookup",
                                arguments='{"name": "popcorn"}',
                            ),
                        )
                    ],
                ),
                metadata={"response_id": "resp_tool_1"},
            )
        else:
            # Second call: model uses tool result to respond
            return SimpleNamespace(
                message=SimpleNamespace(content="Popcorn has 100 calories!", tool_calls=[]),
                metadata={"response_id": "resp_tool_2"},
            )

    monkeypatch.setattr(ResponsesWebSocketAdapter, "create_completion_a", fake_create_completion_a)
    result = chat.chat("How many calories in popcorn?")

    # The result should be a Chat with the final response
    assert "Popcorn has 100 calories!" in result.response
    assert call_count["n"] == 2
