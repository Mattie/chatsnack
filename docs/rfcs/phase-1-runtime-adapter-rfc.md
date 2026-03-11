# Phase 1 RFC: Runtime Adapter Boundary and Normalized Runtime Types

## Status
Draft

## Summary
This RFC introduces an internal runtime boundary (`chatsnack/runtime/`) that isolates provider-specific SDK objects from the `Chat` layer.

## Ownership boundary
- **Chat layer owns prompt compilation**: fillings/template expansion, message construction, and feature orchestration remain in `chatsnack/chat/*`.
- **Runtime adapter owns provider I/O**: calling provider SDKs and converting provider-specific payloads into normalized internal types.

This split enables future provider backends and consistent listener event contracts.

## New internal runtime model
- `RuntimeAdapter` protocol for sync/async completion and stream operations.
- `NormalizedCompletionResult` for non-stream responses.
- `NormalizedAssistantMessage` and `NormalizedToolCall` for assistant/tool payloads.
- `RuntimeStreamEvent` envelope for listener events with schema versioning.
- `RuntimeTerminalMetadata` and `RuntimeErrorPayload` for stream terminal states.

## Event schema (v1.0)
Envelope fields:
- `schema_version`
- `type`
- `index`
- `data`

Reserved event types:
- `text_delta`
- `tool_call_delta`
- `tool_result`
- `phase`
- `usage`
- `completed`
- `error`

## Initial adapter
`ChatCompletionsAdapter` is the first implementation. It preserves current Chat Completions behavior while normalizing responses/chunks.

## Migration notes
- Existing prompt compilation paths stay unchanged in phase 1.
- Listener `events=True` remains backward-compatible by default with legacy event payloads (`text_delta` + `done`).
- The v1 envelope (`schema_version`, `type`, `index`, `data`) is available as an explicit opt-in (`event_schema="v1"`).
- `ChatStreamListener` can consume runtime events in normalized mode while maintaining legacy plain text streaming behavior for compatibility.
