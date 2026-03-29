import json
import pytest
from pathlib import Path
from ruamel.yaml import YAML

from chatsnack import Chat, CHATSNACK_BASE_DIR
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime.types import NormalizedAssistantMessage, NormalizedCompletionResult, NormalizedToolCall, NormalizedToolFunction
from chatsnack.yamlformat import _normalize_data_on_load


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


def test_tool_search_handler_propagates_across_chat_continuations(monkeypatch):
    handled = {"n": 0}

    def handler(payload):
        handled["n"] += 1
        return {"ok": True, "payload": payload}

    chat = Chat(params=ChatParams(model="gpt-5.4", runtime="responses"), tool_search_handler=handler)

    async def fake_submit(self, track_continuation=True, **kwargs):
        message = NormalizedAssistantMessage(
            content=None,
            tool_calls=[
                NormalizedToolCall(
                    id=f"ts_{handled['n'] + 1}",
                    type="tool_search",
                    function=NormalizedToolFunction(name="tool_search", arguments=json.dumps({"goal": "find docs"})),
                    payload={"goal": "find docs"},
                )
            ],
        )
        return "[]", NormalizedCompletionResult(message=message)

    async def fake_follow_up(self, prompt, track_continuation=False, **kwargs):
        return "done"

    monkeypatch.setattr(Chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(Chat, "_cleaned_chat_completion", fake_follow_up)

    first = chat.chat("turn one")
    second = first.chat("turn two")

    assert first.last == "done"
    assert second.last == "done"
    assert handled["n"] == 2


def test_load_normalization_preserves_legacy_native_tools_when_tools_present():
    data = {
        "params": {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup_weather",
                        "description": "Lookup weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                        },
                    },
                },
            ],
            "native_tools": [{"type": "web_search"}],
        }
    }

    normalized = _normalize_data_on_load(data)
    params = normalized["params"]
    assert isinstance(params["tools"], list)
    assert params["tools"][0]["type"] == "function"
    assert params["native_tools"] == [{"type": "web_search"}]


