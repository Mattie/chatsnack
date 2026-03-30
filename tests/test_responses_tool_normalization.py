"""Tests for Responses API function-tool normalization.

Verifies that the shared compile step in ResponsesNormalizationMixin
flattens nested Chat Completions function tools into the Responses API
request shape, while preserving provider-native tools, tool order, and
the internal Chat Completions representation.
"""

from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest

from chatsnack.runtime.responses_common import ResponsesNormalizationMixin
from chatsnack.chat.mixin_params import ChatParams


# ── Fixtures ──────────────────────────────────────────────────────────

def _nested_function_tool(name="my_tool", description="Does stuff",
                          parameters=None, strict=None):
    """Build a Chat Completions-shaped function tool (nested)."""
    func = {"name": name, "description": description}
    if parameters is not None:
        func["parameters"] = parameters
    if strict is not None:
        func["strict"] = strict
    return {"type": "function", "function": func}


def _flat_function_tool(name="my_tool", description="Does stuff",
                        parameters=None, strict=None):
    """Build a Responses API-shaped function tool (flat)."""
    tool = {"type": "function", "name": name, "description": description}
    if parameters is not None:
        tool["parameters"] = parameters
    if strict is not None:
        tool["strict"] = strict
    return tool


_SAMPLE_PARAMS = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


# ═══════════════════════════════════════════════════════════════════════
# 1. Unit: nested function tool → flat Responses tool
# ═══════════════════════════════════════════════════════════════════════

class TestNormalizeToolsFlattening:

    def test_nested_function_tool_flattened(self):
        """A nested function tool should be flattened to the Responses shape."""
        nested = _nested_function_tool(
            name="trackable_tool",
            description="Returns data about a query.",
            parameters=_SAMPLE_PARAMS,
        )
        [result] = ResponsesNormalizationMixin._normalize_tools_for_responses_request([nested])
        assert result["type"] == "function"
        assert result["name"] == "trackable_tool"
        assert result["description"] == "Returns data about a query."
        assert result["parameters"] == _SAMPLE_PARAMS
        # Must NOT have the nested "function" key.
        assert "function" not in result

    def test_strict_survives_flattening(self):
        """The strict flag inside the nested function payload must be preserved."""
        nested = _nested_function_tool(name="strict_tool", strict=True)
        [result] = ResponsesNormalizationMixin._normalize_tools_for_responses_request([nested])
        assert result["strict"] is True

    def test_strict_false_survives(self):
        nested = _nested_function_tool(name="t", strict=False)
        [result] = ResponsesNormalizationMixin._normalize_tools_for_responses_request([nested])
        assert result["strict"] is False

    def test_already_flat_function_tool_passes_through(self):
        """A tool already in flat Responses shape should not be altered."""
        flat = _flat_function_tool(name="already_flat", parameters=_SAMPLE_PARAMS)
        [result] = ResponsesNormalizationMixin._normalize_tools_for_responses_request([flat])
        assert result == flat

    def test_unknown_top_level_keys_preserved(self):
        """Extra top-level keys on the nested tool dict should survive."""
        nested = _nested_function_tool(name="t")
        nested["custom_flag"] = 42
        [result] = ResponsesNormalizationMixin._normalize_tools_for_responses_request([nested])
        assert result["custom_flag"] == 42


# ═══════════════════════════════════════════════════════════════════════
# 2. Unit: provider-native tools pass through unchanged
# ═══════════════════════════════════════════════════════════════════════

class TestNativeToolsPassthrough:

    @pytest.mark.parametrize("tool_type", [
        "web_search", "file_search", "tool_search",
        "code_interpreter", "image_generation", "mcp", "namespace",
    ])
    def test_native_tool_passes_through(self, tool_type):
        tool = {"type": tool_type, "some_config": "value"}
        [result] = ResponsesNormalizationMixin._normalize_tools_for_responses_request([tool])
        assert result is tool  # exact same object, not copied


