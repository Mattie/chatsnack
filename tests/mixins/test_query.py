import pytest
import json
from types import SimpleNamespace
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.runtime import ChatCompletionsAdapter, ResponsesAdapter
from chatsnack.chat.mixin_params import DEFAULT_MODEL_FALLBACK

import os
import shutil

TEST_FILENAME = "./.test_text_expansion.txt"

@pytest.fixture(scope="function", autouse=True)
def setup_and_cleanup():
    chatsnack_dir = CHATSNACK_BASE_DIR
    safe_to_cleanup = False
    # to be safe, verify that this directory is under the current working directory
    # is it a subdirectory of the current working directory?
    chatsnack_dir = os.path.abspath(chatsnack_dir)
    if os.path.commonpath([os.path.abspath(os.getcwd()), chatsnack_dir]) == os.path.abspath(os.getcwd()):
        # now check to be sure the only files under this directory (recursive) are .txt, .yaml, .yml, .log, and .json files.
        # if so, it's safe to delete the directory
        bad_file_found = False
        for root, dirs, files in os.walk(chatsnack_dir):
            for file in files:
                if not file.endswith((".txt", ".yaml", ".yml", ".log", ".json")):
                    bad_file_found = True
                    break
            else:
                continue
            break
        if not bad_file_found:
            safe_to_cleanup = True
    # if safe and the test directory already exists, remove it, should be set in the tests .env file
    if safe_to_cleanup and os.path.exists(chatsnack_dir):
        shutil.rmtree(chatsnack_dir)
    # create the test directory, recursively to the final directory
    if not os.path.exists(chatsnack_dir):
        os.makedirs(chatsnack_dir)
    else:
        # problem, the directory should have been missing
        raise Exception("The test directory already exists, it should have been missing.")
    # also delete TEST_FILENAME
    if os.path.exists(TEST_FILENAME):
        os.remove(TEST_FILENAME)
    yield

    # Clean up the test environment
    import time
    time.sleep(2)
    if safe_to_cleanup and os.path.exists(chatsnack_dir):
        # it's okay for this to fail, it's just a cleanup
        try:
            shutil.rmtree(chatsnack_dir)
        except:
            pass
    # also delete TEST_FILENAME
    if os.path.exists(TEST_FILENAME):
        os.remove(TEST_FILENAME)



@pytest.fixture 
def chat():
    return Chat()


def _set_runtime_mode(chat, use_runtime_adapter: bool):
    if use_runtime_adapter:
        assert chat.runtime is not None
    else:
        chat.runtime = None



def test_default_runtime_is_chat_completions_adapter():
    chat = Chat()
    assert isinstance(chat.runtime, ChatCompletionsAdapter)


def test_runtime_selector_selects_responses_adapter():
    chat = Chat(runtime_selector="responses")
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_runtime_profile_selects_responses_adapter():
    chat = Chat(params=ChatParams(runtime="responses"))
    assert isinstance(chat.runtime, ResponsesAdapter)


def test_runtime_injection_takes_precedence_over_selector():
    runtime = object()
    chat = Chat(runtime=runtime, runtime_selector="responses")
    assert chat.runtime is runtime


def test_ask_with_responses_runtime_returns_str(chat, monkeypatch):
    chat.runtime = ResponsesAdapter(chat.ai)

    async def fake_create_completion_a(messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="reply", tool_calls=[]))

    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)

    out = chat.ask()
    assert isinstance(out, str)
    assert out == "reply"


def test_chat_with_responses_runtime_returns_chat_with_assistant_history(chat, monkeypatch):
    chat.runtime = ResponsesAdapter(chat.ai)

    async def fake_create_completion_a(messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="reply", tool_calls=[]))

    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)

    result = chat.chat("hello")
    assert isinstance(result, Chat)
    assert isinstance(result.runtime, ResponsesAdapter)
    assert result.get_messages()[-1] == {"role": "assistant", "content": "reply"}


def test_copy_preserves_responses_runtime_selection_from_params():
    chat = Chat(params=ChatParams(runtime="responses"))
    assert isinstance(chat.runtime, ResponsesAdapter)

    copied = chat.copy()

    assert isinstance(copied.runtime, ResponsesAdapter)


def test_copy_creates_independent_adapter_instances():
    """Cloned chats must not share the parent's adapter instance."""
    chat = Chat(params=ChatParams(runtime="responses"))
    copied = chat.copy()
    assert copied.runtime is not chat.runtime
    assert copied.runtime.ai_client is not chat.runtime.ai_client


