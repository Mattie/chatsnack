from contextlib import contextmanager
from io import StringIO
import sys
import threading
import types
from types import SimpleNamespace

import pytest
from loguru import logger

from chatsnack.runtime import (
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
    RuntimeStreamEvent,
)
from chatsnack.runtime.responses_websocket_adapter import (
    ResponsesWebSocketTransportError,
    _SDK_VERSION_GUIDANCE,
)


@contextmanager
def _capture_loguru():
    sink = StringIO()
    sink_id = logger.add(sink, format="{message}")
    try:
        yield sink
    finally:
        logger.remove(sink_id)


class _FakeCompletedResponse:
    def __init__(self, text="ok", response_id="resp_ok", model="gpt-4.1"):
        self.output_text = text
        self._response_id = response_id
        self._model = model

    def model_dump(self):
        return {
            "id": self._response_id,
            "status": "completed",
            "model": self._model,
            "usage": {"total_tokens": 4},
            "output_text": self.output_text,
        }


class _FakeCompletedEvent:
    type = "response.completed"

    def __init__(self, text="ok", response_id="resp_ok", model="gpt-4.1"):
        self.response = _FakeCompletedResponse(text=text, response_id=response_id, model=model)


class _FakeTopLevelErrorEvent:
    type = "error"

    def __init__(self, code, message=None, *, status=None, provider_type=None):
        self.code = code
        self.message = message or code
        self.status = status
        self.provider_type = provider_type

    def model_dump(self):
        error = {"code": self.code, "message": self.message}
        if self.provider_type is not None:
            error["type"] = self.provider_type
        payload = {"type": "error", "error": error}
        if self.status is not None:
            payload["status"] = self.status
        return payload


class _FakeResponseFailedEvent:
    type = "response.failed"

    def __init__(self, code, message=None, *, provider_type=None):
        self.response = SimpleNamespace(
            id="resp_failed",
            status="failed",
            error=SimpleNamespace(
                code=code,
                message=message or code,
                type=provider_type,
            ),
        )


class _FakeSyncConnection:
    def __init__(self, events=None, *, create_error=None):
        self.response = SimpleNamespace(create=self.create)
        self._events = list(events or [])
        self.create_error = create_error
        self.create_calls = []
        self.closed = False

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error

    def __iter__(self):
        return self

    def __next__(self):
        if self._events:
            return self._events.pop(0)
        raise StopIteration

    def close(self):
        self.closed = True


class _FakeAsyncConnection:
    def __init__(self, events=None, *, create_error=None):
        async def create(**kwargs):
            self.create_calls.append(kwargs)
            if self.create_error is not None:
                raise self.create_error

        self.response = SimpleNamespace(create=create)
        self._events = list(events or [])
        self.create_error = create_error
        self.create_calls = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._events:
            return self._events.pop(0)
        raise StopAsyncIteration

    async def close(self):
        self.closed = True


class _SequencedSyncResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.connect_calls = 0

    def connect(self):
        return self

    def enter(self):
        self.connect_calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected sync connect attempt")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _SequencedAsyncResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.connect_calls = 0

    def connect(self):
        return self

    async def enter(self):
        self.connect_calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected async connect attempt")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _fake_sdk_error(status, code, message=None, provider_type=None):
    exc = Exception(message or code)
    exc.status_code = status
    exc.request_id = "req_test"
    exc.body = {
        "code": code,
        "message": message or code,
        "type": provider_type,
    }
    return exc


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

    request = adapter._request_with_session(messages, {"model": "gpt-4.1", "store": True}, include_prev=True)

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
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"), retry_initial_delay=0)
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


def test_create_completion_retries_transport_error_before_output_and_succeeds(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )
    calls = []
    dropped = {"count": 0}

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append((kwargs.copy(), include_prev))
        if len(calls) == 1:
            raise ResponsesWebSocketTransportError(
                "opening handshake timed out",
                code="socket_open_timeout",
                retriable=True,
                details={"phase": "opening_handshake"},
            )
        yield RuntimeStreamEvent(
            type="completed",
            index=0,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {"total_tokens": 4},
                    "response_text": "recovered",
                    "metadata": {"response_id": "resp_retry"},
                }
            },
        )

    def drop_connection():
        dropped["count"] += 1

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)
    monkeypatch.setattr(adapter, "_drop_sync_connection", drop_connection)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "recovered"
    assert len(calls) == 2
    assert dropped["count"] == 1


