"""Goal: ordinary saved Chats retain the provider conversation used to continue."""

import json

import httpx
import openai
import pytest

from chatsnack import Chat, Text, utensil
from chatsnack.runtime.conversation import item_to_message
from chatsnack.runtime import ResponsesAdapter
from types import SimpleNamespace
from ruamel.yaml import YAML


@pytest.mark.parametrize("loaded", [False, True])
@pytest.mark.parametrize("metadata", [{"refusal": "blocked"}, {"provider_extras": {"future": None}}])
def test_imported_null_assistant_preserves_metadata_without_inventing_text(tmp_path, loaded, metadata):
    """Null dialogue stays separate from metadata and recorded refusal content."""
    from chatsnack.runtime.conversation import project_chat_completions
    chat = Chat()
    chat.add_messages_json(json.dumps([{"role": "assistant", "content": None, **metadata}]))
    if loaded:
        path = tmp_path / "refusal.yml"
        chat.save(str(path))
        chat = Chat()
        chat.load(str(path))
    before = json.loads(chat.json)
    assert chat.get_messages()[0]["content"] is None
    assert chat.response is None
    if loaded or "provider_extras" in metadata:
        with pytest.warns(UserWarning, match="provider-only history"):
            projected = project_chat_completions(chat.get_messages())
    else:
        projected = project_chat_completions(chat.get_messages())
    expected_cc = {"role": "assistant", "content": None}
    if "refusal" in metadata:
        expected_cc["refusal"] = "blocked"
    assert projected == [expected_cc]
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(chat.get_messages(), {})
    assert replay["input"][0]["content"] == ([{"type": "refusal", "refusal": "blocked"}] if "refusal" in metadata else [])
    if "provider_extras" in metadata:
        assert replay["input"][0]["future"] is None
    assert json.loads(chat.json) == before


@pytest.mark.parametrize("loaded", [False, True])
@pytest.mark.parametrize("refusal", [None, "blocked"])
def test_imported_assistant_text_and_refusal_use_responses_content_parts(tmp_path, loaded, refusal):
    """CC refusal metadata never leaks as an unsupported Responses item field."""
    chat = Chat()
    chat.add_messages_json(json.dumps([{"role": "assistant", "content": "Hello", "refusal": refusal}]))
    if loaded:
        path = tmp_path / "text-and-refusal.yml"
        chat.save(str(path))
        chat = Chat()
        chat.load(str(path))
    original = json.loads(chat.json)
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(chat.get_messages(), {})
    message = replay["input"][0]
    assert "refusal" not in message
    expected = [{"type": "output_text", "text": "Hello", "annotations": []}]
    if refusal is not None:
        expected.append({"type": "refusal", "refusal": refusal})
    assert message["content"] == expected
    assert json.loads(chat.json) == original


@pytest.mark.parametrize("role", ["user", "system", "developer"])
def test_legacy_dialogue_metadata_survives_responses_replay(tmp_path, role):
    """Imported dialogue keeps unknown wire fields beside explicit provider extras."""
    item = {"role": role, "content": "Hello", "future": {"nullable": None},
            "provider_extras": {"other": [], "future": "overridden"}}
    chat = Chat()
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "dialogue-extras.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    original = json.loads(restored.json)
    request = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert request["input"] == [{"type": "message", "role": "system" if role == "developer" else role,
        "content": [{"type": "input_text", "text": "Hello"}],
        "future": {"nullable": None}, "other": []}]
    assert json.loads(restored.json) == original


def test_imported_bare_null_assistant_stays_null(tmp_path):
    """Legacy null dialogue remains null when there is no metadata to expand."""
    item = {"role": "assistant", "content": None}
    chat = Chat()
    chat.add_messages_json(json.dumps([item]))
    assert chat.get_messages() == [item]
    path = tmp_path / "null-assistant.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    assert restored.get_messages() == [item]


@pytest.mark.parametrize("role", ["system", "developer"])
def test_markdown_retains_opaque_instruction_once(tmp_path, role):
    """Opaque instructions are displayed with their role, outside the canonical directive."""
    item = {"type": "message", "role": role,
            "content": [{"type": "input_text", "text": "Imported rules"}]}
    chat = Chat("Canonical rules")
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "instructions.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    markdown = restored.generate_markdown()
    assert restored.system_message == "Canonical rules"
    assert markdown.count("Imported rules") == 1
    assert markdown.count("Canonical rules") == 1
    assert f"**{role.capitalize()}:**" in markdown


