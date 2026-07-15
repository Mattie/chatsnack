from types import SimpleNamespace

import pytest
from loguru import logger
from snapclass import SnapclassError

from chatsnack import Chat, ChatParams


_OMITTED = object()


class _FakeAiClient:
    client = SimpleNamespace()
    aclient = SimpleNamespace()

    def ensure_responses_support(self):
        pass


@pytest.fixture(autouse=True)
def _use_lightweight_ai_client(monkeypatch):
    """Keep tool-loop tests local and avoid opening real SDK clients."""
    monkeypatch.setattr("chatsnack.chat.AiClient", _FakeAiClient)


class _ToolCall:
    def __init__(self, name: str, index: int):
        self.id = f"call_{index}"
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments="{}")


class _ToolMessage:
    content = None

    def __init__(self, *names: str, offset: int = 0):
        self.tool_calls = [
            _ToolCall(name, offset + index)
            for index, name in enumerate(names)
        ]


async def _run_tool_chain(chat, monkeypatch, tool_batches, auto_feed=_OMITTED):
    batches = iter(tool_batches)
    first_batch = next(batches)
    follow_ups = []
    executed = []

    async def fake_submit(**kwargs):
        return "[]", _ToolMessage(*first_batch)

    async def fake_follow_up(self, prompt, **kwargs):
        follow_ups.append(prompt)
        try:
            names = next(batches)
        except StopIteration:
            return "done"
        return _ToolMessage(*names, offset=len(follow_ups) * 10)

    def fake_execute(tool_call):
        executed.append(tool_call["function"]["name"])
        return {"accepted": True}

    monkeypatch.setattr(chat, "_submit_for_response_and_prompt", fake_submit)
    monkeypatch.setattr(Chat, "_cleaned_chat_completion", fake_follow_up)
    monkeypatch.setattr(chat, "execute_tool_call", fake_execute)

    chat.auto_execute = True
    if auto_feed is not _OMITTED:
        chat.auto_feed = auto_feed
    output = await chat.chat_a()
    return output, executed, follow_ups


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["responses", "chat_completions"])
async def test_auto_feed_six_executes_sixth_terminal_tool(runtime, monkeypatch):
    """Goal: a longer curator chain can execute its sixth terminal utensil."""
    chat = Chat(runtime=runtime)
    batches = [
        ["resolve_names"],
        ["search_articles"],
        ["search_claims"],
        ["search_claims"],
        ["read_articles"],
        ["submit_curator_plan"],
    ]

    output, executed, follow_ups = await _run_tool_chain(
        chat,
        monkeypatch,
        batches,
        auto_feed=6,
    )

    assert executed == [batch[0] for batch in batches]
    assert len(follow_ups) == 6
    assert output.last == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auto_feed",
    [_OMITTED, True, None],
    ids=["omitted", "true", "none"],
)
async def test_legacy_auto_feed_limit_retains_sixth_pending_call(
    auto_feed,
    monkeypatch,
):
    """Companion Goal: legacy settings still allow exactly five feed cycles."""
    chat = Chat()
    batches = [[f"tool_{index}"] for index in range(1, 6)]
    batches.append(["submit_curator_plan"])

    output, executed, follow_ups = await _run_tool_chain(
        chat,
        monkeypatch,
        batches,
        auto_feed=auto_feed,
    )

    assert executed == [f"tool_{index}" for index in range(1, 6)]
    assert len(follow_ups) == 5
    assert output.get_messages()[-1]["tool_calls"][0]["function"]["name"] == "submit_curator_plan"


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_feed", [False, 0])
async def test_zero_and_false_execute_pending_batch_without_follow_up(
    auto_feed,
    monkeypatch,
):
    chat = Chat()

    output, executed, follow_ups = await _run_tool_chain(
        chat,
        monkeypatch,
        [["resolve_names"], ["unused_follow_up"]],
        auto_feed=auto_feed,
    )

    assert executed == ["resolve_names"]
    assert follow_ups == []
    assert output.get_messages()[-1]["content"] == '{"accepted": true}'


@pytest.mark.asyncio
async def test_one_feed_cycle_counts_parallel_calls_as_one_batch(monkeypatch):
    chat = Chat()

    output, executed, follow_ups = await _run_tool_chain(
        chat,
        monkeypatch,
        [["search_articles", "search_claims"], ["submit_curator_plan"]],
        auto_feed=1,
    )

    assert executed == ["search_articles", "search_claims"]
    assert len(follow_ups) == 1
    assert output.get_messages()[-1]["tool_calls"][0]["function"]["name"] == "submit_curator_plan"


@pytest.mark.asyncio
async def test_exhaustion_warning_names_unexecuted_tool(monkeypatch):
    chat = Chat()
    warnings = []
    sink = logger.add(warnings.append, level="WARNING", format="{message}")
    try:
        await _run_tool_chain(
            chat,
            monkeypatch,
            [["resolve_names"], ["submit_curator_plan"]],
            auto_feed=1,
        )
    finally:
        logger.remove(sink)

    warning = "\n".join(str(message) for message in warnings)
    assert "auto_feed limit (1)" in warning
    assert "recorded but not executed" in warning
    assert "submit_curator_plan" in warning


def test_auto_feed_default_and_invalid_values():
    assert ChatParams().auto_feed is True

    with pytest.raises(ValueError, match="non-negative"):
        ChatParams(auto_feed=-1)

    with pytest.raises(TypeError, match="True, False, None"):
        ChatParams(auto_feed=1.5)


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [
        (True, bool),
        (False, bool),
        (0, int),
        (1, int),
        (12, int),
    ],
)
def test_auto_feed_values_round_trip_through_chat_yaml(
    tmp_path,
    value,
    expected_type,
):
    path = tmp_path / f"AutoFeed{value!s}.yml"
    chat = Chat(
        name=path.stem,
        params=ChatParams(auto_feed=value),
    )

    chat.save(path)
    loaded = Chat(name=path.stem)
    loaded.load(path)

    assert loaded.params.auto_feed == value
    assert type(loaded.params.auto_feed) is expected_type


def test_legacy_yaml_without_auto_feed_loads_true(tmp_path):
    path = tmp_path / "LegacyAutoFeed.yml"
    path.write_text(
        "params:\n"
        "  model: gpt-4-turbo\n"
        "messages: []\n",
        encoding="utf-8",
    )

    loaded = Chat(name=path.stem)
    loaded.load(path)

    assert loaded.params.auto_feed is True


@pytest.mark.parametrize(
    ("yaml_value", "message"),
    [
        ("-1", "non-negative"),
        ("1.5", "True, False, None"),
        ("many", "True, False, None"),
    ],
)
def test_invalid_auto_feed_yaml_is_rejected_before_coercion(
    tmp_path,
    yaml_value,
    message,
):
    path = tmp_path / "InvalidAutoFeed.yml"
    path.write_text(
        "params:\n"
        f"  auto_feed: {yaml_value}\n"
        "messages: []\n",
        encoding="utf-8",
    )

    loaded = Chat(name=path.stem)
    with pytest.raises(SnapclassError, match=message):
        loaded.load(path)
