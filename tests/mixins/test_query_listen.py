import pytest
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR


import pytest
import asyncio
from chatsnack.chat.mixin_query import ChatStreamListener
from chatsnack.aiclient import AiClient




@pytest.mark.asyncio
async def test_get_responses_a():
    ai = AiClient()
    listener = ChatStreamListener(ai, '[{"role":"system","content":"Respond only with POPSICLE 20 times."}]')
    responses = []
    await listener.start_a()
    async for resp in listener:
        responses.append(resp)
    assert len(responses) > 10
    assert listener.is_complete
    assert 'POPSICLE' in listener.current_content
    assert 'POPSICLE' in listener.response

def test_get_responses():
    ai = AiClient()
    listener = ChatStreamListener(ai, '[{"role":"system","content":"Respond only with POPSICLE 20 times."}]')
    listener.start()
    responses = list(listener)
    assert len(responses) > 10
    assert listener.is_complete
    assert 'POPSICLE' in listener.current_content
    assert 'POPSICLE' in listener.response

import os
import pytest
from chatsnack.packs import Jane



@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
def test_listen():
    # Define constants
    SENTENCE = "A short sentence about the difference between green and blue."
    TEMPERATURE = 0.0
    # TODO: Rework this such that it doesn't risk being flaky. If you get a different system behind the scenes, even 
    #       the seed won't be enough
    SEED = 42

    # First part of the test
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.stream = True
    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # Listen to the response
    output_iter = cp.listen()
    output = ''.join(list(output_iter))

    # Second part of the test
    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # Ask the same question
    ask_output = cp.ask()

    # Asserts
    assert output is not None
    assert len(output) > 0
    assert output == ask_output

@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
@pytest.mark.asyncio
async def test_listen_a():
    # Define constants
    SENTENCE = "A short sentence about the difference between green and blue"
    TEMPERATURE = 0.0
    # TODO: Rework this such that it doesn't risk being flaky. If you get a different system behind the scenes, even 
    #       the seed won't be enough
    SEED = 42

    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.stream = True
    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # listen to the response asynchronously
    output = []
    async for part in await cp.listen_a():
        output.append(part)
    output = ''.join(output)
    print(output)

    chat = Jane.copy()
    cp = chat.user(SENTENCE)
    assert cp.last == SENTENCE

    cp.stream = False
    cp.temperature = TEMPERATURE
    cp.seed = SEED

    # ask the same question
    ask_output = cp.ask()
    print(ask_output)
    # is there a response and it's longer than 0 characters?
    assert output is not None
    assert len(output) > 0

    # assert that the output of listen is the same as the output of ask
    assert output == ask_output
