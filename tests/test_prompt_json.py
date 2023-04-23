import pytest
import json
from chatsnack import Chat

@pytest.fixture
def empty_prompt():
    return Chat()

@pytest.fixture
def populated_prompt():
    prompt = Chat()
    prompt.add_message("user", "Hello!")
    prompt.add_message("assistant", "Hi there!")
    return prompt

def test_add_messages_json(populated_prompt):
    messages_json = """
        [
            {"role": "user", "content": "What's the weather like?"},
            {"role": "assistant", "content": "It's sunny outside."}
        ]
    """
    populated_prompt.add_messages_json(messages_json)

    assert populated_prompt.messages[-2:] == [
        {"user": "What's the weather like?"},
        {"assistant": "It's sunny outside."}
    ]

def test_get_json(populated_prompt):
    l = [{"role":"user", "content": "Hello!"},
         {"role":"assistant", "content": "Hi there!"}]
    
    expected_json = json.dumps(l)

    assert populated_prompt.json == expected_json

def test_add_messages_json_invalid_format(populated_prompt):
    invalid_messages_json = """
        [
            {"role": "user"},
            {"role": "assistant", "content": "It's sunny outside."}
        ]
    """
    with pytest.raises(Exception):
        populated_prompt.add_messages_json(invalid_messages_json)

def test_add_messages_json_invalid_type(populated_prompt):
    invalid_messages_json = """
        [
            {"role": "user", "something": "It's sunny outside."]},
            {"role": "assistant", "content": "It's sunny outside."}
        ]
    """
    with pytest.raises(Exception):
        populated_prompt.add_messages_json(invalid_messages_json)
