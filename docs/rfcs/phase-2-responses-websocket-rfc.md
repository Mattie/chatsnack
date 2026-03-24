# Phase 2 RFC: Responses API WebSocket Support for Chatsnack

## Status
Completed (implemented on March 20, 2026).

## Summary
Phase 2 should deliver true WebSocket support for the Responses API in chatsnack.

The official WebSocket mode keeps a persistent connection to `/v1/responses` and starts each turn with a `response.create` event whose payload mirrors the normal Responses create body. This is a strong fit for chatsnack because our current Responses adapter already knows how to compile chats into that request shape.

That means Phase 2 can stay focused and practical:

- keep the current `Chat` authoring model
- keep `runtime="responses"` as the public runtime family
- enable WebSocket transport only when `session` is explicitly set
- keep `listen()` and `listen_a()` as the main notebook experience
- keep `ask()` and `chat()` behavior stable
- add a real WebSocket transport for Responses streaming
- preserve function-calling and multi-turn continuation through `chat()` chains

The YAML design work belongs in Phase 3.

## Why this phase is timely

The official WebSocket mode is aimed at long-running, tool-call-heavy workflows and uses persistent connections plus incremental inputs for lower-latency execution. The docs call out workflows with many model-tool round trips and report meaningful end-to-end latency gains for long chains. That lines up well with the kinds of chats we want chatsnack to make easy in notebooks and scripts.

Phase 2 should therefore focus on a real, usable runtime path instead of broader transport architecture work.

## Current state in our code

Today we have a clean runtime boundary:

- [Chat](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/__init__.py) selects a runtime adapter
- [RuntimeAdapter](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/types.py) defines normalized completion and stream interfaces
- [ChatStreamListener](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/mixin_query.py) consumes normalized runtime events
- [ResponsesAdapter](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/responses_adapter.py) handles HTTP Responses requests

The gap is narrow and concrete.

In [responses_adapter.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/responses_adapter.py), `stream_completion()` and `stream_completion_a()` currently call the non-stream create path and replay a synthetic event stream after the full HTTP response arrives. That gives us compatibility with the listener API, though it does not provide true provider-side streaming or a persistent Responses WebSocket session.

## Grounding from current OpenAI docs

As of March 19, 2026, the official docs show the following about Responses API WebSocket mode:

