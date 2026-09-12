"""Opt-in real-model contracts for portable Responses conversation history.

Run with CHATSNACK_RUN_LIVE_TESTS=1. CHATSNACK_LIVE_MODEL selects the primary
model (GPT-6 Astra); CHATSNACK_LIVE_REASONING_MODEL selects a second reasoning
model (GPT-5.4). Both must reason at high effort and preserve encrypted items.
"""

import os
import json
import secrets
from itertools import combinations
from ruamel.yaml import YAML

import pytest

from chatsnack import Chat, ChatParams, utensil
from chatsnack.runtime.conversation import copy_value
from chatsnack.runtime.responses_common import ResponsesNormalizationMixin


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY")
    or os.getenv("CHATSNACK_RUN_LIVE_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="Requires OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)


def expected_replay(items):
    """Allow only the documented omission of optional, empty provider defaults.

    Keep this wire-level oracle independent of chatsnack's conversation codec:
    IDs, phases, encrypted bytes, nonempty metadata, and unknown fields must
    still compare exactly against the original provider response.
    """
    expected = copy_value(items)
    for item in expected:
        kind = item.get("type")
        if kind in {"reasoning", "function_call", "function_call_output"}:
            if item.get("status") in (None, "completed"):
                item.pop("status", None)
        if kind == "reasoning":
            for key in ("content", "encrypted_content"):
                if item.get(key) in (None, "", []):
                    item.pop(key, None)
        parts = item.get("content")
        if (kind == "message" and item.get("role") == "assistant"
                and isinstance(parts, list) and len(parts) == 1
                and parts[0].get("type") == "output_text"
                and isinstance(parts[0].get("text"), str)):
            if item.get("phase") in (None, ""):
                item.pop("phase", None)
            for part in item.get("content", []):
                if part.get("type") == "output_text" and part.get("logprobs") in (None, []):
                    part.pop("logprobs", None)
    return expected


@pytest.mark.parametrize("session, store", [(None, False), (None, True), ("inherit", False)],
                         ids=["http-stateless", "http-stored", "websocket"])
