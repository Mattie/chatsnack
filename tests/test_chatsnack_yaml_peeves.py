import pytest
from ruamel.yaml import YAML
import pytest
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR, ChatParams
import os
import shutil

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


def read_yaml_file(file_path):
    yaml = YAML()
    with open(file_path, 'r') as yaml_file:
        return yaml.load(yaml_file)


def test_yaml_file_has_no_empty_values():
    chat = Chat(name="test_text_chat_expansion")
    chat.system("Respond only with 'DUCK!' regardless of what is said.")
    chat.user("Should I buy a goose or a duck?")
    chat.params = ChatParams(temperature = 0.0)
    chat.save()

    yaml_data = read_yaml_file(chat.datafile.path)
    messages = yaml_data.get('messages')

    if not messages:
        pytest.fail("YAML file has no 'messages' field")

    for message in messages:
        for key, value in message.items():
            if value == '' or value is None:
                pytest.fail(f"Empty value found in '{key}' field")

def test_yaml_file_has_no_empty_values2():
    chat = Chat(name="test_text_chat_expansion")
    chat.system("Respond only with 'DUCK!' regardless of what is said.")
    chat.user("Should I buy a goose or a duck?")
    chat.params = ChatParams(temperature = 0.0, stream = True) # setting stream property
    chat.save()

    yaml_data = read_yaml_file(chat.datafile.path)
    messages = yaml_data.get('messages')
    chat_params = yaml_data.get('params') # getting params field

    if not messages:
        pytest.fail("YAML file has no 'messages' field")

    if not chat_params:
        pytest.fail("YAML file has no 'params' field")
    
    if chat_params.get('stream') is None:
        pytest.fail("YAML file has no 'stream' field in 'params'")

    for message in messages:
        for key, value in message.items():
            if value == '' or value is None:
                pytest.fail(f"Empty value found in '{key}' field")
                
    assert chat_params.get('stream') == True, "Stream value not saved correctly in the YAML file"

    chat.params = None
    chat.stream = False
    chat.save()

    yaml_data = read_yaml_file(chat.datafile.path)
    chat_params = yaml_data.get('params') # getting params field

    if not chat_params:
        pytest.fail("YAML file has no 'params' field")
    
    # assert that stream is False as we said it should be
    assert chat_params.get('stream') == False, "Stream value not saved correctly in the YAML file"