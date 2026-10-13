"""Goal and Steer contracts for Wonder AUTO configuration and saved conversations."""

import ast
import inspect
import json
import warnings
from pathlib import Path

import httpx
import openai
import pytest

from chatsnack import Chat, ChatParams, utensil
from chatsnack.aiclient import AiClient
from chatsnack.runtime import ResponsesAdapter
from chatsnack.runtime.model_advisories import is_meta_endpoint, warn_model_options


MODEL = "muse-wonder-1.0"
META_URL = "https://api.meta.ai/v1"


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch, tmp_path):
    """Keep model defaults independent of developer credentials and saved assets."""
    for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_AZURE_ENDPOINT",
                 "CHATSNACK_DEFAULT_RUNTIME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "meta-sentinel")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-sentinel")
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))


@pytest.fixture
def provider_wire(monkeypatch):
    """Use the real SDK's request serialization with an in-memory HTTP provider."""
    records = []

    def respond(request):
        """Return a reasoning/tool exchange or an SSE completion without networking."""
        body = json.loads(request.content)
        records.append((request, body))
        index = len(records)
        if any(item.get("type") == "reasoning" and not item.get("encrypted_content")
               for item in body["input"]) and not body.get("previous_response_id"):
            return httpx.Response(400, json={"error": {
                "message": "Referenced reasoning item was not found or has expired",
                "type": "invalid_request_error", "param": "input", "code": None,
            }})
        output = [{"type": "reasoning", "id": f"rs_{index}", "summary": []}]
        if "reasoning.encrypted_content" in body.get("include", []):
            output[0]["encrypted_content"] = f"opaque_{index}"
        has_result = any(item.get("type") == "function_call_output"
                         for item in body["input"])
        lookup_requested = any(part.get("text") == "Look up popcorn."
                               or part.get("text", "").startswith("Check ")
                               for item in body["input"] for part in item.get("content", [])
                               if isinstance(part, dict))
        if body.get("tools") and lookup_requested and not has_result:
            name = body["tools"][0]["name"]
            arguments = {"snack": "popcorn"} if name == "stock" else {"name": "popcorn"}
            output.append({"type": "function_call", "id": "fc_snack",
                           "call_id": "call_snack", "name": name,
                           "arguments": json.dumps(arguments)})
        else:
            output.append({"type": "message", "id": f"msg_{index}",
                           "role": "assistant", "status": "completed",
                           "content": [{"type": "output_text", "text": "POPSICLE",
                                        "annotations": []}]})
        response = {"id": f"resp_{index}", "object": "response", "created_at": 1,
                    "status": "completed", "model": body["model"], "output": output,
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
        if body.get("stream"):
            events = [{"type": "response.output_text.delta", "delta": "POPSICLE"},
                      {"type": "response.completed", "response": response}]
            content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, content=content,
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=response)

    original_kwargs = AiClient._client_kwargs

    def client_kwargs(self, client_class):
        """Intercept both clients because synchronous Chat calls use async I/O too."""
        options = original_kwargs(self, client_class)
        http_client = httpx.AsyncClient if client_class is openai.AsyncOpenAI else httpx.Client
        options["http_client"] = http_client(transport=httpx.MockTransport(respond))
        return options

    monkeypatch.setattr(AiClient, "_client_kwargs", client_kwargs)
    return records


