r"""Opt-in live Goals for Chatsnack's OpenRouter Responses workflow.

Run from PowerShell with::

    $env:CHATSNACK_RUN_OPENROUTER_LIVE = "1"
    .\.venv\Scripts\python.exe -m pytest -q -m openrouter_live tests/test_live_openrouter.py

The module reads ``.env.openrouter`` only after the explicit live flag is set.
Shell environment variables take precedence over values in that file.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path

import pytest
from dotenv import load_dotenv


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_RUN_LIVE = (
    os.environ.get("CHATSNACK_RUN_OPENROUTER_LIVE", "").strip().lower()
    in _TRUE_VALUES
)
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODEL = "z-ai/glm-5.3-flash"
_API_KEY_ENV = "OPENROUTER_API_KEY"
_API_BASE_ENV = "OPENROUTER_API_BASE"

if _RUN_LIVE:
    load_dotenv(_REPO_ROOT / ".env.openrouter", override=False)
    _missing = [
        name
        for name in (_API_KEY_ENV, _API_BASE_ENV)
        if not os.environ.get(name, "").strip()
    ]
    if _missing:
        raise RuntimeError(
            "OpenRouter live tests were enabled, but these environment variables "
            f"are missing or blank: {', '.join(_missing)}"
        )

pytestmark = [
    pytest.mark.openrouter_live,
    pytest.mark.filterwarnings(
        "ignore:Model 'z-ai/glm-5.3-flash' may not support reasoning options; "
        "forwarding as authored.:UserWarning"
    ),
    pytest.mark.skipif(
        not _RUN_LIVE,
        reason=(
            "Live OpenRouter tests require "
            "CHATSNACK_RUN_OPENROUTER_LIVE=1"
        ),
    ),
]

# Capture the opt-in decision before importing chatsnack, whose normal startup
# loads the ordinary .env file. A saved .env value must not enable paid tests.
from chatsnack import Chat, ChatParams, utensil
from chatsnack.runtime import ResponsesAdapter


@pytest.fixture(scope="module", autouse=True)
def _close_sync_test_loop_workers():
    """Release workers left on chatsnack's process-wide sync wrapper loop."""
    yield
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if loop.is_running() or loop.is_closed():
        return
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()
    asyncio.set_event_loop(None)


def _required_env(name: str) -> str:
    """Return one configuration value after the opt-in setup has validated it."""
    return os.environ[name].strip()


def _live_params() -> ChatParams:
    """Build the bounded parameter set shared by live OpenRouter Goals."""
    return ChatParams(
        model=_MODEL,
        base_url=_required_env(_API_BASE_ENV),
        api_key_env=_API_KEY_ENV,
        max_tokens=512,
        temperature=0,
        responses={"timeout": 60, "reasoning": {"effort": "low"}},
    )


def _live_chat(system: str, **kwargs) -> Chat:
    """Build a dynamic Chat while leaving custom-endpoint runtime selection implicit."""
    return Chat(system, params=_live_params(), **kwargs)


def _label(prefix: str) -> str:
    """Create a harmless per-request label that cannot come from a cached response."""
    return f"{prefix.lower()}-{secrets.token_hex(3)}"


def _close_sync(*chats: Chat | None) -> None:
    """Close every sync Chat client opened by a live Goal."""
    for chat in chats:
        if chat is not None:
            chat.close()


async def _close_async(*chats: Chat | None) -> None:
    """Close every async Chat client opened by a live Goal."""
    for chat in chats:
        if chat is not None:
            await chat.close_a()


