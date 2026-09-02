import asyncio
from contextlib import contextmanager

import pytest
from snapclass import Stash

import chatsnack
from chatsnack import Chat, Text
from chatsnack.fillings import (
    FillingAuthorityError,
    FillingError,
    FillingLimitError,
    active_filling_stash,
    resolve_fillings_a,
    snack_catalog,
)


@contextmanager
def use_filling_stash(path):
    token = active_filling_stash.set(Stash(path))
    try:
        yield
    finally:
        active_filling_stash.reset(token)


def save_text(path, name, content):
    Text(name=name, content=content).save(path / f"{name}.txt")


def save_chat(path, name, content):
    Chat(name=name).system(content).save(path / f"{name}.yml")


def test_goal_known_reference_uses_the_shared_formatter_catalog(monkeypatch):
    calls = []

    async def expand(name, additional):
        calls.append((name, additional))
        return f"{additional['tone']} {name}"

    monkeypatch.setitem(snack_catalog.vendors, "text", expand)

    result = asyncio.run(
        resolve_fillings_a(
            ["text.Voice"],
            variables={"tone": "bright"},
        )
    )

    assert result == {"text": {"Voice": "bright Voice"}}
    assert calls == [("Voice", {"tone": "bright"})]


def test_goal_recursive_text_uses_main_expansion_and_keeps_values_opaque(tmp_path):
    save_text(tmp_path, "Outer", "before {text.Inner} {topic} after")
    save_text(tmp_path, "Inner", "literal {payload}")
    save_text(tmp_path, "NotRescanned", "wrong")

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(
                ["text.Outer"],
                variables={
                    "topic": "snacks",
                    "payload": "{text.NotRescanned}",
                },
            )
        )

    assert result == {
        "text": {
            "Outer": "before literal {text.NotRescanned} snacks after",
        }
    }


def test_goal_authorized_chat_can_use_nested_text_and_chat_fillings(
    tmp_path,
    monkeypatch,
):
    save_text(tmp_path, "Voice", "Use a {tone} voice.")
    save_chat(tmp_path, "Child", "child answer")
    save_chat(tmp_path, "Parent", "{text.Voice} {chat.Child}")
    calls = []

    async def build_without_provider(self, **variables):
        calls.append(self.name)
        return await self._build_final_prompt(variables)

    monkeypatch.setattr(Chat, "ask_a", build_without_provider)

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(
                ["chat.Parent"],
                variables={"tone": "playful"},
                allow_chat=True,
            )
        )

    assert "Use a playful voice." in result["chat"]["Parent"]
    assert "child answer" in result["chat"]["Parent"]
    assert calls == ["Parent", "Child"]


@pytest.mark.parametrize(
    "variable_name",
    [
        "usermsg",
        "files",
        "images",
        "__user",
        "track_continuation",
        "_call_usage_ledger",
        "_submitted_runtime_out",
    ],
)
def test_chat_resolution_keeps_query_control_names_as_template_variables(
    tmp_path,
    monkeypatch,
    variable_name,
):
    save_chat(tmp_path, "Reserved", f"reserved {{{variable_name}}}")
    prompts = []

    async def capture_prompt(self, prompt, **kwargs):
        prompts.append(prompt)
        return "resolved"

    monkeypatch.setattr(Chat, "_cleaned_chat_completion", capture_prompt)

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(
                ["chat.Reserved"],
                variables={variable_name: "kept"},
                allow_chat=True,
            )
        )

    assert result == {"chat": {"Reserved": "resolved"}}
    assert len(prompts) == 1
    assert "reserved kept" in prompts[0]


def test_chat_resolution_forwards_query_control_names_to_ask_override(
    tmp_path,
    monkeypatch,
):
    save_chat(tmp_path, "Reserved", "reserved {usermsg} {files} {images}")
    calls = []

    async def build_without_provider(self, **variables):
        calls.append(variables)
        return await self._build_final_prompt(variables)

    monkeypatch.setattr(Chat, "ask_a", build_without_provider)
    variables = {
        "usermsg": "hello",
        "files": "notes",
        "images": "cover",
    }

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(
                ["chat.Reserved"],
                variables=variables,
                allow_chat=True,
            )
        )

    assert "reserved hello notes cover" in result["chat"]["Reserved"]
    assert calls == [variables]