def test_chat_continuation_creates_independent_adapter_instance(chat, monkeypatch):
    """chat() continuation must not share the source chat's adapter instance."""
    chat.runtime = ResponsesAdapter(chat.ai)

    async def fake_create_completion_a(messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="reply", tool_calls=[]))

    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)

    result = chat.chat("hello")
    assert isinstance(result.runtime, ResponsesAdapter)
    assert result.runtime is not chat.runtime
    assert result.runtime.ai_client is not chat.runtime.ai_client



def test_default_runtime_selection_preserves_phase0_behavior(chat, monkeypatch):
    assert isinstance(chat.runtime, ChatCompletionsAdapter)

    async def fake_create_completion_a(messages, **kwargs):
        return SimpleNamespace(message=SimpleNamespace(content="legacy-shape", tool_calls=[]))

    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)
    assert chat.ask() == "legacy-shape"


def test_profile_forwarded_to_adapter_via_submit(chat, monkeypatch):
    """profile set in ChatParams must be forwarded to adapter.create_completion_a."""
    captured_kwargs = {}

    async def fake_create_completion_a(messages, **kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))

    profile = {"defaults": {"temperature": 0.7}}
    chat.params = ChatParams(profile=profile)
    monkeypatch.setattr(chat.runtime, "create_completion_a", fake_create_completion_a)

    chat.ask()

    assert "profile" in captured_kwargs
    assert captured_kwargs["profile"] == profile


@pytest.mark.asyncio
async def test_chat_a_tool_recursion_with_responses_runtime(chat, monkeypatch):
    chat.runtime = ResponsesAdapter(chat.ai)
    chat.auto_execute = True
    chat.auto_feed = True
    chat.user("hello")

    class _ToolCall:
        id = "call_1"
        function = SimpleNamespace(name="echo", arguments='{"x":1}')

    class _ToolMessage:
        content = None
        tool_calls = [_ToolCall()]

        def model_dump(self):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"x":1}'},
                    }
                ],
            }

    async def fake_submit(**kwargs):
        return json.dumps(chat.get_messages()), _ToolMessage()

    async def fake_follow_up(self, prompt, **kwargs):
        return "final"

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(chat, "execute_tool_call", lambda tc: {"ok": True})
    monkeypatch.setattr(Chat, "_cleaned_chat_completion", fake_follow_up)

    output = await chat.chat_a()
    roles = [msg["role"] for msg in output.get_messages()]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert output.get_messages()[-1]["content"] == "final"



def test_chat_continuation_injects_previous_response_id_and_persists_metadata(chat, monkeypatch):
    chat.runtime = ResponsesAdapter(chat.ai)
    calls = []

    async def fake_create_completion_a(self, messages, **kwargs):
        calls.append(kwargs.copy())
        if len(calls) == 1:
            return SimpleNamespace(
                message=SimpleNamespace(content="first", tool_calls=[]),
                usage={"total_tokens": 11},
                metadata={
                    "response_id": "resp_1",
                    "assistant_phase": "completed",
                    "provider_extras": {"status": "completed"},
                },
            )
        return SimpleNamespace(
            message=SimpleNamespace(content="second", tool_calls=[]),
            usage={"total_tokens": 22},
            metadata={
                "response_id": "resp_2",
                "assistant_phase": "completed",
                "provider_extras": {"status": "completed"},
            },
        )

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", fake_create_completion_a)

    first = chat.chat("hello")

    assert calls[0].get("previous_response_id") is None
    assert calls[0]["store"] is True
    assert first._last_runtime_metadata["response_id"] == "resp_1"
    assert first._last_runtime_metadata["usage"] == {"total_tokens": 11}

    second = first.chat("continue")

    assert calls[1]["previous_response_id"] == "resp_1"
    assert calls[1]["store"] is True
    assert second._last_runtime_metadata["response_id"] == "resp_2"


