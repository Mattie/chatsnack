"""Goal and contract coverage for Python async utensils (not provider async calls)."""

import asyncio
import gc
import json
from contextvars import ContextVar

import pytest

from chatsnack import Chat, utensil
from chatsnack.utensil import _REGISTRY, UtensilFunction, handle_tool_call, handle_tool_call_a
from chatsnack.runtime import ChatCompletionsAdapter, ResponsesAdapter, ResponsesWebSocketAdapter
from chatsnack.runtime.types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
    NormalizedToolFunction,
)


@pytest.fixture(autouse=True)
async def isolated_assets_and_registry(monkeypatch, tmp_path):
    """Keep saved demo assets and globally registered test capabilities local to each test."""
    monkeypatch.chdir(tmp_path)
    previous = list(_REGISTRY)
    _REGISTRY.clear()
    chats = []
    initialize = Chat.__init__

    def record_chat(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        chats.append(self)

    monkeypatch.setattr(Chat, "__init__", record_chat)
    try:
        yield
    finally:
        for chat in reversed(chats):
            await chat.close_a()
        _REGISTRY[:] = previous


def tool_completion(name="stock", arguments=None, call_id="call_stock"):
    """Represent a completed provider request for one local capability."""
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(tool_calls=[NormalizedToolCall(
            id=call_id, type="function",
            function=NormalizedToolFunction(name=name, arguments=json.dumps(arguments or {})),
        )]),
        finish_reason="tool_calls",
        metadata={"response_id": "resp_stock"},
    )


def final_completion(text="12 snack boxes are available."):
    """Finish a tool exchange without accessing a provider."""
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(content=text),
        finish_reason="stop", metadata={"response_id": "resp_final"},
    )


@pytest.fixture
def provider_sequence(monkeypatch):
    """Supply deterministic provider turns through the active runtime boundary."""
    def install(completions):
        sequence = iter(completions)
        requests = []

        async def create(adapter, messages, **kwargs):
            requests.append(messages)
            return next(sequence)

        for adapter_type in (ResponsesAdapter, ResponsesWebSocketAdapter, ChatCompletionsAdapter):
            monkeypatch.setattr(adapter_type, "create_completion_a", create)
        return requests

    return install


def local_call(name="stock", call_id="call_stock", **arguments):
    """Describe a manual execution using the same shape as model function calls."""
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


@pytest.mark.parametrize("runtime", ["responses", "responses_websocket", "chat_completions"])
async def test_goal_async_tool_result_reaches_model_and_history(monkeypatch, tmp_path, runtime):
    """G1: an ordinary async utensil executes once and feeds its actual result back."""
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(tmp_path))
    calls = []
    requests = []

    @utensil
    async def stock(sku: str):
        """Look up snack stock."""
        await asyncio.sleep(0)
        calls.append(sku)
        return {"sku": sku, "available": 12}

    completions = iter([tool_completion(arguments={"sku": "snack-box"}), final_completion()])

    async def create(adapter, messages, **kwargs):
        requests.append(messages)
        return next(completions)

    for adapter_type in (ResponsesAdapter, ResponsesWebSocketAdapter, ChatCompletionsAdapter):
        monkeypatch.setattr(adapter_type, "create_completion_a", create)

    chat = Chat("Look up stock.", runtime=runtime, utensils=[stock])
    thread = await chat.chat_a("Check snack-box stock.")

    assert thread.last == "12 snack boxes are available."
    assert calls == ["snack-box"]
    outputs = [message for message in requests[1] if message.get("role") == "tool"]
    assert len(outputs) == 1
    assert outputs[0]["tool_call_id"] == "call_stock"
    assert json.loads(outputs[0]["content"]) == {
        "sku": "snack-box", "available": 12, "tool_call_id": "call_stock",
    }
    assert [message["role"] for message in thread.get_messages()] == [
        "system", "user", "assistant", "tool", "assistant",
    ]


