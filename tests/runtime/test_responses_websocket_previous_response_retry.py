from types import SimpleNamespace

import pytest

from chatsnack.runtime.responses_websocket_adapter import (
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
)


class _FakeErrorEvent:
    type = "error"

    def model_dump(self):
        return {
            "type": "error",
            "status": 400,
            "error": {
                "code": "previous_response_not_found",
                "message": "Previous response was not found.",
                "param": "previous_response_id",
                "type": "invalid_request_error",
            },
        }


class _FakeCompletedResponse:
    output_text = "done"

    def model_dump(self):
        return {
            "id": "resp_new",
            "status": "completed",
            "model": "gpt-5.4",
            "usage": None,
            "output_text": "done",
        }


class _FakeCompletedEvent:
    type = "response.completed"
    response = _FakeCompletedResponse()


class _FakeAsyncConnection:
    def __init__(self):
        self.calls = []
        self.attempt = 0
        self.response = SimpleNamespace(create=self.create)
        self._emitted = False

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        self.attempt += 1
        self._emitted = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._emitted:
            raise StopAsyncIteration
        self._emitted = True
        if self.attempt == 1:
            return _FakeErrorEvent()
        if self.attempt == 2:
            return _FakeCompletedEvent()
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_stream_completion_a_retries_previous_response_not_found_with_full_context(monkeypatch):
    session = ResponsesWebSocketSession(mode="inherit")
    session.last_response_id = "resp_prev"
    adapter = ResponsesWebSocketAdapter(SimpleNamespace(), session=session)
    connection = _FakeAsyncConnection()

    async def fake_connect_async():
        return connection

    monkeypatch.setattr(adapter, "_connect_async", fake_connect_async)

    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "FIRST"},
        {"role": "user", "content": "second"},
    ]

    events = []
    async for event in adapter.stream_completion_a(messages, model="gpt-5.4", store=False):
        events.append(event)

    assert [event.type for event in events] == ["completed"]
    assert connection.calls[0]["previous_response_id"] == "resp_prev"
    assert len(connection.calls[0]["input"]) == 1
    assert "previous_response_id" not in connection.calls[1]
    assert len(connection.calls[1]["input"]) == 3
    assert session.last_response_id == "resp_new"
