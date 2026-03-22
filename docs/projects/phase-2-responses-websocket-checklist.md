# Phase 2 Responses WebSocket Checklist

Primary RFC: [phase-2-responses-websocket-rfc.md](../rfcs/phase-2-responses-websocket-rfc.md)

Use this as the running punch list for Phase 2. Check things off, leave short notes, and say what somebody can actually do now. The goal is to make progress easy to scan without having to re-read the whole RFC.

## Quick Update Template

Drop a note into `## Progress Notes` whenever something meaningfully changes.

```md
### YYYY-MM-DD - Short update title
- Status: done | partial | blocked
- RFC sections: `Session parameter`; `Definitive session behavior matrix`
- What works for users: I can create a `Chat(..., session="inherit")`, stream with `listen()`, and continue with `chat()` on the same session line.
- Caveats: Concurrent calls on the same session still fail fast, and rich events still need `event_schema="v1"`.
- How we checked it: adapter tests, chat integration tests, notebook/manual check
- Follow-up: leftover tests, docs, cleanup, or edge cases
```

## Punch List

### Getting onto the WebSocket path
- [x] Leaving `session` unset keeps us on plain HTTP Responses.
  RFC: `Design principles -> Make session intent explicit`; `Proposed public behavior -> Runtime selection`
- [x] `session="inherit"` and `session="new"` move us onto the WebSocket transport.
  RFC: `Design principles -> Make session intent explicit`; `Proposed public behavior -> Runtime selection`
- [x] `chat.session` and `ChatParams(session=...)` are easy to understand from the public API.
  RFC: `Proposed public behavior -> Session parameter`
- [x] `chat.close_session()` and `Chat.close_all_sessions()` work the way the RFC says they should.
  RFC: `Proposed public behavior -> Session shutdown methods`

### Session behavior and lineage
- [x] `ask()`, `listen()`, `chat()`, and `copy()` match the matrix for `None`, `inherit`, and `new`.
  RFC: `Proposed public behavior -> Definitive session behavior matrix`
- [x] The named edge cases behave the same way they do in the RFC examples.
  RFC: `Proposed public behavior -> Session edge cases`
- [x] `ask()` and `listen()` stay one-shot and do not grab continuation ownership.
  RFC: `Design principles -> Preserve ask() versus chat() semantics`; `How ask(), chat(), listen(), and listen_a() should work`
- [x] `chat()` is still the place where committed continuation state moves forward.
  RFC: `Design principles -> Preserve ask() versus chat() semantics`; `How ask(), chat(), listen(), and listen_a() should work`

### Busy sessions, shutdown, and cleanup
- [x] Hitting a busy shared session raises `ResponsesSessionBusyError` with the documented fail-fast behavior.
  RFC: `Concurrency and error contract -> Busy-session exception`; `Queueing policy`; `Sync/async parity`
- [x] We do not quietly queue extra work on a busy session.
  RFC: `Concurrency and error contract -> Queueing policy`
- [x] Background thread, worker, or async-task cleanup happens on completion, explicit close, cancellation, and transport/provider errors.
  RFC: `Concurrency and error contract -> Cleanup expectation`; `Proposed refactor -> Lock ownership and lifecycle boundaries -> Shutdown path`

### Adapter and event flow
- [x] Shared Responses request building and normalization live outside the transport-specific adapter.
  RFC: `Proposed refactor -> Extract shared Responses request building`
- [x] `ResponsesWebSocketAdapter` exists for sync and async streaming.
  RFC: `Proposed refactor -> Add ResponsesWebSocketAdapter`
- [x] Lock ownership, one-in-flight state, and lifecycle reset follow the RFC.
  RFC: `Proposed refactor -> Lock ownership and lifecycle boundaries`
- [x] Runtime events map cleanly into chatsnack's event schema.
  RFC: `Proposed refactor -> Add a shared event normalizer`
- [x] Legacy listener behavior and `event_schema="v1"` both line up with the RFC.
  RFC: `Proposed refactor -> Add a shared event normalizer`

