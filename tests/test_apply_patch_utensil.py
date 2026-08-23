"""Goal and contract tests for caller-executed native Apply Patch utensils."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatsnack import ApplyPatchCall, CHATSNACK_BASE_DIR, Chat, utensil
from chatsnack.runtime import (
    ChatCompletionsAdapter,
    ResponsesAdapter,
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
)
from chatsnack.runtime.responses_common import ResponsesNormalizationMixin
from chatsnack.runtime.types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
)


def _patch_completion(*, status: str = "completed") -> NormalizedCompletionResult:
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(
            tool_calls=[
                NormalizedToolCall(
                    id="call_patch_1",
                    item_id="apc_1",
                    type="apply_patch",
                    status=status,
                    payload={
                        "operation": {
                            "type": "update_file",
                            "path": "snacks.txt",
                            "diff": "@@\n-old\n+new",
                        },
                        "caller": {"type": "direct"},
                        "agent": {"agent_name": "snack-editor"},
                        "created_by": "agent_1",
                    },
                    provider_extras={"future_field": "kept"},
                )
            ]
        ),
        finish_reason="completed",
        metadata={
            "response_id": "resp_patch",
            "assistant_phase": "completed",
        },
    )


def _final_completion() -> NormalizedCompletionResult:
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(content="Patch complete."),
        finish_reason="completed",
        metadata={
            "response_id": "resp_final",
            "assistant_phase": "completed",
        },
    )


@pytest.mark.asyncio
async def test_goal_http_apply_patch_executes_once_and_continues_with_canonical_output(monkeypatch):
    """G1: the terse utensil path executes and continues through real wire mapping."""
    received = []

    async def execute(call: ApplyPatchCall):
        received.append(call)
        return {"status": "completed", "output": "Updated snacks.txt"}

    patch = utensil.apply_patch(execute=execute)
    chat = Chat("Edit only files the workspace permits.", utensils=[patch])
    completions = iter([_patch_completion(), _final_completion()])
    requests = []

    async def create_completion_a(adapter, messages, **kwargs):
        requests.append(adapter.build_responses_request(messages, kwargs))
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat.runtime = ResponsesAdapter(chat.ai)

    continued = await chat.chat_a("Replace old with new.")

    assert continued.last == "Patch complete."
    assert len(received) == 1
    call = received[0]
    assert call.item_id == "apc_1"
    assert call.call_id == "call_patch_1"
    assert call.status == "completed"
    assert call.operation == {
        "type": "update_file",
        "path": "snacks.txt",
        "diff": "@@\n-old\n+new",
    }
    assert call.caller == {"type": "direct"}
    assert call.agent == {"agent_name": "snack-editor"}
    assert call.created_by == "agent_1"
    assert call.provider_extras == {"future_field": "kept"}
    with pytest.raises(TypeError):
        call.operation["path"] = "other.txt"
    with pytest.raises(TypeError):
        call.caller["type"] = "program"

    assert requests[0]["tools"] == [{"type": "apply_patch"}]
    follow_up_items = requests[1]["input"]
    patch_calls = [item for item in follow_up_items if item["type"] == "apply_patch_call"]
    patch_outputs = [item for item in follow_up_items if item["type"] == "apply_patch_call_output"]
    assert patch_calls == [
        {
            "type": "apply_patch_call",
            "id": "apc_1",
            "call_id": "call_patch_1",
            "status": "completed",
            "operation": {
                "type": "update_file",
                "path": "snacks.txt",
                "diff": "@@\n-old\n+new",
            },
            "caller": {"type": "direct"},
            "agent": {"agent_name": "snack-editor"},
            "created_by": "agent_1",
            "future_field": "kept",
        }
    ]
    assert patch_outputs == [
        {
            "type": "apply_patch_call_output",
            "call_id": "call_patch_1",
            "status": "completed",
            "output": "Updated snacks.txt",
        }
    ]

    assistant_call = next(message["assistant"] for message in continued.messages if "assistant" in message and isinstance(message["assistant"], dict))
    assert assistant_call["tool_calls"][0]["item_id"] == "apc_1"
    tool_turns = [message["tool"] for message in continued.messages if "tool" in message]
    assert tool_turns == [
        {
            "tool_call_id": "call_patch_1",
            "output_type": "apply_patch_call_output",
            "status": "completed",
            "content": "Updated snacks.txt",
        }
    ]


@pytest.mark.asyncio
async def test_goal_websocket_apply_patch_continuation_sends_only_the_output(monkeypatch):
    """G2: stateful continuation does not replay the provider-owned call item."""
    received = []

    def execute(call: ApplyPatchCall):
        received.append(call.call_id)
        return {"status": "completed", "output": "Updated snacks.txt"}

    chat = Chat(
        "Edit only files the workspace permits.",
        utensils=[utensil.apply_patch(execute=execute)],
    )
    completions = iter([_patch_completion(), _final_completion()])
    requests = []

    async def create_completion_a(adapter, messages, **kwargs):
        requests.append(adapter.build_responses_request(messages, kwargs))
        return next(completions)

    monkeypatch.setattr(
        ResponsesWebSocketAdapter,
        "create_completion_a",
        create_completion_a,
    )
    chat.runtime = ResponsesWebSocketAdapter(
        chat.ai,
        session=ResponsesWebSocketSession(mode="inherit"),
    )

    continued = await chat.chat_a("Replace old with new.")

    assert continued.last == "Patch complete."
    assert received == ["call_patch_1"]
    assert requests[1]["previous_response_id"] == "resp_patch"
    assert requests[1]["input"] == [
        {
            "type": "apply_patch_call_output",
            "call_id": "call_patch_1",
            "status": "completed",
            "output": "Updated snacks.txt",
        }
    ]


@pytest.mark.asyncio
async def test_goal_saved_apply_patch_chat_requires_and_accepts_explicit_rebind(monkeypatch, tmp_path):
    """G3: YAML keeps capability intent while application authority stays live."""
    monkeypatch.chdir(tmp_path)
    Path(CHATSNACK_BASE_DIR).mkdir(parents=True, exist_ok=True)
    handled = []

    def execute(call: ApplyPatchCall):
        handled.append(call.call_id)
        return {"status": "completed", "output": "Updated snacks.txt"}

    patch = utensil.apply_patch(execute=execute)
    authored = Chat(
        name="SavedPatchWriter",
        system="Edit only files the workspace permits.",
        utensils=[patch],
    )
    authored.save()

    assert "- apply_patch" in authored.yaml
    assert "execute" not in authored.yaml

    unbound = Chat(name="SavedPatchWriter")
    unbound_requests = []

    async def should_not_submit(adapter, messages, **kwargs):
        unbound_requests.append((messages, kwargs))
        raise AssertionError("unbound chat reached provider I/O")

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", should_not_submit)
    unbound.runtime = ResponsesAdapter(unbound.ai)
    with pytest.raises(RuntimeError, match="Missing runtime binding for apply_patch"):
        await unbound.chat_a("Make the edit.")
    assert unbound_requests == []

    rebound = Chat(name="SavedPatchWriter", utensils=[patch])
    rebound.load()
    completions = iter([_patch_completion(), _final_completion()])

    async def create_completion_a(adapter, messages, **kwargs):
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    rebound.runtime = ResponsesAdapter(rebound.ai)

    continued = await rebound.chat_a("Make the edit.")

    assert continued.last == "Patch complete."
    assert handled == ["call_patch_1"]


def test_configured_apply_patch_yaml_round_trip_keeps_only_the_declaration(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    Path(CHATSNACK_BASE_DIR).mkdir(parents=True, exist_ok=True)

    configured = utensil.apply_patch(
        execute=lambda call: {"status": "completed", "output": "ok"},
        allowed_callers=["direct", "programmatic"],
    )
    Chat(
        name="ConfiguredPatchWriter",
        system="Edit carefully.",
        utensils=[configured],
    ).save()

    loaded = Chat(name="ConfiguredPatchWriter")

    assert loaded.get_tools() == [
        {
            "type": "apply_patch",
            "allowed_callers": ["direct", "programmatic"],
        }
    ]
    assert loaded._runtime_binding("apply_patch") is None
    assert "execute" not in loaded.yaml


def test_apply_patch_builder_and_runtime_binding_lifecycle():
    def execute(call):
        return {"status": "completed", "output": "ok"}

    patch = utensil.apply_patch(execute=execute)
    chat = Chat("Edit carefully.", utensils=[patch])
    configured = utensil.apply_patch(
        execute=execute,
        allowed_callers=["direct", "programmatic"],
    )

    assert patch.to_tool_dict() == {"type": "apply_patch"}
    assert configured.to_tool_dict() == {
        "type": "apply_patch",
        "allowed_callers": ["direct", "programmatic"],
    }
    assert chat._runtime_binding("apply_patch") is execute
    assert chat.copy()._runtime_binding("apply_patch") is execute

    replacement = lambda call: {"status": "failed", "output": "replacement"}
    chat._runtime_bindings["apply_patch"] = replacement
    chat.reset()
    assert chat._runtime_binding("apply_patch") is execute

    with pytest.raises(TypeError, match="execute must be callable"):
        utensil.apply_patch(execute=None)
    with pytest.raises(ValueError, match="Unsupported Apply Patch allowed_callers"):
        utensil.apply_patch(execute=execute, allowed_callers=["indirect"])


def test_tool_search_handler_assignment_remains_authoritative_after_reset():
    original = lambda payload: {"handler": "original", "payload": payload}
    replacement = lambda payload: {"handler": "replacement", "payload": payload}
    chat = Chat("Search when useful.", tool_search_handler=original)

    chat.tool_search_handler = replacement

    assert chat._runtime_binding("tool_search") is replacement
    chat.reset()
    assert chat._runtime_binding("tool_search") is replacement


def test_apply_patch_normalization_preserves_provider_call_identity_and_metadata():
    message, _ = ResponsesNormalizationMixin().normalize_output(
        {
            "output": [
                {
                    "type": "apply_patch_call",
                    "id": "apc_raw",
                    "call_id": "call_raw",
                    "status": "completed",
                    "operation": {
                        "type": "create_file",
                        "path": "new.txt",
                        "diff": "+hello",
                    },
                    "caller": {"type": "program", "caller_id": "prog_1"},
                    "agent": {"agent_name": "snack-editor"},
                    "created_by": "agent_raw",
                    "future_field": {"value": 1},
                }
            ]
        }
    )

    call = message.tool_calls[0]
    assert call.type == "apply_patch"
    assert call.item_id == "apc_raw"
    assert call.id == "call_raw"
    assert call.status == "completed"
    assert call.payload == {
        "operation": {
            "type": "create_file",
            "path": "new.txt",
            "diff": "+hello",
        },
        "caller": {"type": "program", "caller_id": "prog_1"},
        "agent": {"agent_name": "snack-editor"},
        "created_by": "agent_raw",
    }
    assert call.provider_extras == {"future_field": {"value": 1}}


def test_saved_apply_patch_history_rebuilds_native_http_items(monkeypatch, tmp_path):
    """Saved call/output history remains provider-faithful after an independent load."""
    monkeypatch.chdir(tmp_path)
    Path(CHATSNACK_BASE_DIR).mkdir(parents=True, exist_ok=True)
    patch = utensil.apply_patch(
        execute=lambda call: {"status": "completed", "output": "unused"}
    )
    chat = Chat(
        name="SavedPatchHistory",
        system="Edit carefully.",
        utensils=[patch],
    )
    chat.assistant(
        {
            "tool_calls": [
                {
                    "id": "call_saved",
                    "item_id": "apc_saved",
                    "type": "apply_patch",
                    "status": "completed",
                    "payload": {
                        "operation": {
                            "type": "delete_file",
                            "path": "old.txt",
                        },
                        "created_by": "agent_saved",
                    },
                    "provider_extras": {"future_field": "kept"},
                }
            ]
        }
    )
    chat.tool(
        {
            "tool_call_id": "call_saved",
            "output_type": "apply_patch_call_output",
            "status": "completed",
            "content": "Deleted old.txt",
        }
    )
    chat.save()

    loaded = Chat(name="SavedPatchHistory")
    request = ResponsesAdapter(loaded.ai).build_responses_request(
        loaded.get_messages(),
        {"tools": loaded.get_tools()},
    )

    assert request["input"][-2:] == [
        {
            "type": "apply_patch_call",
            "id": "apc_saved",
            "call_id": "call_saved",
            "status": "completed",
            "operation": {"type": "delete_file", "path": "old.txt"},
            "created_by": "agent_saved",
            "future_field": "kept",
        },
        {
            "type": "apply_patch_call_output",
            "call_id": "call_saved",
            "status": "completed",
            "output": "Deleted old.txt",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("execute", "expected_output"),
    [
        (
            lambda call: {"status": "failed", "output": "Denied by workspace policy"},
            "Denied by workspace policy",
        ),
        (lambda call: "invalid", "must return a mapping"),
        (
            lambda call: {"status": "unknown", "output": "invalid"},
            "status must be 'completed' or 'failed'",
        ),
        (
            lambda call: {"status": "completed", "output": {"not": "text"}},
            "output must be a string or None",
        ),
    ],
)
async def test_apply_patch_rejections_and_invalid_results_become_one_failed_output(
    monkeypatch,
    execute,
    expected_output,
):
    chat = Chat("Edit carefully.", utensils=[utensil.apply_patch(execute=execute)])
    completions = iter([_patch_completion(), _final_completion()])
    requests = []

    async def create_completion_a(adapter, messages, **kwargs):
        requests.append(adapter.build_responses_request(messages, kwargs))
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat.runtime = ResponsesAdapter(chat.ai)

    continued = await chat.chat_a("Make the edit.")

    assert continued.last == "Patch complete."
    outputs = [
        item
        for item in requests[1]["input"]
        if item["type"] == "apply_patch_call_output"
    ]
    assert len(outputs) == 1
    assert outputs[0]["status"] == "failed"
    assert expected_output in outputs[0]["output"]


@pytest.mark.asyncio
async def test_apply_patch_executor_exception_becomes_failed_output(monkeypatch):
    def execute(call):
        raise PermissionError("outside workspace")

    chat = Chat("Edit carefully.", utensils=[utensil.apply_patch(execute=execute)])
    completions = iter([_patch_completion(), _final_completion()])
    requests = []

    async def create_completion_a(adapter, messages, **kwargs):
        requests.append(adapter.build_responses_request(messages, kwargs))
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat.runtime = ResponsesAdapter(chat.ai)

    await chat.chat_a("Make the edit.")

    outputs = [
        item
        for item in requests[1]["input"]
        if item["type"] == "apply_patch_call_output"
    ]
    assert outputs == [
        {
            "type": "apply_patch_call_output",
            "call_id": "call_patch_1",
            "status": "failed",
            "output": "PermissionError: outside workspace",
        }
    ]


@pytest.mark.asyncio
async def test_in_progress_apply_patch_call_is_never_executed(monkeypatch):
    handled = []

    def execute(call):
        handled.append(call)
        return {"status": "completed", "output": "unexpected"}

    chat = Chat("Edit carefully.", utensils=[utensil.apply_patch(execute=execute)])
    completions = iter([_patch_completion(status="in_progress")])

    async def create_completion_a(adapter, messages, **kwargs):
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat.runtime = ResponsesAdapter(chat.ai)

    with pytest.raises(RuntimeError, match="not executable"):
        await chat.chat_a("Make the edit.")
    assert handled == []


@pytest.mark.asyncio
async def test_in_progress_apply_patch_blocks_the_whole_batch(monkeypatch):
    handled = []

    def execute(call):
        handled.append(call.call_id)
        return {"status": "completed", "output": "unexpected"}

    completed = _patch_completion().message.tool_calls[0]
    in_progress = NormalizedToolCall(
        id="call_patch_2",
        item_id="apc_2",
        type="apply_patch",
        status="in_progress",
        payload={
            "operation": {
                "type": "delete_file",
                "path": "second.txt",
            }
        },
    )
    patch_batch = NormalizedCompletionResult(
        message=NormalizedAssistantMessage(tool_calls=[completed, in_progress]),
        finish_reason="completed",
        metadata={"response_id": "resp_batch", "assistant_phase": "completed"},
    )

    async def create_completion_a(adapter, messages, **kwargs):
        return patch_batch

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat = Chat("Edit carefully.", utensils=[utensil.apply_patch(execute=execute)])
    chat.runtime = ResponsesAdapter(chat.ai)

    with pytest.raises(RuntimeError, match="not executable"):
        await chat.chat_a("Make both edits.")
    assert handled == []


@pytest.mark.asyncio
async def test_apply_patch_without_call_id_never_reaches_the_executor(monkeypatch):
    handled = []

    def execute(call):
        handled.append(call)
        return {"status": "completed", "output": "unexpected"}

    malformed = _patch_completion()
    malformed.message.tool_calls[0].id = ""

    async def create_completion_a(adapter, messages, **kwargs):
        return malformed

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat = Chat("Edit carefully.", utensils=[utensil.apply_patch(execute=execute)])
    chat.runtime = ResponsesAdapter(chat.ai)

    with pytest.raises(RuntimeError, match="missing call_id"):
        await chat.chat_a("Make the edit.")
    assert handled == []


@pytest.mark.asyncio
async def test_multiple_apply_patch_calls_execute_sequentially_in_provider_order(monkeypatch):
    order = []

    async def execute(call):
        order.append(call.operation["path"])
        return {"status": "completed", "output": f"Updated {call.operation['path']}"}

    calls = []
    for index, path in enumerate(("first.txt", "second.txt"), start=1):
        calls.append(
            NormalizedToolCall(
                id=f"call_{index}",
                item_id=f"apc_{index}",
                type="apply_patch",
                status="completed",
                payload={
                    "operation": {
                        "type": "update_file",
                        "path": path,
                        "diff": "@@\n-old\n+new",
                    }
                },
            )
        )
    patch_batch = NormalizedCompletionResult(
        message=NormalizedAssistantMessage(tool_calls=calls),
        finish_reason="completed",
        metadata={"response_id": "resp_batch", "assistant_phase": "completed"},
    )
    completions = iter([patch_batch, _final_completion()])
    requests = []

    async def create_completion_a(adapter, messages, **kwargs):
        requests.append(adapter.build_responses_request(messages, kwargs))
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat = Chat("Edit carefully.", utensils=[utensil.apply_patch(execute=execute)])
    chat.runtime = ResponsesAdapter(chat.ai)

    await chat.chat_a("Make both edits.")

    assert order == ["first.txt", "second.txt"]
    outputs = [
        item
        for item in requests[1]["input"]
        if item["type"] == "apply_patch_call_output"
    ]
    assert [item["call_id"] for item in outputs] == ["call_1", "call_2"]


@pytest.mark.asyncio
async def test_apply_patch_rejects_unsupported_query_paths_before_provider_io():
    patch = utensil.apply_patch(
        execute=lambda call: {"status": "completed", "output": "ok"}
    )
    chat = Chat("Edit carefully.", utensils=[patch])

    chat.runtime = ChatCompletionsAdapter(chat.ai)
    with pytest.raises(RuntimeError, match="Responses runtime"):
        await chat.chat_a("Make the edit.")

    chat.runtime = ResponsesAdapter(chat.ai)
    with pytest.raises(RuntimeError, match=r"requires chat\(\)/chat_a\(\)"):
        await chat.ask_a("Make the edit.")

    chat.params.stream = True
    with pytest.raises(RuntimeError, match="stream=False"):
        await chat.chat_a("Make the edit.")


@pytest.mark.asyncio
async def test_custom_responses_runtime_can_execute_apply_patch():
    handled = []
    requests = []
    completions = iter([_patch_completion(), _final_completion()])

    class CustomResponsesRuntime:
        runtime_family = "responses"

        async def create_completion_a(self, messages, **kwargs):
            requests.append((messages, kwargs))
            return next(completions)

    def execute(call):
        handled.append(call.call_id)
        return {"status": "completed", "output": "Updated snacks.txt"}

    chat = Chat(
        "Edit carefully.",
        runtime=CustomResponsesRuntime(),
        tool_choice="required",
        utensils=[utensil.apply_patch(execute=execute)],
    )

    continued = await chat.chat_a("Make the edit.")

    assert handled == ["call_patch_1"]
    assert continued.last == "Patch complete."
    assert requests[0][1]["tool_choice"] == "required"
    assert "tool_choice" not in requests[1][1]
    assert [
        message["output_type"]
        for message in requests[1][0]
        if message.get("role") == "tool"
    ] == ["apply_patch_call_output"]