@pytest.mark.asyncio
async def test_goal_auto_wonder_asks_calls_tools_copies_saves_and_streams(
    provider_wire, monkeypatch, tmp_path,
):
    """A model-only Chat keeps its original provider through the complete asset loop."""
    calls = []

    @utensil
    def lookup_snack(name: str) -> dict:
        """Supply data through a normal Python function in the Wonder conversation."""
        calls.append(name)
        return {"name": name, "crunchy": True}

    root = Chat("Respond tersely.", model=MODEL, utensils=[lookup_snack])
    root.reasoning.effort = "minimal"
    root.reasoning.summary = "auto"
    assert isinstance(root.runtime, ResponsesAdapter)
    assert root.params.base_url == META_URL
    assert root.params.api_key_env == "MODEL_API_KEY"
    assert root.params.responses["include"] == ["reasoning.encrypted_content"]
    assert root.params.responses.get("store", False) is False
    assert await root.ask_a("Say POPSICLE.") == "POPSICLE"
    assert len(root.messages) == 1

    monkeypatch.setenv("MODEL_API_KEY", "rotated-meta-sentinel")
    copied = root.copy()
    thread = await copied.chat_a("Look up popcorn.")
    continued = await thread.chat_a("Which snack was crunchy?")
    assert calls == ["popcorn"]
    assert thread.ai is copied.ai
    assert continued.ai is thread.ai
    path = tmp_path / "Wonder.yml"
    continued.save(path)
    text = path.read_text(encoding="utf-8")
    assert "base_url: https://api.meta.ai/v1" in text
    assert "api_key_env: MODEL_API_KEY" in text
    assert "sentinel" not in text
    loaded = Chat()
    loaded.load(path)
    loaded.stream = True
    listener = await loaded.listen_a("Give the answer once more.")
    assert "".join([chunk async for chunk in listener]) == "POPSICLE"
    assert listener.is_complete
    assert loaded.params.base_url == META_URL
    assert all(request.url.host == "api.meta.ai" for request, _ in provider_wire)
    # New loads read current credentials; copies and continuations retain the old key.
    assert all(request.headers["authorization"] == "Bearer meta-sentinel"
               for request, _ in provider_wire[:-1])
    assert provider_wire[-1][0].headers["authorization"] == "Bearer rotated-meta-sentinel"
    assert all(body["include"] == ["reasoning.encrypted_content"] and body["store"] is False
               for _, body in provider_wire)
    final_input = provider_wire[-1][1]["input"]
    assert any(item.get("type") == "reasoning" and item.get("encrypted_content")
               for item in final_input)
    assert any(item.get("type") == "function_call_output" for item in final_input)
    for chat in (loaded, continued, thread, copied, root):
        await chat.close_a()


@pytest.mark.parametrize("creation", ["constructor", "params", "autoload", "snapshot"])
def test_model_only_configuration_works_on_each_creation_path(creation, tmp_path):
    """Inference happens after durable params are loaded, including snapclass loaders."""
    if creation == "constructor":
        chat = Chat(model=MODEL)
    elif creation == "params":
        chat = Chat(params={"model": MODEL})
    else:
        (tmp_path / "BareWonder.yml").write_text(
            f"params:\n  model: {MODEL}\nmessages:\n  - system: Respond tersely.\n",
            encoding="utf-8",
        )
        chat = (Chat(name="BareWonder") if creation == "autoload"
                else Chat.snapshots.get("BareWonder"))
    assert chat.params.base_url == META_URL
    assert chat.params.api_key_env == "MODEL_API_KEY"
    assert isinstance(chat.runtime, ResponsesAdapter)
    chat.close()


@pytest.mark.parametrize("creation", ["constructor", "params", "autoload"])
def test_explicit_connection_wins_without_a_meta_credential(creation, monkeypatch, tmp_path):
    """A Wonder ID at another endpoint must retain that endpoint's credential choice."""
    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.setenv("ROUTER_KEY", "router-sentinel")
    options = dict(model=MODEL, base_url="https://router.example/v1", api_key_env="ROUTER_KEY")
    if creation == "constructor":
        chat = Chat(**options)
    elif creation == "params":
        chat = Chat(params=options)
    else:
        (tmp_path / "RouterWonder.yml").write_text(
            f"params:\n  model: {MODEL}\n  base_url: https://router.example/v1\n"
            "  api_key_env: ROUTER_KEY\nmessages: []\n", encoding="utf-8",
        )
        chat = Chat(name="RouterWonder", model=MODEL)
    assert chat.ai.base_url == "https://router.example/v1"
    assert chat.ai.api_key_env == "ROUTER_KEY"
    assert not (chat.params.responses or {}).get("include")
    chat.close()


def test_explicit_sdk_environment_wins(monkeypatch):
    """An existing global SDK endpoint is a connection choice, not an omitted setting."""
    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://router.example/v1")
    chat = Chat(model=MODEL, runtime="responses")
    assert str(chat.ai.client.base_url).rstrip("/") == "https://router.example/v1"
    assert chat.params.base_url is None
    chat.close()