# ═══════════════════════════════════════════════════════════════════════
# 3. Unit: mixed tool lists preserve authored order
# ═══════════════════════════════════════════════════════════════════════

class TestMixedToolOrder:

    def test_order_preserved_in_mixed_list(self):
        tools = [
            {"type": "web_search"},
            _nested_function_tool(name="fn_a"),
            {"type": "code_interpreter"},
            _nested_function_tool(name="fn_b", strict=True),
            {"type": "file_search", "vector_store_ids": ["vs_1"]},
        ]
        result = ResponsesNormalizationMixin._normalize_tools_for_responses_request(tools)
        assert len(result) == 5
        assert result[0]["type"] == "web_search"
        assert result[1]["name"] == "fn_a"
        assert result[1]["type"] == "function"
        assert "function" not in result[1]
        assert result[2]["type"] == "code_interpreter"
        assert result[3]["name"] == "fn_b"
        assert result[3]["strict"] is True
        assert result[4]["type"] == "file_search"

    def test_empty_list(self):
        assert ResponsesNormalizationMixin._normalize_tools_for_responses_request([]) == []


# ═══════════════════════════════════════════════════════════════════════
# 4. Unit: Chat Completions path still sees nested shape
# ═══════════════════════════════════════════════════════════════════════

class TestChatCompletionsShapeUnchanged:

    def test_get_tools_returns_nested_shape(self):
        """ChatParams.get_tools() must still return the nested Chat Completions shape."""
        from chatsnack.utensil import utensil, get_openai_tools

        @utensil(name="cc_test_tool", description="Test tool for CC shape")
        def cc_test_tool(query: str):
            return {"result": query}

        tools_list = get_openai_tools([cc_test_tool])
        params = ChatParams()
        params.set_tools(tools_list)
        retrieved = params.get_tools()
        # Should have the nested "function" key for function tools.
        fn_tools = [t for t in retrieved if t.get("type") == "function"]
        assert len(fn_tools) >= 1
        assert "function" in fn_tools[0]
        assert fn_tools[0]["function"]["name"] == "cc_test_tool"


# ═══════════════════════════════════════════════════════════════════════
# 5. Integration-style: build_responses_request flattens tools
# ═══════════════════════════════════════════════════════════════════════

class TestBuildResponsesRequestIntegration:

    def test_build_request_flattens_function_tools(self):
        """build_responses_request should produce flat function tools."""
        mixin = ResponsesNormalizationMixin()
        messages = [{"role": "user", "content": "hello"}]
        kwargs = {
            "model": "gpt-5.4-mini",
            "tools": [
                _nested_function_tool(
                    name="trackable_tool",
                    description="Tracks stuff.",
                    parameters=_SAMPLE_PARAMS,
                    strict=True,
                ),
                {"type": "web_search"},
            ],
        }
        request = mixin.build_responses_request(messages, kwargs)
        tools = request["tools"]
        assert len(tools) == 2
        fn_tool = tools[0]
        assert fn_tool["type"] == "function"
        assert fn_tool["name"] == "trackable_tool"
        assert fn_tool["strict"] is True
        assert "function" not in fn_tool
        # Web search passes through.
        assert tools[1]["type"] == "web_search"

    def test_build_request_without_tools(self):
        """build_responses_request should work fine when no tools are provided."""
        mixin = ResponsesNormalizationMixin()
        messages = [{"role": "user", "content": "hi"}]
        request = mixin.build_responses_request(messages, {"model": "gpt-5.4-mini"})
        assert "tools" not in request


# ═══════════════════════════════════════════════════════════════════════
# 6. Integration-style: Chat with runtime="responses" builds flat tools
# ═══════════════════════════════════════════════════════════════════════