@pytest.mark.parametrize("asset_shape", ["text_fields", "chat_messages"])
def test_resolver_cancels_sibling_expansions_before_returning_an_error(
    tmp_path,
    monkeypatch,
    asset_shape,
):
    if asset_shape == "text_fields":
        save_text(tmp_path, "Parallel", "{chat.Failing} {chat.Slow}")
        reference = "text.Parallel"
    else:
        Chat(name="Parallel").system("{chat.Failing}").user(
            "{chat.Slow}"
        ).save(tmp_path / "Parallel.yml")
        reference = "chat.Parallel"
    save_chat(tmp_path, "Failing", "unused")
    save_chat(tmp_path, "Slow", "unused")
    normal_ask_a = Chat.ask_a

    async def exercise():
        slow_started = asyncio.Event()
        slow_cancelled = asyncio.Event()

        async def controlled_ask(self, **variables):
            if self.name == "Slow":
                slow_started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    slow_cancelled.set()
                    raise
            if self.name == "Failing":
                await slow_started.wait()
                raise RuntimeError("failed")
            return await normal_ask_a(self, **variables)

        monkeypatch.setattr(Chat, "ask_a", controlled_ask)

        with use_filling_stash(tmp_path):
            with pytest.raises(FillingError):
                await asyncio.wait_for(
                    resolve_fillings_a(
                        [reference],
                        allow_chat=True,
                    ),
                    timeout=2,
                )

        assert slow_cancelled.is_set()

    asyncio.run(exercise())


def test_resolver_propagates_missing_fillings_from_assistant_messages(
    tmp_path,
    monkeypatch,
):
    Chat(name="AssistantHistory").assistant("{text.Missing}").save(
        tmp_path / "AssistantHistory.yml"
    )
    provider_calls = []

    async def unexpected_provider(self, prompt, **kwargs):
        provider_calls.append(prompt)
        return "unexpected"

    monkeypatch.setattr(Chat, "_cleaned_chat_completion", unexpected_provider)

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingError) as caught:
            asyncio.run(
                resolve_fillings_a(
                    ["chat.AssistantHistory"],
                    allow_chat=True,
                )
            )

    assert "chat.AssistantHistory -> text.Missing" in str(caught.value)
    assert provider_calls == []


def test_resolver_still_tolerates_malformed_assistant_braces(
    tmp_path,
    monkeypatch,
):
    Chat(name="AssistantHistory").assistant("unfinished {").save(
        tmp_path / "AssistantHistory.yml"
    )
    prompts = []

    async def capture_prompt(self, prompt, **kwargs):
        prompts.append(prompt)
        return "resolved"

    monkeypatch.setattr(Chat, "_cleaned_chat_completion", capture_prompt)

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(
                ["chat.AssistantHistory"],
                allow_chat=True,
            )
        )

    assert result == {"chat": {"AssistantHistory": "resolved"}}
    assert len(prompts) == 1
    assert "unfinished {" in prompts[0]


def test_explicit_values_win_without_loading_assets_or_chat_authority(monkeypatch):
    async def unexpected_call(name, additional):
        raise AssertionError(f"catalog called for {name}")

    monkeypatch.setitem(snack_catalog.vendors, "text", unexpected_call)
    monkeypatch.setitem(snack_catalog.vendors, "chat", unexpected_call)
    explicit = "literal {chat.Costly}"

    result = asyncio.run(
        resolve_fillings_a(
            ["text.Voice", "chat.Answer"],
            variables={
                "text": {"Voice": explicit},
                "chat": {"Answer": 42},
            },
        )
    )

    assert result == {
        "text": {"Voice": explicit},
        "chat": {"Answer": 42},
    }


