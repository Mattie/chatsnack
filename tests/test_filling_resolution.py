import asyncio

import pytest
from snapclass import Stash

from chatsnack import Text
from chatsnack.fillings import (
    ChatsnackFillingSource,
    FillingAuthorityError,
    FillingCycleError,
    FillingLimits,
    FillingLimitError,
    FillingResolutionError,
    resolve_fillings,
    resolve_fillings_a,
)


class FakeFillingSource:
    def __init__(self, *, texts=None, chats=None, delays=None):
        self.texts = dict(texts or {})
        self.chats = dict(chats or {})
        self.delays = dict(delays or {})
        self.chat_started = []
        self.active_chat_calls = 0
        self.peak_chat_calls = 0

    def load_text(self, name):
        return self.texts.get(name)

    async def resolve_chat(self, name, variables):
        if name not in self.chats:
            return None
        self.chat_started.append(name)
        self.active_chat_calls += 1
        self.peak_chat_calls = max(self.peak_chat_calls, self.active_chat_calls)
        try:
            await asyncio.sleep(self.delays.get(name, 0))
            value = self.chats[name]
            if isinstance(value, Exception):
                raise value
            return value
        finally:
            self.active_chat_calls -= 1


def test_explicit_values_win_without_catalog_lookup_or_chat_authority():
    source = FakeFillingSource(
        texts={"Voice": "catalog text"},
        chats={"Costly": "catalog chat"},
    )

    result = asyncio.run(
        resolve_fillings_a(
            ["text.Voice", "chat.Costly"],
            variables={
                "text": {"Voice": "explicit text"},
                "chat": {"Costly": "explicit chat"},
            },
            source=source,
        )
    )

    assert result.context == {
        "text": {"Voice": "explicit text"},
        "chat": {"Costly": "explicit chat"},
    }
    assert result.resolved_references == ()
    assert result.missing_references == ()
    assert source.chat_started == []


def test_missing_catalog_names_stay_absent():
    result = asyncio.run(
        resolve_fillings_a(
            ["text.Missing"],
            source=FakeFillingSource(),
        )
    )

    assert result.context == {"text": {}}
    assert result.missing_references == ("text.Missing",)


def test_recursive_text_is_expanded_but_inserted_results_are_opaque():
    source = FakeFillingSource(
        texts={
            "Outer": "before {text.Inner} after",
            "Inner": "literal {payload}",
            "NotRescanned": "wrong",
        }
    )

    result = asyncio.run(
        resolve_fillings_a(
            ["text.Outer"],
            variables={"payload": "{text.NotRescanned}"},
            source=source,
        )
    )

    assert result.context == {
        "text": {"Outer": "before literal {text.NotRescanned} after"}
    }
    assert result.resolved_references == ("text.Inner", "text.Outer")


def test_transitive_chat_reference_is_denied_before_calling_source():
    source = FakeFillingSource(
        texts={"Outer": "answer: {chat.Costly}"},
        chats={"Costly": "paid answer"},
    )

    with pytest.raises(FillingAuthorityError) as caught:
        asyncio.run(resolve_fillings_a(["text.Outer"], source=source))

    assert "text.Outer -> chat.Costly" in str(caught.value)
    assert source.chat_started == []


def test_allowed_chats_fan_out_with_stable_scheduling_and_bounded_concurrency():
    source = FakeFillingSource(
        chats={"First": "one", "Second": "two", "Third": "three"},
        delays={"First": 0.03, "Second": 0.01, "Third": 0},
    )

    result = asyncio.run(
        resolve_fillings_a(
            ["chat.First", "chat.Second", "chat.Third"],
            allow_chat=True,
            limits=FillingLimits(max_chat_concurrency=2),
            source=source,
        )
    )

    assert source.chat_started == ["First", "Second", "Third"]
    assert source.peak_chat_calls == 2
    assert list(result.context["chat"]) == ["First", "Second", "Third"]
    assert result.context["chat"] == {
        "First": "one",
        "Second": "two",
        "Third": "three",
    }


def test_text_cycles_report_only_the_reference_chain():
    source = FakeFillingSource(
        texts={
            "A": "secret-a {text.B}",
            "B": "secret-b {text.A}",
        }
    )

    with pytest.raises(FillingCycleError) as caught:
        asyncio.run(resolve_fillings_a(["text.A"], source=source))

    assert str(caught.value) == "filling cycle: text.A -> text.B -> text.A"
    assert "secret" not in str(caught.value)


def test_provider_failure_does_not_leak_prompt_or_response_content():
    source = FakeFillingSource(
        chats={"Broken": RuntimeError("provider leaked a secret response")}
    )

    with pytest.raises(FillingResolutionError) as caught:
        asyncio.run(
            resolve_fillings_a(
                ["chat.Broken"],
                allow_chat=True,
                source=source,
            )
        )

    assert str(caught.value) == "could not resolve chat.Broken"
    assert "secret" not in str(caught.value)


def test_sync_resolver_matches_async_contract():
    result = resolve_fillings(
        ["text.Voice"],
        source=FakeFillingSource(texts={"Voice": "concise"}),
    )

    assert result.context == {"text": {"Voice": "concise"}}


def test_sync_resolver_rejects_an_active_event_loop():
    async def invoke_sync_resolver():
        with pytest.raises(RuntimeError, match=r"Use resolve_fillings_a\(\)"):
            resolve_fillings([], source=FakeFillingSource())

    asyncio.run(invoke_sync_resolver())


@pytest.mark.parametrize(
    ("name", "maximum"),
    [
        ("max_depth", 64),
        ("max_nodes", 4096),
        ("max_chat_calls", 256),
        ("max_chat_concurrency", 32),
    ],
)
def test_filling_limits_have_finite_inclusive_ceilings(name, maximum):
    FillingLimits(**{name: maximum})

    with pytest.raises(ValueError, match=name):
        FillingLimits(**{name: maximum + 1})


def test_boolean_is_not_an_integer_filling_limit():
    with pytest.raises(TypeError, match="max_chat_calls"):
        FillingLimits(max_chat_calls=True)


def test_node_limit_applies_to_the_transitive_text_graph():
    source = FakeFillingSource(texts={"A": "{text.B}", "B": "done"})

    with pytest.raises(FillingLimitError, match="node limit"):
        resolve_fillings(
            ["text.A"],
            limits=FillingLimits(max_nodes=1),
            source=source,
        )


def test_chat_call_limit_fails_before_any_chat_is_started():
    source = FakeFillingSource(chats={"A": "one", "B": "two"})

    with pytest.raises(FillingLimitError, match="call limit"):
        resolve_fillings(
            ["chat.A", "chat.B"],
            allow_chat=True,
            limits=FillingLimits(max_chat_calls=1),
            source=source,
        )

    assert source.chat_started == []


def test_missing_transitive_text_reports_its_dependency_chain():
    source = FakeFillingSource(texts={"Outer": "{text.Missing}"})

    with pytest.raises(FillingResolutionError) as caught:
        resolve_fillings(["text.Outer"], source=source)

    assert "text.Outer -> text.Missing" in str(caught.value)


def test_default_source_resolves_a_persisted_text_through_public_storage(tmp_path):
    Text(name="Voice", content="clear").save(tmp_path / "Voice.txt")

    result = resolve_fillings(
        ["text.Voice"],
        source=ChatsnackFillingSource(stash=Stash(tmp_path)),
    )

    assert result.context["text"]["Voice"] == "clear"