@pytest.mark.asyncio
async def test_create_completion_a_retries_transport_error_before_output_and_succeeds(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )
    calls = []
    dropped = {"count": 0}

    async def fake_stream(messages, kwargs, include_prev=True):
        calls.append((kwargs.copy(), include_prev))
        if len(calls) == 1:
            raise ResponsesWebSocketTransportError(
                "opening handshake timed out",
                code="socket_open_timeout",
                retriable=True,
                details={"phase": "opening_handshake"},
            )
        yield RuntimeStreamEvent(
            type="completed",
            index=0,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {"total_tokens": 4},
                    "response_text": "recovered",
                    "metadata": {"response_id": "resp_retry_async"},
                }
            },
        )

    async def drop_connection():
        dropped["count"] += 1

    monkeypatch.setattr(adapter, "_stream_async_request", fake_stream)
    monkeypatch.setattr(adapter, "_drop_async_connection", drop_connection)

    result = await adapter.create_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "recovered"
    assert len(calls) == 2
    assert dropped["count"] == 1


def test_create_completion_retries_sync_connect_open_failure_and_succeeds():
    responses = _SequencedSyncResponses(
        [
            TimeoutError("timed out during opening handshake"),
            _FakeSyncConnection([_FakeCompletedEvent(text="recovered", response_id="resp_sync_connect")]),
        ]
    )
    ai = SimpleNamespace(client=SimpleNamespace(responses=responses), aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "recovered"
    assert responses.connect_calls == 2


@pytest.mark.asyncio
async def test_create_completion_a_retries_async_connect_open_failure_and_succeeds():
    responses = _SequencedAsyncResponses(
        [
            TimeoutError("timed out during opening handshake"),
            _FakeAsyncConnection([_FakeCompletedEvent(text="recovered", response_id="resp_async_connect")]),
        ]
    )
    ai = SimpleNamespace(client=None, aclient=SimpleNamespace(responses=responses))
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )

    result = await adapter.create_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "recovered"
    assert responses.connect_calls == 2


def test_create_completion_exhausts_connect_open_failures_with_socket_connect_metadata():
    responses = _SequencedSyncResponses(
        [
            TimeoutError("timed out during opening handshake"),
            TimeoutError("timed out during opening handshake"),
            TimeoutError("timed out during opening handshake"),
        ]
    )
    ai = SimpleNamespace(client=SimpleNamespace(responses=responses), aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        max_transport_retries=2,
        retry_initial_delay=0,
    )

    with pytest.raises(ResponsesWebSocketTransportError, match="timed out during opening handshake") as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert responses.connect_calls == 3
    assert exc_info.value.code == "socket_connect_failed"
    assert exc_info.value.retriable is True
    assert exc_info.value.details["phase"] == "opening_handshake"
    assert exc_info.value.details["request_summary"]["model"] == "gpt-4.1"


