"""Goal contracts for per-Chat OpenAI-compatible provider configuration.

These tests exercise the installed OpenAI SDK against a loopback HTTP server.
They prove the user-visible YAML -> Chat -> ask/chat/listen path while keeping
real provider credentials and network calls out of the offline suite.
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from chatsnack import Chat, utensil
from chatsnack.runtime import ResponsesAdapter


def _response_payload(model: str, text: str, *, tool_call: bool = False) -> dict:
    output = []
    if tool_call:
        output.extend(
            [
                {
                    "type": "reasoning",
                    "id": "rs_lookup",
                    "summary": [],
                    "encrypted_content": "encrypted-snack-state",
                },
                {
                    "type": "message",
                    "id": "msg_lookup",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Looking that up.",
                            "annotations": [],
                            "logprobs": [],
                        }
                    ],
                },
                {
                    "type": "function_call",
                    "id": "fc_lookup",
                    "call_id": "call_lookup",
                    "name": "lookup_snack",
                    "arguments": '{"name":"popcorn"}',
                    "status": "completed",
                },
            ]
        )
    else:
        output.append(
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "store": False,
        "temperature": 0.4,
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "usage": {
            "input_tokens": 3,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 2,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 5,
        },
    }


@pytest.fixture
def provider_server():
    """Run a temporary OpenAI-compatible endpoint and retain every request."""
    records: list[dict] = []
    records_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # noqa: A003 - stdlib hook name
            return

        def do_POST(self):  # noqa: N802 - stdlib hook name
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))))
            record = {
                "path": self.path,
                "authorization": self.headers.get("authorization"),
                "api_key": self.headers.get("api-key"),
                "organization": self.headers.get("openai-organization"),
                "project": self.headers.get("openai-project"),
                "ambient_private": self.headers.get("x-private-tenant"),
                "explicit_header": self.headers.get("x-explicit"),
                "openrouter_title": self.headers.get("x-openrouter-title"),
                "provider_secret": self.headers.get("x-provider-secret"),
                "body": body,
            }
            with records_lock:
                records.append(record)

            provider = "azure" if self.path.startswith("/azure/") else "openrouter"
            model = body.get("model", "unknown")
            text = f"{provider}:{model}"
            input_items = body.get("input") or []
            has_tool_output = any(
                item.get("type") == "function_call_output"
                for item in input_items
                if isinstance(item, dict)
            )
            needs_tool = bool(body.get("tools")) and not has_tool_output
            response = _response_payload(model, text, tool_call=needs_tool)

            if body.get("stream"):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("connection", "close")
                self.end_headers()
                delta_type = (
                    "response.content_part.delta"
                    if provider == "openrouter"
                    else "response.output_text.delta"
                )
                terminal_type = (
                    "response.done"
                    if provider == "openrouter"
                    else "response.completed"
                )
                events = (
                    {
                        "type": delta_type,
                        "sequence_number": 1,
                        "item_id": "msg_test",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": f"{provider}:",
                        "logprobs": [],
                    },
                    {
                        "type": delta_type,
                        "sequence_number": 2,
                        "item_id": "msg_test",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": model,
                        "logprobs": [],
                    },
                    {
                        "type": terminal_type,
                        "sequence_number": 3,
                        "response": response,
                    },
                )
                for event in events:
                    payload = json.dumps(event).encode()
                    self.wfile.write(b"data: " + payload + b"\n\n")
                    self.wfile.flush()
                if provider == "openrouter":
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                self.close_connection = True
                return

            payload = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield type(
            "ProviderServer",
            (),
            {
                "url": f"http://127.0.0.1:{server.server_port}",
                "records": records,
            },
        )()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _write_named_chat(
    root: Path,
    *,
    name: str,
    model: str,
    base_url: str,
    api_key_env: str,
    provider_extensions: bool = False,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    params = [
        "params:",
        f"  model: {model}",
        f"  base_url: {base_url}",
        f"  api_key_env: {api_key_env}",
    ]
    if provider_extensions:
        params.extend(
            (
                "  temperature: 0.4",
                "  responses:",
                "    extra_body:",
                "      presence_penalty: 0.3",
                "      frequency_penalty: 0.4",
            )
        )
    (root / f"{name}.yml").write_text(
        "\n".join(
            (
                *params,
                "messages:",
                "  - system: Respond with the provider route.",
                "",
            )
        ),
        encoding="utf-8",
    )


def test_goal_g1_named_openrouter_chat_asks_chats_and_streams(provider_server, tmp_path, monkeypatch):
    """G1: one named OpenRouter asset keeps the ordinary Chat interaction shape."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_TEST_KEY", "openrouter-sentinel")
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-openai-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "ambient-openai-project")
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS",
        "X-Private-Tenant: ambient-tenant-secret\nAuthorization: Bearer ambient-secret",
    )
    _write_named_chat(
        tmp_path,
        name="OpenRouterGoal",
        model="openai/gpt-oss-20b",
        base_url=f"{provider_server.url}/openrouter/api/v1",
        api_key_env="OPENROUTER_TEST_KEY",
        provider_extensions=True,
    )

    chat = Chat(name="OpenRouterGoal")
    assert isinstance(chat.runtime, ResponsesAdapter)
    assert chat.ask("Which route?") == "openrouter:openai/gpt-oss-20b"
    continued = chat.chat("Continue once.")
    assert continued.last == "openrouter:openai/gpt-oss-20b"
    continued_again = continued.chat("Continue twice.")
    assert continued_again.last == "openrouter:openai/gpt-oss-20b"

    chat.stream = True
    assert "".join(chat.listen("Stream it.")) == "openrouter:openai/gpt-oss-20b"

    relevant = [record for record in provider_server.records if record["path"].startswith("/openrouter/")]
    assert relevant
    assert {record["path"] for record in relevant} == {"/openrouter/api/v1/responses"}
    assert {record["authorization"] for record in relevant} == {"Bearer openrouter-sentinel"}
    assert all(record["organization"] is None for record in relevant)
    assert all(record["project"] is None for record in relevant)
    assert all(record["ambient_private"] is None for record in relevant)
    assert all("base_url" not in record["body"] for record in relevant)
    assert all("api_key_env" not in record["body"] for record in relevant)
    assert all(record["body"].get("store") is False for record in relevant)
    assert all("previous_response_id" not in record["body"] for record in relevant)
    assert all(record["body"]["temperature"] == 0.4 for record in relevant)
    assert all(record["body"]["presence_penalty"] == 0.3 for record in relevant)
    assert all(record["body"]["frequency_penalty"] == 0.4 for record in relevant)

    continued_again.close()
    continued.close()
    chat.close()