@pytest.mark.parametrize("model", [
    os.getenv("CHATSNACK_LIVE_MODEL", "gpt-6-astra"),
    os.getenv("CHATSNACK_LIVE_REASONING_MODEL", "gpt-5.4"),
], ids=["primary-model", "encrypted-reasoning-model"])
@pytest.mark.asyncio
async def test_live_saved_tool_history_replays_and_retains_reasoning(
    tmp_path, monkeypatch, session, store, model, record_property,
):
    """Solve a tool-supplied problem, then replay its reasoning and private receipt."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path / "data"))
    proof = "STOCK_" + secrets.token_hex(12)
    executions, requests, outputs = [], [], []
    reasoning_tokens = []
    # Exhaustive enumeration supplies an answer independent of the live model.
    offers = [("A", 9, 23), ("B", 7, 19), ("C", 13, 34), ("D", 6, 16),
              ("E", 11, 29), ("F", 5, 12), ("G", 8, 22), ("H", 12, 31)]
    capacity = 23
    feasible = [subset for size in range(len(offers) + 1)
                for subset in combinations(offers, size)
                if sum(item[1] for item in subset) <= capacity]
    best_value = max(sum(item[2] for item in subset) for subset in feasible)
    best_ids = min("".join(item[0] for item in subset) for subset in feasible
                   if sum(item[2] for item in subset) == best_value)
    build_request = ResponsesNormalizationMixin.build_responses_request
    normalize_completion = ResponsesNormalizationMixin.normalize_completion

    def capture_request(adapter, messages, kwargs):
        """Observe provider requests while leaving the live transport untouched."""
        request = build_request(adapter, messages, kwargs)
        requests.append(copy_value(request))
        return request

    monkeypatch.setattr(ResponsesNormalizationMixin, "build_responses_request", capture_request)

    def capture_response(adapter, response, request):
        """Retain original wire items as an independent oracle for cold replay."""
        wire = response if isinstance(response, dict) else response.model_dump(
            by_alias=True, exclude_unset=True, warnings=False,
        )
        outputs.append(copy_value(wire.get("output", [])))
        reasoning_tokens.append(
            ((wire.get("usage") or {}).get("output_tokens_details") or {})
            .get("reasoning_tokens", 0)
        )
        return normalize_completion(adapter, response, request)

    monkeypatch.setattr(ResponsesNormalizationMixin, "normalize_completion", capture_response)

    @utensil
    def stock(sku: str):
        """Get stock, selection offers, and a private receipt for one snack SKU."""
        executions.append(sku)
        return {"available": 12, "proof": proof, "offers": offers, "capacity": capacity}

    source = Chat(
        "Use stock exactly once for the requested SKU. After the tool returns, reply "
        "with the solution to this problem: offers are [ID, weight, value]. Select "
        "each offer at most once, maximizing total value with total weight at most "
        "capacity. Break ties by the lexicographically smallest string of sorted IDs. "
        "Reply with only READY: followed by that string, without spaces. "
        "Do not repeat the proof token until explicitly asked. "
        "On later questions, use the existing tool result without calling stock again.",
        params=ChatParams(
            runtime="responses", session=session,
            model=model,
            max_tokens=8192, tool_choice="required", auto_feed=1,
            responses={"store": store, "include": ["reasoning.encrypted_content"],
                       "reasoning": {"effort": "high", "summary": "auto"}},
        ),
        utensils=[stock],
    ).user("Check stock for {sku}.")
    chats = [source]
    try:
        continued = await source.chat_a(sku="snack-box")
        chats.append(continued)
        assert executions == ["snack-box"]
        assert "{sku}" in source.yaml
        history = copy_value(continued.messages)
        reasoning = [entry["reasoning"] for entry in history if "reasoning" in entry]
        calls = [entry["tool_call"] for entry in history if "tool_call" in entry]
        record_property("model", model)
        record_property("reasoning_items", len(reasoning))
        record_property("reasoning_effort", "high")
        record_property("reasoning_tokens", sum(reasoning_tokens))
        assert len(outputs) == 2
        record_property("problem_reasoning_tokens", reasoning_tokens[1])
        assert (continued.response or "").strip() == "READY:" + best_ids
        assert all(request["reasoning"]["effort"] == "high" for request in requests)
        assert reasoning_tokens[1] > 0, "The tool-result problem must use reasoning tokens"
        assert any(item.get("encrypted_content") for item in outputs[1]
                   if item.get("type") == "reasoning")
        assert reasoning and any(item.get("encrypted_content") for item in reasoning)
        provider_items = expected_replay([item for output in outputs for item in output])
        tool_outputs = [item for item in requests[-1]["input"] if item.get("type") == "function_call_output"]
        assert len(tool_outputs) == 1 and json.loads(tool_outputs[0]["output"])["proof"] == proof
        expected_prefix = requests[0]["input"] + expected_replay(outputs[0]) + tool_outputs + expected_replay(outputs[1])
        assert len(calls) == 1 and calls[0]["item_id"] and calls[0]["call_id"]
        assert any(entry.get("assistant", {}).get("item_id") for entry in history if isinstance(entry.get("assistant"), dict))
        assert "export_state" not in continued.yaml
        for entry in YAML(typ="safe").load(continued.yaml)["messages"]:
            if "reasoning" in entry:
                assert entry["reasoning"].get("summary") != []
                assert entry["reasoning"].get("content") != []
            for role in ("reasoning", "assistant", "tool_call"):
                block = entry.get(role)
                if isinstance(block, dict):
                    assert block.get("status") != "completed"
            assistant = entry.get("assistant")
            if isinstance(assistant, dict):
                for part in (assistant.get("provider_extras") or {}).get("content", []):
                    assert part.get("annotations") != []
                    assert part.get("logprobs") != []
        assert all(proof not in part.get("text", "")
                   for item in provider_items if item.get("type") == "message"
                   for part in item.get("content", []))

        # Exercise the live continuation shortcut before testing cold restoration.
        continued.params.tool_choice = "none"
        request_start = len(requests)
        warm = await continued.chat_a("Reply with only the proof token from the stock result.")
        chats.append(warm)
        assert (warm.response or "").strip() == proof
        warm_request = requests[request_start]
        if session or store:
            assert warm_request.get("previous_response_id")
            assert len(warm_request["input"]) == 1
        else:
            assert "previous_response_id" not in warm_request

        path = tmp_path / "conversation.yml"
        continued.save(str(path))
        restored = Chat(utensils=[stock])
        restored.load(str(path))
        chats.append(restored)
        assert restored.messages == history
        request_start = len(requests)
        reply = await restored.chat_a("Reply with only the proof token from the stock result.")
        chats.append(reply)
        assert (reply.response or "").strip() == proof
        replay = requests[request_start]
        assert "previous_response_id" not in replay
        assert replay["input"][:-1] == expected_prefix
        assert executions == ["snack-box"]
        assert restored.messages == history
        assert [item["call_id"] for item in replay["input"] if item.get("type") == "function_call"] == [calls[0]["call_id"]]
        assert [item["id"] for item in replay["input"] if item.get("type") == "reasoning"] == [item["item_id"] for item in reasoning]
        replayed_provider_items = [item for item in replay["input"]
                                   if item.get("type") != "function_call_output"
                                   and item.get("role") not in {"system", "developer", "user"}]
        assert replayed_provider_items == provider_items
    finally:
        for chat in reversed(chats):
            await chat.close_a()
