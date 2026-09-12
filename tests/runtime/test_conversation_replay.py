"""Steer tests at the transcript, SDK, and transport boundaries."""

import base64
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

from chatsnack import Chat, ChatParams
from chatsnack.runtime import ResponsesAdapter
from chatsnack.runtime.conversation import copy_value, item_to_message, entries_to_bridge


def answer(number=1, *, multipart=False):
    """Make a provider answer with literal text and explicit empty metadata."""
    parts = [{"type": "output_text", "text": "Answer {literal}", "annotations": []}]
    if multipart:
        parts.append({"type": "output_text", "text": " again", "annotations": []})
    return {"type": "message", "id": f"msg_{number}", "role": "assistant",
            "phase": "final_answer", "status": "completed", "content": parts}


def payload(body, number, output=None):
    """Supply the required SDK response fields without any network access."""
    return {"id": f"resp_{number}", "object": "response", "created_at": 1,
            "status": "completed", "model": body["model"],
            "output": output if output is not None else [answer(number)]}


@pytest.mark.parametrize("store", [False, True])
@pytest.mark.asyncio
async def test_branches_edits_load_and_reset_use_their_own_history(tmp_path, monkeypatch, store):
    """Only an unchanged stored ancestor may shorten the actual SDK input."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=payload(body, len(requests)))

    async with openai.AsyncOpenAI(api_key="offline", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(params=ChatParams(runtime="responses", model="test-model", responses={"store": store})).user("first")
        source.ai.aclient = sdk
        ancestor = await source.chat_a()
        original = copy_value(ancestor.messages)
        left = await ancestor.chat_a("left")
        await ancestor.chat_a("right")
        assert ancestor.messages == original
        for body in requests[1:3]:
            if store:
                assert body.get("previous_response_id") == "resp_1"
                assert len(body["input"]) == 1
            else:
                assert "previous_response_id" not in body
                assert body["input"][:2] == requests[0]["input"] + [answer()]

        edited = ancestor.copy()
        edited.ai.aclient = sdk
        edited.messages[0]["user"] = "edited"
        await edited.chat_a("after edit")
        assert "previous_response_id" not in requests[-1]
        assert requests[-1]["input"][0]["content"][0]["text"] == "edited"
        assert requests[-1]["input"][1] == answer()
        assert ancestor.messages == original

        path = tmp_path / "branch.yml"
        left.save(str(path))
        loaded = Chat()
        loaded.load(str(path))
        loaded.ai.aclient = sdk
        await loaded.chat_a("after load")
        assert "previous_response_id" not in requests[-1]
        assert [item.get("id") for item in requests[-1]["input"] if item.get("id")] == ["msg_1", "msg_2"]

        edited.reset()
        await edited.chat_a("after reset")
        assert "previous_response_id" not in requests[-1]
        assert not any(item.get("id") for item in requests[-1]["input"])
        ancestor.messages[0]["user"] = "edited on the same binding"
        await ancestor.chat_a("after direct edit")
        assert "previous_response_id" not in requests[-1]
        assert requests[-1]["input"][0]["content"][0]["text"] == "edited on the same binding"
        assert requests[-1]["input"][1] == answer()


@pytest.mark.parametrize("external", [
    {"previous_response_id": "external"},
    {"extra_body": {"previous_response_id": "external"}},
    {"conversation": "conv_external"},
])
@pytest.mark.asyncio
async def test_profile_external_ancestry_never_becomes_an_automatic_local_cache(tmp_path, monkeypatch, external):
    """Profile defaults and server conversations cannot certify local ancestry."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=payload(body, len(requests)))

    async with openai.AsyncOpenAI(api_key="offline", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(params=ChatParams(runtime="responses", model="test-model",
                      responses={"store": True}, profile={"defaults": external}))
        source.ai.aclient = sdk
        continued = await source.chat_a("first")
        continued.params.profile = None
        await continued.chat_a("second")
    assert "previous_response_id" not in requests[1]
    assert len(requests[1]["input"]) == 3


@pytest.mark.asyncio
async def test_changed_credentials_invalidate_the_stored_ancestor(tmp_path, monkeypatch):
    """A response ID from another authentication scope must not be reused."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=payload(body, len(requests)))

    async with openai.AsyncOpenAI(api_key="offline-a", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(params=ChatParams(runtime="responses", model="test-model", responses={"store": True}))
        source.ai.aclient = sdk
        continued = await source.chat_a("first")
        continued.ai.api_key = "offline-b"
        await continued.chat_a("second")
    assert "previous_response_id" not in requests[1]
    assert len(requests[1]["input"]) == 3


def test_json_copy_include_and_reset_preserve_nested_provider_values(tmp_path, monkeypatch):
    """Composition retains nulls, empty arrays, aliases, and opaque argument strings."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    items = [
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "{opaque}", "future": None},
        {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "stock",
         "arguments": '{ "sku": "{literal}" }', "async": False, "caller": {"type": "direct"}},
        {"type": "function_call_output", "call_id": "call_1", "output": [
            {"type": "input_image", "image_url": "https://example.test/image.png"}]},
        answer(multipart=True),
        {"type": "future_record", "value": {"array": [], "nullable": None}},
    ]
    recorded = Chat(name="Recorded")
    recorded.add_messages_json(json.dumps(items))
    recorded.save()
    rebuilt = Chat()
    rebuilt.add_messages_json(recorded.json, escape=False)
    assert rebuilt.messages == recorded.messages
    included = Chat().include("Recorded").copy(expand_includes=True)
    assert included.messages == recorded.messages
    clone = recorded.copy()
    clone.messages[0]["reasoning"]["provider_extras"]["future"] = ["changed"]
    assert recorded.messages[0]["reasoning"]["provider_extras"]["future"] is None
    resettable = Chat(messages=copy_value(recorded.messages))
    resettable.messages[0]["reasoning"]["summary"] = [{"text": "changed"}]
    resettable.reset()
    assert resettable.messages == recorded.messages
    adapter = ResponsesAdapter(SimpleNamespace())
    assert adapter.build_responses_request(rebuilt.get_messages(), {"model": "test-model"})["input"] == items