@pytest.mark.asyncio
async def test_chat_a_tool_recursion_preserves_runtime_continuation_metadata(chat, monkeypatch):
    chat.runtime = ResponsesAdapter(chat.ai)
    chat.auto_execute = True
    chat.auto_feed = True
    chat.user("hello")

    class _ToolCall:
        id = "call_1"
        function = SimpleNamespace(name="echo", arguments='{"x":1}')

    class _ToolMessage:
        content = None
        tool_calls = [_ToolCall()]

        def model_dump(self):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"x":1}'},
                    }
                ],
            }

    async def fake_submit(**kwargs):
        chat._set_last_runtime_metadata({
            "response_id": "resp_tool",
            "usage": {"total_tokens": 15},
            "assistant_phase": "incomplete",
            "provider_extras": {"status": "in_progress"},
        })
        return json.dumps(chat.get_messages()), _ToolMessage()

    captured = {}

    async def fake_create_completion_a(self, messages, **kwargs):
        captured["previous_response_id"] = kwargs.get("previous_response_id")
        return SimpleNamespace(
            message=SimpleNamespace(content="final", tool_calls=[]),
            usage={"total_tokens": 20},
            metadata={
                "response_id": "resp_follow_up",
                "assistant_phase": "completed",
                "provider_extras": {"status": "completed"},
            },
        )

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(chat, "execute_tool_call", lambda tc: {"ok": True})
    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", fake_create_completion_a)

    output = await chat.chat_a()

    assert captured["previous_response_id"] == "resp_tool"
    assert output._last_runtime_metadata["response_id"] == "resp_follow_up"
    assert output._last_runtime_metadata["assistant_phase"] == "completed"


def test_copy_chatprompt_same_name():
    """Copying a ChatPrompt with the same name should succeed."""
    chat = Chat(name="test")
    new_chat = chat.copy()
    # assert that it begins with "test"
    assert new_chat.name.startswith("test")
    assert new_chat.name != "test"


def test_copy_chatprompt_new_name():
    """Copying a ChatPrompt with a new name should succeed."""
    chat = Chat(name="test")
    new_chat = chat.copy(name="new_name")
    assert new_chat.name == "new_name"

@pytest.mark.parametrize("expand_includes, expand_fillings, expected_system, expected_last, expected_exception", [
    (True, True, "Respond only with 'YES' regardless of what is said.","here we are again", None),
    (False, True, "Respond only with 'YES' regardless of what is said.", "AnotherTest", NotImplementedError),
    (True, False, "{text.test_text_expansion}","here we are again", None),
    (False, False, "{text.test_text_expansion}","AnotherTest", None),
]) 
def test_copy_chatprompt_expands(expand_includes, expand_fillings, expected_system, expected_last, expected_exception):
    """Copying a ChatPrompt should correctly expand includes/fillings based on params."""
    # we need a text object saved to disk
    text = Text(name="test_text_expansion", content="Respond only with 'YES' regardless of what is said.")
    # save it to disk
    text.save()
    # we need a chat object to use it
    chat = Chat()
    # set the logging level to trace for chatsnack
    chat.system("{text.test_text_expansion}")
    AnotherTest = Chat(name="AnotherTest")
    AnotherTest.user("here we are again")
    AnotherTest.save()
    chat.include("AnotherTest")
    # todo add more tests for fillings
    if expected_exception is not None:
        with pytest.raises(expected_exception):
            new_chat = chat.copy(expand_includes=expand_includes, expand_fillings=expand_fillings)
    else:
        new_chat = chat.copy(expand_includes=expand_includes, expand_fillings=expand_fillings)
        assert new_chat.system_message == expected_system
        assert new_chat.last == expected_last

def test_copy_chatprompt_expand_fillings_not_implemented():
    """Copying a ChatPrompt with expand_fillings=True and expand_includes=False should raise a NotImplemented error."""
    chat = Chat(name="test")
    with pytest.raises(NotImplementedError):
        new_chat = chat.copy(expand_includes=False, expand_fillings=True)


def test_copy_chatprompt_no_name(): 
    """Copying a ChatPrompt without specifying a name should generate a name."""
    chat = Chat(name="test")
    new_chat = chat.copy()
    assert new_chat.name != "test"
    assert len(new_chat.name) > 0

def test_copy_chatprompt_preserves_system():
    """Copying a ChatPrompt should preserve the system."""
    chat = Chat(name="test")
    chat.system("test_system")
    new_chat = chat.copy()
    assert new_chat.system_message == "test_system"

def test_copy_chatprompt_no_system():
    """Copying a ChatPrompt without a system should result in no system."""
    chat = Chat(name="test")
    new_chat = chat.copy()
    assert new_chat.system_message is None 

def test_copy_chatprompt_copies_params():
    """Copying a ChatPrompt should copy over params."""
    chat = Chat(name="test", params={"key": "value"})
    new_chat = chat.copy()
    assert new_chat.params == {"key": "value"}

def test_copy_chatprompt_independent_params():
    """Copying a ChatPrompt should result in independent params."""
    chat = Chat(name="test", params={"key": "value"})
    new_chat = chat.copy()
    new_chat.params["key"] = "new_value"
    assert chat.params == {"key": "value"}
    assert new_chat.params == {"key": "new_value"}