def test_missing_meta_key_does_not_use_the_openai_key(monkeypatch):
    """AUTO names the missing Meta credential before any request can be submitted."""
    monkeypatch.delenv("MODEL_API_KEY")
    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        Chat(model=MODEL)


@pytest.mark.parametrize("model", ["muse-wonder-full-1.0", "muse-wonder-1.0-2026-10-12",
                                  "vendor/muse-wonder-1.0", "muse-wonder-2.0"])
def test_unverified_model_ids_do_not_infer_a_provider(model, monkeypatch):
    """Unsupported Full, snapshots, and gateway aliases remain caller-owned."""
    monkeypatch.delenv("MODEL_API_KEY")
    chat = Chat(model=model)
    assert chat.params.base_url is None
    assert chat.params.api_key_env is None
    chat.close()


def test_changing_model_on_a_copy_never_changes_connection(monkeypatch):
    """Model assignment cannot retarget an already-established conversation binding."""
    monkeypatch.delenv("MODEL_API_KEY")
    source = Chat(model="gpt-5.4", runtime="responses")
    source.model = MODEL
    copied = source.copy()
    assert copied.params.base_url is None
    assert copied.ai.base_url is None
    copied.close()
    source.close()


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high", "xhigh", "max"])
@pytest.mark.parametrize("summary", ["auto", "concise", "detailed"])
def test_verified_reasoning_is_warning_free_and_passed_through(effort, summary):
    """Every documented Wonder effort and summary is accepted by advisory validation."""
    reasoning = {"effort": effort, "summary": summary}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        options = ChatParams(model=MODEL, responses={"reasoning": reasoning})._get_responses_api_options()
    assert not caught
    assert options["reasoning"] == reasoning


def test_unsupported_reasoning_warns_without_rewriting():
    """Known unsupported values remain advisory rather than becoming local rejection."""
    params = ChatParams(model=MODEL, responses={"reasoning": {"effort": "none"}})
    with pytest.warns(UserWarning, match="not in the known supported set"):
        assert params._get_responses_api_options()["reasoning"]["effort"] == "none"


def test_explicit_replay_and_transport_options_win():
    """Authored opt-outs remain visible; defaults do not replace a caller's choices."""
    chat = Chat(params=ChatParams(model=MODEL, runtime="chat_completions",
                                 responses={"store": True, "include": []}))
    assert chat.runtime.runtime_family == "chat_completions"
    assert chat.params.responses == {"store": True, "include": []}
    chat.close()


@pytest.mark.parametrize("scope", ["defaults", "model_defaults"])
def test_authored_profile_include_wins_over_the_model_default(scope, provider_wire):
    """A provider profile's include choice has the same precedence as explicit params."""
    profile = {scope: {"include": []} if scope == "defaults" else {MODEL: {"include": []}}}
    chat = Chat(model=MODEL, params=ChatParams(profile=profile))
    try:
        assert chat.ask("Say POPSICLE.") == "POPSICLE"
        assert provider_wire[0][1]["include"] == []
    finally:
        chat.close()


def test_sync_ask_uses_the_auto_http_endpoint(provider_wire):
    """The synchronous convenience API submits the same Responses HTTP request."""
    chat = Chat("Respond tersely.", model=MODEL)
    try:
        assert chat.ask("Say POPSICLE.") == "POPSICLE"
        assert provider_wire[0][0].url.path == "/v1/responses"
    finally:
        chat.close()


