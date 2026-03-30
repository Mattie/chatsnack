"""Tests for Responses continuation behavior.

Verifies that automatic previous_response_id injection is only applied
to WebSocket Responses (provider-side continuation), not plain HTTP
Responses (local message history continuation).
"""

import os
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from chatsnack.chat import Chat
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime.responses_common import ResponsesNormalizationMixin


# ── Helpers ───────────────────────────────────────────────────────────

class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


def _simple_response_payload(resp_id="resp_test_123"):
    return {
        "id": resp_id,
        "status": "completed",
        "model": "gpt-5.4-mini",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello"}],
            }
        ],
    }


def _make_responses_adapter_with_capture():
    """Build a ResponsesAdapter that captures its kwargs."""
    from chatsnack.runtime import ResponsesAdapter

    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj(_simple_response_payload())

    async def acreate(**kwargs):
        captured.update(kwargs)
        return _FakeObj(_simple_response_payload())

    ai = SimpleNamespace(
        client=SimpleNamespace(responses=SimpleNamespace(create=create)),
        aclient=SimpleNamespace(responses=SimpleNamespace(create=acreate)),
    )
    adapter = ResponsesAdapter(ai)
    return adapter, captured


# ═══════════════════════════════════════════════════════════════════════
# 1. HTTP Responses does NOT auto-inject previous_response_id
# ═══════════════════════════════════════════════════════════════════════

class TestHTTPResponsesNoContinuation:

    def test_http_responses_no_auto_previous_response_id(self):
        """Plain HTTP Responses should not auto-inject previous_response_id."""
        adapter, captured = _make_responses_adapter_with_capture()

        chat = Chat(system="test", runtime="responses")
        chat.runtime = adapter
        chat.model = "gpt-5.4-mini"

        # Seed last runtime metadata as if a previous turn happened.
        chat._last_runtime_metadata = {"response_id": "resp_previous_999"}
        chat.user("follow up question")

        # Run chat — this calls _cleaned_chat_completion with track_continuation=True
        chat.chat()

        # The HTTP adapter should NOT receive previous_response_id.
        assert "previous_response_id" not in captured or captured.get("previous_response_id") is None

    def test_http_responses_explicit_previous_response_id_passes_through(self):
        """Explicitly authored previous_response_id should still pass through on HTTP."""
        adapter, captured = _make_responses_adapter_with_capture()

        chat = Chat(system="test", runtime="responses")
        chat.runtime = adapter
        chat.model = "gpt-5.4-mini"

        # Set explicit previous_response_id in params.responses
        if chat.params.responses is None:
            chat.params.responses = {}
        chat.params.responses["previous_response_id"] = "resp_explicit_abc"

        chat.user("continue from explicit")
        chat.chat()

        # Explicit previous_response_id should reach the adapter.
        assert captured.get("previous_response_id") == "resp_explicit_abc"


# ═══════════════════════════════════════════════════════════════════════
# 2. WebSocket Responses STILL auto-injects previous_response_id
# ═══════════════════════════════════════════════════════════════════════

class TestWebSocketResponsesContinuation:

    def test_websocket_responses_auto_injects_previous_response_id(self):
        """WebSocket Responses should auto-inject previous_response_id."""
        from chatsnack.runtime.responses_websocket_adapter import (
            ResponsesWebSocketAdapter,
            ResponsesWebSocketSession,
        )

        chat = Chat(system="test")
        chat.model = "gpt-5.4-mini"

        # Set up a WebSocket adapter as the runtime.
        session = ResponsesWebSocketSession(mode="inherit")
        mock_client = MagicMock()
        ws_adapter = ResponsesWebSocketAdapter(mock_client, session=session)
        chat.runtime = ws_adapter

        # Verify the narrower helper returns True for WebSocket.
        assert chat._runtime_supports_provider_continuation() is True


# ═══════════════════════════════════════════════════════════════════════
# 3. Runtime helper classification
# ═══════════════════════════════════════════════════════════════════════