def test_goal_g1b_continuations_keep_the_root_credential_binding(
    provider_server,
    monkeypatch,
):
    """G1b: a conversation lineage does not re-read its named credential."""
    base_url = f"{provider_server.url}/openrouter/api/v1"
    monkeypatch.setenv("OPENROUTER_LINEAGE_KEY", "lineage-original")
    root = Chat(
        "Keep using the provider selected for this conversation.",
        model="openrouter/lineage-model",
        base_url=base_url,
        api_key_env="OPENROUTER_LINEAGE_KEY",
    )

    first = root.chat("First turn.")
    monkeypatch.setenv("OPENROUTER_LINEAGE_KEY", "lineage-rotated")
    second = first.chat("Second turn.")
    assert second.ask("Read from the continued binding.") == (
        "openrouter:openrouter/lineage-model"
    )

    fresh = Chat(
        "Use the current environment for a new conversation.",
        model="openrouter/lineage-model",
        base_url=base_url,
        api_key_env="OPENROUTER_LINEAGE_KEY",
    )
    assert fresh.ask("Read from the fresh binding.") == (
        "openrouter:openrouter/lineage-model"
    )

    relevant = [
        record
        for record in provider_server.records
        if record["path"].startswith("/openrouter/")
    ]
    assert [record["authorization"] for record in relevant] == [
        "Bearer lineage-original",
        "Bearer lineage-original",
        "Bearer lineage-original",
        "Bearer lineage-rotated",
    ]

    fresh.close()
    second.close()
    first.close()
    root.close()


@pytest.mark.asyncio
async def test_goal_g1c_continuation_keeps_ownership_of_the_opened_client(
    provider_server,
    monkeypatch,
):
    """G1c: closing a returned continuation closes the client that made its request."""
    monkeypatch.setenv("OPENROUTER_OWNER_KEY", "owner-sentinel")
    root = Chat(
        "Keep the request client with this conversation.",
        model="openrouter/owner-model",
        base_url=f"{provider_server.url}/openrouter/api/v1",
        api_key_env="OPENROUTER_OWNER_KEY",
    )

    continued = await root.chat_a("Continue once.")

    assert continued.ai is root.ai
    assert root.ai._aclient is not None
    await continued.close_a()
    assert root.ai._aclient is None
    await root.close_a()


