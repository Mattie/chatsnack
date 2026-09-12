import pytest
from chatsnack import Chat
from chatsnack.runtime.conversation import copy_value


@pytest.mark.parametrize("loaded", [False, True], ids=["constructed", "loaded"])
@pytest.mark.parametrize("role", ["system", "developer"])
def test_reset_restores_expanded_system_metadata(tmp_path, loaded, role):
    """Reset restores the saved system block, including nested metadata, every time."""
    chat = Chat(messages=[{role: {"text": "Rules", "provider_extras": {
        "future": {"items": [], "nullable": None}}}}, {"user": "Hi"}])
    if loaded:
        path = tmp_path / "reset.yml"
        chat.save(str(path))
        chat = Chat()
        chat.load(str(path))
    original = copy_value(chat.messages)
    for _ in range(2):
        block = next(iter(chat.messages[0].values()))
        block["provider_extras"]["future"]["items"].append("changed")
        chat.system("Temporary rules").user("Later")
        chat.reset()
        assert chat.messages == original
        assert chat.system_message == "Rules"

def test_reset_feature():
    # Create a Chat object with a user message
    my_chat = Chat().user("What's the weather like today?")

    # Check the current chat messages
    assert len(my_chat.get_messages()) == 1

    # Reset the chat object
    my_chat.reset()

    # Check the chat messages after reset
    assert len(my_chat.get_messages()) == 0

def test_reset_with_system_message():
    my_chat = Chat().system("You are an AI assistant.").user("What's the weather like today?")

    # Check the current chat messages
    assert len(my_chat.get_messages()) == 2

    # Reset the chat object
    my_chat.reset()

    # Check the chat messages after reset
    assert len(my_chat.get_messages()) == 0

def test_reset_idempotence():
    my_chat = Chat().user("What's the weather like today?").reset().reset()

    # Check the chat messages after calling reset() twice
    assert len(my_chat.get_messages()) == 0

def test_reset_interaction_with_other_methods():
    my_chat = Chat().user("What's the weather like today?")
    my_chat.reset()
    my_chat.user("How are you?")

    # Check the chat messages after reset and adding a new user message
    messages = my_chat.get_messages()
    assert len(messages) == 1
    assert messages[0]['role'] == 'user'
    assert messages[0]['content'] == 'How are you?'

def test_reset_empty_chat():
    # Create an empty Chat object
    my_chat = Chat()

    # Reset the empty Chat object
    my_chat.reset()

    # Check the chat messages after reset
    assert len(my_chat.get_messages()) == 0

def test_reset_with_includes(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    # Create a base chat and save it
    base_chat = Chat(name="BaseChat").user("What's your favorite color?")
    base_chat.save()

    # Create a new chat with included messages from the base chat
    my_chat = Chat().include("BaseChat").user("What's your favorite animal?")

    # Check the current chat messages
    assert len(my_chat.get_messages()) == 2

    # Reset the chat object
    my_chat.reset()

    # Check the chat messages after reset
    assert len(my_chat.get_messages()) == 0
