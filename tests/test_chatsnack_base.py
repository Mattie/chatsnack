import pytest
from chatsnack import Chat

@pytest.fixture
def sample_chatprompt():
    return Chat(name="sample_chatprompt", messages=[{"user": "hello"}])

@pytest.fixture
def empty_chatprompt():
    return Chat()


# Test initialization
def test_chatprompt_init():
    cp = Chat(name="test_chatprompt")
    assert cp.name == "test_chatprompt"
    assert cp.params is None
    assert cp.messages == []


# Test message manipulation
def test_add_message(sample_chatprompt):
    sample_chatprompt.add_message("assistant", "hi there")
    assert sample_chatprompt.last == "hi there"


def test_add_messages_json(sample_chatprompt):
    json_messages = '[{"role": "assistant", "content": "hi there"}]'
    sample_chatprompt.add_messages_json(json_messages)
    assert sample_chatprompt.last == "hi there"


def test_system(sample_chatprompt):
    sample_chatprompt.system("system message")
    assert sample_chatprompt.system_message == "system message"


def test_user(sample_chatprompt):
    sample_chatprompt.user("user message")
    assert sample_chatprompt.last == "user message"


def test_assistant(sample_chatprompt):
    sample_chatprompt.assistant("assistant message")
    assert sample_chatprompt.last == "assistant message"


def test_include(sample_chatprompt):
    sample_chatprompt.include("other_chatprompt")
    assert sample_chatprompt.last == "other_chatprompt"


# Test get_last_message method
def test_get_last_message(sample_chatprompt):
    assert sample_chatprompt.last == "hello"


# Test get_json method
def test_get_json(sample_chatprompt):
    json_str = sample_chatprompt.json
    assert json_str == '[{"role": "user", "content": "hello"}]'

# Test get_system_message method
def test_get_system_message(empty_chatprompt):
    assert empty_chatprompt.system_message is None

    empty_chatprompt.system("this is a system message")
    assert empty_chatprompt.system_message == "this is a system message"

    # be sure it doesn't return user messages
    empty_chatprompt.user("this is a user message")
    assert empty_chatprompt.system_message == "this is a system message"

    # be sure it updates to provide the current system message
    empty_chatprompt.system("this is another system message")
    assert empty_chatprompt.system_message == "this is another system message"

    # delete all messages
    empty_chatprompt.messages = {}
    assert empty_chatprompt.system_message is None
