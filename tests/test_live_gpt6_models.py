"""Opt-in provider checks for GPT-6 Sol and Luna through chatsnack.

Run with OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1. These checks exercise
the Responses runtime and verify that a requested reasoning summary is returned.
"""

import asyncio
import os

import pytest
import pytest_asyncio

from chatsnack import Chat, ChatParams, utensil


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY")
    or os.getenv("CHATSNACK_RUN_LIVE_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="Requires OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)


@pytest_asyncio.fixture(autouse=True)
async def _drain_live_callbacks():
    """Let AnyIO release its HTTP workers before pytest closes the event loop."""
    yield
    await asyncio.sleep(0)


@pytest.mark.parametrize("model", ("gpt-6-sol", "gpt-6-luna"))
@pytest.mark.asyncio
async def test_live_gpt6_reasoning_summary(model):
    """Each known model accepts a summary request and returns one through Chat."""
    chat = Chat(
        "Solve the selection problem carefully, then answer with only the best "
        "total value. Each item may be chosen once.",
        params=ChatParams(
            model=model,
            runtime="responses",
            max_tokens=2048,
            responses={
                "store": False,
                "reasoning": {"effort": "medium", "summary": "concise"},
            },
        ),
    )
    completed = None
    try:
        completed = await chat.chat_a(
            "Capacity is 23. Items have (weight, value): A (9, 23), "
            "B (7, 19), C (13, 34), D (6, 16), E (11, 29), F (5, 12), "
            "G (8, 22), H (12, 31). What is the maximum total value?"
        )
        assert (completed.response or "").strip()
        summaries = [
            part.get("text", "")
            for entry in completed.messages
            for part in entry.get("reasoning", {}).get("summary", [])
        ]
        assert any(text.strip() for text in summaries)
    finally:
        if completed is not None:
            await completed.close_a()
        await chat.close_a()


@pytest.mark.parametrize("model", ("gpt-6-sol", "gpt-6-luna"))
@pytest.mark.asyncio
async def test_live_gpt6_chat_completions_utensil_without_reasoning(model):
    """The public Chat API can request a real function call at none effort."""
    @utensil
    def stock(sku: str):
        """Look up the stock for a snack SKU."""
        return {"sku": sku, "available": 3}

    chat = Chat(
        "Call stock when asked about inventory.",
        model=model,
        runtime="chat_completions",
        reasoning_effort="none",
        utensils=[stock],
        tool_choice="required",
        auto_execute=False,
    )
    completed = None
    try:
        completed = await chat.chat_a("Call stock for SKU popcorn and report availability.")
        tool_calls = [
            call
            for message in completed.get_messages()
            for call in message.get("tool_calls", [])
        ]
        assert any(call.get("function", {}).get("name") == "stock" for call in tool_calls)
    finally:
        if completed is not None:
            await completed.close_a()
        await chat.close_a()
