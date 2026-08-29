import os
import pytest
from chatsnack.packs import Jane as chat


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY")
    or os.environ.get("CHATSNACK_RUN_LIVE_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="Live OpenAI tests require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)
def test_snackpack_chat():
    cp = chat.user("Or is green a form of blue?")
    assert cp.last == "Or is green a form of blue?"

    # ask the question
    output = cp.ask()
    # is there a response and it's longer than 0 characters?
    assert output is not None
    assert len(output) > 0


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY")
    or os.environ.get("CHATSNACK_RUN_LIVE_TESTS", "").lower() not in {"1", "true", "yes"},
    reason="Live OpenAI tests require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1",
)
def test_snackpack_ask_with_existing_asst():
    cp = chat.copy()
    cp.user("Is the sky blue?")
    cp.asst("No! ")
    # ask the question
    output = cp.ask()
    # is there a response and it's longer than 0 characters?
    assert output is not None
    assert len(output) > 0

    # check to see if the asst response was appended to
    # the existing asst response
    # check to see if the cp.response starts with "No! "
    output = cp.response
    assert output.startswith("No! ")