# Tests for new_chat.name generation 
def test_copy_chatprompt_generated_name_length():
    """The generated name for a copied ChatPrompt should be greater than 0 characters."""
    chat = Chat(name="test")
    new_chat = chat.copy()
    assert len(new_chat.name) > 0





import asyncio


class _FakeMessage:
    def __init__(self, content="hello", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": self.tool_calls,
        }


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class _FakeAsyncCompletions:
    def __init__(self):
        self.last_kwargs = None

    async def create(self, messages, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(_FakeMessage(content="ok", tool_calls=None))


@pytest.mark.asyncio
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
async def test_sync_methods_fail_fast_in_active_loop(chat, monkeypatch, use_runtime_adapter):
    _set_runtime_mode(chat, use_runtime_adapter)

    def raise_active_loop(coro):
        coro.close()
        raise RuntimeError("asyncio.run() cannot be called from a running event loop")

    monkeypatch.setattr("chatsnack.chat.mixin_query.asyncio.run", raise_active_loop)

    with pytest.raises(RuntimeError, match=r"Cannot call sync ask\(\)"):
        chat.ask()
    with pytest.raises(RuntimeError, match=r"Cannot call sync chat\(\)"):
        chat.chat()
    with pytest.raises(RuntimeError, match=r"Cannot call sync listen\(\)"):
        chat.listen()


@pytest.mark.asyncio
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
async def test_async_methods_work_in_active_loop(chat, monkeypatch, use_runtime_adapter):
    _set_runtime_mode(chat, use_runtime_adapter)

    async def fake_submit(**kwargs):
        return "[]", "async-output"

    async def fake_chat_a(self, usermsg=None, **additional_vars):
        return Chat(name="async-chat")

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)

    assert await chat.ask_a() == "async-output"

    async def fake_submit_listener(**kwargs):
        return "[]", SimpleNamespace(start_a=lambda: asyncio.sleep(0), events=False)

    chat.stream = True
    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit_listener)
    listener = await chat.listen_a(events=True)
    assert listener.events is True


@pytest.mark.asyncio
async def test_ask_a_and_chat_a_raise_when_stream_enabled(chat):
    chat.stream = True
    with pytest.raises(Exception, match=r"Cannot use ask\(\) with a stream"):
        await chat.ask_a()
    with pytest.raises(Exception, match=r"Cannot use chat\(\) with a stream"):
        await chat.chat_a()


@pytest.mark.asyncio
async def test_cleaned_chat_completion_model_fallback(chat):
    fake_completions = _FakeAsyncCompletions()
    chat.ai.aclient = SimpleNamespace(
        chat=SimpleNamespace(completions=fake_completions)
    )
    chat.system("system")
    await chat._cleaned_chat_completion(chat.json)
    assert fake_completions.last_kwargs["model"] == DEFAULT_MODEL_FALLBACK


@pytest.mark.asyncio
async def test_cleaned_chat_completion_returns_message_object_for_tool_calls(chat):
    class ToolCompletions:
        async def create(self, messages, **kwargs):
            tool_calls = [SimpleNamespace(id="1", function=SimpleNamespace(name="x", arguments="{}"))]
            return _FakeResponse(_FakeMessage(content=None, tool_calls=tool_calls))

    chat.ai.aclient = SimpleNamespace(chat=SimpleNamespace(completions=ToolCompletions()))
    response = await chat._cleaned_chat_completion("[]")
    assert hasattr(response, "tool_calls")
    assert response.tool_calls


@pytest.mark.asyncio
async def test_tool_recursion_auto_feed_false_keeps_tool_messages(chat, monkeypatch):
    class _ToolCall:
        def __init__(self):
            self.id = "call_1"
            self.function = SimpleNamespace(name="echo", arguments='{"x":1}')

        def as_dict(self):
            return {"id": self.id, "type": "function", "function": {"name": self.function.name, "arguments": self.function.arguments}}

    tool_call = _ToolCall()

    class _ToolMessage(_FakeMessage):
        def model_dump(self):
            return {"role": "assistant", "content": None, "tool_calls": [tool_call.as_dict()]}

    first_response = _ToolMessage(content=None, tool_calls=[tool_call])

    async def fake_submit(**kwargs):
        return "[]", first_response

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(chat, "execute_tool_call", lambda tc: {"ok": True})

    chat.auto_execute = True
    chat.auto_feed = False
    out = await chat.chat_a()
    messages = out.get_messages()
    assert any(msg["role"] == "assistant" and msg.get("tool_calls") for msg in messages)
    assert any(msg["role"] == "tool" for msg in messages)


