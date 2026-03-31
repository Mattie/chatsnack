"""Tests for runtime-boundary isolation.

Verifies that Responses-only request options (reasoning, include, store, …)
are only sent to Responses-family runtimes, and never leak into Chat
Completions requests.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from chatsnack.runtime.chat_completions_adapter import ChatCompletionsAdapter
from chatsnack.runtime.responses_common import ResponsesNormalizationMixin


# ── Helpers ───────────────────────────────────────────────────────────

class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


def _make_cc_adapter():
    """Build a ChatCompletionsAdapter with a mock client that captures kwargs."""
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return _FakeObj({
            "model": "gpt-5.4-mini",
            "usage": {"total_tokens": 10},
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hi"},
            }],
        })

    ai = SimpleNamespace(
        client=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )
    )
    return ChatCompletionsAdapter(ai), captured


# ═══════════════════════════════════════════════════════════════════════
# 1. Regression: CC adapter strips Responses-only keys
# ═══════════════════════════════════════════════════════════════════════

class TestChatCompletionsStripsResponsesKeys:

    def test_reasoning_stripped_from_cc_request(self):
        """runtime='chat_completions' with gpt-5.4-mini must not pass 'reasoning'."""
        adapter, captured = _make_cc_adapter()
        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.4-mini",
            reasoning={"effort": "low"},
        )
        assert "reasoning" not in captured

    def test_no_responses_only_keys_in_cc_request(self):
        """No Responses-only keys should survive into Chat Completions."""
        adapter, captured = _make_cc_adapter()
        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.4-mini",
            reasoning={"effort": "low"},
            include=["reasoning.encrypted_content"],
            store=True,
            previous_response_id="resp_abc",
            text={"format": {"type": "text"}},
        )
        for key in ChatCompletionsAdapter._RESPONSES_ONLY_KEYS:
            assert key not in captured, f"Responses key '{key}' leaked into CC request"

    def test_legitimate_cc_keys_preserved(self):
        """Model, temperature, tools, etc. must still reach the CC call."""
        adapter, captured = _make_cc_adapter()
        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.4-mini",
            temperature=0.7,
            tools=[{"type": "function", "function": {"name": "f"}}],
            reasoning={"effort": "low"},  # should be stripped
        )
        assert captured["model"] == "gpt-5.4-mini"
        assert captured["temperature"] == 0.7
        assert captured["tools"] == [{"type": "function", "function": {"name": "f"}}]
        assert "reasoning" not in captured


# ═══════════════════════════════════════════════════════════════════════
# 2. Defensive adapter test: stream paths also strip keys
# ═══════════════════════════════════════════════════════════════════════

class TestChatCompletionsStreamStripsKeys:

    def test_stream_completion_strips_responses_keys(self):
        """stream_completion must also strip Responses-only keys."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return iter([
                _FakeObj({
                    "choices": [{"delta": {"content": "Hi"}, "finish_reason": None}],
                }),
                _FakeObj({
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "model": "gpt-5.4-mini",
                }),
            ])

        ai = SimpleNamespace(
            client=SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=create)
                )
            )
        )
        adapter = ChatCompletionsAdapter(ai)
        events = list(adapter.stream_completion(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-5.4-mini",
            reasoning={"effort": "low"},
            store=True,
        ))
        assert "reasoning" not in captured
        assert "store" not in captured


# ═══════════════════════════════════════════════════════════════════════
# 3. Positive: Responses runtime preserves authored reasoning
# ═══════════════════════════════════════════════════════════════════════

class TestResponsesRuntimePreservesReasoning:

    def test_responses_build_request_preserves_reasoning(self):
        """build_responses_request should preserve reasoning options."""
        mixin = ResponsesNormalizationMixin()
        messages = [{"role": "user", "content": "hello"}]
        kwargs = {
            "model": "gpt-5.4-mini",
            "reasoning": {"effort": "low"},
            "include": ["reasoning.encrypted_content"],
        }
        request = mixin.build_responses_request(messages, kwargs)
        assert request["reasoning"] == {"effort": "low"}
        assert request["include"] == ["reasoning.encrypted_content"]


# ═══════════════════════════════════════════════════════════════════════
# 4. Positive: WebSocket path also receives Responses options
# ═══════════════════════════════════════════════════════════════════════

class TestWebSocketReceivesResponsesOptions:

    def test_websocket_request_preserves_reasoning(self):
        """WebSocket adapter's _request_with_session should preserve Responses options."""
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
            "reasoning": {"effort": "low"},
            "store": False,
        }
        request = adapter._request_with_session(messages, kwargs)
        assert request["reasoning"] == {"effort": "low"}
        assert request["store"] is False


# ═══════════════════════════════════════════════════════════════════════
# 5. Integration: Chat runtime boundaries stay clean
# ═══════════════════════════════════════════════════════════════════════

class TestChatCCRuntimeNoResponsesLeak:

    def test_chat_cc_runtime_gpt54_mini_no_reasoning_kwarg(self):
        """Chat with runtime='chat_completions' and gpt-5.4-mini must not inject reasoning."""
        from chatsnack.chat import Chat
        from chatsnack.chat.mixin_params import ChatParams

        chat = Chat(
            system="test",
            runtime="chat_completions",
        )
        chat.model = "gpt-5.4-mini"
        chat.user("hello")

        # Simulate what _prepare_prompt_and_kwargs does: get params and
        # check whether Responses options would leak.
        kwargs = chat.params._get_non_none_params()

        # The gating is in _prepare_prompt_and_kwargs via
        # _runtime_supports_continuation(). Since we're on CC runtime,
        # _runtime_supports_continuation() returns False, and responses
        # options are never merged.  Verify params._get_non_none_params()
        # itself doesn't inject them (it shouldn't — they live in
        # params.responses, which is stripped from _get_non_none_params).
        assert "reasoning" not in kwargs
        assert "include" not in kwargs
        assert "store" not in kwargs

    def test_chat_responses_runtime_gpt54_mini_has_no_implicit_reasoning(self):
        """Chat with runtime='responses' should only send reasoning when authored."""
        from chatsnack.chat import Chat
        from chatsnack.chat.mixin_params import ChatParams

        chat = Chat(
            system="test",
            runtime="responses",
        )
        chat.model = "gpt-5.4-mini"

        responses_opts = chat.params._get_responses_api_options()
        assert "reasoning" not in responses_opts