@pytest.mark.parametrize("store", [False, True])
@pytest.mark.parametrize("multipart", [False, True])
@pytest.mark.parametrize("image_last", [False, True], ids=["image-first", "image-after-commentary"])
@pytest.mark.asyncio
async def test_multipart_answer_sources_and_generated_image_replay(tmp_path, monkeypatch, store, multipart, image_last):
    """Save media under the asset policy and restore its bytes only for submission."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    image_bytes = b"\x89PNG\r\n\x1a\nprovider-image"
    image_item = {"type": "image_generation_call", "id": "ig_1", "status": "completed",
                  "result": base64.b64encode(image_bytes).decode("ascii")}
    message = answer(multipart=multipart)
    message["content"][0]["annotations"] = [{"type": "url_citation", "url": "https://example.test",
                                             "title": "Source", "start_index": 0, "end_index": 6}]
    if image_last:
        message["phase"] = "commentary"
    output = [message, image_item] if image_last else [image_item, message]
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=payload(body, len(requests), output))

    async with openai.AsyncOpenAI(api_key="offline", http_client=httpx.AsyncClient(
        transport=httpx.MockTransport(respond),
    )) as sdk:
        source = Chat(params=ChatParams(runtime="responses", model="test-model", responses={"store": store}))
        source.ai.aclient = sdk
        continued = await source.chat_a("draw")
        assert continued.response == "Answer {literal}" + (" again" if multipart else "")
        assert len(continued.messages) == 3
        assert continued.images[0].read_bytes() == image_bytes
        assert continued.files[0].read_bytes() == image_bytes
        assert image_item["result"] not in continued.yaml
        await continued.chat_a("edit immediately")
        if store:
            assert requests[1]["previous_response_id"] == "resp_1"
            assert len(requests[1]["input"]) == 1
        else:
            assert requests[1]["input"][1:3] == output
        path = tmp_path / "image.yml"
        continued.save(str(path))
        loaded = Chat()
        loaded.load(str(path))
        assert loaded.images[0].read_bytes() == image_bytes
        assert loaded.files[0].read_bytes() == image_bytes
        loaded.ai.aclient = sdk
        await loaded.chat_a("edit")
    assert requests[2]["input"][1:3] == output


def test_chat_completions_projects_dialogue_and_calls_with_one_warning():
    """The SDK gets supported exchanges while the stored Responses entries survive."""
    from chatsnack.runtime.chat_completions_adapter import ChatCompletionsAdapter
    captured = []

    def create(**kwargs):
        captured.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    adapter = ChatCompletionsAdapter(SimpleNamespace(client=SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )))
    entries = [{"user": "check"}, item_to_message({"type": "reasoning", "summary": []}),
               {"tool_call": {"name": "stock", "call_id": "call_1", "arguments": {"sku": "box"}}},
               {"tool": {"tool_call_id": "call_1", "content": "12"}}, item_to_message(answer())]
    entries[-1]["assistant"]["sources"] = [{"url": "https://example.test"}]
    entries[-1]["assistant"]["images"] = [{"asset": "sha256:display-only"}]
    entries[-1]["assistant"]["files"] = [{"asset": "sha256:display-file"}]
    original = copy_value(entries)
    with pytest.warns(UserWarning, match="provider-only history") as warnings:
        adapter.create_completion(entries_to_bridge(entries), model="test-model")
    assert len(warnings) == 1
    assert entries == original
    assert captured[0]["messages"] == [
        {"role": "user", "content": "check"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
            "function": {"name": "stock", "arguments": '{"sku": "box"}'}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "12"},
        {"role": "assistant", "content": "Answer {literal}"},
    ]


@pytest.mark.asyncio
async def test_imported_legacy_metadata_and_recorded_text_without_ids_survive(tmp_path, monkeypatch):
    """Legacy JSON retains extras; recorded text is literal even without an ID."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    legacy = [
        {"role": "system", "content": "Use {style}", "provider_extras": {"future": None}},
        {"role": "user", "content": "Check", "provider_extras": {"cache_control": {"type": "ephemeral"}}},
        {"role": "assistant", "content": "Calling", "phase": "commentary", "tool_calls": [
            {"id": "call_1", "type": "function", "future": None,
             "function": {"name": "stock", "arguments": "{}", "future": []}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "12", "future": {"nullable": None}},
    ]
    chat = Chat(runtime="responses", model="test-model")
    chat.add_messages_json(json.dumps(legacy), escape=False)
    assert chat.get_messages() == legacy
    path = tmp_path / "legacy.yml"
    chat.save(str(path))
    restored = Chat()
    restored.load(str(path))
    assert restored.get_messages() == legacy
    no_id = answer()
    no_id.pop("id")
    restored.add_messages_json(json.dumps([no_id]))
    request = json.loads(await restored._build_final_prompt({"style": "plain", "literal": "WRONG"}))
    assert request[0]["content"] == "Use plain"
    assert request[-1]["content"] == "Answer {literal}"
    assert request[-1]["provider_extras"]["content"] == [{"type": "output_text"}]


@pytest.mark.parametrize("parts, expected", [
    ([{"type": "input_text", "text": "done"}], "done"),
    ([{"type": "input_image", "image_url": "https://example.test/image.png"}], ""),
])
def test_cc_projection_preserves_tool_correlation_for_structured_outputs(parts, expected):
    """Omitting an unsupported content part must never strand its function call."""
    from chatsnack.runtime.conversation import project_chat_completions
    entries = [
        {"tool_call": {"call_id": "c1", "name": "stock", "arguments": "{}"}},
        item_to_message({"type": "function_call_output", "call_id": "c1", "output": parts}),
        {"assistant": "finished"},
    ]
    original = copy_value(entries)
    with pytest.warns(UserWarning, match="provider-only history"):
        projected = project_chat_completions(entries_to_bridge(entries))
    assert projected[0]["tool_calls"][0]["id"] == "c1"
    assert projected[1] == {"role": "tool", "tool_call_id": "c1", "content": expected}
    assert entries == original


@pytest.mark.parametrize("opaque_commentary", [False, True])
def test_cc_projection_keeps_tool_results_next_to_their_calls(opaque_commentary):
    """Move results only in the CC view, retaining interleaved assistant content."""
    from chatsnack.runtime.conversation import project_chat_completions
    commentary = {"assistant": {"text": [{"type": "text", "text": "Checking"}], "name": "helper"}}
    if opaque_commentary:
        commentary = item_to_message(answer(multipart=True))
    entries = [
        {"user": "Check both."},
        {"tool_call": {"call_id": "c1", "name": "stock", "arguments": "{}"}},
        {"tool_call": {"call_id": "c2", "name": "stock", "arguments": "{}"}},
        commentary,
        {"tool": {"tool_call_id": "c2", "content": "second"}},
        {"tool": {"tool_call_id": "c1", "content": "first"}},
        {"assistant": "Done."},
        {"assistant": "Anything else?"},
    ]
    original = copy_value(entries)
    if opaque_commentary:
        with pytest.warns(UserWarning, match="provider-only history"):
            projected = project_chat_completions(entries_to_bridge(entries))
    else:
        projected = project_chat_completions(entries_to_bridge(entries))
    assert [item["role"] for item in projected] == ["user", "assistant", "tool", "tool", "assistant", "assistant", "assistant"]
    assert [call["id"] for call in projected[1]["tool_calls"]] == ["c1", "c2"]
    assert projected[2:4] == [
        {"role": "tool", "tool_call_id": "c2", "content": "second"},
        {"role": "tool", "tool_call_id": "c1", "content": "first"},
    ]
    if opaque_commentary:
        assert projected[4] == {"role": "assistant", "content": "Answer {literal} again"}
    else:
        assert projected[4] == {"role": "assistant", "content": [{"type": "text", "text": "Checking"}], "name": "helper"}
    assert projected[5:] == [{"role": "assistant", "content": "Done."}, {"role": "assistant", "content": "Anything else?"}]
    assert entries == original


def test_cc_projection_accepts_explicit_null_tool_calls():
    """Ordinary imported CC messages may explicitly carry no tool calls."""
    from chatsnack.runtime.conversation import project_chat_completions
    messages = [{"role": "assistant", "content": "Hello", "tool_calls": None}]
    assert project_chat_completions(messages) == messages


def test_incomplete_image_retains_explicit_null_result():
    """An absent image result is still a meaningful provider field."""
    adapter = ResponsesAdapter(SimpleNamespace())
    item = {"type": "image_generation_call", "id": "ig_1", "status": "in_progress", "result": None}
    result = adapter.normalize_completion(payload({"model": "test-model"}, 1, [item]), {})
    assert adapter.build_responses_request(entries_to_bridge(result.messages), {})["input"] == [item]


@pytest.mark.asyncio
async def test_latest_output_accessors_follow_opaque_assistant_boundaries():
    """Image-only and multipart replies cannot borrow text/assets from older turns."""
    adapter = ResponsesAdapter(SimpleNamespace())
    chat = Chat().asst("Previous answer").user("Draw a snack.")
    image = {"type": "message", "id": "msg_image", "role": "assistant", "status": "completed",
             "content": [{"type": "output_image", "file_id": "file_new"}]}
    result = adapter.normalize_completion(payload({"model": "test-model"}, 1, [image]), {})
    await chat._prepare_response_history(result)
    chat._append_response_messages(result)
    assert chat.response is None
    assert chat.images[0].file_id == "file_new"
    chat.user("Now just describe it.")
    text = answer(multipart=True)
    result = adapter.normalize_completion(payload({"model": "test-model"}, 2, [text]), {})
    await chat._prepare_response_history(result)
    chat._append_response_messages(result)
    assert chat.response == "Answer {literal} again"
    assert chat.images == []
    assert chat.files == []


@pytest.mark.asyncio
async def test_multipart_final_owns_assets_after_compact_commentary(tmp_path):
    """Asset views follow the final opaque assistant through ordinary save/load."""
    commentary = answer()
    commentary.update(phase="commentary")
    final = answer(2, multipart=True)
    final["content"].append({"type": "output_image", "file_id": "file_final"})
    adapter = ResponsesAdapter(SimpleNamespace())
    result = adapter.normalize_completion(payload({"model": "test-model"}, 1, [commentary, final]), {})
    chat = Chat().user("Draw and describe.")
    await chat._prepare_response_history(result)
    chat._append_response_messages(result)
    assert "images" not in chat.messages[-2]["assistant"]
    assert chat.response == "Answer {literal} again"
    assert chat.images[0].file_id == "file_final"
    path = tmp_path / "multipart.yml"
    chat.save(str(path))
    loaded = Chat()
    loaded.load(str(path))
    assert loaded.response == chat.response
    assert loaded.images == chat.images


@pytest.mark.parametrize("commentary", [False, True])
@pytest.mark.parametrize("boundary", ["user", "tool", "opaque-tool", "final-answer"])
def test_tool_only_output_does_not_reuse_previous_answer(tmp_path, commentary, boundary):
    """A pending call can expose its own commentary, never an earlier answer."""
    previous = answer()
    previous["content"][0]["text"] = "Previous answer"
    entries = [item_to_message(previous)]
    if boundary == "user":
        entries.append({"user": "Check stock."})
    elif boundary == "tool":
        entries.append({"tool": {"tool_call_id": "earlier", "content": "result"}})
    elif boundary == "opaque-tool":
        entries.append({"provider_item": {"type": "function_call_output", "call_id": "earlier", "output": []}})
    if commentary:
        current = answer(2)
        current.update(phase="commentary")
        current["content"][0]["text"] = "Checking stock."
        entries.append(item_to_message(current))
    entries.append(item_to_message({"type": "function_call", "id": "fc_1", "call_id": "call_1",
                                   "name": "stock", "arguments": "{}"}))
    chat = Chat(messages=entries)
    assert chat.response == ("Checking stock." if commentary else None)
    assert chat.images == []
    path = tmp_path / "pending.yml"
    chat.save(str(path))
    loaded = Chat()
    loaded.load(str(path))
    assert loaded.response == chat.response


def test_unknown_provider_phase_does_not_split_assistant_output():
    """Only an assistant's phase defines a response boundary."""
    chat = Chat(messages=[
        {"user": "Check stock."},
        {"assistant": {"text": "Checking.", "phase": "commentary"}},
        {"provider_item": {"type": "future_record", "phase": "final_answer"}},
        {"tool_call": {"name": "stock", "call_id": "c1", "arguments": "{}"}},
    ])
    assert chat.response == "Checking."
