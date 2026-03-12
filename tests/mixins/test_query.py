import pytest
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR
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
from types import SimpleNamespace


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
async def test_sync_methods_fail_fast_in_active_loop(chat, monkeypatch):
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
async def test_async_methods_work_in_active_loop(chat, monkeypatch):
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

def test_listen_returns_plain_str_payload_when_stream_disabled(chat, monkeypatch):
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