@pytest.mark.parametrize("runtime", ["responses", "responses_websocket", "chat_completions"])
async def test_goal_independent_chat_finishes_while_another_tool_waits(monkeypatch, runtime):
    """G2: yielding in game A permits game B to finish on the same event loop."""
    entered = asyncio.Event()
    release = asyncio.Event()
    game_context = ContextVar("async_utensil_game", default=None)

    @utensil
    async def lookup(game: str):
        """Read one game's lookup result."""
        assert game_context.get() == game
        if game == "slow":
            entered.set()
            await release.wait()
        assert game_context.get() == game
        return {"game": game}

    async def create(adapter, messages, **kwargs):
        outputs = [message for message in messages if message.get("role") == "tool"]
        if outputs:
            return final_completion(json.loads(outputs[-1]["content"])["game"])
        game = messages[-1]["content"]
        return tool_completion("lookup", {"game": game}, f"call_{game}")

    for adapter_type in (ResponsesAdapter, ResponsesWebSocketAdapter, ChatCompletionsAdapter):
        monkeypatch.setattr(adapter_type, "create_completion_a", create)

    async def ask(game):
        token = game_context.set(game)
        try:
            chat = Chat("Look up this game.", runtime=runtime, utensils=[lookup])
            return await chat.chat_a(game)
        finally:
            game_context.reset(token)

    slow = asyncio.create_task(ask("slow"))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        fast = await asyncio.wait_for(ask("fast"), timeout=2)
        assert fast.last == "fast"
        assert not slow.done()
        release.set()
        assert (await asyncio.wait_for(slow, timeout=2)).last == "slow"
        assert game_context.get() is None
    finally:
        slow.cancel()
        await asyncio.gather(slow, return_exceptions=True)


async def test_goal_saved_grouped_async_tool_survives_lifecycle(tmp_path, monkeypatch, provider_sequence):
    """G3: saved assets bind the right async capability through copy/reset/continuation."""
    monkeypatch.chdir(tmp_path)
    calls = []
    pantry = utensil.group("pantry", "Snack stock.")

    @pantry
    async def stock(sku: str):
        """Look up snack stock."""
        calls.append(sku)
        return {"available": 12}

    # A conflicting global name must never replace this chat's local binding.
    @utensil(name="stock")
    def other_stock(sku: str):
        raise AssertionError("Wrong capability binding")

    original = Chat(name="AsyncPantry", runtime="responses", utensils=[pantry])
    original.system("Check snack stock.").user("Check {sku}.")
    original.save()
    assert "async:" not in original.yaml
    loaded = Chat(name="AsyncPantry", utensils=[pantry])
    loaded.load()
    copied = loaded.copy()
    copied.reset()
    completions = []
    for index in range(3):
        completions.extend([tool_completion(arguments={"sku": str(index)}), final_completion()])
    provider_sequence(completions)

    thread = await copied.chat_a(sku="snack-box")
    continued = await thread.chat_a("Check it again.")
    continued.reset()
    await continued.chat_a("Check once more.", sku="snack-box")
    assert calls == ["0", "1", "2"]


@pytest.mark.parametrize("native", [False, True])
async def test_live_async_service_binding_is_not_deepcopied(provider_sequence, native):
    """Contract G3: prompt copies preserve async service instances and their live resources."""
    class Inventory:
        def __init__(self):
            self.calls = []

        def __deepcopy__(self, memo):
            raise TypeError("Live inventory connections cannot be deepcopied")

        async def stock(self, sku: str):
            """Read stock using this inventory connection."""
            self.calls.append(sku)
            return {"available": 12}

        async def patch(self, call):
            self.calls.append(call.operation["path"])
            return {"status": "completed", "output": "done"}

    inventory = Inventory()
    stock = utensil.apply_patch(execute=inventory.patch) if native else UtensilFunction(inventory.stock)
    chat = Chat(runtime="responses", utensils=[stock])
    copied = chat.copy()
    copied.reset()
    completions = []
    for name in ("first", "second"):
        completion = tool_completion(arguments={"sku": name})
        if native:
            completion.message.tool_calls = [NormalizedToolCall(
                id=f"call_{name}", item_id=f"item_{name}", type="apply_patch", status="completed",
                payload={"operation": {"type": "delete_file", "path": name}},
            )]
        completions.extend([completion, final_completion()])
    provider_sequence(completions)
    thread = await copied.chat_a()
    await thread.chat_a("Check again.")
    assert inventory.calls == ["first", "second"]


async def test_mixed_batch_executes_once_in_provider_order(provider_sequence):
    """Steer G1: async I/O changes scheduling without changing batch ordering."""
    events = []

    @utensil
    async def first():
        events.append("first:start")
        await asyncio.sleep(0)
        events.append("first:end")
        return "one"

    @utensil
    def second():
        events.append("second")
        return {"value": "two"}

    batch = tool_completion("first", call_id="call_first")
    batch.message.tool_calls.extend(tool_completion("second", call_id="call_second").message.tool_calls)
    requests = provider_sequence([batch, final_completion()])
    thread = await Chat("Use both tools.", runtime="responses", utensils=[first, second]).chat_a()
    assert thread.last == "12 snack boxes are available."
    assert events == ["first:start", "first:end", "second"]
    outputs = [message for message in requests[1] if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in outputs] == ["call_first", "call_second"]
    assert json.loads(outputs[0]["content"])["result"] == "one"


