"""Opt-in live Goal for Wonder AUTO, utensils, durable history, and HTTP SSE.

Run with CHATSNACK_RUN_MUSE_LIVE=1 and MODEL_API_KEY supplied by Joydex:
    python -m pytest -q tests/test_live_muse_wonder.py
"""

import asyncio
import os
import secrets

import pytest
from loguru import logger


# Decide before importing chatsnack: its ordinary .env loading cannot opt in.
_RUN_LIVE = os.getenv("CHATSNACK_RUN_MUSE_LIVE", "").lower() in {"1", "true", "yes", "on"}
pytestmark = pytest.mark.skipif(
    not _RUN_LIVE, reason="Set CHATSNACK_RUN_MUSE_LIVE=1 to run paid Meta requests.",
)

from chatsnack import Chat, utensil
from chatsnack.runtime import ResponsesAdapter


@pytest.mark.asyncio
async def test_goal_live_wonder_auto_tools_continuation_save_and_sse(tmp_path, monkeypatch):
    """Prove the model-only workflow against Meta with a private, per-run tool fact."""
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_AZURE_ENDPOINT",
                 "CHATSNACK_DEFAULT_RUNTIME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    label = "snack-" + secrets.token_hex(4)
    calls = []
    owned = []

    @utensil
    def lookup_snack(name: str) -> dict:
        """Return the current secret-free stock label for the requested snack."""
        calls.append(name)
        return {"name": name, "stock_label": label}

    logger.disable("chatsnack")
    try:
        root = Chat(
            "Answer briefly. For stock questions call lookup_snack, then report its stock_label.",
            model="muse-wonder-1.0", utensils=[lookup_snack],
            params={"max_tokens": 2048, "responses": {"timeout": 60,
                    "reasoning": {"effort": "minimal", "summary": "auto"}}},
        )
        owned.append(root)
        assert isinstance(root.runtime, ResponsesAdapter)
        assert root.params.base_url == "https://api.meta.ai/v1"
        assert root.params.api_key_env == "MODEL_API_KEY"
        assert root.params.responses["include"] == ["reasoning.encrypted_content"]
        answer = await asyncio.wait_for(root.ask_a("Reply with only POPSICLE."), 90)
        assert "POPSICLE" in answer.upper()
        copied = root.copy()
        owned.append(copied)
        first = await asyncio.wait_for(copied.chat_a("Look up the stock label for popcorn."), 120)
        owned.append(first)
        assert calls and all(name.lower() == "popcorn" for name in calls)
        assert label in first.last
        assert first.ai is copied.ai
        continued = await asyncio.wait_for(
            first.chat_a("Repeat that exact stock label from our history without calling a tool."), 90,
        )
        owned.append(continued)
        assert label in continued.last
        assert continued.ai is first.ai
        path = tmp_path / "WonderLive.yml"
        continued.save(path)
        # Durable history includes opaque reasoning, rather than bare server IDs.
        assert "encrypted_content:" in path.read_text(encoding="utf-8")
        loaded = Chat()
        owned.append(loaded)
        loaded.load(path)
        assert loaded.params.base_url == root.params.base_url
        assert loaded.params.api_key_env == root.params.api_key_env
        loaded.stream = True
        listener = await loaded.listen_a("Repeat the stock label from history, with no tool call.")

        async def consume():
            """Bound the whole stream, including the initial reasoning delay."""
            return "".join([chunk async for chunk in listener])

        streamed = await asyncio.wait_for(consume(), 90)
        assert label in streamed
        assert listener.is_complete
    finally:
        for chat in reversed(owned):
            await chat.close_a()
        logger.enable("chatsnack")


@pytest.mark.asyncio
async def test_goal_live_wonder_replays_an_unencrypted_saved_turn(tmp_path, monkeypatch):
    """An imported turn with an unusable reasoning ID can still continue on Meta."""
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_AZURE_ENDPOINT",
                 "CHATSNACK_DEFAULT_RUNTIME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    label = "snack-" + secrets.token_hex(4)
    path = tmp_path / "LegacyWonder.yml"
    path.write_text(
        "params:\n  model: muse-wonder-1.0\n  max_tokens: 2048\n  responses:\n"
        "    include: []\n    reasoning:\n      effort: minimal\n      summary: auto\n"
        "messages:\n  - system: Repeat stock labels exactly, with no explanation.\n"
        f"  - user: The stock label is {label}. Remember it.\n"
        "  - reasoning:\n      item_id: rs_expired_import\n      summary: []\n"
        f"  - assistant: {label}\n", encoding="utf-8",
    )
    logger.disable("chatsnack")
    chat = continued = None
    try:
        chat = Chat(name="LegacyWonder")
        with pytest.warns(UserWarning, match="Omitting Meta reasoning items without encrypted_content"):
            continued = await asyncio.wait_for(
                chat.chat_a("Repeat the stock label from our previous exchange."), 90,
            )
        assert label in continued.last
        continued.save(path)
        assert "rs_expired_import" in path.read_text(encoding="utf-8")
        assert continued.params.responses["include"] == []
    finally:
        for owned in (continued, chat):
            if owned is not None:
                await owned.close_a()
        logger.enable("chatsnack")