def test_replacement_chat_callback_obeys_resolver_authority(monkeypatch):
    calls = []

    async def replacement(name, additional):
        calls.append(name)
        return "generated"

    monkeypatch.setitem(snack_catalog.vendors, "chat", replacement)

    with pytest.raises(FillingAuthorityError):
        asyncio.run(resolve_fillings_a(["chat.Dynamic"]))
    assert calls == []

    result = asyncio.run(
        resolve_fillings_a(["chat.Dynamic"], allow_chat=True)
    )
    assert result == {"chat": {"Dynamic": "generated"}}
    assert calls == ["Dynamic"]


def test_namespace_overrides_only_apply_to_explicitly_requested_references(tmp_path):
    save_text(tmp_path, "Outer", "saved {text.Inner}")
    save_text(tmp_path, "Inner", "inner asset")

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(
                ["text.Outer"],
                variables={"text": {"Inner": "override"}},
            )
        )

    assert result == {"text": {"Outer": "saved inner asset"}}


def test_missing_requested_asset_is_omitted(tmp_path):
    with use_filling_stash(tmp_path):
        result = asyncio.run(resolve_fillings_a(["text.Missing"]))

    assert result == {"text": {}}


def test_missing_transitive_asset_reports_only_its_reference_chain(tmp_path):
    save_text(tmp_path, "Outer", "secret {text.Missing}")

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingError) as caught:
            asyncio.run(resolve_fillings_a(["text.Outer"]))

    assert str(caught.value) == (
        "could not resolve text.Missing (via text.Outer -> text.Missing)"
    )
    assert "secret" not in str(caught.value)


def test_transitive_chat_is_denied_before_loading_or_calling_it(tmp_path, monkeypatch):
    save_text(tmp_path, "Outer", "answer: {chat.Costly}")
    calls = []

    async def unexpected_provider(self, **variables):
        calls.append(self.name)
        return "paid answer"

    monkeypatch.setattr(Chat, "ask_a", unexpected_provider)

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingAuthorityError) as caught:
            asyncio.run(resolve_fillings_a(["text.Outer"]))

    assert "text.Outer -> chat.Costly" in str(caught.value)
    assert calls == []


@pytest.mark.parametrize("allow_chat", ["false", 1, None])
def test_chat_authority_requires_a_boolean(allow_chat):
    with pytest.raises(TypeError, match="allow_chat must be a bool"):
        asyncio.run(
            resolve_fillings_a(
                ["chat.Costly"],
                allow_chat=allow_chat,
            )
        )


def test_text_cycle_reports_only_the_reference_chain(tmp_path):
    save_text(tmp_path, "A", "secret-a {text.B}")
    save_text(tmp_path, "B", "secret-b {text.A}")

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingError) as caught:
            asyncio.run(resolve_fillings_a(["text.A"]))

    assert str(caught.value) == "filling cycle: text.A -> text.B -> text.A"
    assert "secret" not in str(caught.value)


def test_fixed_depth_limit_bounds_recursive_text(tmp_path):
    for index in range(17):
        content = "done" if index == 16 else f"{{text.N{index + 1}}}"
        save_text(tmp_path, f"N{index}", content)

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingLimitError, match="depth limit"):
            asyncio.run(resolve_fillings_a(["text.N0"]))


def test_fixed_expansion_limit_bounds_formatter_fanout(tmp_path):
    save_text(tmp_path, "Root", "{text.Leaf}" * 256)
    save_text(tmp_path, "Leaf", "x")

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingLimitError, match="expansion limit"):
            asyncio.run(resolve_fillings_a(["text.Root"]))


def test_fixed_chat_limit_stops_before_the_seventeenth_model_call(
    tmp_path,
    monkeypatch,
):
    references = []
    calls = []
    for index in range(17):
        name = f"C{index}"
        references.append(f"chat.{name}")
        save_chat(tmp_path, name, name)

    async def fake_provider(self, **variables):
        calls.append(self.name)
        return self.name

    monkeypatch.setattr(Chat, "ask_a", fake_provider)

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingLimitError, match="call limit"):
            asyncio.run(
                resolve_fillings_a(references, allow_chat=True)
            )

    assert calls == [f"C{index}" for index in range(16)]


