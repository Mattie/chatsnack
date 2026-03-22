# Phase 2a RFC: Responses WebSocket via Official OpenAI SDK

## Status
Implemented.

## Summary
Phase 2a corrects the transport design for Phase 2.

We should keep the chatsnack public API we already want:

- `runtime="responses"`
- `session=None | "inherit" | "new"`
- `ask()`, `chat()`, `listen()`, and `listen_a()`
- the existing chatsnack tool loop

What changes is the transport implementation.

Chatsnack should stop hand-rolling the Responses WebSocket protocol and should instead use the official OpenAI Python SDK WebSocket support:

- `client.responses.connect()`
- `connection.response.create(...)`
- typed Responses server events from the SDK connection

This is the smallest correction that gets us back onto the documented API and makes the notebook examples realistic again.

## Why this RFC exists

The earlier Phase 2 work was pointed at the right product goal, though it was off at the protocol boundary.

The main issue was transport framing:

- we treated the socket flow too much like a custom raw WebSocket client
- we sent `{"type": "response.create", "response": payload}` instead of the documented top-level event body
- we carried some Realtime-style assumptions into a Responses WebSocket design

The latest OpenAI docs and SDK are clearer now:

- Responses WebSocket mode is part of `/v1/responses`
- the official Python SDK already implements `responses.connect()`
- the connection exposes `connection.response.create(...)`
- the client and server event model matches Responses streaming

So Phase 2a is a corrective RFC, not a new product idea.

## Required dependency baseline

Phase 2a should require an OpenAI SDK version that actually includes Responses WebSocket support.

Required baseline:

- `openai>=2.29.0`
- websocket support available in the environment

Practical guidance:

- if chatsnack keeps a direct `websockets` dependency, that is fine
- the equivalent upstream install guidance is `openai[realtime]>=2.29.0`

If a user enables `session="inherit"` or `session="new"` without the required SDK support, chatsnack should fail fast with a clear message.

Suggested error text:

`Responses WebSocket mode requires openai>=2.29.0 with websocket support. Upgrade OpenAI or install openai[realtime].`

## What stays the same

Phase 2a does not change the public chatsnack story.

- `session` stays the switch for WebSocket mode
- leaving `session` unset keeps us on normal HTTP Responses
- `listen()` stays the main notebook entrypoint
- `ask()` and `chat()` keep their current meanings
- chatsnack still compiles chats into Responses-style input items
- chatsnack still owns tool execution, lineage, and YAML decisions

## What changes

### 1. Use the SDK connection, not a raw socket

`ResponsesWebSocketAdapter` should become a thin wrapper around the official SDK connection manager.

Sync shape:

```python
with client.responses.connect() as connection:
    connection.response.create(
        model="gpt-5.4",
        input=[...],
        store=False,
        previous_response_id="resp_123",
        tools=[],
    )
    for event in connection:
        ...
```

Async shape:

```python
async with client.responses.connect() as connection:
    await connection.response.create(
        model="gpt-5.4",
        input=[...],
        store=False,
        previous_response_id="resp_123",
        tools=[],
    )
    async for event in connection:
        ...
```

Chatsnack should not manually call:

- `websocket.create_connection(...)`
- `ws.send(json.dumps(...))`
- `json.loads(ws.recv())`

when the official SDK already provides the correct Responses transport.

### 2. Stop nesting the request under `response`

The documented event shape is top-level:

```json
{
  "type": "response.create",
  "model": "gpt-5.4",
  "store": false,
  "input": [...],
  "tools": []
}
```

Chatsnack must not send:

```json
{
  "type": "response.create",
  "response": {
    "model": "gpt-5.4",
    "input": [...]
  }
}
```

This is the most important corrective rule in this RFC.

### 3. Let the SDK parse server events

Chatsnack should consume the typed Responses server events from the SDK connection and map them into our runtime event surface.

Live SDK testing showed that a plain text turn emits a larger lifecycle sequence than just deltas and completion, including:

- `response.created`
- `response.in_progress`
- `response.output_item.added`
- `response.content_part.added`
- repeated `response.output_text.delta`
- `response.output_text.done`
- `response.content_part.done`
- `response.output_item.done`
- `response.completed`

A function-call turn emitted:

- `response.output_item.added`
- repeated `response.function_call_arguments.delta`
- `response.function_call_arguments.done`
- `response.output_item.done`
- `response.completed`

Phase 2a should map the events we care about and safely ignore the extra lifecycle events. The minimum useful mapping for chatsnack is still:

- `response.output_text.delta`
- `response.function_call_arguments.delta`
- `response.function_call_arguments.done`
- `response.output_item.done`
- `response.completed`
- `error`
- `response.failed`

### 4. Keep stripping transport-only fields

