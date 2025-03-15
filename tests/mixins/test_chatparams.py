import os
import pytest
from chatsnack.packs import Jane
from chatsnack import Chat, ChatParams

@pytest.fixture
def chat_params():
    return ChatParams()

@pytest.fixture 
def chat_params_mixin():
    # Creates a Chat instance; its params will be None until a property is set.
    return Chat()

def test_engine_default(chat_params):
    assert chat_params.model == "gpt-4-turbo"

def test_engine_set(chat_params_mixin):
    chat_params_mixin.model = "gpt-4"
    assert chat_params_mixin.model == "gpt-4"

@pytest.mark.parametrize("temp, expected", [(0.5, 0.5), (0.8, 0.8)]) 
def test_temperature(chat_params_mixin, temp, expected):
    chat_params_mixin.temperature = temp
    assert chat_params_mixin.temperature == expected

def test_stream_default(chat_params_mixin):
    assert chat_params_mixin.stream == False

def test_stream_set(chat_params_mixin):
    chat_params_mixin.stream = True
    assert chat_params_mixin.stream == True

def test_stream_change(chat_params_mixin):
    chat_params_mixin.stream = True
    assert chat_params_mixin.stream == True
    chat_params_mixin.stream = False
    assert chat_params_mixin.stream == False

# Additional tests for tool-related parameters

def test_auto_execute_default(chat_params_mixin):
    """
    By default, if auto_execute was not explicitly set, the property should return None.
    (i.e. ChatParams should not be auto-created just for reading auto_execute)
    """
    # Assuming no auto_execute was set during construction, it should be None.
    assert chat_params_mixin.auto_execute is None

def test_set_auto_execute_creates_params(chat_params_mixin):
    """
    When auto_execute is explicitly set, the ChatParams should be created and the value stored.
    """
    chat_params_mixin.auto_execute = False
    # Now params should have been created
    assert chat_params_mixin.params is not None
    assert chat_params_mixin.auto_execute is False

def test_tool_choice_default(chat_params_mixin):
    """
    By default, if tool_choice was not explicitly set, it should return None.
    """
    assert chat_params_mixin.tool_choice is None

def test_set_tool_choice_creates_params(chat_params_mixin):
    """
    When tool_choice is set, the ChatParams is created if needed and returns the correct value.
    """
    chat_params_mixin.tool_choice = "manual"
    assert chat_params_mixin.params is not None
    assert chat_params_mixin.tool_choice == "manual"



# Existing engine tests for various models; you can skip these if needed.
@pytest.mark.parametrize("engine", ["gpt-3.5-turbo", "gpt-4", "gpt-4o", "o1", "o1-mini", "o3-mini", "o1-preview", "gpt-4o-mini", "gpt-4-turbo", "chatgpt-4o-latest", "gpt-4.5-preview"])
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
def test_engines(engine):
    SENTENCE = "A short sentence about the difference between green and blue."
    TEMPERATURE = 0.0
    SEED = 42
    ENGINE = engine
    
    # Jane is an existing chat we can build upon
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.temperature = TEMPERATURE
    cp.seed = SEED
    cp.model = ENGINE

    output_iter = cp.listen()
    output = ''.join(list(output_iter))

    assert output is not None
    assert len(output) > 0
    print(output)