def test_child_tool_round_trip_preserves_optional_args_without_defaults():
    """P1a: optional args with no default must stay optional after save/load."""
    from chatsnack.compact_tools import _expand_child_tool, _serialize_child_tool

    child_provider = {
        "type": "function",
        "function": {
            "name": "search_orders",
            "description": "Search orders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "region": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    }

    compact = _serialize_child_tool(child_provider, implicit_defer=False)
    # Should use structured form because region is optional without default
    assert isinstance(compact.get("search_orders"), dict), (
        "Expected structured form for optional args without defaults, got inline form"
    )
    assert "args" in compact["search_orders"]
    assert compact["search_orders"]["required"] == ["query"]

    expanded = _expand_child_tool(compact)
    assert expanded["function"]["parameters"]["required"] == ["query"]


def test_child_tool_inline_form_when_all_args_required():
    """Simple child tools with all-required args should use inline form."""
    from chatsnack.compact_tools import _serialize_child_tool

    child_provider = {
        "type": "function",
        "function": {
            "name": "get_user",
            "description": "Get user by ID.",
            "parameters": {
                "type": "object",
                "properties": {"user_id": {"type": "string"}},
                "required": ["user_id"],
            },
        },
    }

    compact = _serialize_child_tool(child_provider, implicit_defer=False)
    assert compact.get("get_user") == "Get user by ID."
    assert compact.get("user_id") == "str"


def test_child_tool_inline_form_when_optional_args_have_defaults():
    """Optional args with defaults can use inline form faithfully."""
    from chatsnack.compact_tools import _expand_child_tool, _serialize_child_tool

    child_provider = {
        "type": "function",
        "function": {
            "name": "list_items",
            "description": "List items.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        },
    }

    compact = _serialize_child_tool(child_provider, implicit_defer=False)
    # Should use inline form since limit has a default
    assert compact.get("list_items") == "List items."
    assert compact.get("limit") == "int = 10"

    expanded = _expand_child_tool(compact)
    assert expanded["function"]["parameters"]["required"] == ["query"]


def test_structured_child_tool_preserves_provider_level_fields():
    """Structured child tools should keep future provider-level child fields."""
    from chatsnack.compact_tools import _expand_child_tool, _serialize_child_tool

    compact = {
        "search_accounts": {
            "description": "Search accounts.",
            "args": {"query": "str"},
            "strict": True,
        }
    }

    expanded = _expand_child_tool(compact)
    assert expanded["strict"] is True
    assert expanded["function"]["parameters"]["properties"]["query"] == {"type": "string"}

    reserialized = _serialize_child_tool(expanded, implicit_defer=False)
    assert reserialized["search_accounts"]["strict"] is True
    assert reserialized["search_accounts"]["args"]["query"] == "str"


def test_child_tool_serializer_uses_structured_form_for_provider_level_fields():
    """Serializer should avoid inline form when child-level extras must be preserved."""
    from chatsnack.compact_tools import _expand_child_tool, _serialize_child_tool

    child_provider = {
        "type": "function",
        "strict": True,
        "function": {
            "name": "lookup_order",
            "description": "Lookup an order.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    }

    compact = _serialize_child_tool(child_provider, implicit_defer=False)
    assert isinstance(compact["lookup_order"], dict)
    assert compact["lookup_order"]["strict"] is True

    expanded = _expand_child_tool(compact)
    assert expanded["strict"] is True
    assert expanded["function"]["parameters"]["required"] == ["order_id"]


def test_client_tool_search_args_compiled_to_schema():
    """P1b: tool_search with execution:client and compact args should compile."""
    from chatsnack.compact_tools import parse_tools_authoring, serialize_tools_authoring

    authored = [
        {"tool_search": {"execution": "client", "args": {"goal": "str"}}},
    ]

    parsed = parse_tools_authoring(authored)
    assert parsed[0]["type"] == "tool_search"
    assert parsed[0]["execution"] == "client"
    assert parsed[0]["args"]["properties"]["goal"] == {"type": "string"}
    assert parsed[0]["args"]["required"] == ["goal"]

    serialized = serialize_tools_authoring(parsed)
    assert serialized[0]["tool_search"]["args"] == {"goal": "str"}

    reparsed = parse_tools_authoring(serialized)
    assert reparsed[0]["args"]["properties"]["goal"] == {"type": "string"}


def test_client_tool_search_args_yaml_round_trip(tmp_path, monkeypatch):
    """Full YAML round-trip for client tool_search with compact args."""
    monkeypatch.chdir(tmp_path)
    data_dir = Path(CHATSNACK_BASE_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)
    authored = {
        "params": {
            "model": "gpt-5.4",
            "tools": [
                {"tool_search": {"execution": "client", "args": {"goal": "str"}}},
            ],
        },
        "messages": [{"system": "Help."}],
    }

    yaml = YAML()
    with open(data_dir / "client_ts.yml", "w", encoding="utf-8") as f:
        yaml.dump(authored, f)

    loaded = Chat(name="client_ts")
    tools = loaded.params.get_tools()
    ts = [t for t in tools if t.get("type") == "tool_search"][0]
    assert ts["execution"] == "client"
    assert ts["args"]["properties"]["goal"] == {"type": "string"}

    saved = loaded.yaml
    assert "goal: str" in saved


def test_mixed_tool_order_round_trips(tmp_path, monkeypatch):
    """P2a: Mixed tool surface should round-trip in authored order."""
    monkeypatch.chdir(tmp_path)
    data_dir = Path(CHATSNACK_BASE_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    authored = {
        "params": {
            "model": "gpt-4o",
            "tools": [
                "tool_search",
                {
                    "type": "function",
                    "function": {
                        "name": "my_func",
                        "description": "A function.",
                        "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
                    },
                },
                {"web_search": {"filters": {"allowed_domains": ["docs.python.org"]}}},
            ],
        },
        "messages": [{"system": "Test."}],
    }

    yaml = YAML()
    with open(data_dir / "order_test.yml", "w", encoding="utf-8") as f:
        yaml.dump(authored, f)

    loaded = Chat(name="order_test")
    tools = loaded.params.get_tools()
    types = [t.get("type") for t in tools]
    assert types == ["tool_search", "function", "web_search"], f"Expected original order, got {types}"

    # Save and verify order persists in the YAML text.
    saved = loaded.yaml
    # Check that tool_search appears before my_func, which appears before web_search.
    ts_pos = saved.index("tool_search")
    fn_pos = saved.index("my_func")
    ws_pos = saved.index("web_search")
    assert ts_pos < fn_pos < ws_pos, (
        f"Expected tool_search < my_func < web_search in YAML, "
        f"got positions {ts_pos}, {fn_pos}, {ws_pos}"
    )


def test_set_tools_preserves_interleaved_order():
    """P2a: set_tools() -> get_tools() should preserve interleaved order."""
    from chatsnack.chat.mixin_params import ChatParams

    p = ChatParams()
    p.set_tools([
        {"type": "web_search"},
        {"type": "function", "function": {"name": "fn", "description": "f", "parameters": {"type": "object", "properties": {}}}},
        {"type": "tool_search"},
    ])
    types = [t.get("type") for t in p.get_tools()]
    assert types == ["web_search", "function", "tool_search"]
