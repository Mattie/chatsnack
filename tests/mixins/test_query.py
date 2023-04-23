import pytest
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR

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




