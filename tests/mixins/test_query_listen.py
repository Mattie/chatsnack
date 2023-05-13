import pytest
from chatsnack import Chat, Text, CHATSNACK_BASE_DIR


import pytest
import asyncio
from chatsnack.chat.mixin_query import ChatStreamListener

# Assuming _chatcompletion is in the same module as ChatStreamListener
from chatsnack.aiwrapper import _chatcompletion


@pytest.mark.asyncio
async def test_get_responses_a():
    listener = ChatStreamListener('[{"role":"system","content":"Respond only with POPSICLE 20 times."}]')
    responses = []
    await listener.start_a()
    async for resp in listener:
        responses.append(resp)
    assert len(responses) > 10
    assert listener.is_complete
    assert 'POPSICLE' in listener.current_content
    assert 'POPSICLE' in listener.response

def test_get_responses():
    listener = ChatStreamListener('[{"role":"system","content":"Respond only with POPSICLE 20 times."}]')
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
    chat = Jane.copy()
    cp = chat.user("Or is green a form of blue?")
    assert cp.last == "Or is green a form of blue?"

    cp.stream = True
    cp.temperature = 0.0

    # listen to the response
    output_iter = cp.listen()
    output = ''.join(list(output_iter))

    chat = Jane.copy()
    cp = chat.user("Or is green a form of blue?")
    assert cp.last == "Or is green a form of blue?"

    cp.temperature = 0.0

    # ask the same question
    ask_output = cp.ask()

    # is there a response and it's longer than 0 characters?
    assert output is not None
    assert len(output) > 0

    # assert that the output of listen is the same as the output of ask
    assert output == ask_output


@pytest.mark.skipif(os.environ.get("OPENAI_API_KEY") is None, reason="OPENAI_API_KEY is not set in environment or .env")
@pytest.mark.asyncio
async def test_listen_a():
    chat = Jane.copy()
    cp = chat.user("Or is green a form of blue?")
    assert cp.last == "Or is green a form of blue?"

    cp.stream = True
    cp.temperature = 0.0

    # listen to the response asynchronously
    output = []
    async for part in await cp.listen_a():
        output.append(part)
    output = ''.join(output)

    chat = Jane.copy()
    cp = chat.user("Or is green a form of blue?")
    assert cp.last == "Or is green a form of blue?"

    cp.temperature = 0.0

    # ask the same question
    ask_output = cp.ask()

    # is there a response and it's longer than 0 characters?
    assert output is not None
    assert len(output) > 0

    # assert that the output of listen is the same as the output of ask
    assert output == ask_output
