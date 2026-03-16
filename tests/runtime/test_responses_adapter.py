from types import SimpleNamespace

import pytest

from chatsnack.runtime import ResponsesAdapter


class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


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