def test_websocket_connection_limit_reached_reconnects_before_output():
    first_connection = _FakeSyncConnection(
        [
            _FakeTopLevelErrorEvent(
                "websocket_connection_limit_reached",
                "Responses websocket connection limit reached (60 minutes).",
                status=400,
                provider_type="invalid_request_error",
            )
        ]
    )
    second_connection = _FakeSyncConnection([_FakeCompletedEvent(text="continued", response_id="resp_limit_retry")])
    responses = _SequencedSyncResponses([first_connection, second_connection])
    ai = SimpleNamespace(client=SimpleNamespace(responses=responses), aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "continued"
    assert responses.connect_calls == 2
    assert first_connection.closed is True


def test_response_create_validation_error_fails_fast_without_retry():
    validation_error = _fake_sdk_error(
        400,
        "invalid_value",
        "Invalid value: 'namespace'.",
        "invalid_request_error",
    )
    connection = _FakeSyncConnection(create_error=validation_error)
    responses = _SequencedSyncResponses([connection])
    ai = SimpleNamespace(client=SimpleNamespace(responses=responses), aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        max_transport_retries=2,
        retry_initial_delay=0,
    )

    with pytest.raises(ResponsesWebSocketTransportError, match="Invalid value") as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert responses.connect_calls == 1
    assert len(connection.create_calls) == 1
    assert exc_info.value.code == "invalid_value"
    assert exc_info.value.retriable is False


def test_streamed_validation_failure_fails_fast_without_retry():
    connection = _FakeSyncConnection(
        [_FakeResponseFailedEvent("invalid_tools", "Tool schema is invalid", provider_type="invalid_request_error")]
    )
    responses = _SequencedSyncResponses([connection])
    ai = SimpleNamespace(client=SimpleNamespace(responses=responses), aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        max_transport_retries=2,
        retry_initial_delay=0,
    )

    with pytest.raises(ResponsesWebSocketTransportError, match="Tool schema is invalid") as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert responses.connect_calls == 1
    assert exc_info.value.code == "invalid_tools"
    assert exc_info.value.retriable is False


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (429, "rate_limit_exceeded"),
        (500, "server_error"),
    ],
)
def test_response_create_transient_provider_errors_retry_before_output(status, code):
    first_connection = _FakeSyncConnection(create_error=_fake_sdk_error(status, code, code))
    second_connection = _FakeSyncConnection([_FakeCompletedEvent(text="recovered", response_id=f"resp_{code}")])
    responses = _SequencedSyncResponses([first_connection, second_connection])
    ai = SimpleNamespace(client=SimpleNamespace(responses=responses), aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "recovered"
    assert responses.connect_calls == 2
    assert first_connection.closed is True


@pytest.mark.parametrize("event_type", ["text_delta", "tool_call_delta", "completed"])
def test_retry_guard_consumes_observable_output_events(event_type):
    assert ResponsesWebSocketAdapter._event_consumes_retry_guard(SimpleNamespace(type=event_type)) is True


def test_create_completion_retries_structured_stream_error_before_output(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )
    calls = []
    dropped = {"count": 0}

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            yield RuntimeStreamEvent(
                type="error",
                index=0,
                data={
                    "error": {
                        "message": "opening handshake timed out",
                        "code": "socket_open_timeout",
                        "retriable": True,
                        "details": {"phase": "opening_handshake"},
                    }
                },
            )
            return
        yield RuntimeStreamEvent(
            type="completed",
            index=0,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {"total_tokens": 4},
                    "response_text": "ok",
                    "metadata": {"response_id": "resp_structured_retry"},
                }
            },
        )

    def drop_connection():
        dropped["count"] += 1

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)
    monkeypatch.setattr(adapter, "_drop_sync_connection", drop_connection)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "ok"
    assert calls == [1, 2]
    assert dropped["count"] == 1


def test_create_completion_does_not_retry_transport_error_after_text_delta(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )
    calls = []

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append(len(calls) + 1)
        yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "partial"})
        raise ResponsesWebSocketTransportError(
            "socket_receive_failed",
            code="socket_receive_failed",
            retriable=True,
        )

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    with pytest.raises(ResponsesWebSocketTransportError, match="socket_receive_failed"):
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert calls == [1]


def test_create_completion_does_not_retry_auth_error_even_when_marked_retriable(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )
    calls = []

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append(len(calls) + 1)
        raise ResponsesWebSocketTransportError("auth failed", code="auth_error", retriable=True)
        yield  # pragma: no cover

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    with pytest.raises(ResponsesWebSocketTransportError, match="auth failed") as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert exc_info.value.code == "auth_error"
    assert calls == [1]


def test_create_completion_exhausts_transport_retries_and_preserves_error_details(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        max_transport_retries=2,
        retry_initial_delay=0,
    )
    calls = []
    dropped = {"count": 0}

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append(len(calls) + 1)
        raise ResponsesWebSocketTransportError(
            "opening handshake timed out",
            code="socket_open_timeout",
            retriable=True,
            details={"phase": "opening_handshake"},
        )
        yield  # pragma: no cover

    def drop_connection():
        dropped["count"] += 1

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)
    monkeypatch.setattr(adapter, "_drop_sync_connection", drop_connection)

    with pytest.raises(ResponsesWebSocketTransportError, match="opening handshake timed out") as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert calls == [1, 2, 3]
    assert dropped["count"] == 2
    assert exc_info.value.code == "socket_open_timeout"
    assert exc_info.value.details == {"phase": "opening_handshake"}