WebSocket mode uses the Responses create body, though transport-only fields should still be omitted.

For chatsnack, that means the WebSocket adapter should continue to remove:

- `stream`
- `background`

before calling `connection.response.create(...)`.

`listen()` implies streaming behavior at the transport level already. We do not need to pass `stream=True` into the WebSocket event body.

## Correct public behavior

### Runtime selection

- `runtime="responses"` with no `session`: use HTTP Responses via `ResponsesAdapter`
- `runtime="responses", session="inherit"`: use `ResponsesWebSocketAdapter` backed by `client.responses.connect()`
- `runtime="responses", session="new"`: use `ResponsesWebSocketAdapter` backed by a fresh `client.responses.connect()` for each new chat lineage object

### `ask()`, `listen()`, and `chat()`

- `listen()` and `listen_a()` should be the most natural way to see live WebSocket output
- `ask()` should consume the stream and return the final assistant text
- `chat()` should consume the stream, preserve tool behavior, and return the next `Chat`

### Lineage authority

Chatsnack should keep lineage ownership on the `Chat`, not on the socket.

That means:

- the committed `response_id` for continuation lives in the chat runtime metadata
- `chat()` writes continuation metadata into the returned child chat
- `ask()` and `listen()` do not advance lineage on the source chat

The adapter may still track the most recent completed response on the live connection for transport management, though chat lineage remains the source of truth for continuation behavior.

## Continuation rules

### `session="inherit"`

This is the primary WebSocket mode.

Behavior:

- reuse the same SDK connection across descendant chats
- if the current chat lineage has a committed `response_id`, send `previous_response_id`
- when `previous_response_id` is present, send only new input items
- keep `store=False` by default unless the user explicitly asks for persisted state

This is the fast path the docs are designed around.

### `session="new"`

This mode creates a fresh connection for each chat object lineage step.

Behavior:

- open a fresh SDK connection for each returned child chat
- if the user explicitly set `store=True` and the current chat lineage has a committed `response_id`, we may continue with `previous_response_id` plus only new input items
- if `store=False` or unset, do not assume a fresh connection can hydrate prior state
- in that case, omit `previous_response_id` and send full local context for the next turn

This rule matters because the WebSocket docs only guarantee the low-latency cache on the active socket.

### Reconnect

On reconnect after a dropped connection or the 60-minute limit:

- if we have `store=True` and a valid committed `response_id`, retry with `previous_response_id`
- if we do not have a persisted fallback, omit `previous_response_id` and send full local context
- if a prior continuation fails with `previous_response_not_found`, retry once without `previous_response_id` and with full local context

## Tool calling

Phase 2a should keep the existing chatsnack tool loop.

That means:

- streamed function-call argument deltas still map into our normalized tool-call events
- `chat()` still supports auto-execute and auto-feed
- chatsnack still executes local utensils itself

We are replacing the transport plumbing, not the chatsnack tool model.

## Errors and retries

Phase 2a should stay small and conservative.

Rules:

- one in-flight response per chatsnack-owned inherited session
- fail fast on concurrent use of the same inherited session
- treat provider validation errors as non-retriable
- treat `previous_response_not_found` as a one-time fallback to full local context
- treat `websocket_connection_limit_reached` as a reconnect signal

Live API checks showed that the service itself can queue back-to-back `response.create` calls on one socket and run them sequentially. chatsnack should still keep fail-fast session ownership for Phase 2a so `Chat` lineage and shared session behavior stay predictable.

The earlier retry logic was too optimistic for malformed requests. Phase 2a should tighten that up.

## Observed API caveats

These are small implementation notes from live SDK checks that are worth keeping in mind.

- same-socket continuation with `store=False` works with `previous_response_id`
- fresh-socket continuation with `store=False` fails immediately with `previous_response_not_found`
- fresh-socket continuation with `store=True` can continue successfully from `previous_response_id`
- tool-only turns can complete with function-call lifecycle events and `response.completed`, even when no text delta is emitted
- a follow-up turn after `function_call_output` may succeed even if `tools` is omitted, though chatsnack should still resend tools when a chat owns utensils so behavior stays stable across runtimes

These caveats support the Phase 2a rules above:

- `session="inherit"` is the primary low-latency path
- `session="new"` with `store=False` must rebuild from full local context on a fresh connection
- the event mapper must treat tool-only completion as a normal successful turn

## Guardrails for implementation

These are hard rules for this phase:

1. Do not open raw WebSocket connections directly inside chatsnack for Responses mode.
2. Do not manually frame `response.create` JSON events.
3. Do not nest the request body under `response`.
4. Do not treat this as Realtime API work.
5. Do not make the Phase 2 notebook examples depend on undocumented socket behavior.