class TestRuntimeHelperClassification:

    def test_http_responses_not_provider_continuation(self):
        """ResponsesAdapter should NOT support provider continuation."""
        from chatsnack.runtime import ResponsesAdapter

        ai = SimpleNamespace(
            client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: None)),
        )
        adapter = ResponsesAdapter(ai)
        chat = Chat(system="test")
        chat.runtime = adapter

        assert chat._runtime_supports_continuation() is True  # still a Responses runtime
        assert chat._runtime_supports_provider_continuation() is False  # NOT provider continuation

    def test_websocket_responses_is_provider_continuation(self):
        """ResponsesWebSocketAdapter SHOULD support provider continuation."""
        from chatsnack.runtime.responses_websocket_adapter import (
            ResponsesWebSocketAdapter,
            ResponsesWebSocketSession,
        )

        session = ResponsesWebSocketSession(mode="inherit")
        mock_client = MagicMock()
        adapter = ResponsesWebSocketAdapter(mock_client, session=session)
        chat = Chat(system="test")
        chat.runtime = adapter

        assert chat._runtime_supports_continuation() is True
        assert chat._runtime_supports_provider_continuation() is True

    def test_no_runtime_not_provider_continuation(self):
        """No runtime should NOT support provider continuation."""
        chat = Chat(system="test")
        chat.runtime = None

        assert chat._runtime_supports_continuation() is False
        assert chat._runtime_supports_provider_continuation() is False

    def test_cc_adapter_not_provider_continuation(self):
        """ChatCompletionsAdapter should NOT support provider continuation."""
        from chatsnack.runtime import ChatCompletionsAdapter

        ai = SimpleNamespace(
            client=SimpleNamespace(chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: None)
            )),
        )
        adapter = ChatCompletionsAdapter(ai)
        chat = Chat(system="test")
        chat.runtime = adapter

        assert chat._runtime_supports_continuation() is False
        assert chat._runtime_supports_provider_continuation() is False


# ═══════════════════════════════════════════════════════════════════════
# 4. HTTP Responses tool follow-up resends message history
# ═══════════════════════════════════════════════════════════════════════

class TestHTTPResponsesToolFollowUp:

    def test_http_followup_after_seeded_metadata_no_previous_response_id(self):
        """Even after multiple turns with seeded metadata, HTTP Responses should not auto-inject previous_response_id."""
        adapter, captured = _make_responses_adapter_with_capture()

        chat = Chat(system="test", runtime="responses")
        chat.runtime = adapter
        chat.model = "gpt-5.4-mini"

        # Simulate having completed a first turn that returned a response_id.
        chat._last_runtime_metadata = {
            "response_id": "resp_first_turn",
            "previous_response_id": None,
            "usage": None,
            "assistant_phase": None,
            "provider_extras": None,
        }

        # Now do a follow-up that would normally trigger auto-continuation.
        chat.user("follow up after tool result")
        chat.chat()

        # HTTP Responses should NOT have auto-injected previous_response_id.
        assert "previous_response_id" not in captured or captured.get("previous_response_id") is None


# ═══════════════════════════════════════════════════════════════════════
# 5. Live HTTP Responses tool loop (requires API key)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None,
    reason="OPENAI_API_KEY is not set",
)
class TestLiveHTTPResponsesToolLoop:

    def test_live_http_responses_tool_loop(self):
        """Live: HTTP Responses tool loop with store=False should succeed."""
        from chatsnack.utensil import utensil

        call_tracker = {"called": False}

        @utensil(name="live_trackable_tool", description="Returns data about a query and tracks it was called.")
        def live_trackable_tool(query: str):
            call_tracker["called"] = True
            return {"result": f"tracked data for: {query}", "query": query}

        chat = Chat(
            system="You are a helpful assistant. When asked about data, use the live_trackable_tool.",
            utensils=[live_trackable_tool],
            auto_execute=True,
            auto_feed=True,
            tool_choice="required",
            runtime="responses",
        )
        chat.model = "gpt-5.4-mini"
        chat.user("What data do you have about chatsnack?")

        result = chat.chat()

        # Tool should have been called.
        assert call_tracker["called"], "Tool was never called"

        # Should have a final assistant response.
        final = result.last
        assert final is not None, "No final response"
        assert len(final) > 0, "Empty final response"
