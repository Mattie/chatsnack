# Chatsnack Phase 0 Compatibility RFC: `Chat` Public Contract

## Status
Accepted for Phase 0 guardrails.

## Scope
This RFC locks current, observable `Chat` behavior before runtime adapter and transport migration work.

## Public Sync/Async Matrix

| Method | Sync script usage | Sync active-loop usage | Async usage in loop | Streaming contract |
| --- | --- | --- | --- | --- |
| `ask()` | returns `str` through async implementation | fail fast with deterministic guidance error | use `ask_a()` | non-stream |
| `ask_a()` | n/a | n/a | returns `str`; raises if `self.stream` is true | non-stream |
| `chat()` | returns `Chat` through async implementation | fail fast with deterministic guidance error | use `chat_a()` | non-stream |
| `chat_a()` | n/a | n/a | returns `Chat`; raises if `self.stream` is true | non-stream |
| `listen()` | returns `ChatStreamListener` when stream enabled; otherwise plain completion `str` payload | fail fast with deterministic guidance error | use `listen_a()` | stream-first |
| `listen_a()` | n/a | n/a | returns `ChatStreamListener`; raises if `self.stream` is false | stream |

### Active event loop behavior
Sync wrappers (`ask`, `chat`, `listen`) are script-oriented and fail fast if called from an active event loop.

Standardized error text pattern:
- `Cannot call sync ask() from an active event loop. Use ask_a() instead.`
- `Cannot call sync chat() from an active event loop. Use chat_a() instead.`
- `Cannot call sync listen() from an active event loop. Use listen_a() instead.`

## Listener Compatibility Contract

### Legacy default mode
- `listen()` / `listen_a()` default `events=False`.
- Iteration yields `str` chunks.
- `''.join(listener)` remains valid compatibility behavior.

### Opt-in events mode
- `listen(events=True)` and `listen_a(events=True)` yield structured event dictionaries.
- Stable event ordering:
  1. Zero or more `{"type": "text_delta", "index": <int>, "text": <str>}` events.
  2. A terminal `{"type": "done", "index": <int>, "response": <full_text>}` event.

### Non-stream `listen()` compatibility
- When `self.stream` is disabled, `listen()` returns the same plain `str` completion payload contract as `ask()`.
- In this mode, `events` is ignored and no listener/event metadata is returned.
- Stability guarantee for Phase 1: callers can treat non-stream `listen()` as an alias for non-stream completion retrieval.

## Phase 1 Baseline Freeze
The compatibility behaviors in this RFC are frozen as the authoritative baseline for Phase 1 adapter work. Any behavior changes after this point require an RFC update plus guard-test updates in `tests/mixins/`.

## Observable Behavior Locked by Phase 0

### Model fallback
- Non-stream completion path (`_cleaned_chat_completion`) defaults to `gpt-5-chat-latest` if model/engine absent.
- Stream listener constructor defaults to `gpt-5-chat-latest` if model/engine absent.
- Parameter collection (`ChatParams._get_non_none_params`) defaults to `gpt-5-chat-latest` if unset.

### Role remapping
- `_gather_format` remaps `system` role for reasoning-model compatibility:
  - `system -> developer` for models without system but with developer messages (e.g. `o1`).
  - `system -> user` for models without system/developer support (`o1-preview`, `o1-mini`).

### Tool recursion
- `auto_execute=None` behaves as enabled.
- Max recursion depth is `5`.
- `auto_feed=None` behaves as enabled, feeding tool output back for follow-up completion.
- `auto_feed=False` records assistant/tool interactions and stops recursion.
- Tool-call metadata and tool messages are preserved in returned chat history.

### Return shape
- `_cleaned_chat_completion()` returns `str` when no tool calls are present.
- `_cleaned_chat_completion()` returns a message object when tool calls are present.
- `chat_a()` branches on this shape and preserves downstream tool-call data.

## Guard Test Coverage
Phase 0 adds migration-guard tests in `tests/mixins/` to lock:
- sync wrapper fail-fast loop semantics,
- async method behavior in active loops,
- fallback model defaults,
- role remapping behavior,
- tool recursion `auto_execute`/`auto_feed` behavior,
- return-shape branching,
- listener legacy text iteration and events-mode iteration.