def test_legacy_function_call_metadata_survives_responses_replay(tmp_path):
    """Unknown call metadata survives the legacy nested-function representation."""
    item = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "future": {"nullable": None},
         "provider_extras": {"other": [], "future": "overridden"},
         "function": {"name": "stock", "arguments": "{}"}}]}
    chat = Chat()
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "call-extras.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    original = json.loads(restored.json)
    request = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert request["input"] == [{"type": "function_call", "call_id": "call_1", "name": "stock",
        "arguments": "{}", "future": {"nullable": None}, "other": []}]
    assert json.loads(restored.json) == original


@pytest.mark.parametrize("output_type", [None, "apply_patch_call_output", "tool_search_output"])
def test_legacy_tool_metadata_survives_responses_replay(tmp_path, output_type):
    """Top-level imported metadata and explicit extras both survive tool replay."""
    item = {"role": "tool", "tool_call_id": "call_1", "content": "literal {output}",
            "future": {"nullable": None}, "provider_extras": {"other": [], "future": "overridden"}}
    if output_type:
        item.update(output_type=output_type, status="completed")
    chat = Chat()
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "tool.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    assert restored.get_messages() == [item]
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    expected = {"type": output_type or "function_call_output", "output": "literal {output}",
                "future": {"nullable": None}, "other": []}
    expected["tool_call_id" if output_type == "tool_search_output" else "call_id"] = "call_1"
    if output_type:
        expected["status"] = "completed"
    assert replay["input"] == [expected]
    assert restored.get_messages() == [item]


@pytest.mark.parametrize("content", [None, "", {"future": "content"}, [],
    [{"type": "output_text", "text": "stale one"}, {"type": "output_text", "text": "stale two"}],
    [None]])
def test_saved_assistant_with_unmapped_content_replays_text(tmp_path, content):
    """Imported content extras stay saved while mapped text owns wire replay."""
    chat = Chat(messages=[{"assistant": {"text": "Recorded {literal}",
        "provider_extras": {"content": content, "future": None}}}])
    original = json.loads(chat.json)
    path = tmp_path / "imported.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    request = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert request["input"] == [{"type": "message", "role": "assistant",
        "status": "completed", "future": None, "content": [
            {"type": "output_text", "text": "Recorded {literal}", "annotations": []}]}]
    assert json.loads(chat.json) == original
    assert restored.messages == chat.messages
    assert YAML(typ="safe").load(restored.yaml)["messages"][0]["assistant"]["provider_extras"]["content"] == content


@pytest.mark.parametrize("role", ["system", "developer"])
def test_saved_system_metadata_keeps_text_access_and_markdown(tmp_path, role):
    """System convenience views unwrap text without removing persisted extras."""
    chat = Chat(messages=[{role: {"text": "Follow the house style.",
        "provider_extras": {"future": None}}}, {"user": "Hello"}])
    path = tmp_path / "system.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    original = json.loads(restored.json)
    assert restored.system_message == "Follow the house style."
    assert "> Follow the house style." in restored.generate_markdown()
    assert json.loads(restored.json) == original
    assert restored.messages[0]["system"]["provider_extras"] == {"future": None}


@pytest.mark.parametrize("content", [None, "unexpected", {"future": None}])
def test_opaque_assistant_non_list_content_has_no_text(tmp_path, content):
    """Opaque history retains unusual content without breaking text conveniences."""
    item = {"type": "message", "role": "assistant", "content": content}
    chat = Chat().asst("Older answer").user("Next")
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "opaque.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    assert restored.response is None
    assert str(restored) == ""
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert replay["input"][-1] == item
    assert restored.messages[-1] == {"provider_item": item}


