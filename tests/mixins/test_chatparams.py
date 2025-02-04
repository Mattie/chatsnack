import pytest
#from chatsnack.chat.mixin_params import ChatParams, ChatParamsMixin
from chatsnack import Chat, ChatParams

@pytest.fixture
def chat_params():
    return ChatParams()

@pytest.fixture 
def chat_params_mixin(chat_params):
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

import os
import pytest
from chatsnack.packs import Jane

# test with all the current available models, to ensure chat parameters are morphing correctly between the different models
@pytest.mark.parametrize("engine", ["gpt-3.5-turbo", "gpt-4", "gpt-4o", "o1", "o1-mini", "o3-mini", "o1-preview", "gpt-4o-mini", "gpt-4-turbo", "chatgpt-4o-latest"])
@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
def test_engines(engine):
    # Define constants
    SENTENCE = "A short sentence about the difference between green and blue."
    TEMPERATURE = 0.0
    SEED = 42
    ENGINE = engine

    # First part of the test
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.temperature = TEMPERATURE
    cp.seed = SEED
    cp.model = ENGINE

    # Listen to the response
    output_iter = cp.listen()
    output = ''.join(list(output_iter))

    # Asserts
    assert output is not None
    assert len(output) > 0
    print(output)