def test_create_completion_exhausted_previous_response_retry_preserves_error_taxonomy(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        retry_initial_delay=0,
    )
    adapter.session.last_response_id = "resp_missing"
    calls = []

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append(include_prev)
        raise RuntimeError("previous_response_not_found")
        yield  # pragma: no cover

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    with pytest.raises(ResponsesWebSocketTransportError, match="previous_response_not_found") as exc_info:
        adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert calls == [True, False]
    assert exc_info.value.code == "previous_response_not_found"
    assert exc_info.value.retriable is True


def test_stream_completion_emits_error_after_transport_retries_exhausted(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(
        ai,
        session=ResponsesWebSocketSession(mode="inherit"),
        max_transport_retries=2,
        retry_initial_delay=0,
    )
    calls = []

    def fake_stream(messages, kwargs, include_prev=True):
        calls.append(len(calls) + 1)
        raise ResponsesWebSocketTransportError(
            "opening handshake timed out",
            code="socket_open_timeout",
            retriable=True,
            details={"phase": "opening_handshake"},
        )
        yield  # pragma: no cover

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    events = list(adapter.stream_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1"))

    assert calls == [1, 2, 3]
    assert events[-1].type == "error"
    assert events[-1].data["error"]["code"] == "socket_open_timeout"
    assert events[-1].data["error"]["details"] == {"phase": "opening_handshake"}


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

    def fake_stream(messages, kwargs, include_prev=True):
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

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "hello"
    assert result.metadata["response_id"] == "resp_1"


def test_create_completion_uses_terminal_response_payload_for_rich_output(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, kwargs, include_prev=True):
        yield SimpleNamespace(
            type="completed",
            index=0,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {"total_tokens": 5},
                    "response_text": "hello",
                    "metadata": {
                        "response_id": "resp_1",
                        "response": {
                            "id": "resp_1",
                            "status": "completed",
                            "model": "gpt-4.1",
                            "usage": {"total_tokens": 5},
                            "output": [
                                {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {"type": "output_text", "text": "hello"},
                                        {"type": "reasoning", "summary": [{"text": "step"}]},
                                    ],
                                }
                            ],
                        },
                    },
                }
            },
        )

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)
    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "hello"
    assert result.message.reasoning == "step"


def test_create_completion_preserves_streamed_tool_calls(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, kwargs, include_prev=True):
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

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert len(result.message.tool_calls) == 1
    assert result.message.tool_calls[0].id == "call_1"
    assert result.message.tool_calls[0].function.name == "lookup"
    assert result.message.tool_calls[0].function.arguments == '{"q": "snack"}'


def test_create_completion_dedupes_terminal_function_call_already_reconstructed_from_stream(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, kwargs, include_prev=True):
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
                    "response_text": "hello",
                    "metadata": {
                        "response_id": "resp_1",
                        "response": {
                            "id": "resp_1",
                            "status": "completed",
                            "model": "gpt-4.1",
                            "usage": {"total_tokens": 5},
                            "output": [
                                {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {"type": "output_text", "text": "hello"},
                                        {"type": "reasoning", "summary": [{"text": "step"}]},
                                    ],
                                },
                                {
                                    "type": "function_call",
                                    "call_id": "call_1",
                                    "name": "lookup",
                                    "arguments": '{"q": "snack"}',
                                },
                            ],
                        },
                    },
                }
            },
        )

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "hello"
    assert result.message.reasoning == "step"
    assert len(result.message.tool_calls) == 1
    assert result.message.tool_calls[0].id == "call_1"
    assert result.message.tool_calls[0].function.arguments == '{"q": "snack"}'