@pytest.mark.parametrize("auto_execute,auto_feed,executions,submissions", [
    (False, True, 0, 1), (True, False, 1, 1), (True, 0, 1, 1), (True, 1, 1, 2),
])
async def test_async_tools_keep_execution_and_feed_controls(
    provider_sequence, auto_execute, auto_feed, executions, submissions,
):
    """Steer G1: existing orchestration controls retain their meaning."""
    calls = []

    @utensil
    async def stock():
        calls.append("stock")
        return "ready"

    requests = provider_sequence([tool_completion(), final_completion()])
    chat = Chat(runtime="responses", utensils=[stock], auto_execute=auto_execute, auto_feed=auto_feed)
    thread = await chat.chat_a("Check stock.")
    assert len(calls) == executions
    assert len(requests) == submissions
    assert len([message for message in thread.get_messages() if message["role"] == "tool"]) == executions


async def test_awaitable_wrapper_and_shared_result_are_supported():
    """Steer G1/G2: inspect the result, and keep cached dictionaries free of call metadata."""
    cached = {"available": 12}

    @utensil
    def stock():
        future = asyncio.get_running_loop().create_future()
        future.set_result(cached)
        return future

    first = await handle_tool_call_a(local_call(call_id="one"), [stock])
    second = await handle_tool_call_a(local_call(call_id="two"), [stock])
    assert first == {"available": 12, "tool_call_id": "one"}
    assert second == {"available": 12, "tool_call_id": "two"}
    assert cached == {"available": 12}


async def test_async_errors_reach_model_instead_of_coroutine_strings(provider_sequence):
    """Steer G1: errors raised during await retain the established error output."""
    @utensil
    async def stock():
        await asyncio.sleep(0)
        raise ValueError("stock unavailable")

    requests = provider_sequence([tool_completion(), final_completion()])
    await Chat(runtime="responses", utensils=[stock]).chat_a()
    output = next(message for message in requests[1] if message.get("role") == "tool")
    assert json.loads(output["content"]) == {
        "error": "Error executing function: stock unavailable", "tool_call_id": "call_stock",
    }


async def test_cancellation_runs_tool_cleanup_without_model_followup(provider_sequence):
    """Steer G2: cancellation escapes execution rather than becoming a successful tool turn."""
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    @utensil
    async def stock():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    requests = provider_sequence([tool_completion()])
    chat = Chat(runtime="responses", utensils=[stock])
    task = asyncio.create_task(chat.chat_a())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
        assert len(requests) == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_sync_chat_bridge_executes_async_tools(provider_sequence):
    """Steer G1: scripts can keep chat() while the underlying tool is async."""
    @utensil
    async def stock():
        await asyncio.sleep(0)
        return "ready"

    provider_sequence([tool_completion(), final_completion()])
    thread = Chat(runtime="responses", utensils=[stock]).chat()
    output = next(message for message in thread.get_messages() if message["role"] == "tool")
    assert json.loads(output["content"])["result"] == "ready"


def test_manual_sync_execution_rejects_async_without_unawaited_warning(recwarn):
    """Steer G1: direct sync dispatch gives actionable guidance and closes unused coroutines."""
    calls = []

    @utensil
    async def stock():
        calls.append("stock")
        return "ready"

    result = handle_tool_call(local_call(), [stock])
    assert "handle_tool_call_a()" in result["error"]
    assert result["tool_call_id"] == "call_stock"
    assert calls == []
    assert not recwarn.list


@pytest.mark.parametrize("kind", ["task", "future"])
async def test_manual_sync_rejection_cancels_pending_async_work(kind):
    """A rejected sync call cannot leave its returned job running in the background."""
    effects = []
    returned = None

    async def work():
        await asyncio.sleep(0)
        effects.append("unwanted side effect")

    @utensil
    def stock():
        nonlocal returned
        loop = asyncio.get_running_loop()
        returned = loop.create_task(work()) if kind == "task" else loop.create_future()
        return returned

    try:
        result = handle_tool_call(local_call(), [stock])
        assert "handle_tool_call_a()" in result["error"]
        assert result["tool_call_id"] == "call_stock"
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert returned.cancelled()
        assert effects == []
    finally:
        if returned is not None:
            returned.cancel()
            await asyncio.gather(returned, return_exceptions=True)