@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_chat_parity_preserves_response_history(chat, monkeypatch, use_runtime_adapter):
    _set_runtime_mode(chat, use_runtime_adapter)

    async def fake_submit(**kwargs):
        return '[{"role":"user","content":"hello"}]', "reply"

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)

    output = chat.chat()
    assert output.get_messages() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "reply"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
async def test_chat_a_parity_tool_recursion_history(chat, monkeypatch, use_runtime_adapter):
    _set_runtime_mode(chat, use_runtime_adapter)
    chat.auto_execute = True
    chat.auto_feed = True
    chat.user("hello")

    class _ToolCall:
        id = "call_1"
        function = SimpleNamespace(name="echo", arguments='{"x":1}')

    class _ToolMessage(_FakeMessage):
        def model_dump(self):
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "echo", "arguments": '{"x":1}'},
                    }
                ],
            }

    async def fake_submit(**kwargs):
        return "[]", _ToolMessage(content=None, tool_calls=[_ToolCall()])

    async def fake_follow_up(self, prompt, **kwargs):
        return "final"

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(chat, "execute_tool_call", lambda tc: {"ok": True})
    monkeypatch.setattr(Chat, "_cleaned_chat_completion", fake_follow_up)

    output = await chat.chat_a()
    roles = [msg["role"] for msg in output.get_messages()]
    assert roles == ["assistant", "tool", "assistant"]
    assert output.get_messages()[-1]["content"] == "final"


def test_listen_events_true_defaults_to_legacy_schema(chat, monkeypatch):
    class _DummyListener:
        def __init__(self):
            self.events = False
            self.event_schema = None
            self.started = False

        def start(self):
            self.started = True

    async def fake_submit(**kwargs):
        return "[]", _DummyListener()

    chat.stream = True
    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)

    listener = chat.listen(events=True)

    assert listener.events is True
    assert listener.event_schema == "legacy"
    assert listener.started is True


@pytest.mark.asyncio
async def test_listen_a_events_true_defaults_to_legacy_schema(chat, monkeypatch):
    class _DummyListener:
        def __init__(self):
            self.events = False
            self.event_schema = None
            self.started = False

        async def start_a(self):
            self.started = True

    async def fake_submit(**kwargs):
        return "[]", _DummyListener()

    chat.stream = True
    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)

    listener = await chat.listen_a(events=True)

    assert listener.events is True
    assert listener.event_schema == "legacy"
    assert listener.started is True

@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_listen_returns_plain_str_payload_when_stream_disabled(chat, monkeypatch, use_runtime_adapter):
    _set_runtime_mode(chat, use_runtime_adapter)

    async def fake_submit(**kwargs):
        return "[]", "plain-completion"

    chat.stream = False
    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)

    response = chat.listen(events=True)

    assert response == "plain-completion"
    assert isinstance(response, str)
    assert not hasattr(response, "events")


@pytest.mark.asyncio
async def test_listen_a_raises_when_stream_disabled(chat):
    chat.stream = False
    with pytest.raises(Exception, match=r"Cannot use listen\(\) without a stream"):
        await chat.listen_a(events=True)


# ---------------------------------------------------------------------------
# Live API parity tests – skipped when OPENAI_API_KEY is absent.
#
# These tests do NOT mock _submit_for_response_and_prompt.  They exercise
# the full runtime-adapter (ChatCompletionsAdapter) and legacy-client paths
# end-to-end so that real regressions in either branch are caught.
# ---------------------------------------------------------------------------

_LIVE_SYSTEM = "Respond only with the single word POPSICLE, nothing else."
_LIVE_PROMPT = "What is your response?"
_POPSICLE = "POPSICLE"

_skip_no_key = pytest.mark.skipif(
    os.environ.get("OPENAI_API_KEY") is None,
    reason="OPENAI_API_KEY is not set in environment or .env",
)


def _make_live_chat(use_runtime_adapter: bool) -> "Chat":
    """Return a Chat configured for live API calls."""
    c = Chat()
    _set_runtime_mode(c, use_runtime_adapter)
    c.system(_LIVE_SYSTEM)
    c.user(_LIVE_PROMPT)
    return c


def _make_live_responses_gpt54_chat() -> "Chat":
    """Return a Responses-runtime chat pinned to gpt-5.4 for continuation live tests."""
    c = Chat(runtime_selector="responses", params=ChatParams(model="gpt-5.4"))
    return c