def test_create_completion_raises_on_stream_error_event(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    def fake_stream(messages, kwargs, include_prev=True):
        yield SimpleNamespace(type="error", index=0, data={"error": {"message": "busy session", "code": "session_busy"}})

    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

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

    async def fake_stream(messages, kwargs, include_prev=True):
        yield SimpleNamespace(type="error", index=0, data={"error": {"message": "busy session", "code": "session_busy"}})

    monkeypatch.setattr(adapter, "_stream_async_request", fake_stream)

    from chatsnack.runtime.responses_websocket_adapter import ResponsesSessionBusyError
    with pytest.raises(ResponsesSessionBusyError, match="busy session"):
        await adapter.create_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")


@pytest.mark.asyncio
async def test_create_completion_a_dedupes_terminal_function_call_already_reconstructed_from_stream(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))

    async def fake_stream(messages, kwargs, include_prev=True):
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
                    "response_text": "hello",
                    "metadata": {
                        "response_id": "resp_1",
                        "response": {
                            "id": "resp_1",
                            "status": "completed",
                            "model": "gpt-4.1",
                            "usage": {"total_tokens": 5},
                            "output": [
                                {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {"type": "output_text", "text": "hello"},
                                        {"type": "reasoning", "summary": [{"text": "step"}]},
                                    ],
                                },
                                {
                                    "type": "function_call",
                                    "call_id": "call_1",
                                    "name": "lookup",
                                    "arguments": '{"q": "snack"}',
                                },
                            ],
                        },
                    },
                }
            },
        )

    monkeypatch.setattr(adapter, "_stream_async_request", fake_stream)

    result = await adapter.create_completion_a(messages=[{"role": "user", "content": "hi"}], model="gpt-4.1")

    assert result.message.content == "hello"
    assert result.message.reasoning == "step"
    assert len(result.message.tool_calls) == 1
    assert result.message.tool_calls[0].id == "call_1"
    assert result.message.tool_calls[0].function.arguments == '{"q": "snack"}'


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
    with pytest.raises(ResponsesWebSocketTransportError, match="openai>=2.29.0") as exc_info:
        adapter._connect_sync()

    assert exc_info.value.code == "sdk_unsupported"
    assert exc_info.value.retriable is False


def test_create_kwargs_strips_transport_fields():
    """_create_kwargs should remove stream and background from the request."""
    request = {"model": "gpt-4.1", "input": [], "stream": True, "background": True, "store": False}
    result = ResponsesWebSocketAdapter._create_kwargs(request)
    assert "stream" not in result
    assert "background" not in result
    assert result["model"] == "gpt-4.1"
    assert result["store"] is False


def test_create_kwargs_coerces_exact_zero_temperature_to_int_for_ws_transport():
    request = {"model": "gpt-4.1", "input": [], "temperature": 0.0}

    result = ResponsesWebSocketAdapter._create_kwargs(request)

    assert result["temperature"] == 0
    assert isinstance(result["temperature"], int)


def test_stream_sync_request_wraps_iterator_receive_failure(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)

    class SyncConnection:
        def __init__(self):
            self.response = SimpleNamespace(create=lambda **kwargs: None)

        def __iter__(self):
            return self

        def __next__(self):
            raise Exception("socket closed")

        def close(self):
            return None

    connection = SyncConnection()
    session.sync_connection = connection
    monkeypatch.setattr(adapter, "_connect_sync", lambda: connection)

    with pytest.raises(ResponsesWebSocketTransportError, match="socket_receive_failed") as exc_info:
        list(adapter._stream_sync_request(messages=[{"role": "user", "content": "hi"}], kwargs={"model": "gpt-4.1"}))

    assert exc_info.value.code == "socket_receive_failed"
    assert exc_info.value.retriable is True


def test_stream_sync_request_fails_fast_when_stream_ends_before_completed(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)

    class SyncConnection:
        def __init__(self):
            self.response = SimpleNamespace(create=lambda **kwargs: None)
            self._events = [SimpleNamespace(type="response.in_progress")]

        def __iter__(self):
            return self

        def __next__(self):
            if self._events:
                return self._events.pop(0)
            raise StopIteration

        def close(self):
            return None

    connection = SyncConnection()
    session.sync_connection = connection
    monkeypatch.setattr(adapter, "_connect_sync", lambda: connection)

    with pytest.raises(ResponsesWebSocketTransportError, match="socket_receive_failed") as exc_info:
        list(adapter._stream_sync_request(messages=[{"role": "user", "content": "hi"}], kwargs={"model": "gpt-4.1"}))

    assert exc_info.value.details["reason"] == "stream_ended_before_response_completed"