### Reconnect and retry behavior
- [x] Reconnect opens a fresh socket lazily and keeps continuation working the way the RFC describes.
  RFC: `How continuation should work -> On reconnect`
- [x] `previous_response_not_found` falls back to full local context exactly once.
  RFC: `How continuation should work -> On reconnect`; `Error and retry policy`
- [x] Recoverable and non-recoverable errors follow the RFC's small taxonomy.
  RFC: `Error and retry policy`
- [x] Timeout, close-code, and retry/backoff behavior match in sync and async transports.
  RFC: `Error and retry policy`
- [x] Normalized `error` events carry the retry and transport details the RFC calls for.
  RFC: `Error and retry policy`

### Streaming, completion, and tools
- [x] `listen()` and `listen_a()` feel like the main WebSocket entrypoints.
  RFC: `How ask(), chat(), listen(), and listen_a() should work -> listen() and listen_a()`
- [x] `ask()` and `chat()` still feel like the chatsnack methods people already know.
  RFC: `How ask(), chat(), listen(), and listen_a() should work -> ask() and chat()`
- [x] Tool calling over the socket still works with the current chatsnack tool loop.
  RFC: `Function-calling flow`

### Proof that it works
- [x] The sync and async websocket dependencies sit behind the adapter boundary cleanly.
  RFC: `Recommended dependency direction`
- [x] Runtime tests cover transport reuse, retry classification, busy-session behavior, shutdown, and cleanup.
  RFC: `Testing priorities -> Runtime tests`
- [x] Chat integration tests cover session modes, event schemas, lineage edge cases, and explicit shutdown.
  RFC: `Testing priorities -> Chat integration tests`
- [x] Notebook or example-script coverage shows the Phase 2 acceptance target from a user point of view.
  RFC: `Suggested implementation order -> Step 9`; `Acceptance target for Phase 2`; `End-User Example Acceptance Criteria`

## Progress Notes

Add short dated entries here as work lands.


### 2026-03-21 - Phase 2 hardening pass
- Status: done
- RFC sections: `Error and retry policy`; `Concurrency and error contract`; `Session edge cases`; `End-User Example Acceptance Criteria`
- What works for users: `create_completion()` / `create_completion_a()` now raise `ResponsesSessionBusyError` or `ResponsesWebSocketTransportError` with full metadata instead of a generic RuntimeError. Retry after mid-stream `socket_receive_failed` is suppressed once any deltas have been yielded, preventing duplicate content. `close_session_a()` and `close_all_sessions_a()` properly await async socket teardown. `session="new"` descendants are seeded with lineage from the parent session (`last_response_id`, `last_model`, `last_store_value`). Notebook shows direct constructor style with consumable streaming and continuation examples.
- Caveats: Shutdown still does not wait for an in-flight stream to complete before tearing down the socket.
- How we checked it: 16 acceptance-level tests in `test_phase2_sessions.py` covering `ask()`, `chat()`, `listen()`, `copy()`, error taxonomy, retry-after-partial, async close, utensil tool flow, and session seeding. All 157 non-live tests pass.
- Follow-up: End-to-end provider tests remain environment-dependent; graceful stream draining on explicit close.

### 2026-03-20 - Phase 2 completion pass
- Status: done
- RFC sections: `Session parameter`; `How continuation should work`; `How ask(), chat(), listen(), and listen_a() should work`; `Function-calling flow`; `Testing priorities`
- What works for users: `runtime="responses"` + `session="inherit"|"new"` now selects a WebSocket adapter, `listen()/listen_a()` stream runtime events, `chat()` carries continuation metadata, and session shutdown APIs are available.
- Caveats: Runtime tests use mocked transport seams for deterministic behavior; end-to-end provider websocket smoke tests remain environment-dependent.
- How we checked it: new runtime websocket tests, new chat session-selection tests, and existing runtime/mixin tests.
- Follow-up: Phase 3 YAML work remains in its own RFC/checklist.
