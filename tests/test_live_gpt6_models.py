"""Opt-in provider checks for GPT-6 Sol, Luna, and GPT-6.1 Sol through chatsnack.

Run with OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1. These checks exercise
the Responses runtime and confirm supported reasoning requests complete.
"""

import asyncio
import os

import pytest
import pytest_asyncio

from chatsnack import Chat, ChatParams


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


@pytest.mark.parametrize(("model", "summary"), (
    ("gpt-6-sol", "concise"),
    ("gpt-6-luna", "concise"),
    ("gpt-6.1-sol", "auto"),
))
@pytest.mark.asyncio
async def test_live_gpt6_reasoning_summary(model, summary):
    """Each model accepts the request; earlier Sol and Luna return summaries."""
    chat = Chat(
        "Solve the selection problem carefully, then answer with only the best "
        "total value. Each item may be chosen once.",
        params=ChatParams(
            model=model,
            runtime="responses",
            max_tokens=2048,
            responses={
                "store": False,
                "reasoning": {"effort": "medium", "summary": summary},
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
        if model != "gpt-6.1-sol":
            assert any(text.strip() for text in summaries)
    finally:
        if completed is not None:
            await completed.close_a()
        await chat.close_a()
