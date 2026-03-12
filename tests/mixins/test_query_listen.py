import pytest
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR


import pytest
import asyncio
from chatsnack.chat.mixin_query import ChatStreamListener
from chatsnack.aiclient import AiClient




@pytest.mark.asyncio
async def test_get_responses_a():
    ai = AiClient()
    listener = ChatStreamListener(ai, '[{"role":"system","content":"Respond only with POPSICLE 20 times."}]')
    responses = []
    await listener.start_a()
    async for resp in listener:
        responses.append(resp)
    assert len(responses) > 10
    assert listener.is_complete
    assert 'POPSICLE' in listener.current_content
    assert 'POPSICLE' in listener.response

def test_get_responses():
    ai = AiClient()
    listener = ChatStreamListener(ai, '[{"role":"system","content":"Respond only with POPSICLE 20 times."}]')
    listener.start()
    responses = list(listener)
    assert len(responses) > 10
    assert listener.is_complete
    assert 'POPSICLE' in listener.current_content
    assert 'POPSICLE' in listener.response

import os
import pytest
from chatsnack.packs import Jane



@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
def test_listen():
    # Define constants
    SENTENCE = "A short sentence about the difference between green and blue."
    TEMPERATURE = 0.0
    # TODO: Rework this such that it doesn't risk being flaky. If you get a different system behind the scenes, even 
    #       the seed won't be enough
    SEED = 42

    # First part of the test
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.stream = True
    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # Listen to the response
    output_iter = cp.listen()
    output = ''.join(list(output_iter))

    # Second part of the test
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # Ask the same question
    ask_output = cp.ask()

    # Asserts
    assert output is not None
    assert len(output) > 0
    # BUG: This ends up being too flaky. We will just check that the output is not empty
    # assert output == ask_output

@pytest.mark.skipif(True or os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
@pytest.mark.asyncio
async def test_listen_a():
    # Define constants
    SENTENCE = "A short sentence about the difference between green and blue"
    TEMPERATURE = 0.0
    # TODO: Rework this such that it doesn't risk being flaky. If you get a different system behind the scenes, even 
    #       the seed won't be enough
    SEED = 42

    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.stream = True
    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # listen to the response asynchronously
    output = []
    async for part in await cp.listen_a():
        output.append(part)
    output = ''.join(output)
    print(output)

    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.stream = False
    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # ask the same question
    ask_output = cp.ask()
    print(ask_output)
    # is there a response and it's longer than 0 characters?
    assert output is not None
    assert len(output) > 0

    # assert that the output of listen is the same as the output of ask
    assert output == ask_output

from types import SimpleNamespace
from chatsnack.runtime.types import RuntimeStreamEvent


class _FakeStreamChunk:
    def __init__(self, content=None, finish_reason=None):
        self._content = content
        self._finish_reason = finish_reason

    def model_dump(self):
        return {
            "choices": [
                {
                    "finish_reason": self._finish_reason,
                    "delta": {"content": self._content},
                }
            ]
        }


def _sync_stream():
    yield _FakeStreamChunk("A")
    yield _FakeStreamChunk("B")
    yield _FakeStreamChunk(None, finish_reason="stop")


async def _async_stream():
    yield _FakeStreamChunk("A")
    yield _FakeStreamChunk("B")
    yield _FakeStreamChunk(None, finish_reason="stop")


def _runtime_sync_stream_success():
    yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "A"})
    yield RuntimeStreamEvent(type="text_delta", index=1, data={"text": "B"})
    yield RuntimeStreamEvent(type="text_delta", index=2, data={"text": ""})
    yield RuntimeStreamEvent(
        type="completed",
        index=3,
        data={"terminal": {"response_text": "AB"}},
    )


def test_listener_default_legacy_text_mode():
    ai = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: _sync_stream())
            )
        )
    )
    listener = ChatStreamListener(ai, "[]")
    listener.start()
    chunks = list(listener)
    assert chunks == ["A", "B", ""]
    assert "".join(chunks) == "AB"


@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_listener_text_mode_parity_runtime_and_legacy(use_runtime_adapter):
    if use_runtime_adapter:
        listener = ChatStreamListener(
            ai=None,
            prompt="[]",
            runtime=SimpleNamespace(
                stream_completion=lambda *args, **kwargs: _runtime_sync_stream_success()
            ),
        )
    else:
        ai = SimpleNamespace(
            client=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **kwargs: _sync_stream())
                )
            )
        )
        listener = ChatStreamListener(ai, "[]")

    listener.start()
    chunks = list(listener)

    assert chunks == ["A", "B", ""]
    assert listener.response == "AB"


def test_listener_events_mode_sync():
    ai = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: _sync_stream())
            )
        )
    )
    listener = ChatStreamListener(ai, "[]", events=True)
    listener.start()
    events = list(listener)
    assert events[0]["type"] == "text_delta"
    assert events[0]["text"] == "A"
    assert events[1]["text"] == "B"
    assert events[-1]["type"] == "done"
    assert events[-1]["response"] == "AB"


