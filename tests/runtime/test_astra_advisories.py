"""Steers: Astra diagnostics use the submitting SDK endpoint and preserve authored options."""

from types import SimpleNamespace
from copy import deepcopy
import json
import warnings

import httpx
import openai
import pytest

from chatsnack.aiclient import AiClient
from chatsnack.runtime import ChatCompletionsAdapter, ResponsesAdapter, ResponsesWebSocketAdapter


def _fake_adapter(adapter_type, monkeypatch, base_url="https://api.openai.com/v1/"):
    """Fake only the SDK boundary; retain each adapter's request and streaming paths."""
    calls = []
    response = {"id": "resp_astra", "model": "gpt-6-astra", "status": "completed",
                "output": [], "output_text": "ok"}
    event = SimpleNamespace(type="response.completed",
                            response=SimpleNamespace(model_dump=lambda: response))

    def create(**kwargs):
        """Capture submitted options and supply the endpoint's minimal response."""
        calls.append(kwargs)
        if adapter_type is ChatCompletionsAdapter:
            choice = {"finish_reason": "stop", "delta": {"content": "ok"},
                      "message": {"role": "assistant", "content": "ok"}}
            result = {"id": "cc_astra", "model": "gpt-6-astra", "choices": [choice]}
        else:
            result = {"type": "response.completed", "response": response}
        if kwargs.get("stream"):
            return iter([result])
        return result if adapter_type is ChatCompletionsAdapter else response

    async def create_a(**kwargs):
        """Match the SDK's asynchronous return shape, including stream iteration."""
        result = create(**kwargs)
        if kwargs.get("stream"):
            async def chunks():
                for chunk in result:
                    yield chunk
            return chunks()
        return result

    ai = AiClient()
    ai.client = SimpleNamespace(base_url=base_url, responses=SimpleNamespace(create=create),
                                chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    ai.aclient = SimpleNamespace(base_url=base_url, responses=SimpleNamespace(create=create_a),
                                 chat=SimpleNamespace(completions=SimpleNamespace(create=create_a)))
    adapter = adapter_type(ai)
    if adapter_type is ResponsesWebSocketAdapter:
        class Connection:
            """Expose a completed response to both SDK WebSocket reader paths."""
            response = SimpleNamespace(create=create)

            def __iter__(self):
                return iter([event])

            async def __aiter__(self):
                yield event

        connection = Connection()
        monkeypatch.setattr(adapter, "_connect_sync", lambda: connection)

        async def connect_a():
            connection.response = SimpleNamespace(create=create_a)
            return connection

        monkeypatch.setattr(adapter, "_connect_async", connect_a)
    return adapter, calls


@pytest.mark.parametrize("adapter_type", (ResponsesAdapter, ChatCompletionsAdapter, ResponsesWebSocketAdapter))
@pytest.mark.parametrize("async_mode", (False, True))
@pytest.mark.parametrize("stream", (False, True))
@pytest.mark.asyncio
async def test_astra_sampling_warns_unchanged_on_every_transport_path(adapter_type, async_mode, stream, monkeypatch):
    adapter, calls = _fake_adapter(adapter_type, monkeypatch)
    adapter.ai_client.base_url = "https://provider.example/v1/"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.example/v1/")
    method = "stream_completion" if stream else "create_completion"
    if async_mode:
        method += "_a"
    with pytest.warns(UserWarning, match="gpt-6-astra.*temperature.*unchanged"):
        result = getattr(adapter, method)([{"role": "user", "content": "Hi"}],
                                          model="gpt-6-astra", temperature=0.25)
        if stream:
            events = [event async for event in result] if async_mode else list(result)
            assert events[-1].type == "completed"
        elif async_mode:
            await result
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.25


@pytest.mark.parametrize("model,base_url", (
    ("gpt-5.4", "https://api.openai.com/v1/"),
    ("gpt-6-astra-pro", "https://api.openai.com/v1/"),
    ("openai/gpt-6-astra", "https://openrouter.ai/api/v1/"),
    ("gpt-6-astra", "https://provider.example/openai/v1/"),
    ("gpt-6-astra", "https://api.openai.com.example/v1/"),
    ("gpt-6-astra", None),
))
def test_sampling_diagnostics_require_verified_model_and_resolved_endpoint(model, base_url, monkeypatch):
    adapter, calls = _fake_adapter(ResponsesAdapter, monkeypatch, base_url)
    # Authored settings and the environment must not override the actual SDK destination.
    adapter.ai_client.base_url = "https://api.openai.com/v1/"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1/")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        adapter.create_completion([], model=model, temperature=0.25, top_p=0.8)
    assert not caught
    assert calls[0]["temperature"] == 0.25
    assert calls[0]["top_p"] == 0.8


@pytest.mark.parametrize("adapter_type", (ResponsesAdapter, ChatCompletionsAdapter))
def test_astra_advisories_preserve_all_authored_options(adapter_type, monkeypatch):
    adapter, calls = _fake_adapter(adapter_type, monkeypatch)
    options = {"model": "gpt-6-astra", "temperature": 0, "top_p": 0.8, "top_logprobs": 2}
    if adapter_type is ChatCompletionsAdapter:
        options.update(logprobs=False, tools=[{"type": "function", "function": {"name": "stock"}}])
    else:
        options["include"] = ["message.output_text.logprobs", "reasoning.encrypted_content"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        adapter.create_completion([], **options)
    messages = " ".join(str(w.message) for w in caught)
    for key in ("temperature", "top_p", "top_logprobs"):
        assert key in messages
        assert calls[0][key] == options[key]
    if adapter_type is ChatCompletionsAdapter:
        assert "logprobs" in messages and "tools require Responses" in messages
        assert calls[0]["tools"] == options["tools"]
        assert calls[0]["logprobs"] is False
    else:
        assert "message.output_text.logprobs" in messages
        assert calls[0]["include"] == options["include"]


@pytest.mark.parametrize("options,expected_warning", (
    ({"extra_body": {"temperature": 0.3}}, "temperature"),
    ({"temperature": 0.3, "extra_body": {"temperature": None}}, None),
    ({"temperature": 0.3, "extra_body": {"model": "provider-alias"}}, None),
    ({"top_logprobs": 2, "extra_body": {"top_logprobs": None}}, None),
))
def test_http_advisories_follow_the_prepared_sdk_body(options, expected_warning):
    """Check actual SDK extension precedence without changing authored dictionaries."""
    original = deepcopy(options)
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "resp_options", "output": [], "status": "completed"})

    with openai.OpenAI(api_key="offline-test-key", base_url="https://api.openai.com/v1/",
                       http_client=httpx.Client(transport=httpx.MockTransport(respond))) as sdk:
        ai = AiClient()
        ai.client = sdk
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ResponsesAdapter(ai).create_completion([], model="gpt-6-astra", **options)
    assert options == original
    assert len(bodies) == 1
    if expected_warning:
        assert expected_warning in " ".join(str(w.message) for w in caught)
        assert bodies[0][expected_warning] is not None
    else:
        assert not caught
        if "top_logprobs" in options:
            assert bodies[0]["top_logprobs"] is None