def test_stream_sync_request_logs_ws_payload_and_failure_event_when_debug_enabled(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)
    monkeypatch.setenv("CHATSNACK_DEBUG_RESPONSES", "1")

    class DumpableError:
        code = "invalid_tools"
        message = "Tool schema is invalid"

        def model_dump(self):
            return {"code": self.code, "message": self.message}

    class DumpableResponse:
        id = "resp_dbg"
        status = "failed"
        error = DumpableError()

        def model_dump(self):
            return {
                "id": self.id,
                "status": self.status,
                "error": self.error.model_dump(),
            }

    class DumpableEvent:
        type = "response.failed"
        response = DumpableResponse()

        def model_dump(self):
            return {
                "type": self.type,
                "response": self.response.model_dump(),
            }

    class SyncConnection:
        def __init__(self):
            self.response = SimpleNamespace(create=lambda **kwargs: None)
            self._events = [DumpableEvent()]

        def __iter__(self):
            return self

        def __next__(self):
            if self._events:
                return self._events.pop(0)
            raise StopIteration

        def close(self):
            return None

    connection = SyncConnection()
    session.sync_connection = connection
    monkeypatch.setattr(adapter, "_connect_sync", lambda: connection)

    with _capture_loguru() as sink:
        with pytest.raises(ResponsesWebSocketTransportError, match="Tool schema is invalid"):
            list(
                adapter._stream_sync_request(
                    messages=[{"role": "user", "content": "hi"}],
                    kwargs={"model": "gpt-4.1", "tools": [{"type": "function", "name": "lookup", "description": "d"}]},
                )
            )

    output = sink.getvalue()
    assert "Responses WS response.create payload" in output
    assert "Responses WS failure event" in output
    assert '"type": "response.failed"' in output
    assert '"code": "invalid_tools"' in output


@pytest.mark.asyncio
async def test_stream_async_request_wraps_iterator_receive_failure(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)

    class AsyncConnection:
        def __init__(self):
            async def create(**kwargs):
                return None
            self.response = SimpleNamespace(create=create)

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise Exception("socket closed")

        async def close(self):
            return None

    connection = AsyncConnection()
    session.async_connection = connection

    async def connect_async():
        return connection

    monkeypatch.setattr(adapter, "_connect_async", connect_async)

    with pytest.raises(ResponsesWebSocketTransportError, match="socket_receive_failed") as exc_info:
        events = [event async for event in adapter._stream_async_request(messages=[{"role": "user", "content": "hi"}], kwargs={"model": "gpt-4.1"})]
        assert events == []

    assert exc_info.value.code == "socket_receive_failed"
    assert exc_info.value.retriable is True


@pytest.mark.asyncio
async def test_stream_async_request_fails_fast_when_stream_ends_before_completed(monkeypatch):
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)

    class AsyncConnection:
        def __init__(self):
            async def create(**kwargs):
                return None
            self.response = SimpleNamespace(create=create)
            self._events = [SimpleNamespace(type="response.in_progress")]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._events:
                return self._events.pop(0)
            raise StopAsyncIteration

        async def close(self):
            return None

    connection = AsyncConnection()
    session.async_connection = connection

    async def connect_async():
        return connection

    monkeypatch.setattr(adapter, "_connect_async", connect_async)

    with pytest.raises(ResponsesWebSocketTransportError, match="socket_receive_failed") as exc_info:
        events = [event async for event in adapter._stream_async_request(messages=[{"role": "user", "content": "hi"}], kwargs={"model": "gpt-4.1"})]
        assert events == []

    assert exc_info.value.details["reason"] == "stream_ended_before_response_completed"


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