@pytest.mark.parametrize("kind", ["task", "future"])
async def test_manual_sync_rejection_collects_completed_async_failures(kind):
    """Discarding an already failed result does not log an unretrieved async exception."""
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

    async def fail():
        raise ValueError("failed lookup")

    failed = loop.create_task(fail()) if kind == "task" else loop.create_future()
    if kind == "future":
        failed.set_exception(ValueError("failed lookup"))
    await asyncio.sleep(0)
    assert failed.done()

    @utensil
    def stock():
        return failed

    try:
        result = handle_tool_call(local_call(), [stock])
        assert "handle_tool_call_a()" in result["error"]
        failed = None
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled == []
    finally:
        if failed is not None:
            failed.exception()
        loop.set_exception_handler(previous_handler)


async def test_manual_sync_rejection_collects_task_cleanup_failure():
    """Cancellation cleanup may fail; its exception must still be retrieved."""
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
            raise ValueError("cleanup failed")

    returned = loop.create_task(work())
    await entered.wait()

    @utensil
    def stock():
        return returned

    try:
        result = handle_tool_call(local_call(), [stock])
        assert "handle_tool_call_a()" in result["error"]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert cleaned.is_set()
        assert returned.done()
        returned = None
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled == []
    finally:
        if returned is not None:
            returned.cancel()
            await asyncio.gather(returned, return_exceptions=True)
        loop.set_exception_handler(previous_handler)


@pytest.mark.parametrize("async_override", [False, True])
async def test_existing_executor_overrides_remain_authoritative(monkeypatch, provider_sequence, async_override):
    """Steer G1: introducing the async hook preserves custom execution policies."""
    calls = []

    def execute(call):
        calls.append(call["id"])
        return {"custom": True}

    async def execute_a(call):
        await asyncio.sleep(0)
        return execute(call)

    requests = provider_sequence([tool_completion(), final_completion()])
    chat = Chat(runtime="responses")
    monkeypatch.setattr(chat, "execute_tool_call", execute_a if async_override else execute)
    await chat.chat_a()
    output = next(message for message in requests[1] if message.get("role") == "tool")
    assert json.loads(output["content"]) == {"custom": True}
    assert calls == ["call_stock"]


@pytest.mark.parametrize("kind", ["apply_patch", "tool_search"])
async def test_native_handlers_accept_future_results(provider_sequence, kind):
    """Contract: existing native handlers use the same awaitable-result rule."""
    calls = []

    def handler(call):
        calls.append(call)
        future = asyncio.get_running_loop().create_future()
        future.set_result({"status": "completed", "output": "done"} if kind == "apply_patch" else {"tools": []})
        return future

    if kind == "apply_patch":
        chat = Chat(runtime="responses", utensils=[utensil.apply_patch(execute=handler)])
        call = NormalizedToolCall(
            id="call_native", item_id="native_item", type=kind, status="completed",
            payload={"operation": {"type": "delete_file", "path": "snacks.txt"}},
        )
    else:
        chat = Chat(runtime="responses", utensils=[utensil.tool_search], tool_search_handler=handler)
        call = NormalizedToolCall(id="call_native", type=kind, payload={"goal": "snack tools"})
    completion = NormalizedCompletionResult(
        message=NormalizedAssistantMessage(tool_calls=[call]),
        finish_reason="tool_calls", metadata={"response_id": "resp_native"},
    )
    provider_sequence([completion, final_completion()])
    thread = await chat.chat_a()
    assert len(calls) == 1
    output = next(message for message in thread.get_messages() if message["role"] == "tool")
    assert output["tool_call_id"] == "call_native"
    assert output["content"] == ("done" if kind == "apply_patch" else '{"tools": []}')


@pytest.mark.parametrize("async_dispatch", [False, True])
async def test_dispatch_preserves_argument_and_lookup_errors(async_dispatch):
    """Contract: sync and async dispatch agree on existing failure payloads."""
    @utensil
    def stock():
        return "ready"

    async def dispatch(call):
        if async_dispatch:
            return await handle_tool_call_a(call, [stock])
        return handle_tool_call(call, [stock])

    malformed = local_call()
    malformed["function"]["arguments"] = "{"
    assert await dispatch(malformed) == {
        "error": "Invalid JSON arguments: {", "tool_call_id": "call_stock",
    }
    assert await dispatch(local_call("missing")) == {
        "error": "Function 'missing' not found", "tool_call_id": "call_stock",
    }