def test_goal_or_live_1_named_yaml_chat_asks_and_replays_history(
    tmp_path: Path,
    monkeypatch,
):
    """A named OpenRouter asset keeps ordinary ask/chat behavior and local history."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    base_url = _required_env(_API_BASE_ENV)
    asset_path = tmp_path / "OpenRouterLiveGoal.yml"
    asset_path.write_text(
        "\n".join(
            (
                "params:",
                f"  model: {json.dumps(_MODEL)}",
                "  max_tokens: 512",
                "  temperature: 0",
                f"  base_url: {json.dumps(base_url)}",
                f"  api_key_env: {_API_KEY_ENV}",
                "  responses:",
                "    timeout: 60",
                "    reasoning:",
                "      effort: low",
                "messages:",
                "  - system: This is a text-copy integration test. Copy TESTLABEL values exactly.",
                "",
            )
        ),
        encoding="utf-8",
    )

    chat = None
    first = None
    continued = None
    ask_label = _label("snackask")
    history_label = _label("snackhistory")
    try:
        chat = Chat(name="OpenRouterLiveGoal")
        assert isinstance(chat.runtime, ResponsesAdapter)
        assert chat.params.base_url == base_url
        assert chat.params.api_key_env == _API_KEY_ENV

        answer = chat.ask(f"Copy this TESTLABEL exactly: {ask_label}")
        assert isinstance(answer, str)
        assert ask_label in answer.lower()

        first = chat.chat(
            f"The TESTLABEL for this conversation is {history_label}. Reply with ACK."
        )
        continued = first.chat(
            "Copy the TESTLABEL from my previous message. Reply with the label only."
        )
        assert history_label in (continued.last or "").lower()
    finally:
        _close_sync(continued, first, chat)


def test_goal_or_live_2_sync_responses_sse_completes():
    """A dynamic OpenRouter Chat streams and accumulates its complete response."""
    label = _label("snacksync")
    chat = _live_chat(
        "Copy requested TESTLABEL values exactly with no explanation.",
        stream=True,
    )
    try:
        assert isinstance(chat.runtime, ResponsesAdapter)
        listener = chat.listen(f"Copy this TESTLABEL exactly: {label}")
        full_text = "".join(listener)

        assert label in full_text.lower()
        assert listener.is_complete
        assert label in listener.response.lower()
    finally:
        _close_sync(chat)


@pytest.mark.asyncio
async def test_goal_or_live_3_async_responses_sse_completes():
    """A dynamic OpenRouter Chat streams asynchronously and closes cleanly."""
    label = _label("snackasync")
    chat = _live_chat(
        "Copy requested TESTLABEL values exactly with no explanation.",
        stream=True,
    )

    async def consume():
        listener = await chat.listen_a(f"Copy this TESTLABEL exactly: {label}")
        full_text = "".join([chunk async for chunk in listener])
        return listener, full_text

    try:
        assert isinstance(chat.runtime, ResponsesAdapter)
        listener, full_text = await asyncio.wait_for(consume(), timeout=75)

        assert label in full_text.lower()
        assert listener.is_complete
        assert label in listener.response.lower()
    finally:
        await _close_async(chat)


def test_goal_or_live_4_local_utensil_executes_and_continues():
    """OpenRouter calls a local utensil and receives its output for the final turn."""
    result_label = _label("snacktool")
    received_values: list[int] = []

    @utensil(
        name="openrouter_live_number",
        description="Return the live-test label associated with an integer.",
    )
    def reveal_number(value: int) -> dict:
        """Record the model's argument and return the test result label."""
        received_values.append(value)
        return {"label": result_label}

    chat = _live_chat(
        (
            "Call the supplied function exactly once. After it succeeds, reply "
            "with only the label value returned by the function."
        ),
        utensils=[reveal_number],
        tool_choice="required",
        auto_feed=1,
    )
    continued = None
    try:
        assert isinstance(chat.runtime, ResponsesAdapter)
        continued = chat.chat("Call openrouter_live_number with value 7.")

        assert received_values == [7]
        assert result_label in (continued.last or "").lower()
        assert any(
            message.get("role") == "tool"
            and result_label in str(message.get("content", "")).lower()
            for message in continued.get_messages()
        )
    finally:
        _close_sync(continued, chat)