def test_saved_recorded_conversation_exports_readable_markdown(tmp_path):
    """Markdown reads expanded/opaque dialogue without dumping provider metadata."""
    chat = Chat(messages=[{"system": {"text": "House rules", "provider_extras": {"future": None}}},
                          {"user": {"text": "Draw a snack", "images": [{"file_id": "file_input"}]}}])
    chat.add_messages_json(json.dumps([
        {"type": "message", "role": "assistant", "id": "msg_1",
         "content": [{"type": "output_text", "text": "Checking stock"}]},
        {"type": "reasoning", "summary": [], "encrypted_content": "private-token"},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Include popcorn"}]},
        {"type": "message", "role": "assistant", "id": "msg_2", "content": [
            {"type": "output_text", "text": "Here is "}, {"type": "output_text", "text": "popcorn"}]},
        {"type": "message", "role": "assistant", "content": None},
    ]))
    path = tmp_path / "markdown.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    original = json.loads(restored.json)
    markdown = restored.generate_markdown()
    assert all(text in markdown for text in ["House rules", "Draw a snack", "Checking stock",
                                              "Include popcorn", "Here is popcorn"])
    assert "**User:**" in markdown
    assert "**Assistant:**" in markdown
    assert "private-token" not in markdown
    assert "provider_item" not in markdown
    assert json.loads(restored.json) == original


@pytest.mark.parametrize("role", ["user", "system", "developer"])
@pytest.mark.parametrize("content", ["Keep it short", [{"type": "input_text", "text": "Keep it short"}]])
def test_imported_input_messages_reach_chat_completions(tmp_path, role, content):
    """Switching runtimes retains imported dialogue and instructions after load."""
    from chatsnack.runtime.chat_completions_adapter import ChatCompletionsAdapter
    captured = []

    def create(**kwargs):
        """Capture the final CC request without making a provider call."""
        captured.append(kwargs["messages"])
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    item = {"type": "message", "role": role, "content": content, "id": "msg_imported"}
    chat = Chat()
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "imported-input.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    adapter = ChatCompletionsAdapter(SimpleNamespace(client=SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))))
    with pytest.warns(UserWarning, match="provider-only history"):
        adapter.create_completion(restored.get_messages(), model="test-model")
    expected = content if isinstance(content, str) else [{"type": "text", "text": "Keep it short"}]
    assert captured == [[{"role": role, "content": expected}]]
    assert restored.messages == [{"provider_item": item}]


@pytest.mark.parametrize("content, expected_text, expected_refusal", [
    ([{"type": "refusal", "refusal": "Cannot help with {request}."}], None, "Cannot help with {request}."),
    ([{"type": "output_text", "text": "Here is {context}."},
      {"type": "refusal", "refusal": "Cannot help."}], "Here is {context}.", "Cannot help."),
    ([{"type": "refusal", "refusal": "Cannot "},
      {"type": "output_text", "text": "Safe alternative."},
      {"type": "refusal", "refusal": "help."}], "Safe alternative.", "Cannot help."),
    ([{"type": "refusal", "refusal": ""}], None, ""),
])
def test_saved_responses_refusals_reach_chat_completions(tmp_path, content, expected_text, expected_refusal):
    """Switching APIs preserves refusal and text while saved Responses items stay intact."""
    from chatsnack.runtime.chat_completions_adapter import ChatCompletionsAdapter
    captured = []

    def respond(request):
        """Capture the serialized SDK request without making a provider call."""
        captured.append(json.loads(request.content)["messages"])
        return httpx.Response(200, json={"id": "cc_1", "object": "chat.completion",
            "created": 1, "model": "test-model", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

    item = {"type": "message", "role": "assistant", "id": "msg_refusal", "content": content}
    chat = Chat().user("Request")
    chat.add_messages_json(json.dumps([item]))
    path = tmp_path / "refusal-history.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    original = json.loads(restored.json)
    with openai.OpenAI(api_key="offline", http_client=httpx.Client(
            transport=httpx.MockTransport(respond))) as sdk:
        adapter = ChatCompletionsAdapter(SimpleNamespace(client=sdk))
        with pytest.warns(UserWarning, match="provider-only history"):
            adapter.create_completion(restored.get_messages(), model="test-model")
    assert captured == [[{"role": "user", "content": "Request"},
                         {"role": "assistant", "content": expected_text, "refusal": expected_refusal}]]
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert replay["input"][-1] == item
    assert json.loads(restored.json) == original


@pytest.mark.parametrize("detail", ["low", "original"])
def test_cc_projects_imported_user_attachments_and_keeps_unmapped_parts(detail):
    """Representable input parts survive projection; unsupported data stays saved."""
    from chatsnack.runtime.conversation import project_chat_completions
    item = {"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": "Compare these"},
        {"type": "input_image", "image_url": "https://example.test/snack.png", "detail": detail},
        {"type": "input_file", "file_id": "file_1"},
        {"type": "input_file", "file_data": "data:text/plain;base64,aGk=", "filename": "note.txt"},
        {"type": "future_input", "data": "keep"},
    ]}
    chat = Chat()
    chat.add_messages_json(json.dumps([item]))
    with pytest.warns(UserWarning, match="provider-only history"):
        projected = project_chat_completions(chat.get_messages())
    assert projected == [{"role": "user", "content": [
        {"type": "text", "text": "Compare these"},
        {"type": "image_url", "image_url": {"url": "https://example.test/snack.png", **({"detail": detail} if detail == "low" else {})}},
        {"type": "file", "file": {"file_id": "file_1"}},
        {"type": "file", "file": {"file_data": "data:text/plain;base64,aGk=", "filename": "note.txt"}},
    ]}]
    assert chat.messages == [{"provider_item": item}]


