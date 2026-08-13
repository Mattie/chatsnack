"""Goal proof for inspecting a fully composed saved prompt without submitting it."""

from __future__ import annotations

import json

import pytest

from chatsnack import Chat, Text


@pytest.mark.asyncio
async def test_saved_prompt_composes_exact_messages_without_an_outer_request(
    tmp_path,
    monkeypatch,
):
    """A caller can reuse living prompt assets without sending the outer chat."""

    Text(
        name="ComposeVoice",
        content="Keep JSON and template braces exactly as supplied.",
    ).save(tmp_path / "ComposeVoice.txt")
    Chat(name="ComposePrelude").system("Included operating context.").save(
        tmp_path / "ComposePrelude.yml"
    )

    asset_path = tmp_path / "ComposeWorkflow.yml"
    (
        Chat(name="ComposeWorkflow")
        .system("{text.ComposeVoice}")
        .include("ComposePrelude")
        .user("Payload: {payload}")
        .save(asset_path)
    )

    chat = Chat(name="ComposeWorkflow")
    chat.load(asset_path)
    original_messages = json.loads(json.dumps(chat.messages))
    original_yaml = chat.yaml
    outer_requests = 0

    async def reject_outer_request(*args, **kwargs):
        nonlocal outer_requests
        outer_requests += 1
        raise AssertionError("compose_a() submitted the outer chat")

    monkeypatch.setattr(chat, "_cleaned_chat_completion", reject_outer_request)

    messages = await chat.compose_a(
        payload='{"template":"{keep_me}","object":{"value":1}}'
    )

    assert messages == [
        {
            "role": "system",
            "content": "Keep JSON and template braces exactly as supplied.",
        },
        {"role": "system", "content": "Included operating context."},
        {
            "role": "user",
            "content": 'Payload: {"template":"{keep_me}","object":{"value":1}}',
        },
    ]
    assert outer_requests == 0
    assert chat.messages == original_messages
    assert chat.yaml == original_yaml