@pytest.mark.asyncio
async def test_goal_notebook_authors_saves_reuses_and_streams_with_normal_chat_calls(
    provider_wire, monkeypatch, tmp_path,
):
    """Run the notebook as a kernel would, replacing only the provider's HTTP I/O."""
    notebook = Path(__file__).resolve().parents[2] / "notebooks/MuseWonder.ipynb"
    monkeypatch.chdir(tmp_path)
    scope = {}
    for cell in json.loads(notebook.read_text(encoding="utf-8"))["cells"]:
        if cell["cell_type"] == "code":
            code = compile("".join(cell["source"]), str(notebook), "exec",
                           flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            result = eval(code, scope)
            if inspect.isawaitable(result):
                await result
    assert scope["popsicle"].model == MODEL
    assert len(scope["popsicle"].messages) == 1  # ask() keeps the authored Chat.
    template = (tmp_path / "WonderMenu.yml").read_text(encoding="utf-8")
    assert "{occasion}" in template
    assert "sentinel" not in template
    assert (tmp_path / "MoonPicnicThread.yml").is_file()
    assert scope["reused_pantry"].params.base_url == META_URL
    assert scope["stream_chat"].ai.base_url == scope["stock_thread"].ai.base_url
    assert all(request.url.host == "api.meta.ai" for request, _ in provider_wire)
    assert provider_wire[-1][1]["stream"] is True
    results = [item for item in provider_wire[-1][1]["input"]
               if item.get("type") == "function_call_output"]
    assert len(results) == 1
    assert json.loads(results[0]["output"]) == {
        "snack": "popcorn", "available": 7, "tool_call_id": results[0]["call_id"],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_goal_encryption_opt_out_can_replay_without_losing_saved_history(
    async_mode, stream, provider_wire, tmp_path,
):
    """Legacy and opted-out reasoning remains durable without sending invalid IDs."""
    owned = []
    try:
        root = Chat(model=MODEL, params=ChatParams(responses={"include": []}))
        owned.append(root)
        first = await root.chat_a("Say POPSICLE.")
        owned.append(first)
        path = tmp_path / "UnencryptedWonder.yml"
        first.save(path)
        before = path.read_text(encoding="utf-8")
        assert "rs_1" in before
        assert "encrypted_content" not in before
        loaded = Chat()
        owned.append(loaded)
        loaded.load(path)
        loaded.stream = stream
        with pytest.warns(UserWarning, match="Omitting Meta reasoning items without encrypted_content"):
            if stream:
                listener = (await loaded.listen_a("Say POPSICLE.") if async_mode
                            else loaded.listen("Say POPSICLE."))
                answer = ("".join([chunk async for chunk in listener]) if async_mode
                          else "".join(listener))
            else:
                answer = (await loaded.ask_a("Say POPSICLE.") if async_mode
                          else loaded.ask("Say POPSICLE."))
        assert answer == "POPSICLE"
        assert not any(item.get("type") == "reasoning" for item in provider_wire[-1][1]["input"])
        assert provider_wire[-1][1]["include"] == []
        loaded.save(path)
        assert "rs_1" in path.read_text(encoding="utf-8")
        assert loaded.params.responses["include"] == []
    finally:
        for chat in reversed(owned):
            await chat.close_a()


def test_meta_projection_retains_encrypted_items_phases_and_tool_pairing():
    """Only unusable reasoning is omitted; ordered opaque data and options survive."""
    bare = {"type": "reasoning", "id": "rs_bare", "summary": []}
    retained = [
        {"type": "reasoning", "id": "rs_enc", "summary": [], "encrypted_content": "opaque",
         "provider_extra": {"unknown": "preserved"}},
        {"type": "message", "role": "assistant", "phase": "commentary", "content": []},
        {"type": "function_call", "call_id": "call_stock", "name": "stock", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_stock", "output": "7"},
    ]
    options = {"input": [bare, *retained], "store": False, "include": [], "model": MODEL}
    before = json.dumps(options)
    client = type("MetaClient", (), {"base_url": META_URL})()
    with pytest.warns(UserWarning, match="Omitting Meta reasoning"):
        projected = ResponsesAdapter._project_meta_replay(options, client)
    assert projected["input"] == retained
    assert projected["store"] is False
    assert projected["include"] == []
    assert json.dumps(options) == before


@pytest.mark.parametrize("url,extra", [
    ("https://router.example/v1", {}),
    (META_URL, {"previous_response_id": "resp_stored"}),
    (META_URL, {"extra_body": {"previous_response_id": "resp_stored"}}),
    (META_URL, {"extra_body": {"input": [{"type": "reasoning", "id": "authored_id"}]}}),
])
def test_meta_projection_leaves_other_providers_stored_replay_and_authored_input_alone(url, extra):
    """Gateway replay, stored references, and raw authored input remain provider-owned."""
    options = {"input": [{"type": "reasoning", "id": "rs_bare", "summary": []}], **extra}
    client = type("ProviderClient", (), {"base_url": url})()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert ResponsesAdapter._project_meta_replay(options, client) is options
    assert not caught


def test_meta_projection_respects_an_extra_body_continuation_opt_out():
    """An extra_body override can disable stored replay despite the top-level ID."""
    options = {"input": [{"type": "reasoning", "id": "rs_bare", "summary": []}],
               "previous_response_id": "resp_stored", "extra_body": {"previous_response_id": None}}
    client = type("MetaClient", (), {"base_url": META_URL})()
    with pytest.warns(UserWarning, match="Omitting Meta reasoning"):
        projected = ResponsesAdapter._project_meta_replay(options, client)
    assert projected["input"] == []
    assert projected["extra_body"] == {"previous_response_id": None}


def test_constructor_connection_overrides_a_saved_meta_asset(monkeypatch, tmp_path):
    """Per-use constructor settings override saved AUTO defaults before binding."""
    (tmp_path / "Wonder.yml").write_text(
        f"params:\n  model: {MODEL}\n  base_url: {META_URL}\n"
        "  api_key_env: MODEL_API_KEY\nmessages: []\n", encoding="utf-8",
    )
    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.setenv("ROUTER_KEY", "router-sentinel")
    chat = Chat(name="Wonder", base_url="https://router.example/v1", api_key_env="ROUTER_KEY")
    assert chat.params.base_url == "https://router.example/v1"
    assert chat.ai.api_key_env == "ROUTER_KEY"
    chat.close()


def test_reset_and_copy_keep_auto_credentials_after_model_and_env_edits(monkeypatch):
    """Neither reset nor a new copy resolves the source's credential a second time."""
    source = Chat(model=MODEL)
    monkeypatch.setenv("MODEL_API_KEY", "rotated-meta-sentinel")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://router.example/v1")
    source.model = "gpt-5.4"
    copied = source.copy()
    source.reset()
    assert source.model == MODEL
    assert copied.model == "gpt-5.4"
    for chat in (source, copied):
        assert chat.ai.base_url == META_URL
        assert chat.ai.api_key_env == "MODEL_API_KEY"
        assert chat.ai.api_key == "meta-sentinel"
        chat.close()


@pytest.mark.parametrize("choice", ["none", "required", {"type": "function", "name": "stock"}])
@pytest.mark.parametrize("runtime", ["responses", "chat_completions"])
def test_meta_tool_choice_is_advisory_and_uses_effective_extra_body(choice, runtime):
    """Unsupported tool choices warn without changing the caller's payload."""
    options = {"model": MODEL, "tool_choice": "auto", "extra_body": {"tool_choice": choice}}
    client = type("MetaClient", (), {"base_url": META_URL})()
    with pytest.warns(UserWarning, match="supports only tool_choice='auto'"):
        warn_model_options(options, client, runtime)
    assert options["extra_body"]["tool_choice"] == choice
    assert options["tool_choice"] == "auto"


@pytest.mark.parametrize("url", [META_URL, "https://router.example/v1", "https://api.openai.com/v1"])
def test_meta_auto_choice_and_sampling_options_are_warning_free(url):
    """Meta accepts auto choice; OpenAI-specific sampling bans do not spill over."""
    options = {"model": MODEL, "tool_choice": "auto", "temperature": 1, "top_p": 0.9}
    client = type("ProviderClient", (), {"base_url": url})()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_model_options(options, client, "responses")
    assert not caught


@pytest.mark.parametrize("url", ["https://api.meta.ai.attacker.example/v1", "http://api.meta.ai/v1",
                                "https://api.meta.ai:444/v1", "https://api.meta.ai/v2", "nonsense"])
def test_meta_detection_does_not_match_other_endpoints(url):
    """Routing and provider advice require Meta's documented host and API path."""
    assert not is_meta_endpoint(url)
    client = type("ProviderClient", (), {"base_url": url})()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_model_options({"model": MODEL, "tool_choice": "required"}, client, "responses")
    assert not caught