@pytest.mark.asyncio
async def test_goal_g2_modern_azure_v1_uses_standard_responses_routes(provider_server, monkeypatch):
    """G2: Azure v1 uses a normal OpenAI client and deployment-as-model."""
    monkeypatch.setenv("AZURE_CHAT_TEST_KEY", "azure-sentinel")
    chat = Chat(
        "Use the Azure deployment.",
        model="snack-deployment",
        base_url=f"{provider_server.url}/azure/openai/v1/",
        api_key_env="AZURE_CHAT_TEST_KEY",
    )

    assert isinstance(chat.runtime, ResponsesAdapter)
    assert await chat.ask_a("Which route?") == "azure:snack-deployment"
    chat.stream = True
    listener = await chat.listen_a("Stream it.")
    assert "".join([chunk async for chunk in listener]) == "azure:snack-deployment"

    relevant = [record for record in provider_server.records if record["path"].startswith("/azure/")]
    assert {record["path"] for record in relevant} == {"/azure/openai/v1/responses"}
    assert {record["authorization"] for record in relevant} == {"Bearer azure-sentinel"}
    assert all("api-version" not in record["path"] for record in relevant)
    assert all("/deployments/" not in record["path"] for record in relevant)
    assert all(record["body"]["model"] == "snack-deployment" for record in relevant)

    await chat.close_a()


@pytest.mark.asyncio
async def test_goal_g3_mixed_providers_stay_isolated_through_copy_and_utensil_continuation(
    provider_server,
    monkeypatch,
):
    """G3: concurrent providers retain endpoints and keys through child Chats."""
    monkeypatch.setenv("OPENROUTER_ISOLATION_KEY", "openrouter-isolation")
    monkeypatch.setenv("AZURE_ISOLATION_KEY", "azure-isolation")

    @utensil
    def lookup_snack(name: str) -> dict:
        """Look up one snack for the provider-isolation Goal."""
        return {"name": name, "rating": "crunchy"}

    openrouter = Chat(
        "Use the lookup utensil.",
        model="openrouter/tool-model",
        base_url=f"{provider_server.url}/openrouter/api/v1",
        api_key_env="OPENROUTER_ISOLATION_KEY",
        utensils=[lookup_snack],
    )
    azure = Chat(
        "Answer directly.",
        model="azure-isolation-deployment",
        base_url=f"{provider_server.url}/azure/openai/v1/",
        api_key_env="AZURE_ISOLATION_KEY",
    )

    copied_openrouter = openrouter.copy()
    tool_thread, azure_thread = await asyncio.gather(
        copied_openrouter.chat_a("Look up popcorn."),
        azure.chat_a("Answer once."),
    )

    assert tool_thread.last == "openrouter:openrouter/tool-model"
    assert azure_thread.last == "azure:azure-isolation-deployment"

    for record in provider_server.records:
        if record["path"].startswith("/openrouter/"):
            assert record["authorization"] == "Bearer openrouter-isolation"
            assert record["body"]["model"] == "openrouter/tool-model"
        elif record["path"].startswith("/azure/"):
            assert record["authorization"] == "Bearer azure-isolation"
            assert record["body"]["model"] == "azure-isolation-deployment"
        else:
            pytest.fail(f"Unexpected provider route: {record['path']}")

    tool_follow_up = next(
        record
        for record in provider_server.records
        if any(
            item.get("type") == "function_call_output"
            for item in record["body"].get("input", [])
            if isinstance(item, dict)
        )
    )
    replayed_call = next(
        item
        for item in tool_follow_up["body"]["input"]
        if item.get("type") == "function_call"
    )
    assert replayed_call["id"] == "fc_lookup"
    assert replayed_call["call_id"] == "call_lookup"
    assert replayed_call["status"] == "completed"

    await asyncio.gather(
        tool_thread.close_a(),
        azure_thread.close_a(),
        copied_openrouter.close_a(),
        openrouter.close_a(),
        azure.close_a(),
    )