def test_stream_completion_resolves_attachment_paths_before_sync_stream_request(monkeypatch):
    """WebSocket sync path should resolve local attachments before streaming."""
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    original_messages = [{"role": "user", "content": "", "files": [{"path": "./data.csv"}]}]
    resolved_messages = [{"role": "user", "content": "", "files": [{"file_id": "file_uploaded"}]}]
    seen = {}

    def fake_resolve(messages):
        seen["resolved_from"] = messages
        return resolved_messages

    def fake_stream(messages, kwargs, include_prev=True):
        seen["stream_messages"] = messages
        yield RuntimeStreamEvent(
            type="completed",
            index=0,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {},
                    "response_text": "",
                    "metadata": {"response_id": "resp_ws_attach"},
                }
            },
        )

    monkeypatch.setattr(adapter.attachment_resolver, "resolve_messages", fake_resolve)
    monkeypatch.setattr(adapter, "_stream_sync_request", fake_stream)

    events = list(adapter.stream_completion(messages=original_messages, model="gpt-4.1"))

    assert events[0].type == "completed"
    assert seen["resolved_from"] == original_messages
    assert seen["stream_messages"] == resolved_messages


@pytest.mark.asyncio
async def test_stream_completion_a_resolves_attachment_paths_before_async_stream_request(monkeypatch):
    """WebSocket async path should resolve local attachments before streaming."""
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    original_messages = [{"role": "user", "content": "", "images": [{"path": "./photo.png"}]}]
    resolved_messages = [{"role": "user", "content": "", "images": [{"file_id": "file_img_uploaded"}]}]
    seen = {}

    async def fake_resolve(messages):
        seen["resolved_from"] = messages
        return resolved_messages

    async def fake_stream(messages, kwargs, include_prev=True):
        seen["stream_messages"] = messages
        yield RuntimeStreamEvent(
            type="completed",
            index=0,
            data={
                "terminal": {
                    "finish_reason": "completed",
                    "model": "gpt-4.1",
                    "usage": {},
                    "response_text": "",
                    "metadata": {"response_id": "resp_ws_attach_async"},
                }
            },
        )

    monkeypatch.setattr(adapter.attachment_resolver, "resolve_messages_async", fake_resolve)
    monkeypatch.setattr(adapter, "_stream_async_request", fake_stream)

    events = [event async for event in adapter.stream_completion_a(messages=original_messages, model="gpt-4.1")]

    assert events[0].type == "completed"
    assert seen["resolved_from"] == original_messages
    assert seen["stream_messages"] == resolved_messages


def test_request_with_session_keeps_attachment_only_turn_for_continuation():
    """Continuation requests should keep attachment-only suffix turns on the WebSocket path."""
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    adapter = ResponsesWebSocketAdapter(ai, session=ResponsesWebSocketSession(mode="inherit"))
    adapter.session.last_response_id = "resp_prev"

    request = adapter._request_with_session(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "", "files": [{"file_id": "file_abc"}]},
        ],
        {"model": "gpt-4.1"},
        include_prev=True,
    )

    assert request["previous_response_id"] == "resp_prev"
    assert len(request["input"]) == 1
    assert request["input"][0]["role"] == "user"
    assert request["input"][0]["content"] == [{"type": "input_file", "file_id": "file_abc"}]


def test_stream_sync_request_passes_provider_native_tools_unchanged(monkeypatch):
    """WebSocket create kwargs should keep provider-native tools unchanged."""
    ai = SimpleNamespace(api_key="x", base_url=None, client=None, aclient=None)
    session = ResponsesWebSocketSession(mode="inherit")
    adapter = ResponsesWebSocketAdapter(ai, session=session)
    captured = {}

    class ResponsePayload:
        output_text = ""

        def model_dump(self):
            return {"id": "resp_tools_ws", "status": "completed", "model": "gpt-4.1", "usage": None}

    class SyncConnection:
        def __init__(self):
            self.response = SimpleNamespace(create=self._create)
            self._events = [SimpleNamespace(type="response.completed", response=ResponsePayload())]

        def _create(self, **kwargs):
            captured.update(kwargs)
            return None

        def __iter__(self):
            return self

        def __next__(self):
            if self._events:
                return self._events.pop(0)
            raise StopIteration

        def close(self):
            return None

    connection = SyncConnection()
    session.sync_connection = connection
    monkeypatch.setattr(adapter, "_connect_sync", lambda: connection)

    events = list(
        adapter._stream_sync_request(
            messages=[{"role": "user", "content": "search"}],
            kwargs={"model": "gpt-4.1", "tools": [{"type": "web_search"}]},
        )
    )

    assert events[-1].type == "completed"
    assert captured["tools"] == [{"type": "web_search"}]
