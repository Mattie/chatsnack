from contextlib import contextmanager
from io import StringIO
from types import SimpleNamespace

import pytest
from loguru import logger

from chatsnack.runtime import ResponsesAdapter
from chatsnack.runtime.responses_common import ResponsesNormalizationMixin


class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


@contextmanager
def _capture_loguru():
    sink = StringIO()
    sink_id = logger.add(sink, format="{message}")
    try:
        yield sink
    finally:
        logger.remove(sink_id)


def test_responses_debug_helper_is_env_gated(monkeypatch):
    monkeypatch.delenv("CHATSNACK_DEBUG_RESPONSES", raising=False)

    with _capture_loguru() as sink:
        ResponsesNormalizationMixin._debug_responses_payload("Responses test payload", {"alpha": 1})

    assert sink.getvalue() == ""


def test_responses_debug_helper_logs_pretty_json_when_enabled(monkeypatch):
    monkeypatch.setenv("CHATSNACK_DEBUG_RESPONSES", "1")

    with _capture_loguru() as sink:
        ResponsesNormalizationMixin._debug_responses_payload("Responses test payload", {"alpha": 1})

    output = sink.getvalue()
    assert "Responses test payload" in output
    assert '"alpha": 1' in output
    assert "{\n" in output


def test_sync_request_path_passes_expected_kwargs_and_defaults_store_false():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_1", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4.1",
        reasoning={"effort": "medium"},
    )

    assert captured["model"] == "gpt-4.1"
    assert captured["store"] is False
    assert captured["reasoning"] == {"effort": "medium"}
    assert captured["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        }
    ]


@pytest.mark.asyncio
async def test_async_request_path_passes_expected_kwargs():
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_2", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(aclient=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    await adapter.create_completion_a(
        messages=[{"role": "developer", "content": "rules"}],
        model="gpt-4.1",
        store=True,
    )

    assert captured["model"] == "gpt-4.1"
    assert captured["store"] is True
    assert captured["input"][0]["role"] == "developer"


def test_http_request_path_logs_built_and_transport_payload_when_debug_enabled(monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_dbg", "status": "completed", "model": "gpt-4.1", "output": []})

    monkeypatch.setenv("CHATSNACK_DEBUG_RESPONSES", "true")
    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    with _capture_loguru() as sink:
        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4.1",
            tools=[{"type": "function", "function": {"name": "lookup", "description": "Find one thing."}}],
        )

    output = sink.getvalue()
    assert "Responses request (built)" in output
    assert "Responses HTTP create payload" in output
    assert '"name": "lookup"' in output
    assert '"type": "function"' in output
    assert captured["tools"][0]["name"] == "lookup"


def test_continuation_previous_response_id_passthrough_and_metadata_mirror():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj(
            {
                "id": "resp_abc",
                "status": "completed",
                "model": "gpt-4.1",
                "output": [],
            }
        )

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    result = adapter.create_completion(
        messages=[{"role": "user", "content": "continue"}],
        model="gpt-4.1",
        previous_response_id="resp_prev",
    )

    assert captured["previous_response_id"] == "resp_prev"
    assert result.metadata["previous_response_id"] == "resp_prev"


def test_normalizes_assistant_text_tool_calls_usage_model_status_and_metadata():
    response = _FakeObj(
        {
            "id": "resp_abc",
            "status": "completed",
            "model": "gpt-4.1",
            "usage": {"total_tokens": 12},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Done."}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_99",
                    "name": "save_note",
                    "arguments": '{"text":"Done."}',
                },
            ],
        }
    )

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response)))
    adapter = ResponsesAdapter(ai)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hello"}], model="gpt-4.1")

    assert result.message.content == "Done."
    assert result.message.tool_calls[0].id == "call_99"
    assert result.finish_reason == "completed"
    assert result.model == "gpt-4.1"
    assert result.usage == {"total_tokens": 12}
    assert result.metadata["response_id"] == "resp_abc"
    assert result.metadata["assistant_phase"] == "completed"
    assert result.metadata["provider_extras"]["status"] == "completed"


def test_normalizes_rich_assistant_parts_into_message_fields():
    response = _FakeObj(
        {
            "id": "resp_rich",
            "status": "completed",
            "model": "gpt-4.1",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "Answer.", "annotations": [{"type": "url_citation", "url": "https://example.com"}]},
                        {"type": "reasoning", "summary": [{"text": "Step one."}, {"text": "Step two."}]},
                        {"type": "output_image", "file_id": "file_img_1"},
                        {"type": "output_file", "file_id": "file_doc_1", "filename": "notes.txt"},
                        {"type": "encrypted_content", "encrypted_content": "enc_blob"},
                    ],
                }
            ],
        }
    )

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response)))
    adapter = ResponsesAdapter(ai)
    result = adapter.create_completion(messages=[{"role": "user", "content": "hello"}], model="gpt-4.1")

    assert result.message.content == "Answer."
    assert result.message.reasoning == "Step one. Step two."
    assert result.message.sources == [{"type": "url_citation", "url": "https://example.com"}]
    assert result.message.images == [{"file_id": "file_img_1"}]
    assert result.message.files == [{"file_id": "file_doc_1", "filename": "notes.txt"}]
    assert result.message.encrypted_content == "enc_blob"