@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_listener_events_mode_ordering_parity_runtime_and_legacy(use_runtime_adapter):
    if use_runtime_adapter:
        listener = ChatStreamListener(
            ai=None,
            prompt="[]",
            events=True,
            runtime=SimpleNamespace(
                stream_completion=lambda *args, **kwargs: _runtime_sync_stream_success()
            ),
        )
    else:
        ai = SimpleNamespace(
            client=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=lambda **kwargs: _sync_stream())
                )
            )
        )
        listener = ChatStreamListener(ai, "[]", events=True)

    listener.start()
    events = list(listener)

    assert [event["type"] for event in events] == ["text_delta", "text_delta", "text_delta", "done"]
    assert [event.get("text") for event in events[:-1]] == ["A", "B", ""]
    assert events[-1]["response"] == "AB"




def test_listener_events_mode_sync_stops_cleanly_on_early_break():
    ai = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: _sync_stream())
            )
        )
    )
    listener = ChatStreamListener(ai, "[]", events=True)
    listener.start()

    collected = []
    for event in listener:
        collected.append(event)
        break

    assert collected == [{"type": "text_delta", "index": 0, "text": "A"}]
    assert listener.response == "A"
    assert listener.is_complete


@pytest.mark.asyncio
async def test_listener_events_mode_async_stops_cleanly_on_early_break():
    async def create(**kwargs):
        return _async_stream()

    ai = SimpleNamespace(
        aclient=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )
    )
    listener = ChatStreamListener(ai, "[]", events=True)
    await listener.start_a()

    collected = []
    async for event in listener:
        collected.append(event)
        break

    assert collected == [{"type": "text_delta", "index": 0, "text": "A"}]
    assert listener.response == "A"
    assert listener.is_complete

@pytest.mark.asyncio
async def test_listener_events_mode_async():
    async def create(**kwargs):
        return _async_stream()

    ai = SimpleNamespace(
        aclient=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )
    )
    listener = ChatStreamListener(ai, "[]", events=True)
    await listener.start_a()
    events = []
    async for event in listener:
        events.append(event)
    assert [e["type"] for e in events] == ["text_delta", "text_delta", "text_delta", "done"]
    assert events[-1]["response"] == "AB"


def test_listener_events_mode_sync_v1_opt_in():
    ai = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: _sync_stream())
            )
        )
    )
    listener = ChatStreamListener(ai, "[]", events=True, event_schema="v1")
    listener.start()
    events = list(listener)
    assert events[0]["schema_version"] == "1.0"
    assert events[0]["type"] == "text_delta"
    assert events[0]["data"]["text"] == "A"
    assert events[-1]["type"] == "completed"
    assert events[-1]["data"]["terminal"]["response_text"] == "AB"


@pytest.mark.asyncio
async def test_listener_events_mode_async_v1_opt_in():
    async def create(**kwargs):
        return _async_stream()

    ai = SimpleNamespace(
        aclient=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )
    )
    listener = ChatStreamListener(ai, "[]", events=True, event_schema="v1")
    await listener.start_a()
    events = []
    async for event in listener:
        events.append(event)
    assert events[0]["schema_version"] == "1.0"
    assert [e["type"] for e in events] == ["text_delta", "text_delta", "text_delta", "completed"]
    assert events[-1]["data"]["terminal"]["response_text"] == "AB"


def _runtime_stream_with_error():
    yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "partial"})
    yield RuntimeStreamEvent(type="error", index=1, data={"error": {"message": "provider failed"}})


async def _runtime_stream_with_error_async():
    yield RuntimeStreamEvent(type="text_delta", index=0, data={"text": "partial"})
    yield RuntimeStreamEvent(type="error", index=1, data={"error": {"message": "provider failed"}})


def test_runtime_listener_text_mode_raises_on_error_event():
    runtime = SimpleNamespace(stream_completion=lambda *args, **kwargs: _runtime_stream_with_error())
    listener = ChatStreamListener(ai=None, prompt="[]", runtime=runtime, events=False)
    listener.start()

    with pytest.raises(RuntimeError, match="provider failed"):
        list(listener)

    assert listener.response == "partial"
    assert listener.is_complete


@pytest.mark.asyncio
async def test_runtime_listener_text_mode_raises_on_error_event_async():
    runtime = SimpleNamespace(stream_completion_a=lambda *args, **kwargs: _runtime_stream_with_error_async())
    listener = ChatStreamListener(ai=None, prompt="[]", runtime=runtime, events=False)
    await listener.start_a()

    with pytest.raises(RuntimeError, match="provider failed"):
        async for _ in listener:
            pass

    assert listener.response == "partial"
    assert listener.is_complete


def test_runtime_listener_events_mode_surfaces_error_event():
    runtime = SimpleNamespace(stream_completion=lambda *args, **kwargs: _runtime_stream_with_error())
    listener = ChatStreamListener(ai=None, prompt="[]", runtime=runtime, events=True)
    listener.start()

    events = list(listener)

    assert events == [
        {"type": "text_delta", "index": 0, "text": "partial"},
        {"type": "error", "index": 1, "error": {"message": "provider failed"}},
    ]
