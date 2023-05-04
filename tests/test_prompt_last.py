import os
import pytest
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

def test_last_property(populated_prompt):
    assert populated_prompt.last == "Hi there!"


def test_add_message(populated_prompt):
    populated_prompt.add_message("system", "System message")
    assert populated_prompt.last == "System message"

def test_empty_messages(empty_prompt):
    assert empty_prompt.last is None

def test_adding_different_roles(empty_prompt):
    empty_prompt.add_message("user", "Test user")
    empty_prompt.add_message("assistant", "Test assistant")
    empty_prompt.add_message("system", "Test system")
    empty_prompt.add_message("include", "Test include")

    assert empty_prompt.messages == [
        {"user": "Test user"},
        {"assistant": "Test assistant"},
        {"system": "Test system"},
        {"include": "Test include"},
    ]

def test_message_order(empty_prompt):
    empty_prompt.add_message("user", "First message")
    empty_prompt.add_message("assistant", "Second message")
    empty_prompt.add_message("user", "Third message")
    empty_prompt.add_message("assistant", "Fourth message")

    assert [msg["user" if "user" in msg else "assistant"] for msg in empty_prompt.messages] == [
        "First message",
        "Second message",
        "Third message",
        "Fourth message",
    ]

# Not enforced at all
# def test_invalid_role(empty_prompt):
#     with pytest.raises(Exception):
#         empty_prompt.add_message("invalid_role", "Test content")
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
def test_chaining_methods_execution(populated_prompt):
    new_prompt = populated_prompt().user("How's the weather?")
    assert new_prompt.last == "How's the weather?"

def test_chaining_methods_messages(empty_prompt):
    new_prompt = empty_prompt.system("You are a happy robot.").user("How's the weather?").assistant("It's sunny today.").user("How about tomorrow?")
    assert new_prompt.last == "How about tomorrow?"


@pytest.mark.asyncio
async def test_concurrent_access(populated_prompt):
    import asyncio

    async def add_messages():
        for i in range(10):
            populated_prompt.add_message("assistant", f"Message {i}")

    tasks = [add_messages() for _ in range(10)]
    await asyncio.gather(*tasks)

    assert len(populated_prompt.messages) == 102
