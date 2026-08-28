"""Focused Steers for per-Chat endpoint and credential binding."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from snapclass import SnapclassError

from chatsnack import Chat, ChatParams
from chatsnack.runtime import (
    ChatCompletionsAdapter,
    ResponsesAdapter,
    ResponsesWebSocketAdapter,
)


@pytest.mark.parametrize(
    "params",
    (
        ChatParams(base_url="https://example.test/v1"),
        ChatParams(api_key_env="EXAMPLE_API_KEY"),
        ChatParams(base_url="  ", api_key_env="EXAMPLE_API_KEY"),
        ChatParams(base_url="https://example.test/v1", api_key_env="  "),
    ),
)
def test_client_configuration_requires_nonblank_atomic_pair(params):
    with pytest.raises(ValueError, match="base_url.*api_key_env.*together"):
        Chat(params=params)


def test_named_credential_is_resolved_when_chat_is_bound(monkeypatch):
    monkeypatch.setenv("BOUND_PROVIDER_KEY", "provider-sentinel")

    chat = Chat(
        base_url=" https://example.test/v1/ ",
        api_key_env=" BOUND_PROVIDER_KEY ",
    )

    assert chat.params.base_url == "https://example.test/v1/"
    assert chat.params.api_key_env == "BOUND_PROVIDER_KEY"
    assert chat.ai.api_key == "provider-sentinel"
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_named_autoload_endpoint_overrides_preserve_saved_params(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("AUTOLOAD_PROVIDER_KEY", "provider-sentinel")
    saved = Chat(
        name="SavedProvider",
        params=ChatParams(
            model="saved-model",
            temperature=0.42,
            runtime="chat_completions",
        ),
    )
    saved.system("Load this saved prompt.")
    saved.save()

    loaded = Chat(
        name="SavedProvider",
        model="override-model",
        base_url="https://provider.example/v1",
        api_key_env="AUTOLOAD_PROVIDER_KEY",
    )

    assert loaded.system_message == "Load this saved prompt."
    assert loaded.model == "override-model"
    assert loaded.temperature == 0.42
    assert loaded.params.runtime == "chat_completions"
    assert loaded.params.base_url == "https://provider.example/v1"
    assert loaded.params.api_key_env == "AUTOLOAD_PROVIDER_KEY"
    assert isinstance(loaded.runtime, ChatCompletionsAdapter)


def test_named_new_chat_still_applies_endpoint_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("NEW_PROVIDER_KEY", "provider-sentinel")

    chat = Chat(
        name="NewProvider",
        base_url="https://provider.example/v1",
        api_key_env="NEW_PROVIDER_KEY",
    )

    assert chat.params.base_url == "https://provider.example/v1"
    assert chat.params.api_key_env == "NEW_PROVIDER_KEY"
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_mapping_client_params_run_custom_endpoint_request(monkeypatch):
    monkeypatch.setenv("MAPPING_PROVIDER_KEY", "provider-sentinel")
    captured = {}

    async def fake_create_completion_a(self, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            message=SimpleNamespace(content="mapping-reply", tool_calls=[])
        )

    monkeypatch.setattr(
        ResponsesAdapter,
        "create_completion_a",
        fake_create_completion_a,
    )

    chat = Chat(
        params={
            "model": "provider/model",
            "base_url": "https://provider.example/v1",
            "api_key_env": "MAPPING_PROVIDER_KEY",
        }
    )

    assert isinstance(chat.params, ChatParams)
    assert isinstance(chat.runtime, ResponsesAdapter)
    assert chat.ask("Prove the mapping request ran.") == "mapping-reply"
    assert captured["messages"][-1] == {
        "role": "user",
        "content": "Prove the mapping request ran.",
    }
    assert captured["kwargs"]["model"] == "provider/model"


def test_missing_named_credential_fails_before_sdk_client_creation(monkeypatch):
    monkeypatch.delenv("MISSING_PROVIDER_KEY", raising=False)

    with pytest.raises(ValueError, match="MISSING_PROVIDER_KEY.*not set or is blank"):
        Chat(
            base_url="https://example.test/v1",
            api_key_env="MISSING_PROVIDER_KEY",
        )


@pytest.mark.parametrize(
    "legacy_env",
    ("OPENAI_AZURE_ENDPOINT", "OPENAI_API_BASE"),
)
@pytest.mark.parametrize("client_attr", ("client", "aclient"))
def test_legacy_endpoint_environment_fails_closed_with_overlapping_openai_key(
    monkeypatch,
    legacy_env,
    client_attr,
):
    monkeypatch.setenv("OPENAI_API_KEY", "overlapping-openai-sentinel")
    monkeypatch.setenv(legacy_env, "https://legacy-provider.example/v1")
    for other_env in {"OPENAI_AZURE_ENDPOINT", "OPENAI_API_BASE"} - {legacy_env}:
        monkeypatch.delenv(other_env, raising=False)

    chat = Chat()
    assert chat.ai._client is None
    assert chat.ai._aclient is None

    with pytest.raises(ValueError) as exc_info:
        getattr(chat.ai, client_attr)

    message = str(exc_info.value)
    assert legacy_env in message
    assert "base_url" in message
    assert "api_key_env" in message
    assert "https://legacy-provider.example/v1" not in message
    assert chat.ai._client is None
    assert chat.ai._aclient is None


def test_authored_client_configuration_takes_precedence_over_legacy_environment(
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_AZURE_ENDPOINT", "https://legacy-azure.example")
    monkeypatch.setenv("OPENAI_API_BASE", "https://legacy-base.example/v1")
    monkeypatch.setenv("AUTHORED_PROVIDER_KEY", "authored-sentinel")

    chat = Chat(
        base_url="https://authored.example/v1",
        api_key_env="AUTHORED_PROVIDER_KEY",
    )

    assert chat.ai.base_url == "https://authored.example/v1"
    assert chat.ai.api_key == "authored-sentinel"
    assert str(chat.ai.client.base_url) == "https://authored.example/v1/"
    chat.close()


@pytest.mark.parametrize("legacy_key", ("api_base", "deployment", "api_type", "api_version"))
def test_python_legacy_client_fields_are_unexpected_keywords(legacy_key):
    with pytest.raises(TypeError, match=rf"unexpected keyword argument '{legacy_key}'"):
        Chat(**{legacy_key: "legacy"})

    with pytest.raises(TypeError, match=rf"unexpected keyword argument '{legacy_key}'"):
        ChatParams(**{legacy_key: "legacy"})


def test_yaml_legacy_fields_raise_one_migration_error(tmp_path):
    path = tmp_path / "LegacyProvider.yml"
    path.write_text(
        """params:
  model: deployment-name
  api_base: https://legacy.example/openai
  deployment: deployment-name
  api_type: azure
  api_version: 2024-10-21