@pytest.mark.parametrize("old_defaults", [False, True], ids=["provider-capture", "existing-yaml"])
def test_saved_history_omits_metadata_defaults_and_keeps_scalar_dialogue(tmp_path, old_defaults):
    """Compact YAML retains replay data and the ordinary scalar authoring form."""
    chat = Chat().asst("Blah")
    chat.messages.extend([
        item_to_message({"type": "reasoning", "id": "rs_1", "summary": [],
                         "content": [], "encrypted_content": "opaque", "status": "completed"}),
        item_to_message({"type": "message", "id": "msg_1", "role": "assistant",
                         "status": "completed", "phase": "final_answer", "content": [
                             {"type": "output_text", "text": "Answer {literal}",
                              "annotations": [], "logprobs": []}]}),
        {"assistant": {"text": "Simple again", "sources": [], "images": [],
                       "files": [], "tool_calls": [], "provider_extras": {}}},
    ])
    if old_defaults:
        chat.messages[1]["reasoning"].update(summary=[], content=[], status="completed")
        chat.messages[2]["assistant"].update(status="completed", provider_extras={
            "content": [{"type": "output_text", "annotations": [], "logprobs": []}],
        })
    original = json.loads(chat.json)
    saved = YAML(typ="safe").load(chat.yaml)
    assert json.loads(chat.json) == original
    assert saved["messages"] == [
        {"assistant": "Blah"},
        {"reasoning": {"item_id": "rs_1", "encrypted_content": "opaque"}},
        {"assistant": {"text": "Answer {literal}", "item_id": "msg_1", "phase": "final_answer"}},
        {"assistant": "Simple again"},
    ]
    path = tmp_path / "compact.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    request = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert request["input"][1:3] == [
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
         "phase": "final_answer", "content": [
             {"type": "output_text", "text": "Answer {literal}", "annotations": []}]},
    ]
    assert restored.messages[0] == {"assistant": "Blah"}
    assert restored.messages[-1] == {"assistant": "Simple again"}


def test_compact_history_preserves_meaningful_metadata_and_empty_payloads(tmp_path):
    """Only known defaults disappear; partial output and opaque values survive."""
    items = [
        {"type": "reasoning", "id": "rs_1", "status": "in_progress",
         "summary": [{"type": "summary_text", "text": "Checking stock."}],
         "encrypted_content": "opaque", "future": {"list": [], "null": None, "flag": False}},
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "incomplete",
         "phase": "commentary", "content": [{"type": "output_text", "text": "",
             "annotations": [{"type": "url_citation", "url": "https://example.test",
                              "title": "Stock", "start_index": 0, "end_index": 0}],
             "logprobs": [{"token": "stock", "logprob": 0, "bytes": [], "top_logprobs": []}],
             "future": []}]},
        {"type": "function_call", "call_id": "call_1", "name": "stock", "arguments": "{}",
         "status": "incomplete", "async": False},
        {"type": "function_call_output", "call_id": "call_1", "output": ""},
        {"type": "future_record", "value": {"list": [], "null": None, "zero": 0}},
    ]
    chat = Chat(messages=[item_to_message(item) for item in items])
    path = tmp_path / "meaningful.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert replay["input"] == items