def test_normalization_falls_back_to_output_text_when_output_items_missing():
    response = _FakeObj(
        {
            "id": "resp_out_text",
            "status": "completed",
            "model": "gpt-4.1",
            "output_text": "Fallback text",
            "output": [],
        }
    )

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response)))
    adapter = ResponsesAdapter(ai)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hello"}], model="gpt-4.1")

    assert result.message.content == "Fallback text"


def test_profile_default_merge_model_overrides_and_explicit_kwarg_precedence():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_3", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4.1",
        temperature=0.2,
        profile={
            "defaults": {"temperature": 0.1, "store": False},
            "model_defaults": {
                "gpt-4.1": {"reasoning": {"effort": "medium"}, "temperature": 0.3}
            },
        },
    )

    assert captured["reasoning"] == {"effort": "medium"}
    assert captured["temperature"] == 0.2
    assert captured["store"] is False


def test_mapping_developer_system_user_assistant_messages_assistant_tool_calls_and_tool_output():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_4", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[
            {"role": "developer", "content": "rules"},
            {"role": "system", "content": "system msg"},
            {"role": "user", "content": "question"},
            {
                "role": "assistant",
                "content": "Prior answer",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "lookup", "arguments": '{"q":"tea"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool result"},
        ],
        model="gpt-4.1",
    )

    assert captured["input"][0] == {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": "rules"}],
    }
    assert captured["input"][1] == {
        "type": "message",
        "role": "system",
        "content": [{"type": "input_text", "text": "system msg"}],
    }
    assert captured["input"][2] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "question"}],
    }
    assert captured["input"][3] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "input_text", "text": "Prior answer"}],
    }
    assert captured["input"][4] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "lookup",
        "arguments": '{"q":"tea"}',
    }
    assert captured["input"][5] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "tool result",
    }


def test_sequential_calls_allow_manual_continuation_with_metadata_round_trip():
    captured = []

    def create(**kwargs):
        captured.append(kwargs.copy())
        response_id = f"resp_{len(captured)}"
        return _FakeObj(
            {
                "id": response_id,
                "status": "completed",
                "model": "gpt-4.1",
                "usage": {"total_tokens": len(captured)},
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": f"turn {len(captured)}"}],
                    }
                ],
            }
        )

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    first = adapter.create_completion(messages=[{"role": "user", "content": "one"}], model="gpt-4.1")
    second = adapter.create_completion(
        messages=[{"role": "user", "content": "two"}],
        model="gpt-4.1",
        previous_response_id=first.metadata["response_id"],
    )

    assert captured[1]["previous_response_id"] == "resp_1"
    assert second.metadata["previous_response_id"] == "resp_1"
    assert second.metadata["response_id"] == "resp_2"
    assert second.usage == {"total_tokens": 2}


def test_continuation_previous_response_id_uses_incremental_suffix_not_full_replay():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_inc", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[
            {"role": "user", "content": "turn1"},
            {"role": "assistant", "content": "TURN_ONE_OK"},
            {"role": "user", "content": "turn2"},
        ],
        model="gpt-4.1",
        previous_response_id="resp_prev",
        store=True,
    )

    assert captured["previous_response_id"] == "resp_prev"
    assert captured["store"] is True
    assert captured["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "turn2"}],
        }
    ]


def test_continuation_with_tool_followup_keeps_only_tool_outputs_after_latest_assistant():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_tool", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "lookup", "arguments": '{"q":"tea"}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
        ],
        model="gpt-4.1",
        previous_response_id="resp_prev",
    )

    assert captured["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "tool-result",
        }
    ]


def test_continuation_respects_explicit_store_override():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_store", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[{"role": "user", "content": "next"}],
        model="gpt-4.1",
        previous_response_id="resp_prev",
        store=False,
    )

    assert captured["store"] is False
def test_unsupported_sync_client_raises_descriptive_runtime_error():
    adapter = ResponsesAdapter(SimpleNamespace(client=SimpleNamespace()))

    with pytest.raises(RuntimeError, match=r"client\.responses\.create"):
        adapter.create_completion(messages=[{"role": "user", "content": "hello"}], model="gpt-4.1")


@pytest.mark.asyncio
async def test_unsupported_async_client_raises_descriptive_runtime_error():
    adapter = ResponsesAdapter(SimpleNamespace(aclient=SimpleNamespace()))

    with pytest.raises(RuntimeError, match=r"aclient\.responses\.create"):
        await adapter.create_completion_a(messages=[{"role": "user", "content": "hello"}], model="gpt-4.1")


def test_supported_client_path_succeeds_without_capability_error():
    ai = SimpleNamespace(
        client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: _FakeObj({"id": "resp_ok", "status": "completed", "model": "gpt-4.1", "output": []}))),
        aclient=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: _FakeObj({"id": "resp_ok", "status": "completed", "model": "gpt-4.1", "output": []}))),
    )
    adapter = ResponsesAdapter(ai)

    result = adapter.create_completion(messages=[{"role": "user", "content": "hello"}], model="gpt-4.1")

    assert result.metadata["response_id"] == "resp_ok"