messages:
  - user: Hello
""",
        encoding="utf-8",
    )

    with pytest.raises(SnapclassError) as exc_info:
        Chat().load(path)

    message = str(exc_info.value)
    assert "api_base, api_type, api_version, deployment" in message
    assert "base_url" in message
    assert "api_key_env" in message
    assert "deployment name in model" in message


def test_fresh_load_binds_named_credential_and_reset_keeps_it(tmp_path, monkeypatch):
    path = tmp_path / "RebindProvider.yml"
    monkeypatch.setenv("REBIND_PROVIDER_KEY", "saved-sentinel")
    Chat(
        name="RebindProvider",
        base_url="https://saved.example/v1",
        api_key_env="REBIND_PROVIDER_KEY",
    ).save(path)

    loaded = Chat()
    loaded.load(path)
    assert loaded.ai.api_key == "saved-sentinel"
    assert isinstance(loaded.runtime, ResponsesAdapter)

    monkeypatch.setenv("REBIND_PROVIDER_KEY", "reset-sentinel")
    loaded.reset()
    assert loaded.ai.api_key == "saved-sentinel"
    assert isinstance(loaded.runtime, ResponsesAdapter)

    fresh = Chat()
    fresh.load(path)
    assert fresh.ai.api_key == "reset-sentinel"


@pytest.mark.asyncio
async def test_reset_after_async_use_keeps_the_bound_client(monkeypatch):
    monkeypatch.setenv("RESET_PROVIDER_KEY", "bound-sentinel")
    chat = Chat(
        base_url="https://reset.example/v1",
        api_key_env="RESET_PROVIDER_KEY",
    )
    original_ai = chat.ai
    original_runtime = chat.runtime
    async_client = _AsyncCloseProbe()
    chat.ai.aclient = async_client

    monkeypatch.setenv("RESET_PROVIDER_KEY", "rotated-sentinel")
    chat.reset()

    assert chat.ai is original_ai
    assert chat.runtime is original_runtime
    assert chat.ai.api_key == "bound-sentinel"
    assert async_client.closed is False
    await chat.close_a()
    assert async_client.closed is True


def test_active_load_with_same_binding_keeps_client_and_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SAME_PROVIDER_KEY", "same-sentinel")
    path = tmp_path / "SameProvider.yml"
    Chat(
        name="SameProvider",
        model="updated-model",
        base_url="https://same.example/v1",
        api_key_env="SAME_PROVIDER_KEY",
    ).user("Loaded history.").save(path)

    active = Chat(
        params=ChatParams(
            model="original-model",
            base_url="https://same.example/v1",
            api_key_env="SAME_PROVIDER_KEY",
        )
    )
    original_ai = active.ai
    original_runtime = active.runtime

    active.load(path)

    assert active.ai is original_ai
    assert active.runtime is original_runtime
    assert active.model == "updated-model"
    assert active.last == "Loaded history."


def test_reset_starts_fresh_websocket_session_without_rebinding_client(monkeypatch):
    monkeypatch.setenv("RESET_WS_KEY", "reset-ws-sentinel")
    chat = Chat(
        base_url="https://reset-ws.example/v1",
        api_key_env="RESET_WS_KEY",
        session="inherit",
    )
    original_ai = chat.ai
    original_session = chat.runtime.session
    original_session.last_response_id = "resp_old_conversation"

    chat.reset()

    assert chat.ai is original_ai
    assert chat.runtime.session is not original_session
    assert chat.runtime.session.last_response_id is None
    request = chat.runtime._request_with_session(
        [{"role": "user", "content": "Fresh local history."}],
        {"model": "test-model", "store": True},
    )
    assert "previous_response_id" not in request


def test_same_binding_load_starts_fresh_websocket_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOAD_WS_KEY", "load-ws-sentinel")
    path = tmp_path / "LoadWebSocket.yml"
    configured = Chat(
        name="LoadWebSocket",
        base_url="https://load-ws.example/v1",
        api_key_env="LOAD_WS_KEY",
        session="inherit",
    )
    configured.user("Loaded local history.").save(path)

    active = Chat(
        base_url="https://load-ws.example/v1",
        api_key_env="LOAD_WS_KEY",
        session="inherit",
    )
    original_ai = active.ai
    original_session = active.runtime.session
    original_session.last_response_id = "resp_old_conversation"

    active.load(path)

    assert active.ai is original_ai
    assert active.runtime.session is not original_session
    assert active.runtime.session.last_response_id is None
    request = active.runtime._request_with_session(
        [{"role": "user", "content": "Continue loaded local history."}],
        {"model": "test-model", "store": True},
    )
    assert "previous_response_id" not in request


def test_active_load_cannot_change_provider_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRST_PROVIDER_KEY", "first-sentinel")
    monkeypatch.setenv("SECOND_PROVIDER_KEY", "second-sentinel")
    first_path = tmp_path / "FirstProvider.yml"
    path = tmp_path / "SecondProvider.yml"
    Chat(
        name="FirstProvider",
        base_url="https://first.example/v1",
        api_key_env="FIRST_PROVIDER_KEY",
    ).save(first_path)
    Chat(
        name="SecondProvider",
        base_url="https://second.example/v1",
        api_key_env="SECOND_PROVIDER_KEY",
    ).save(path)

    active = Chat()
    active.load(first_path)
    original_ai = active.ai

    with pytest.raises(SnapclassError, match="new Chat"):
        active.load(path)

    active.reset()
    assert active.ai is original_ai
    assert active.params.base_url == "https://first.example/v1"
    assert active.params.api_key_env == "FIRST_PROVIDER_KEY"
    recovered = active.copy()
    assert recovered.params.base_url == "https://first.example/v1"


def test_active_load_cannot_change_transport_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSPORT_PROVIDER_KEY", "transport-sentinel")
    responses_path = tmp_path / "ResponsesProvider.yml"
    completions_path = tmp_path / "CompletionsProvider.yml"
    Chat(
        name="ResponsesProvider",
        base_url="https://transport.example/v1",
        api_key_env="TRANSPORT_PROVIDER_KEY",
    ).save(responses_path)
    Chat(
        name="CompletionsProvider",
        params=ChatParams(
            base_url="https://transport.example/v1",
            api_key_env="TRANSPORT_PROVIDER_KEY",
            runtime="chat_completions",
        ),
    ).save(completions_path)

    active = Chat()
    active.load(responses_path)

    with pytest.raises(SnapclassError, match="new Chat"):
        active.load(completions_path)

    active.reset()
    assert isinstance(active.runtime, ResponsesAdapter)
    assert isinstance(active.copy().runtime, ResponsesAdapter)


def test_in_place_client_parameter_change_requires_a_new_chat(monkeypatch):
    monkeypatch.setenv("BOUND_PROVIDER_KEY", "bound-sentinel")
    monkeypatch.setenv("OTHER_PROVIDER_KEY", "other-sentinel")
    chat = Chat(
        base_url="https://bound.example/v1",
        api_key_env="BOUND_PROVIDER_KEY",
    )

    chat.params.base_url = "https://other.example/v1"
    chat.params.api_key_env = "OTHER_PROVIDER_KEY"

    with pytest.raises(ValueError, match="new Chat"):
        chat.copy()


@pytest.mark.parametrize("change", ("runtime", "session"))
def test_in_place_transport_change_fails_before_submit(monkeypatch, change):
    monkeypatch.setenv("TRANSPORT_CHANGE_KEY", "provider-sentinel")
    chat = Chat(
        base_url="https://transport-change.example/v1",
        api_key_env="TRANSPORT_CHANGE_KEY",
    )

    async def fail_if_submitted(*args, **kwargs):
        pytest.fail("transport changes must fail before the provider request")

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", fail_if_submitted)

    if change == "runtime":
        chat.params.runtime = "chat_completions"
    else:
        chat.session = "inherit"

    with pytest.raises(ValueError, match="Provider and transport settings.*new Chat"):
        chat.ask("Do not submit this request.")


def test_explicit_runtime_does_not_mask_later_param_change(monkeypatch):
    chat = Chat(runtime="responses")

    async def fail_if_submitted(*args, **kwargs):
        pytest.fail("transport changes must fail before the provider request")

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", fail_if_submitted)
    chat.params.runtime = "chat_completions"

    with pytest.raises(ValueError, match="Provider and transport settings.*new Chat"):
        chat.ask("Do not submit this request.")


@pytest.mark.parametrize(
    "change",
    ("runtime_family", "runtime_client", "websocket_mode"),
)
def test_installed_transport_change_fails_before_submit(monkeypatch, change):
    monkeypatch.setenv("INSTALLED_TRANSPORT_KEY", "provider-sentinel")

    async def fail_if_submitted(*args, **kwargs):
        pytest.fail("installed transport changes must fail before the provider request")

    monkeypatch.setattr(
        ResponsesAdapter,
        "create_completion_a",
        fail_if_submitted,
    )
    monkeypatch.setattr(
        ChatCompletionsAdapter,
        "create_completion_a",
        fail_if_submitted,
    )
    monkeypatch.setattr(
        ResponsesWebSocketAdapter,
        "create_completion_a",
        fail_if_submitted,
    )

    if change in {"runtime_family", "runtime_client"}:
        chat = Chat(
            base_url="https://installed-transport.example/v1",
            api_key_env="INSTALLED_TRANSPORT_KEY",
        )
        chat.runtime = (
            ChatCompletionsAdapter(chat.ai)
            if change == "runtime_family"
            else ResponsesAdapter(SimpleNamespace())
        )
    else:
        chat = Chat(
            base_url="https://installed-transport.example/v1",
            api_key_env="INSTALLED_TRANSPORT_KEY",
            session="inherit",
        )
        chat.runtime.session.mode = "new"

    with pytest.raises(ValueError, match="Provider and transport settings.*new Chat"):
        chat.ask("Do not submit this request.")


def test_authored_provider_binding_is_fixed_before_first_request(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRST_PROVIDER_KEY", "first-sentinel")
    monkeypatch.setenv("SECOND_PROVIDER_KEY", "second-sentinel")
    path = tmp_path / "SecondProvider.yml"
    Chat(
        name="SecondProvider",
        base_url="https://second.example/v1",
        api_key_env="SECOND_PROVIDER_KEY",
    ).save(path)
    chat = Chat(
        params=ChatParams(
            base_url="https://first.example/v1",
            api_key_env="FIRST_PROVIDER_KEY",
        )
    )

    with pytest.raises(SnapclassError, match="new Chat"):
        chat.load(path)


def test_copy_clones_the_resolved_binding_without_rereading_the_environment(monkeypatch):
    monkeypatch.setenv("LINEAGE_PROVIDER_KEY", "lineage-sentinel")
    root = Chat(
        base_url="https://lineage.example/v1",
        api_key_env="LINEAGE_PROVIDER_KEY",
    )

    monkeypatch.setenv("LINEAGE_PROVIDER_KEY", "rotated-sentinel")
    child = root.copy()

    assert child.ai is not root.ai
    assert child.ai.api_key == "lineage-sentinel"
    assert child.runtime is not root.runtime


def test_transport_defaults_remain_configuration_driven(monkeypatch):
    monkeypatch.setenv("CUSTOM_PROVIDER_KEY", "provider-sentinel")

    default_openai = Chat()
    custom = Chat(
        base_url="https://custom.example/v1",
        api_key_env="CUSTOM_PROVIDER_KEY",
    )
    completions = Chat(
        base_url="https://custom.example/v1",
        api_key_env="CUSTOM_PROVIDER_KEY",
        runtime="chat_completions",
    )

    assert isinstance(default_openai.runtime, ResponsesWebSocketAdapter)
    assert isinstance(custom.runtime, ResponsesAdapter)
    assert isinstance(completions.runtime, ChatCompletionsAdapter)


def test_yaml_round_trip_keeps_names_and_omits_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUND_TRIP_PROVIDER_KEY", "private-sentinel-value")
    path = tmp_path / "RoundTripProvider.yml"
    Chat(
        name="RoundTripProvider",
        base_url="https://round-trip.example/v1",
        api_key_env="ROUND_TRIP_PROVIDER_KEY",
    ).save(path)

    saved = path.read_text(encoding="utf-8")
    loaded = Chat()
    loaded.load(path)

    assert "base_url: https://round-trip.example/v1" in saved
    assert "api_key_env: ROUND_TRIP_PROVIDER_KEY" in saved
    assert "private-sentinel-value" not in saved
    assert loaded.params.base_url == "https://round-trip.example/v1"
    assert loaded.params.api_key_env == "ROUND_TRIP_PROVIDER_KEY"


class _SyncCloseProbe:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _AsyncCloseProbe:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_chat_close_a_closes_opened_sdk_clients():
    chat = Chat(runtime="chat_completions")
    sync_client = _SyncCloseProbe()
    async_client = _AsyncCloseProbe()
    chat.ai.client = sync_client
    chat.ai.aclient = async_client

    await chat.close_a()

    assert sync_client.closed is True
    assert async_client.closed is True


@pytest.mark.asyncio
async def test_continuation_owns_the_websocket_session_that_made_its_request(
    monkeypatch,
):
    root = Chat()
    request_connection = _AsyncCloseProbe()
    captured = {}

    async def fake_create_completion_a(runtime, messages, **kwargs):
        captured["session"] = runtime.session
        runtime.session.async_connection = request_connection
        runtime.session.last_response_id = "resp_request"
        return SimpleNamespace(
            message=SimpleNamespace(content="reply", tool_calls=[])
        )

    monkeypatch.setattr(
        ResponsesWebSocketAdapter,
        "create_completion_a",
        fake_create_completion_a,
    )

    continued = await root.chat_a("hello")

    assert continued.runtime.session is captured["session"]
    await continued.close_a()
    assert request_connection.closed is True
    await root.close_a()


@pytest.mark.asyncio
async def test_ask_closes_its_temporary_websocket_request_session(monkeypatch):
    root = Chat()
    request_connection = _AsyncCloseProbe()
    captured = {}

    async def fake_create_completion_a(runtime, messages, **kwargs):
        captured["session"] = runtime.session
        runtime.session.async_connection = request_connection
        return SimpleNamespace(
            message=SimpleNamespace(content="reply", tool_calls=[])
        )

    monkeypatch.setattr(
        ResponsesWebSocketAdapter,
        "create_completion_a",
        fake_create_completion_a,
    )

    assert await root.ask_a("hello") == "reply"

    assert captured["session"] is not root.runtime.session
    assert request_connection.closed is True
    await root.close_a()
