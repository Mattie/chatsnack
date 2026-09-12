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