def test_missing_chats_do_not_consume_the_model_call_budget(tmp_path, monkeypatch):
    references = [f"chat.Missing{index}" for index in range(16)]
    references.append("chat.Valid")
    save_chat(tmp_path, "Valid", "valid")
    calls = []

    async def fake_provider(self, **variables):
        calls.append(self.name)
        return "resolved"

    monkeypatch.setattr(Chat, "ask_a", fake_provider)

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(references, allow_chat=True)
        )

    assert result["chat"] == {"Valid": "resolved"}
    assert calls == ["Valid"]


def test_missing_chat_after_full_model_call_budget_is_still_omitted(
    tmp_path,
    monkeypatch,
):
    references = []
    for index in range(16):
        name = f"Valid{index}"
        references.append(f"chat.{name}")
        save_chat(tmp_path, name, name)
    references.append("chat.Missing")
    calls = []

    async def fake_provider(self, **variables):
        calls.append(self.name)
        return self.name

    monkeypatch.setattr(Chat, "ask_a", fake_provider)

    with use_filling_stash(tmp_path):
        result = asyncio.run(
            resolve_fillings_a(references, allow_chat=True)
        )

    assert result["chat"] == {
        f"Valid{index}": f"Valid{index}" for index in range(16)
    }
    assert calls == [f"Valid{index}" for index in range(16)]


def test_provider_failure_is_content_free(tmp_path, monkeypatch):
    save_chat(tmp_path, "Broken", "private prompt")

    async def fail(self, **variables):
        raise RuntimeError("provider leaked a secret response")

    monkeypatch.setattr(Chat, "ask_a", fail)

    with use_filling_stash(tmp_path):
        with pytest.raises(FillingError) as caught:
            asyncio.run(
                resolve_fillings_a(["chat.Broken"], allow_chat=True)
            )

    assert str(caught.value) == "could not resolve chat.Broken"
    assert "secret" not in str(caught.value)
    assert "private" not in str(caught.value)


def test_cancellation_propagates(tmp_path, monkeypatch):
    save_chat(tmp_path, "Cancelled", "unused")

    async def cancel(self, **variables):
        raise asyncio.CancelledError

    monkeypatch.setattr(Chat, "ask_a", cancel)

    with use_filling_stash(tmp_path):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(
                resolve_fillings_a(["chat.Cancelled"], allow_chat=True)
            )


def test_hyphenated_names_are_valid(tmp_path):
    save_text(tmp_path, "snack-style", "playful")

    with use_filling_stash(tmp_path):
        result = asyncio.run(resolve_fillings_a(["text.snack-style"]))

    assert result == {"text": {"snack-style": "playful"}}


@pytest.mark.parametrize(
    "reference",
    ["text../secret", "text.Snack/Secret", "text.Snack.Secret", "other.Name"],
)
def test_references_reject_non_static_or_traversal_shapes(reference):
    with pytest.raises(ValueError, match="static text.Name or chat.Name"):
        asyncio.run(resolve_fillings_a([reference]))


def test_normal_chat_prompt_expansion_keeps_its_existing_path(tmp_path):
    save_text(tmp_path, "Voice", "clear")
    save_chat(tmp_path, "Prompt", "Use {text.Voice} instructions.")
    chat = Chat.objects(Stash(tmp_path)).get("Prompt")

    prompt = asyncio.run(chat._build_final_prompt({}))

    assert "Use clear instructions." in prompt


def test_normal_chat_fillings_have_no_resolver_authority_or_call_cap(
    tmp_path,
    monkeypatch,
):
    save_chat(tmp_path, "Child", "child")
    save_chat(tmp_path, "Parent", " ".join(["{chat.Child}"] * 17))
    parent = Chat.objects(Stash(tmp_path)).get("Parent")
    calls = []

    async def fake_provider(self, **variables):
        calls.append(self.name)
        return "resolved"

    monkeypatch.setattr(Chat, "ask_a", fake_provider)

    prompt = asyncio.run(parent._build_final_prompt({}))

    assert prompt.count("resolved") == 17
    assert calls == ["Child"] * 17


def test_resolver_policy_helpers_are_not_public_top_level_names():
    assert not hasattr(chatsnack, "bounded_filling_expansion")
    assert not hasattr(chatsnack, "filling_resolution_active")
    assert not hasattr(chatsnack, "missing_filling")
