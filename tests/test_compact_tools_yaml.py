import json
import pytest
from pathlib import Path
from ruamel.yaml import YAML

from chatsnack import Chat, CHATSNACK_BASE_DIR
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime.types import NormalizedAssistantMessage, NormalizedCompletionResult, NormalizedToolCall, NormalizedToolFunction


def test_compact_tools_yaml_round_trip_and_internal_split(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data_dir = Path(CHATSNACK_BASE_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    authored = {
        "params": {
            "model": "gpt-5.4",
            "runtime": "responses",
            "tools": [
                {"web_search": {"external_web_access": True}},
                {
                    "crm": "CRM helper tools.",
                    "tools": [
                        {"get_customer": "Look up customer.", "customer_id": "str"},
                        {
                            "update_order_status": {
                                "description": "Update status",
                                "defer_loading": False,
                                "args": {
                                    "order_id": "str",
                                    "status": "Literal['pending', 'shipped']",
                                },
                                "required": ["order_id", "status"],
                            }
                        },
                    ],
                },
                "tool_search",
                "code_interpreter",
            ],
        },
        "messages": [{"system": "Be helpful."}],
    }

    yaml = YAML()
    with open(data_dir / "compact_tools.yml", "w", encoding="utf-8") as f:
        yaml.dump(authored, f)

    loaded = Chat(name="compact_tools")
    tools = loaded.params.get_tools()
    tool_types = [t.get("type") for t in tools]
    assert "tool_search" in tool_types
    assert "web_search" in tool_types
    assert "namespace" in tool_types

    namespace = [t for t in tools if t.get("type") == "namespace"][0]
    children = namespace["tools"]
    assert children[0]["defer_loading"] is True  # implicit when tool_search exists
    assert children[1]["defer_loading"] is False  # explicit override

    saved_text = loaded.yaml
    assert "- tool_search" in saved_text
    assert "- code_interpreter" in saved_text
    assert "crm: CRM helper tools." in saved_text


def test_client_tool_search_requires_handler(monkeypatch):
    chat = Chat(params=ChatParams(model="gpt-5.4", runtime="responses"))

    async def fake_submit(track_continuation=True, **kwargs):
        message = NormalizedAssistantMessage(
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="ts_1",
                    type="tool_search",
                    function=NormalizedToolFunction(name="tool_search", arguments=json.dumps({"goal": "find docs"})),
                    payload={"goal": "find docs"},
                )
            ],
        )
        return "[]", NormalizedCompletionResult(message=message)

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)

    with pytest.raises(RuntimeError, match="tool_search handler"):
        chat.chat()


def test_client_tool_search_handler_continues_loop(monkeypatch):
    chat = Chat(params=ChatParams(model="gpt-5.4", runtime="responses"))
    chat.tool_search_handler = lambda payload: {"matches": [{"name": "docs_lookup", "score": 0.9}], "payload": payload}

    calls = {"n": 0}

    async def fake_submit(track_continuation=True, **kwargs):
        message = NormalizedAssistantMessage(
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id="ts_1",
                    type="tool_search",
                    function=NormalizedToolFunction(name="tool_search", arguments=json.dumps({"goal": "find docs"})),
                    payload={"goal": "find docs"},
                )
            ],
        )
        return "[]", NormalizedCompletionResult(message=message)

    async def fake_follow_up(self, prompt, track_continuation=False, **kwargs):
        calls["n"] += 1
        return "done"

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(Chat, "_cleaned_chat_completion", fake_follow_up)

    out = chat.chat()
    assert out.last == "done"
    tool_turns = [m for m in out.messages if "tool" in m]
    assert tool_turns
    assert tool_turns[0]["tool"]["output_type"] == "tool_search_output"
    assert calls["n"] == 1
