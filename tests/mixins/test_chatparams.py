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
    assert chat_params.engine == "gpt-3.5-turbo"

def test_engine_set(chat_params_mixin):
    chat_params_mixin.engine = "gpt-4"
    assert chat_params_mixin.engine == "gpt-4"

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

