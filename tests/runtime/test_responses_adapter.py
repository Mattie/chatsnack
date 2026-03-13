from types import SimpleNamespace

from chatsnack.runtime import ResponsesAdapter


class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


def test_maps_compiled_messages_to_responses_input_items_and_defaults_store_false():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_1", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[
            {"role": "developer", "content": "rules"},
            {
                "role": "assistant",
                "content": None,
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

    assert captured["store"] is False
    assert captured["input"][0] == {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": "rules"}],
    }
    assert captured["input"][1]["type"] == "function_call"
    assert captured["input"][1]["call_id"] == "call_1"
    assert captured["input"][2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "tool result",
    }


def test_normalizes_response_text_tool_calls_and_runtime_metadata():
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

    ai = SimpleNamespace(
        client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: response))
    )
    adapter = ResponsesAdapter(ai)

    result = adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        model="gpt-4.1",
        previous_response_id="resp_prev",
    )

    assert result.message.content == "Done."
    assert result.message.tool_calls[0].id == "call_99"
    assert result.metadata["response_id"] == "resp_abc"
    assert result.metadata["previous_response_id"] == "resp_prev"
    assert result.metadata["assistant_phase"] == "completed"
    assert result.usage == {"total_tokens": 12}


def test_profile_defaults_and_model_specific_options_are_applied():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_2", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4.1",
        profile={
            "defaults": {"temperature": 0.1, "store": False},
            "model_defaults": {"gpt-4.1": {"reasoning": {"effort": "medium"}}},
        },
    )

    assert captured["temperature"] == 0.1
    assert captured["reasoning"] == {"effort": "medium"}
    assert captured["store"] is False


def test_assistant_history_message_is_encoded_as_input_text():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({"id": "resp_3", "status": "completed", "model": "gpt-4.1", "output": []})

    ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    adapter = ResponsesAdapter(ai)

    adapter.create_completion(
        messages=[
            {"role": "assistant", "content": "Prior answer."},
            {"role": "user", "content": "Follow up?"},
        ],
        model="gpt-4.1",
    )

    assert captured["input"][0] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "input_text", "text": "Prior answer."}],
    }