def test_compaction_preserves_native_tool_success_and_unknown_role_fields(tmp_path):
    """Defaults belong to one role/protocol; native patch success is required."""
    chat = Chat(messages=[
        {role: {"text": "Authored", "status": "completed", "phase": None, "item_id": ""}}
        for role in ("system", "user")
    ] + [{"tool": {"tool_call_id": "patch_1", "output_type": "apply_patch_call_output",
                   "status": "completed", "content": ""}}])
    saved = YAML(typ="safe").load(chat.yaml)["messages"]
    assert saved[0]["system"]["status"] == saved[1]["user"]["status"] == "completed"
    assert saved[0]["system"]["phase"] is None
    assert saved[1]["user"]["item_id"] == ""
    path = tmp_path / "patch.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    replay = ResponsesAdapter(SimpleNamespace()).build_responses_request(restored.get_messages(), {})
    assert replay["input"][-1] == {
        "type": "apply_patch_call_output", "call_id": "patch_1", "status": "completed", "output": "",
    }


@pytest.mark.asyncio
async def test_saved_tool_exchange_replays_every_item(tmp_path, monkeypatch):
    """Cross the real authoring, persistence, utensil, and SDK request boundaries."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    requests, lookups = [], []
    first = [
        {"type": "reasoning", "id": "rs_1", "summary": [],
         "encrypted_content": "opaque-{text.DoNotResolve}"},
        {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
         "phase": "commentary", "content": [{"type": "output_text", "text": "Checking stock.", "annotations": []}]},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "stock",
         "arguments": '{"sku":"snack-box"}', "status": "completed", "async": False,
         "caller": {"type": "direct"}, "future_flag": {"nested": [1, None]}},
    ]
    second = [
        {"type": "reasoning", "id": "rs_2", "summary": [], "encrypted_content": "opaque-2"},
        {"type": "future_record", "id": "future_1", "value": {"keep": "{literal}"}},
        {"type": "message", "id": "msg_2", "role": "assistant", "status": "completed",
         "phase": "final_answer", "content": [{"type": "output_text", "text": "12 available: {sku}.", "annotations": []}]},
    ]

    @utensil
    def stock(sku: str):
        """Return a deterministic stock count without external effects."""
        lookups.append(sku)
        return {"available": 12}

    def respond(request):
        """Capture real SDK serialization, then supply the next provider response."""
        body = json.loads(request.content)
        requests.append(body)
        output = first if len(requests) == 1 else second
        return httpx.Response(200, json={
            "id": f"resp_{len(requests)}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"], "output": output,
        })

    Text(name="StockStyle", content="Use the stock utensil.").save()
    helper = Chat(name="StockHelper", runtime="responses", model="test-model", utensils=[stock])
    helper.system("{text.StockStyle}").user("Check stock for {sku}.")
    helper.save()

    async with openai.AsyncOpenAI(
        api_key="offline", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        helper.ai.aclient = sdk
        thread = await helper.chat_a(sku="snack-box")
        thread.save()
        restored = Chat(name=thread.name, utensils=[stock])
        restored.load()
        restored.ai.aclient = sdk
        await restored.chat_a("Could I order six?")

    assert lookups == ["snack-box"]
    assert thread.response == restored.response == "12 available: {sku}."
    assert [next(iter(m)) for m in restored.messages] == [
        "system", "user", "reasoning", "assistant", "tool_call", "tool",
        "reasoning", "provider_item", "assistant",
    ]
    assert "{text.StockStyle}" in helper.yaml and "{sku}" in helper.yaml
    assert "export_state" not in thread.yaml
    assert "opaque-{text.DoNotResolve}" in restored.yaml
    assert len(requests) == 3
    assert all("previous_response_id" not in request for request in requests)
    expected_first = first[:2] + [{k: v for k, v in first[2].items() if k != "status"}]
    assert requests[1]["input"][2:5] == expected_first
    tool_output = requests[1]["input"][5]
    assert tool_output["type"] == "function_call_output"
    assert tool_output["call_id"] == "call_1"
    assert json.loads(tool_output["output"])["available"] == 12
    assert requests[2]["input"][:-1] == requests[1]["input"] + second
    assert requests[2]["input"][-1]["content"][0]["text"] == "Could I order six?"
