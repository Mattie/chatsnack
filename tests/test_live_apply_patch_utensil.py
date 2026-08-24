"""Opt-in live contracts for native Apply Patch execution and continuation."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from chatsnack import ApplyPatchCall, Chat, utensil
from chatsnack.runtime import ResponsesAdapter, ResponsesWebSocketAdapter
from examples.apply_patch_workspace import LocalWorkspace


_RUN_LIVE = os.environ.get("CHATSNACK_RUN_LIVE_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}
_skip_no_key = pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None or not _RUN_LIVE,
    reason="Live OpenAI tests require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)


def _run_live_patch(tmp_path: Path, *, session: str | None = None):
    target = tmp_path / "snack.txt"
    target.write_text("old snack\n", encoding="utf-8")
    received: list[ApplyPatchCall] = []
    workspace = LocalWorkspace(tmp_path)
    proof = f"PATCH_LIVE_{secrets.token_hex(8)}"

    def execute(call: ApplyPatchCall):
        received.append(call)
        result = workspace.apply_patch(call)
        if result["status"] == "completed":
            result = {
                **result,
                "output": f"{result['output']} Reply with exactly this proof token: {proof}",
            }
        return result

    model = os.environ.get("CHATSNACK_LIVE_MODEL", "gpt-5.4")
    patch = utensil.apply_patch(execute=execute, allowed_callers=["direct"])
    chat = Chat(
        (
            "You are an Apply Patch protocol test. Use Apply Patch exactly once "
            "for the requested edit. After it succeeds, reply with only the proof "
            "token supplied in the tool output."
        ),
        model=model,
        runtime="responses",
        session=session,
        tool_choice="required",
        utensils=[patch],
    )

    continued = None
    try:
        continued = chat.chat(
            "Update the relative file snack.txt from old snack to fresh snack."
        )
        return chat, continued, received, target, proof
    except BaseException:
        chat.close_session()
        raise


def _assert_live_patch_result(continued, received, target, proof):
    assert (continued.response or "").strip() == proof
    assert target.read_text(encoding="utf-8") == "fresh snack\n"
    assert len(received) == 1
    call = received[0]
    assert call.item_id
    assert call.call_id
    assert call.status == "completed"
    assert call.operation["type"] == "update_file"
    assert call.operation["path"] in {"snack.txt", "./snack.txt"}
    assert call.operation.get("diff")

    tool_turns = [
        message
        for message in continued.get_messages()
        if message.get("role") == "tool"
        and message.get("output_type") == "apply_patch_call_output"
    ]
    assert tool_turns == [
        {
            "role": "tool",
            "content": f"Updated snack.txt. Reply with exactly this proof token: {proof}",
            "tool_call_id": call.call_id,
            "output_type": "apply_patch_call_output",
            "status": "completed",
        }
    ]


@_skip_no_key
def test_live_http_apply_patch_executes_and_continues(tmp_path, monkeypatch):
    """HTTP Responses carries the native call and correlated output end to end."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path / "chatsnack-data"))

    chat, continued, received, target, proof = _run_live_patch(tmp_path)
    try:
        assert isinstance(chat.runtime, ResponsesAdapter)
        assert isinstance(continued.runtime, ResponsesAdapter)
        _assert_live_patch_result(continued, received, target, proof)
    finally:
        continued.close_session()
        chat.close_session()


@_skip_no_key
def test_live_websocket_apply_patch_continues_on_the_same_session(
    tmp_path,
    monkeypatch,
):
    """WebSocket Responses sends the native output through provider-owned state."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path / "chatsnack-data"))

    chat, continued, received, target, proof = _run_live_patch(
        tmp_path,
        session="inherit",
    )
    try:
        assert isinstance(chat.runtime, ResponsesWebSocketAdapter)
        assert isinstance(continued.runtime, ResponsesWebSocketAdapter)
        _assert_live_patch_result(continued, received, target, proof)
        assert continued.runtime.session is chat.runtime.session
    finally:
        continued.close_session()
        chat.close_session()
