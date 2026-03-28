import warnings

from chatsnack import Chat
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime import ChatCompletionsAdapter, ResponsesAdapter, ResponsesWebSocketAdapter


def test_implicit_runtime_defaults_to_responses_websocket(monkeypatch):
    monkeypatch.delenv("CHATSNACK_DEFAULT_RUNTIME", raising=False)
    chat = Chat()
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter)


def test_invalid_runtime_env_warns_once_and_falls_back(monkeypatch):
    monkeypatch.setenv("CHATSNACK_DEFAULT_RUNTIME", "banana")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        a = Chat()
        b = Chat()
    assert isinstance(a.runtime, ResponsesWebSocketAdapter)
    assert isinstance(b.runtime, ResponsesWebSocketAdapter)
    assert len(caught) == 1
    assert "Invalid CHATSNACK_DEFAULT_RUNTIME" in str(caught[0].message)


def test_explicit_runtime_keeps_precedence_over_env(monkeypatch):
    monkeypatch.setenv("CHATSNACK_DEFAULT_RUNTIME", "chat_completions")
    chat = Chat(runtime="responses")
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_explicit_session_forces_responses_websocket(monkeypatch):
    monkeypatch.setenv("CHATSNACK_DEFAULT_RUNTIME", "chat_completions")
    chat = Chat(session="inherit")
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter)


def test_reasoning_proxy_reads_and_writes_nested_params():
    chat = Chat(params=ChatParams(model="gpt-5.4", runtime="responses"))
    assert chat.reasoning.effort is None

    chat.reasoning.effort = "medium"
    chat.reasoning.summary = "auto"

    assert chat.params.responses["reasoning"]["effort"] == "medium"
    assert chat.params.responses["reasoning"]["summary"] == "auto"


def test_reasoning_default_injected_for_reasoning_model():
    params = ChatParams(model="gpt-5.4", runtime="responses")
    opts = params._get_responses_api_options()
    assert opts["reasoning"]["effort"] == "low"


def test_reasoning_default_not_injected_for_non_reasoning_model():
    params = ChatParams(model="gpt-4o", runtime="responses")
    opts = params._get_responses_api_options()
    assert "reasoning" not in opts


def test_reasoning_unknown_values_warn_but_pass_through():
    params = ChatParams(model="gpt-5.4", runtime="responses", responses={"reasoning": {"effort": "turbo"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        opts = params._get_responses_api_options()
    assert opts["reasoning"]["effort"] == "turbo"
    assert any("Unknown reasoning effort" in str(w.message) for w in caught)


def test_reasoning_known_model_warns_for_known_unsupported_effort():
    params = ChatParams(model="gpt-5.4", runtime="responses", responses={"reasoning": {"effort": "minimal"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        params._get_responses_api_options()
    assert any("known supported set" in str(w.message) and "gpt-5.4" in str(w.message) for w in caught)


def test_reasoning_known_model_warns_for_known_unsupported_summary():
    params = ChatParams(model="o3-mini", runtime="responses", responses={"reasoning": {"summary": "verbose"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        params._get_responses_api_options()
    assert any("Unknown reasoning summary" in str(w.message) for w in caught)


def test_reasoning_known_model_warns_for_supported_value_that_table_disallows():
    params = ChatParams(model="o3-mini", runtime="responses", responses={"reasoning": {"effort": "minimal"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        params._get_responses_api_options()
    assert any("known supported set" in str(w.message) and "o3-mini" in str(w.message) for w in caught)


def test_reasoning_non_reasoning_model_warns_generically():
    params = ChatParams(model="gpt-4o", runtime="responses", responses={"reasoning": {"effort": "low"}})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        params._get_responses_api_options()
    assert any("may not support reasoning options" in str(w.message) for w in caught)


def test_reasoning_capability_profiles_are_model_aware():
    gpt54 = ChatParams(model="gpt-5.4", runtime="responses")
    gpt5 = ChatParams(model="gpt-5", runtime="responses")
    o3 = ChatParams(model="o3-mini", runtime="responses")

    assert "xhigh" in gpt54._get_reasoning_capabilities()["effort"]
    assert "minimal" in gpt5._get_reasoning_capabilities()["effort"]
    assert gpt5._get_reasoning_capabilities()["effort"] != gpt54._get_reasoning_capabilities()["effort"]
    assert o3._get_reasoning_capabilities()["effort"] == frozenset({"low", "medium", "high"})


def test_params_session_wins_over_env_default(monkeypatch):
    """P1: authored params.session should beat CHATSNACK_DEFAULT_RUNTIME."""
    monkeypatch.setenv("CHATSNACK_DEFAULT_RUNTIME", "chat_completions")
    chat = Chat(params=ChatParams(session="inherit"))
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter), (
        "params.session='inherit' should force Responses WebSocket even when "
        "env says chat_completions"
    )


def test_params_session_new_wins_over_env_default(monkeypatch):
    """Variant: params.session='new' also beats env override."""
    monkeypatch.setenv("CHATSNACK_DEFAULT_RUNTIME", "chat_completions")
    chat = Chat(params=ChatParams(session="new"))
    assert isinstance(chat.runtime, ResponsesWebSocketAdapter)


def test_tool_order_is_not_forwarded_to_responses_api_options():
    params = ChatParams(
        model="gpt-5.4",
        runtime="responses",
        responses={
            "_tool_order": [("native", 0), ("fn", 0)],
            "include": ["web_search_call.action.sources"],
        },
    )
    opts = params._get_responses_api_options()
    assert "_tool_order" not in opts
    assert opts["include"] == ["web_search_call.action.sources"]