@_skip_no_key
def test_live_responses_continuation_ownership_gpt54():
    """Live multi-turn continuation should be owned internally for Responses runtime on gpt-5.4."""
    chat = _make_live_responses_gpt54_chat()

    first = chat.chat("Return exactly: TURN_ONE_OK")
    first_messages = first.get_messages()
    first_assistant = [m for m in first_messages if m["role"] == "assistant"]
    assert len(first_assistant) >= 1
    assert "TURN_ONE_OK" in (first_assistant[-1].get("content") or "").upper()

    first_response_id = first._last_runtime_metadata["response_id"]
    assert first_response_id

    second = first.chat("Return exactly: TURN_TWO_OK")
    second_messages = second.get_messages()
    second_assistant = [m for m in second_messages if m["role"] == "assistant"]
    assert len(second_assistant) >= 1
    assert "TURN_TWO_OK" in (second_assistant[-1].get("content") or "").upper()

    second_response_id = second._last_runtime_metadata["response_id"]
    assert second_response_id
    assert second_response_id != first_response_id


@_skip_no_key
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_live_ask_parity(use_runtime_adapter):
    """Both adapter paths return a non-empty string via ask()."""
    c = _make_live_chat(use_runtime_adapter)
    response = c.ask()
    assert isinstance(response, str)
    assert len(response) > 0
    assert _POPSICLE in response.upper()


@_skip_no_key
@pytest.mark.asyncio
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
async def test_live_ask_a_parity(use_runtime_adapter):
    """Both adapter paths return a non-empty string via ask_a()."""
    c = _make_live_chat(use_runtime_adapter)
    response = await c.ask_a()
    assert isinstance(response, str)
    assert len(response) > 0
    assert _POPSICLE in response.upper()


@_skip_no_key
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_live_chat_parity(use_runtime_adapter):
    """Both adapter paths return a Chat with an assistant message via chat()."""
    c = _make_live_chat(use_runtime_adapter)
    result = c.chat()
    messages = result.get_messages()
    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) >= 1
    assert _POPSICLE in assistant_messages[-1]["content"].upper()


@_skip_no_key
@pytest.mark.asyncio
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
async def test_live_chat_a_parity(use_runtime_adapter):
    """Both adapter paths return a Chat with an assistant message via chat_a()."""
    c = _make_live_chat(use_runtime_adapter)
    result = await c.chat_a()
    messages = result.get_messages()
    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) >= 1
    assert _POPSICLE in assistant_messages[-1]["content"].upper()


@_skip_no_key
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_live_listen_non_stream_parity(use_runtime_adapter):
    """Both adapter paths return the plain response string via listen() when stream=False."""
    c = _make_live_chat(use_runtime_adapter)
    # stream defaults to False; listen() returns the completion string directly
    response = c.listen()
    assert isinstance(response, str)
    assert len(response) > 0
    assert _POPSICLE in response.upper()


@_skip_no_key
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
def test_live_listen_stream_parity(use_runtime_adapter):
    """Both adapter paths yield text chunks and accumulate the full response via listen() when stream=True."""
    c = _make_live_chat(use_runtime_adapter)
    c.stream = True
    listener = c.listen()
    chunks = list(listener)
    full_text = "".join(chunks)
    assert len(full_text) > 0
    assert _POPSICLE in full_text.upper()
    # The listener should have accumulated the complete response too
    assert listener.is_complete
    assert _POPSICLE in listener.response.upper()


@_skip_no_key
@pytest.mark.asyncio
@pytest.mark.parametrize("use_runtime_adapter", [True, False])
async def test_live_listen_a_stream_parity(use_runtime_adapter):
    """Both adapter paths yield text chunks via listen_a() when stream=True."""
    c = _make_live_chat(use_runtime_adapter)
    c.stream = True
    listener = await c.listen_a()
    chunks = []
    async for chunk in listener:
        chunks.append(chunk)
    full_text = "".join(chunks)
    assert len(full_text) > 0
    assert _POPSICLE in full_text.upper()
    assert listener.is_complete
    assert _POPSICLE in listener.response.upper()


def test_runtime_selector_responses_surfaces_aiclient_capability_error(chat):
    def _raise():
        raise RuntimeError("missing responses endpoints")

    chat.ai = SimpleNamespace(ensure_responses_support=_raise)

    with pytest.raises(RuntimeError, match="missing responses endpoints"):
        chat._select_runtime(runtime_selector="responses")
