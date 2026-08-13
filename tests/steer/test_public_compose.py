"""Steer tests for the public prompt-composition boundary."""

from __future__ import annotations

import json

import pytest

from chatsnack import Chat


@pytest.mark.asyncio
async def test_request_submission_uses_the_same_literal_brace_composition(monkeypatch):
    chat = Chat("Policy: {policy}").user("Payload: {payload}")
    fillings = {
        "policy": "Keep {named} placeholders literal.",
        "payload": '{"query":"{article.title}","limit":3}',
    }
    captured_messages = None

    async def capture_completion(prompt, **kwargs):
        nonlocal captured_messages
        captured_messages = json.loads(prompt)
        return "ok"

    monkeypatch.setattr(chat, "_cleaned_chat_completion", capture_completion)

    composed = await chat.compose_a(**fillings)
    prompt, response = await chat._submit_for_response_and_prompt(**fillings)

    assert response == "ok"
    assert json.loads(prompt) == composed == captured_messages
    assert composed == [
        {
            "role": "system",
            "content": "Policy: Keep {named} placeholders literal.",
        },
        {
            "role": "user",
            "content": 'Payload: {"query":"{article.title}","limit":3}',
        },
    ]


@pytest.mark.asyncio
async def test_compose_preserves_model_backed_chat_filling_semantics(
    tmp_path,
    monkeypatch,
):
    child_path = tmp_path / "ComposeChild.yml"
    Chat(name="ComposeChild").user("Generate one ingredient.").save(child_path)

    parent_path = tmp_path / "ComposeParent.yml"
    Chat(name="ComposeParent").user("Ingredient: {chat.ComposeChild}").save(
        parent_path
    )
    parent = Chat(name="ComposeParent")
    parent.load(parent_path)
    child_queries = []

    async def answer_child(chat, usermsg=None, files=None, images=None, **fillings):
        child_queries.append(chat.name)
        return "salt {and} pepper"

    monkeypatch.setattr(Chat, "ask_a", answer_child)

    messages = await parent.compose_a()

    assert messages == [
        {"role": "user", "content": "Ingredient: salt {and} pepper"}
    ]
    assert child_queries == ["ComposeChild"]