class TestChatResponsesRuntimeToolShape:

    def test_chat_responses_runtime_flat_tools(self):
        """Chat(..., runtime='responses') should send flat function tools."""
        from chatsnack.chat import Chat
        from chatsnack.utensil import utensil

        @utensil(name="resp_shape_test", description="Shape test tool")
        def resp_shape_test(query: str):
            return {"result": query}

        chat = Chat(
            system="test",
            utensils=[resp_shape_test],
            runtime="responses",
        )
        chat.model = "gpt-5.4-mini"
        chat.user("test query")

        # Build the request the same way the adapter does.
        mixin = ResponsesNormalizationMixin()
        params = chat.params
        tools = params.get_tools()
        kwargs = params._get_non_none_params()
        kwargs["tools"] = tools
        kwargs.update(params._get_responses_api_options())

        messages = [{"role": "user", "content": "test query"}]
        request = mixin.build_responses_request(messages, kwargs)

        fn_tools = [t for t in request.get("tools", []) if t.get("type") == "function"]
        assert len(fn_tools) >= 1
        for ft in fn_tools:
            assert "function" not in ft, f"Function tool still nested: {ft}"
            assert "name" in ft


# ═══════════════════════════════════════════════════════════════════════
# 7. Integration-style: WebSocket session='inherit' builds flat tools
# ═══════════════════════════════════════════════════════════════════════

class TestWebSocketSessionToolShape:

    def test_websocket_request_builds_flat_tools(self):
        """WebSocket adapter's _request_with_session should produce flat tools."""
        from chatsnack.runtime.responses_websocket_adapter import (
            ResponsesWebSocketAdapter,
            ResponsesWebSocketSession,
        )

        session = ResponsesWebSocketSession(mode="inherit")
        mock_client = MagicMock()
        adapter = ResponsesWebSocketAdapter(mock_client, session=session)

        messages = [{"role": "user", "content": "hello"}]
        kwargs = {
            "model": "gpt-5.4-mini",
            "tools": [
                _nested_function_tool(name="ws_tool", parameters=_SAMPLE_PARAMS, strict=True),
            ],
        }
        request = adapter._request_with_session(messages, kwargs)
        fn_tool = request["tools"][0]
        assert fn_tool["type"] == "function"
        assert fn_tool["name"] == "ws_tool"
        assert fn_tool["strict"] is True
        assert "function" not in fn_tool


# ═══════════════════════════════════════════════════════════════════════
# 8. WebSocket error surface carries provider details
# ═══════════════════════════════════════════════════════════════════════

class TestWebSocketErrorSurface:

    def test_response_failed_includes_provider_details(self):
        """response.failed events should surface provider_message, response_id, response_status."""
        from chatsnack.runtime.responses_websocket_adapter import (
            ResponsesWebSocketAdapter,
            ResponsesWebSocketSession,
            ResponsesWebSocketTransportError,
        )

        session = ResponsesWebSocketSession(mode="inherit")
        mock_client = MagicMock()
        adapter = ResponsesWebSocketAdapter(mock_client, session=session)

        # Build a fake response.failed event that the adapter should see.
        resp_error = SimpleNamespace(code="invalid_tools", message="Tool schema is invalid")
        resp = SimpleNamespace(error=resp_error, id="resp_abc", status="failed")
        event = SimpleNamespace(type="response.failed", response=resp)

        # Mock the underlying client's stream so that _stream_sync_request
        # processes our response.failed event from its for-loop.
        stream_events = iter([event])
        mock_client.responses.stream.return_value = stream_events

        # Invoke the real streaming code path and assert on the raised error.
        dummy_request = {"input": "test"}  # minimal placeholder request
        with pytest.raises(ResponsesWebSocketTransportError) as exc_info:
            # Consume the generator to trigger processing of the event.
            list(adapter._stream_sync_request(dummy_request, stream=True))

        exc = exc_info.value
        assert exc.details["provider_code"] == "invalid_tools"
        assert exc.details["provider_message"] == "Tool schema is invalid"
        assert exc.details["response_id"] == "resp_abc"
        assert exc.details["response_status"] == "failed"