If we need a lower-level transport later, we can discuss it then. It should not be the default Phase 2 path now that the SDK already supports this mode.

## Implementation targets

Primary code targets:

- [responses_websocket_adapter.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/responses_websocket_adapter.py)
- [responses_common.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/responses_common.py)
- [responses_adapter.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/responses_adapter.py)
- [chat/__init__.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/__init__.py)
- [mixin_query.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/mixin_query.py)

Recommended shape:

- keep `ResponsesWebSocketAdapter`
- replace its raw socket code with SDK connection ownership
- keep shared request compilation in `responses_common.py`
- keep chatsnack runtime normalization above the SDK event layer

## Out of scope for Phase 2a

- a standalone chatsnack helper for `/responses/compact`
- a warmup helper for `generate=False`
- YAML export changes
- audio, WebRTC, or Realtime API support

Those can land later once the main notebook path is solid.

## Testing priorities

We should keep the tests very close to user behavior.

Must cover:

- direct constructor style: `Chat(..., runtime="responses", session="inherit")`
- `listen()` over the SDK-backed connection
- `ask()` over the SDK-backed connection
- `chat()` continuation with `previous_response_id`
- tool-call recursion over the SDK-backed connection
- `session="new"` with `store=False` rebuilding from full local context
- `session="new"` with `store=True` continuing from `previous_response_id` on a fresh connection
- tool-only first turns that finish with no text delta before `response.completed`
- clear failure when the SDK is too old or websocket support is missing
- `previous_response_not_found` fallback behavior
- `websocket_connection_limit_reached` reconnect behavior

To keep regressions down across the existing codebase, the major user-facing live tests should be parameterized across:

- `chat_completions`
- HTTP `responses`
- WebSocket `responses` with `session="inherit"`

The main cross-runtime checks should stay focused on shared chatsnack behavior:

- direct constructor syntax
- `ask()` versus `chat()` semantics
- local utensil execution and follow-up completion
- `auto_execute` and `auto_feed`
- streaming event compatibility through `event_schema="v1"`

## End-User Example Acceptance Criteria

These examples should work before we call Phase 2a done.

### 1. Simple notebook streaming

```python
from chatsnack import Chat

chat = Chat(
    "Respond tersely.",
    model="gpt-5.4",
    runtime="responses",
    session="inherit",
    stream=True,
)

listener = chat.listen("Give one sentence on reusable prompts.")
for chunk in listener:
    print(chunk, end="")
```

What should be true:

- this uses the official SDK Responses WebSocket path
- the adapter does not manually build socket JSON
- the request succeeds with the documented top-level `response.create` shape

### 2. Multi-turn continuation on one live connection

```python
from chatsnack import Chat

chat = Chat("You are concise.", model="gpt-5.4", runtime="responses", session="inherit")
first = chat.chat("Name one healthy snack.")
second = first.chat("Why is it healthy?")
```

What should be true:

- the second turn uses `previous_response_id`
- the second turn sends only new input items
- the same connection stays in use

### 3. Fresh connection with no persisted fallback

```python
from chatsnack import Chat

chat = Chat("You are concise.", model="gpt-5.4", runtime="responses", session="new")
first = chat.chat("Name one healthy snack.")
second = first.chat("Why is it healthy?")
```

What should be true:

- `second` uses a fresh connection
- if `store=False`, chatsnack rebuilds from full local context instead of assuming `previous_response_id` will hydrate on the new socket

### 4. Tool call round trip

```python
from chatsnack import Chat, utensil

@utensil
def get_weather(location: str):
    return {"forecast": "sunny"}

chat = Chat(
    "Use tools when helpful.",
    model="gpt-5.4",
    runtime="responses",
    session="inherit",
    utensils=[get_weather],
)

result = chat.chat("What is the weather in Austin?")
print(result.response)
```

What should be true:

- tool-call deltas stream in from the SDK connection
- chatsnack executes the local utensil
- the follow-up model turn completes on the same WebSocket session

## Relationship to the Phase 2 RFC

This RFC keeps the public API and product goals from [phase-2-responses-websocket-rfc.md](/Users/matti/Documents/dev/codex/chatsnack/docs/rfcs/phase-2-responses-websocket-rfc.md).

It supersedes the low-level transport design for WebSocket mode.

If there is any conflict between the earlier raw-socket transport sketches and this RFC, Phase 2a wins.


## Appendix A: Live-Tested SDK Notebook Example

This appendix is here so we have one copy-paste example that was exercised against the official SDK WebSocket path during Phase 2a design work.

Environment used during the live check:

- `openai[realtime]>=2.29.0`
- `client.responses.connect()` from the official SDK
- `store=False`
- repeated turns on one live `/v1/responses` connection

What this proves:

