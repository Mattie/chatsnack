"""Opt-in provider contracts for mixed Python sync/async utensils.

Run with CHATSNACK_RUN_LIVE_TESTS=1 and configured OpenAI credentials.
OpenRouter additionally requires CHATSNACK_RUN_OPENROUTER_LIVE=1.
"""

import asyncio
import json
import os
import secrets

import pytest
import pytest_asyncio

from chatsnack import Chat, ChatParams, utensil


_OPENAI_ENABLED = (
    bool(os.getenv("OPENAI_API_KEY"))
    and os.getenv("CHATSNACK_RUN_LIVE_TESTS", "").lower() in {"1", "true", "yes"}
)
_OPENROUTER_ENABLED = (
    bool(os.getenv("OPENROUTER_API_KEY"))
    and os.getenv("CHATSNACK_RUN_OPENROUTER_LIVE", "").lower() in {"1", "true", "yes"}
)
_CASES = [
    pytest.param("responses", "openai", marks=pytest.mark.skipif(
        not _OPENAI_ENABLED, reason="Requires live OpenAI opt-in and credentials")),
    pytest.param("responses_websocket", "openai", marks=pytest.mark.skipif(
        not _OPENAI_ENABLED, reason="Requires live OpenAI opt-in and credentials")),
    pytest.param("chat_completions", "openai", marks=pytest.mark.skipif(
        not _OPENAI_ENABLED, reason="Requires live OpenAI opt-in and credentials")),
    pytest.param("responses", "openrouter", marks=[
        pytest.mark.openrouter_live,
        pytest.mark.skipif(not _OPENROUTER_ENABLED, reason="Requires live OpenRouter opt-in and credentials"),
    ]),
    pytest.param("chat_completions", "openrouter", marks=[
        pytest.mark.openrouter_live,
        pytest.mark.skipif(not _OPENROUTER_ENABLED, reason="Requires live OpenRouter opt-in and credentials"),
    ]),
]


@pytest_asyncio.fixture(autouse=True)
async def drain_callbacks():
    """Let worker-stop callbacks complete before pytest closes the test loop."""
    yield
    await asyncio.sleep(0)


def mixed_chat(runtime, provider):
    """Create a bounded real-provider chat with one sync and one async capability."""
    events = []
    sync_proof = "SYNC_" + secrets.token_hex(6)
    async_proof = "ASYNC_" + secrets.token_hex(6)

    @utensil
    def sync_stock():
        """Read the first inventory receipt."""
        events.append("sync")
        return {"receipt": sync_proof}

    @utensil
    async def async_stock():
        """Read the second inventory receipt asynchronously."""
        events.append("async:start")
        await asyncio.sleep(0)
        events.append("async:end")
        return {"receipt": async_proof}

    params = ChatParams(
        model=("z-ai/glm-5.3-flash" if provider == "openrouter" else "gpt-5.4-mini"),
        runtime=runtime, max_tokens=1024, auto_feed=3,
        responses={"timeout": 60},
    )
    if provider == "openrouter":
        params.base_url = os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
        params.api_key_env = "OPENROUTER_API_KEY"
    chat = Chat(
        "Call sync_stock exactly once, then call async_stock exactly once. "
        "After receiving both receipts, return their values in that order, "
        "separated by a space. On later turns, recall the receipts without calling tools.",
        params=params, utensils=[sync_stock, async_stock],
    )
    return chat, events, sync_proof, async_proof


def assert_mixed_results(thread, events, sync_proof, async_proof):
    """Require real execution, resolved output, and correlated persistent tool history."""
    assert events == ["sync", "async:start", "async:end"]
    assert sync_proof in (thread.last or "")
    assert async_proof in (thread.last or "")
    messages = thread.get_messages()
    calls = []
    for message in messages:
        if message.get("role") == "tool_call":
            # Responses keeps each provider call as its own transcript item.
            call = message["content"]
            calls.append((call["name"], call["call_id"]))
        elif message.get("role") == "assistant":
            # Chat Completions retains the assistant's grouped tool_calls.
            calls.extend((call["function"]["name"], call["id"])
                         for call in message.get("tool_calls", []))
    outputs = [message for message in messages if message.get("role") == "tool"]
    assert [name for name, _ in calls] == ["sync_stock", "async_stock"]
    assert [message["tool_call_id"] for message in outputs] == [call_id for _, call_id in calls]
    assert [json.loads(message["content"])["receipt"] for message in outputs] == [sync_proof, async_proof]
    assert "coroutine object" not in thread.yaml


@pytest.mark.parametrize("runtime,provider", _CASES)
def test_live_sync_chat_mixes_sync_and_async_utensils(tmp_path, monkeypatch, runtime, provider):
    """Real chat() executes both kinds of utensils and retains their results on continuation."""
    monkeypatch.chdir(tmp_path)
    chat, events, sync_proof, async_proof = mixed_chat(runtime, provider)
    thread = continued = None
    try:
        thread = chat.chat("Read both inventory receipts.")
        assert_mixed_results(thread, events, sync_proof, async_proof)
        continued = thread.chat("Repeat both receipts in the same order. Do not use tools.")
        assert_mixed_results(continued, events, sync_proof, async_proof)
    finally:
        for owned in (continued, thread, chat):
            if owned is not None:
                owned.close()


@pytest.mark.parametrize("runtime,provider", _CASES)
async def test_live_async_chat_mixes_sync_and_async_utensils(tmp_path, monkeypatch, runtime, provider):
    """Real chat_a() preserves the same mixed-tool execution and continuation contract."""
    monkeypatch.chdir(tmp_path)
    chat, events, sync_proof, async_proof = mixed_chat(runtime, provider)
    thread = continued = None
    try:
        async with asyncio.timeout(150):
            thread = await chat.chat_a("Read both inventory receipts.")
            assert_mixed_results(thread, events, sync_proof, async_proof)
            continued = await thread.chat_a("Repeat both receipts in the same order. Do not use tools.")
            assert_mixed_results(continued, events, sync_proof, async_proof)
    finally:
        async with asyncio.timeout(30):
            for owned in (continued, thread, chat):
                if owned is not None:
                    await owned.close_a()