- WebSocket mode is part of the Responses API and keeps a persistent connection to `/v1/responses`. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- Each turn is started by sending a `response.create` event whose payload mirrors the normal Responses create body, while transport-only fields such as `stream` and `background` are excluded. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- Continuation uses `previous_response_id` plus only the new input items for the next turn. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- The active connection keeps the most recent previous response in a connection-local in-memory cache for low-latency continuation. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode), [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- With `store=true`, an older response may be hydrated from persisted state. With `store=false`, an uncached id returns `previous_response_not_found`. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- Server events and ordering match the existing Responses streaming event model, and only one response can be in flight per WebSocket connection. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- Connections are limited to 60 minutes. [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- The standard Responses streaming event model includes events such as `response.created`, `response.output_text.delta`, `response.completed`, `response.function_call_arguments.delta`, and `error`. [Streaming responses](https://platform.openai.com/docs/guides/streaming-responses), [Function calling](https://platform.openai.com/docs/guides/function-calling)
- The normal Responses request body still supports fields like `tools`, `reasoning`, `text`, `include`, and `conversation`. [Responses API reference](https://platform.openai.com/docs/api-reference/responses)

These details matter because they let us build WebSocket support as a second transport for the same Responses request model. We do not need a Realtime-style conversation mirror with `session.update`, `conversation.item.create`, or `synced_message_count` bookkeeping.

## Goals

- Deliver true incremental Responses streaming over WebSocket.
- Keep the current `Chat` API intact.
- Keep the current runtime event schema intact.
- Support text-first multi-turn chats in notebooks.
- Support function calling over the socket.
- Reuse the current Responses request compilation rules.
- Recover cleanly after reconnects and the 60-minute connection limit when `session` is enabled.

## Non-goals

- YAML serialization expansion in Phase 2.
- Audio or WebRTC support in Phase 2.
- Full provider event exposure in the public chatsnack listener surface.
- A large runtime rewrite before the feature works end to end.

## Design principles

### 1. Treat this as Responses with a conditional transport

The payload shape is still Responses. Our chat compilation rules already produce most of what the socket needs.

Phase 2 should therefore keep the Responses mental model front and center:

- same message compilation
- same tool definitions
- same reasoning and text settings
- same continuation fields
- same normalized final result shape

### 2. Make session intent explicit

`responses` should continue to name the runtime family. Transport selection should come from a new `session` parameter instead of a second public runtime name.

Suggested public contract:

- `session=None` or unset: use the existing HTTP Responses path
- `session="inherit"`: use the WebSocket path and pass the same session down through `chat()` continuations
- `session="new"`: use the WebSocket path and give each `Chat` object its own fresh session

This keeps the public API aligned with chatsnack's existing conversation model.

### 3. Optimize for notebook usability

The best Phase 2 experience is simple:

- streaming text appears as it arrives
- multi-turn chats reuse the same socket when `session="inherit"`
- function calls surface incrementally
- `listen()` and `listen_a()` feel natural in notebooks

### 4. Preserve `ask()` versus `chat()` semantics

The philosophy and notebooks make an important distinction:

- `ask()` is for immediate readback without mutating the chat lineage
- `chat()` is for continuation and returns the next `Chat`

Phase 2 should keep that line sharp.

- `ask()` and `listen()` may use a WebSocket-backed session when `session` is enabled
- `ask()` and `listen()` do not stamp continuation ownership onto the source chat
- `chat()` remains the method that owns conversation continuation across returned chats

### 5. Fail fast on one-in-flight session misuse

The provider allows only one response in flight per WebSocket connection. chatsnack should reflect that with a deterministic fail-fast behavior.

- if a session already has an in-flight response, starting another response on that same session should raise a guidance error
- callers that need concurrency should use a separate chat object or `session="new"`

## Proposed public behavior

### Runtime selection

Suggested behavior:

- `runtime="responses"` or `runtime_selector="responses"` keeps the Responses runtime family
- `session=None` or unset keeps the current HTTP adapter behavior
- `session="inherit"` or `session="new"` selects the WebSocket transport internally

No additional public runtime selector is required for WebSocket mode.

### Session parameter

Suggested Python surface:

- `chat.session`
- `ChatParams(session=...)`

Allowed values in Phase 2:

- `None` or unset
- `"inherit"`
- `"new"`

### Synchronous chat flow

```python
from chatsnack import Chat, ChatParams

chat = Chat(
    "Respond tersely.",
    params=ChatParams(model="gpt-5.4", runtime="responses", stream=True, session="inherit"),
)

listener = chat.listen("What is chatsnack?")
for chunk in listener:
    print(chunk, end="")
```

### Async notebook flow

```python
from chatsnack import Chat, ChatParams

chat = Chat(
    "Respond tersely.",
    params=ChatParams(model="gpt-5.4", runtime="responses", stream=True, session="inherit"),
)

listener = await chat.listen_a("What is chatsnack?")
async for chunk in listener:
    print(chunk, end="")
```

### Multi-turn continuation through `chat()`

```python
root = Chat(
    "You are a coding assistant.",
    params=ChatParams(model="gpt-5.4", runtime="responses", session="inherit"),
)

turn1 = root.chat("Summarize this file.")
turn2 = turn1.chat("Now extract the three riskiest issues.")

print(turn1.response)
print(turn2.response)
```

When `session="inherit"`, the adapter should reuse the live socket when it is healthy and continue with the most recent `response_id` plus only the incremental input items for the next turn.

### Fresh session isolation

```python
isolated = turn2.copy()
isolated.session = "new"
fresh = isolated.chat("Start a fresh review of the same file.")
```

`session="new"` should create a fresh session for that chat object lineage without mutating the existing inherited session.

## Proposed refactor

Phase 2 can stay small if we split shared Responses logic from transport logic.

### 1. Extract shared Responses request building

Create a shared internal helper module, for example:

- `chatsnack/runtime/responses_common.py`

Move these responsibilities out of the current HTTP adapter:

- profile default merging
- message to Responses input-item mapping
- continuation suffix selection for incremental inputs
- request body assembly for Responses
- transport-only field stripping before `response.create`
- final output normalization into `NormalizedCompletionResult`

That shared code should accept normal chatsnack messages and normal adapter kwargs, then build a Responses request payload that either transport can send.

### 2. Keep the current HTTP adapter

Keep [ResponsesAdapter](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/runtime/responses_adapter.py) as the HTTP runtime.

That path is already working well enough for non-WebSocket usage and already has tests. Phase 2 should avoid churn here beyond moving common logic into shared helpers.

### 3. Add `ResponsesWebSocketAdapter`

Add a new adapter alongside the HTTP adapter, for example:

- `chatsnack/runtime/responses_websocket_adapter.py`

Responsibilities:

- open and manage the Responses WebSocket connection
- send `response.create` events using the shared request builder
- read provider events and normalize them into chatsnack runtime events
- accumulate a final `NormalizedCompletionResult` for `ask()` and `chat()`
- maintain lightweight continuation state for the current connection

### 4. Add a small session object

A session object should hold only what the socket path truly needs.

Suggested fields:

- `mode`
- `socket`
- `connected_at`
- `expires_at`
- `last_response_id`
- `in_flight`
- `last_store_value`
- `last_model`

This is intentionally smaller than the Realtime-session design we discussed earlier because Responses WebSocket mode already takes a normal Responses request body on each turn.

### 5. Add session-aware adapter selection

In [chat/__init__.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/__init__.py), runtime selection should stay at `responses`, while transport selection should be derived from `session`.

Suggested internal behavior:

- `runtime="responses"` plus unset `session` -> `ResponsesAdapter`
- `runtime="responses"` plus `session in {"inherit", "new"}` -> `ResponsesWebSocketAdapter`

### 6. Add a shared event normalizer

Create a small event normalizer that converts provider events into our existing runtime event schema.

Suggested mappings:

- `response.output_text.delta` -> `text_delta`
- `response.function_call_arguments.delta` -> `tool_call_delta`
- final tool call items in `response.completed` -> finalized `tool_call_delta` payloads when needed
- terminal response payload in `response.completed` -> `completed`
- provider `error` or `response.failed` -> `error`
- usage in terminal payload -> `usage` before `completed`

This keeps `ChatStreamListener` unchanged.

Legacy listener compatibility still matters. In Phase 2:

- `events=True` without `event_schema` should emit the deprecation warning planned in Phase 1
- `event_schema="legacy"` should keep surfacing `text_delta` plus terminal `done`
- `event_schema="v1"` should expose the richer runtime event stream, including tool-call and usage events

## How continuation should work

### When `session` is unset

When `session` is unset or `None`, chatsnack should stay on the current HTTP Responses path. No WebSocket session is opened.

### On a healthy inherited session

When the chat has `session="inherit"`, a live socket, and a recent `response_id`:

1. build the next Responses request body
2. set `previous_response_id` to the last response id
3. send only the incremental suffix of local messages
4. stream server events until completion
5. store the new response id for the next turn

This follows the official WebSocket-mode continuation model closely.

When `chat()` returns a new `Chat`, that descendant should inherit the same session object unless its `session` parameter is changed explicitly.

### On `session="new"`

When a chat is configured with `session="new"`:

1. create a fresh session object for that chat object
2. reuse it for calls on that same chat object when practical
3. do not pass it down automatically to descendants created by `chat()`
4. give each descendant its own fresh session object unless its `session` parameter is changed explicitly

### On reconnect

When the socket closes or reaches the 60-minute limit:

1. open a new socket lazily on the next request
2. if we have `store=true` and a previous response id, try `previous_response_id` first
3. if the server returns `previous_response_not_found`, rebuild the request by sending full local chat context and omitting `previous_response_id`
4. continue the chain from the newly returned response id

This gives chatsnack a practical recovery path without adding a second transcript system.

### Warmup support

The docs allow `response.create` with `generate: false` as a warmup path that returns a response id and prepares request state for faster subsequent turns.

Phase 2 should treat this as an internal optimization hook, not a required public feature. If we expose it later, it should feel like a small chatsnack convenience rather than another transport concept the user has to manage.

## How `ask()`, `chat()`, `listen()`, and `listen_a()` should work

### `listen()` and `listen_a()`

These should be the first-class WebSocket flows.

They should:

- connect if needed
- send `response.create`
- yield normalized events as soon as they arrive
- preserve existing `events=True` behavior through `ChatStreamListener`
- finalize `listener.response` and completion state exactly as today
- respect `session="inherit"` versus `session="new"` when choosing the session object

### `ask()` and `chat()`

These should keep their current semantics.

Implementation approach:

- `create_completion()` and `create_completion_a()` in the WebSocket adapter can internally consume the streamed provider events until terminal completion
- once complete, they return the same `NormalizedCompletionResult` shape used by the HTTP adapter

This keeps the rest of the chat orchestration code stable.

Additional semantic guardrails:

- `ask()` stays one-shot and does not claim continuation ownership for later turns
- `chat()` owns continuation metadata and session inheritance for returned chats

## Function-calling flow

Function calling should remain aligned with the current chatsnack tool model.

The official Responses streaming model includes `response.output_item.added` for function call items and `response.function_call_arguments.delta` for incremental argument filling. The WebSocket adapter should aggregate those deltas into the same normalized tool-call structure our chat layer already understands.

That preserves the existing chatsnack pattern:

- assistant emits tool calls
- local tool executes
- tool result is appended as a tool message
- next turn sends the tool output back through Responses

Because the WebSocket request body uses the same Responses input-item shapes, our existing `function_call_output` mapping can stay in the shared request builder.

Detailed function-call progress belongs in the normalized runtime stream. Legacy listener mode should continue to focus on text-first output.

## Recommended dependency direction

The current official examples use a direct WebSocket client rather than the OpenAI Python SDK.

Phase 2 should therefore plan for an explicit websocket dependency under chatsnack's control.

A practical option is:

- `websocket-client` for sync transport
- `websockets` for async transport

If we later find a stable SDK-native path that covers both sync and async cleanly, we can swap the transport implementation behind the adapter without changing the public chatsnack surface.

## Suggested implementation order

### Step 1

Extract shared Responses request and normalization helpers from the current HTTP adapter.

### Step 2

Add `session` support in the relevant params layer and [chat/__init__.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/__init__.py) so `responses` selects the runtime family and `session` selects the transport mode.

### Step 3

Add `ResponsesWebSocketAdapter` with `stream_completion()` and `stream_completion_a()` implemented against the real socket.

### Step 4

Add `create_completion()` and `create_completion_a()` wrappers that consume the stream to completion and return normal normalized results.

### Step 5

Add one-in-flight enforcement and transport-field sanitization for the WebSocket path.

### Step 6

Add reconnect handling and fallback-to-full-context logic for stale `previous_response_id` cases.

### Step 7

Add example notebooks or example scripts focused on:

- plain text streaming
- multi-turn continuation via `chat()`
- function calling over the socket

## Testing priorities

Phase 2 should focus on a small set of high-value tests.

### Runtime tests

Add focused adapter tests for:

- request-body reuse between HTTP and WebSocket paths
- transport-only field stripping before `response.create`
- text delta streaming
- function-call argument delta aggregation
- response completion normalization
- socket reconnect behavior after `previous_response_not_found`
- one-in-flight enforcement in the session object
- `session=None` staying on HTTP Responses
- `session="inherit"` session reuse across `chat()` descendants
- `session="new"` isolation across `chat()` descendants

### Chat integration tests

Extend the existing query and listener tests to cover:

- `runtime="responses"` plus `session="inherit"` and `session="new"`
- `listen()` text accumulation
- `listen_a()` async iteration
- continuation metadata updates after streamed completion
- tool call recursion staying compatible with the current chat flow
- `events=True` deprecation warning when `event_schema` is omitted
- `event_schema="v1"` surfacing richer runtime events without changing legacy defaults

## Acceptance target for Phase 2

Phase 2 is successful when this feels good:

1. create a `Chat` with `runtime="responses"` and `session="inherit"` or `session="new"`
2. stream text in a notebook with `listen()` or `listen_a()`
3. continue for several turns through `chat()` with inherited session ownership
4. execute a function tool round trip
5. recover from a dropped connection without losing the chat session
6. leave `session` unset and keep the current HTTP Responses behavior

That is enough surface area to prove the transport, preserve chatsnack ergonomics, and give us a strong base for Phase 3 YAML work.

## References

- [WebSocket mode](https://developers.openai.com/api/docs/guides/websocket-mode)
- [Conversation state](https://developers.openai.com/api/docs/guides/conversation-state)
- [Responses API reference](https://platform.openai.com/docs/api-reference/responses)
- [Streaming responses](https://platform.openai.com/docs/guides/streaming-responses)
- [Function calling](https://platform.openai.com/docs/guides/function-calling)

## End-User Example Acceptance Criteria

### Example 1: HTTP Responses remains the default

```python
from chatsnack import Chat, ChatParams

chat = Chat("Respond tersely.", model="gpt-5.4-mini", runtime="responses")

answer = chat.ask("What color is the sky?")
```

Acceptance criteria:

- the request uses the HTTP Responses path because `session` is unset
- `answer` is returned as a plain string
- no WebSocket session is created
- the source chat remains a one-shot query unless `chat()` is called

### Example 2: Streaming over an inherited session

```python
from chatsnack import Chat, ChatParams

chat = Chat("Respond tersely.", model="gpt-5.4", runtime="responses", stream=True, session="inherit")

listener = chat.listen("Summarize this file.")
text = "".join(listener)
```

Acceptance criteria:

- the request uses a WebSocket-backed Responses session
- text chunks arrive incrementally through `listen()`
- `listener.response` matches the accumulated text
- the session remains available for later inherited continuation

### Example 3: Continuation through `chat()`

```python
from chatsnack import Chat, ChatParams

root = Chat("You are a coding assistant." model="gpt-5.4", runtime="responses", session="inherit")

turn1 = root.chat("Summarize C++'s memory model.")
turn2 = turn1.chat("List the three riskiest aspects of it for security.")
```

Acceptance criteria:

- `turn1` and `turn2` are new `Chat` objects
- the inherited websocket session flows through the `chat()` lineage
- continuation uses the latest `response_id` plus incremental input where possible
- the source chat objects preserve normal chatsnack continuation semantics

### Example 4: Fresh session isolation

```python
from chatsnack import Chat, ChatParams

chat = Chat("You are a coding assistant.",
    model="gpt-5.4", runtime="responses", session="new")

turn1 = root.chat("Summarize C++'s memory model.")
turn2 = turn1.chat("List the three riskiest aspects of it for security.")
```

Acceptance criteria:

- `chat` gets a fresh WebSocket session
- `turn1` does not inherit that session automatically
- `turn2` gets its own fresh session unless the session mode is changed explicitly
- separate lineages can proceed without sharing one in-flight lock

### Example 5: Tool round trip over the socket

```python
from chatsnack import Chat, ChatParams, utensil

@utensil
def get_weather(location: str):
    return {"forecast": "sunny"}

chat = Chat("Use tools when helpful.", model="gpt-5.4", runtime="responses", session="inherit",
    utensils=[get_weather])

result = chat.chat("What is the weather in Austin?")
```

Acceptance criteria:

- the model can emit a tool call over the WebSocket path
- the local utensil executes through the existing chatsnack tool loop
- tool output is fed back through the Responses runtime as a tool message
- the final returned chat preserves assistant, tool, and follow-up assistant history
