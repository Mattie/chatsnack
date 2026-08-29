import os
import warnings

import pytest

_RUN_OPENAI_LIVE = os.environ.get("CHATSNACK_RUN_LIVE_TESTS", "").lower() in {
    "1",
    "true",
    "yes",
}

from chatsnack.packs import Jane
from chatsnack.chat.mixin_params import DEFAULT_MODEL_FALLBACK
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
@pytest.mark.parametrize("engine", ["gpt-3.5-turbo", "gpt-4", "gpt-4o", "o1", "o3-mini", "gpt-4o-mini", "gpt-4-turbo", "gpt-5-nano", "gpt-5-mini", "gpt-5.6-terra", "gpt-5.4"])
@pytest.mark.skipif(
    not _RUN_OPENAI_LIVE or not os.environ.get("OPENAI_API_KEY"),
    reason="Live OpenAI tests require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)
def test_engines(engine):
    SENTENCE = "A short sentence about the difference between green and blue."
    ENGINE = engine
    
    # Jane is an existing chat we can build upon
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.model = ENGINE

    output_iter = cp.listen()
    output = ''.join(list(output_iter))

    assert output is not None
    assert len(output) > 0
    print(output)


def test_get_non_none_params_default_model_fallback(chat_params):
    chat_params.model = ""
    out = chat_params._get_non_none_params()
    assert DEFAULT_MODEL_FALLBACK == "gpt-5.4"
    assert out["model"] == "gpt-5.4"


def test_get_non_none_params_preserves_profile(chat_params):
    chat_params.profile = {"defaults": {"temperature": 0.5}}
    out = chat_params._get_non_none_params()
    assert "profile" in out
    assert out["profile"] == {"defaults": {"temperature": 0.5}}


def test_provider_model_options_pass_through_and_client_fields_do_not():
    params = ChatParams(
        model="openrouter/vendor-new-model",
        temperature=0.73,
        max_tokens=321,
        base_url="https://provider.example/v1",
        api_key_env="PROVIDER_KEY",
    )

    provider_params = params._get_non_none_params()

    assert provider_params["temperature"] == 0.73
    assert provider_params["max_tokens"] == 321
    assert "base_url" not in provider_params
    assert "api_key_env" not in provider_params


def test_reasoning_model_temperature_passes_through_without_local_warning():
    params = ChatParams(model="gpt-5.4", temperature=0.2)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        provider_params = params._get_non_none_params()

    assert caught == []
    assert provider_params["temperature"] == 0.2


@pytest.mark.asyncio
async def test_reasoning_model_role_remap_to_developer(chat_params_mixin):
    chat_params_mixin.model = "o1"
    chat_params_mixin.system("You are system")
    prompt = await chat_params_mixin._build_final_prompt()
    import json
    messages = json.loads(prompt)
    assert messages[0]["role"] == "developer"


@pytest.mark.asyncio
async def test_o1_preview_role_remap_to_user(chat_params_mixin):
    chat_params_mixin.model = "o1-preview"
    chat_params_mixin.system("You are system")
    prompt = await chat_params_mixin._build_final_prompt()
    import json
    messages = json.loads(prompt)
    assert messages[0]["role"] == "user"