- `client.responses.connect()` works for repeated turns on one live connection
- `store=False` still supports same-socket continuation with `previous_response_id`
- function-call output can be fed back over the same WebSocket connection
- the server emits the standard Responses streaming lifecycle, so chatsnack should map the events it needs and ignore the rest

Observed event families during the live check:

- plain text turn: `response.created`, `response.in_progress`, `response.output_item.added`, `response.content_part.added`, repeated `response.output_text.delta`, `response.output_text.done`, `response.content_part.done`, `response.output_item.done`, `response.completed`
- function-call turn: `response.output_item.added`, repeated `response.function_call_arguments.delta`, `response.function_call_arguments.done`, `response.output_item.done`, `response.completed`

### Repeated query example

This exact flow returned the same invented word on turn 1 and turn 2 during the live check.

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def run_turn(connection, *, model, input_items, previous_response_id=None, store=False):
    connection.response.create(
        model=model,
        input=input_items,
        previous_response_id=previous_response_id,
        store=store,
        tools=[],
    )

    text_chunks = []
    event_types = []

    while True:
        event = connection.recv()
        etype = event.type
        event_types.append(etype)

        if etype == "response.output_text.delta":
            delta = getattr(event, "delta", "") or ""
            print(delta, end="", flush=True)
            text_chunks.append(delta)

        elif etype == "response.completed":
            data = event.model_dump()
            response = data["response"]
            print()
            return {
                "response_id": response["id"],
                "text": response.get("output_text") or "".join(text_chunks),
                "event_types": event_types,
            }

        elif etype in {"error", "response.failed"}:
            raise RuntimeError(event.model_dump())

model = "gpt-5.4"

with client.responses.connect() as connection:
    turn1 = run_turn(
        connection,
        model=model,
        input_items=[
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Invent a secret word and reply with only that word."}
                ],
            }
        ],
        store=False,
    )

    print("turn1_id:", turn1["response_id"])
    print("turn1_text:", turn1["text"])

    turn2 = run_turn(
        connection,
        model=model,
        previous_response_id=turn1["response_id"],
        input_items=[
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "What secret word did you just invent? Reply with only that word."}
                ],
            }
        ],
        store=False,
    )

    print("turn2_id:", turn2["response_id"])
    print("turn2_text:", turn2["text"])
    print("same_word:", turn1["text"].strip() == turn2["text"].strip())
    print("turn1_events:", turn1["event_types"])
    print("turn2_events:", turn2["event_types"])
```

### Tool round-trip example

This exact flow produced a function call for `get_weather`, then a final assistant answer of `Austin is sunny and 72 degrees Fahrenheit.` during the live check.

```python
import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

TOOLS = [
    {
        "type": "function",
        "name": "get_weather",
        "description": "Get the weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
            },
            "required": ["location"],
            "additionalProperties": False,
        },
    }
]

def get_weather(location: str):
    fake_weather = {
        "Austin": {"forecast": "sunny", "temperature_f": 72},
        "Chicago": {"forecast": "windy", "temperature_f": 48},
        "Seattle": {"forecast": "rainy", "temperature_f": 55},
    }
    return fake_weather.get(location, {"forecast": "unknown", "temperature_f": None})

def event_dict(event):
    return event.model_dump() if hasattr(event, "model_dump") else dict(event)

with client.responses.connect() as connection:
    connection.response.create(
        model="gpt-5.4",
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Use the get_weather tool for Austin, then answer in one short sentence.",
                    }
                ],
            }
        ],
        tools=TOOLS,
        tool_choice="required",
        store=False,
    )

    first_response_id = None
    call_id = None
    arguments_json = None

    while True:
        event = connection.recv()
        data = event_dict(event)
        etype = event.type

        if etype == "response.output_item.done":
            item = data.get("item", {})
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                arguments_json = item.get("arguments")

        elif etype == "response.completed":
            first_response_id = data["response"]["id"]
            break

        elif etype in {"error", "response.failed"}:
            raise RuntimeError(json.dumps(data, indent=2))

    args = json.loads(arguments_json)
    tool_result = get_weather(args["location"])

    connection.response.create(
        model="gpt-5.4",
        previous_response_id=first_response_id,
        input=[
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(tool_result),
            }
        ],
        tools=TOOLS,
        store=False,
    )

    text_chunks = []
    while True:
        event = connection.recv()
        data = event_dict(event)
        etype = event.type

        if etype == "response.output_text.delta":
            delta = data.get("delta", "")
            print(delta, end="", flush=True)
            text_chunks.append(delta)

        elif etype == "response.completed":
            response = data["response"]
            print()
            print("final_text:", response.get("output_text") or "".join(text_chunks))
            break

        elif etype in {"error", "response.failed"}:
            raise RuntimeError(json.dumps(data, indent=2))
```
