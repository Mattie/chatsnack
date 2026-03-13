# Phase 2 RFC: Responses HTTP (Non-Streaming) Adapter Rollout

## Status
Proposed.

## Summary
Phase 2 adds a new runtime adapter path for OpenAI Responses API **non-stream** HTTP completions only. This phase does **not** include lane transport or WebSocket streaming work.

## Explicit scope boundaries

### In scope
- Non-stream request/response execution through the Responses API path.
- Runtime-level normalization into existing internal runtime types consumed by `Chat`.
- Compatibility-preserving integration behind explicit opt-in controls.

### Out of scope
- Any lane transport implementation.
- Any WebSocket transport implementation.
- Streaming migration (`listen`, `listen_a`, stream event schema/default behavior changes).
- Prompt compiler rewrites in `chatsnack/chat/*`.

## Phase 0 + Phase 1 constraints preserved
This RFC inherits and preserves prior accepted constraints:

- **Phase 0 public behavior freeze remains authoritative** for sync/async wrappers, fail-fast loop semantics, listener compatibility, fallback expectations, and tool recursion/return-shape behavior exposed at the `Chat` surface.
- **Phase 1 ownership boundary remains unchanged**: prompt compilation stays in the `Chat` layer; provider I/O and payload conversion stay in runtime adapters.
- **`ChatCompletionsAdapter` remains the compatibility baseline** during rollout; Responses support must match established observable behavior unless explicitly RFC-approved.

## Decisions

### 1) Runtime selection approach
- Runtime selection remains **explicit opt-in** via explicit params and/or profile configuration.
- No implicit default flip to Responses in Phase 2.
- Existing Chat Completions runtime selection remains default compatibility behavior.

### 2) Prompt-to-Responses mapping boundary
- Mapping from compiled prompt/messages to provider-specific Responses request payloads is owned by the runtime adapter.
- Prompt compiler behavior and interfaces remain unchanged in Phase 2.

### 3) Normalization targets
- Responses outputs are normalized into existing runtime result structures used by `Chat`.
- Minimum normalization target for this phase:
  - assistant text content
  - tool call payloads
- Normalized outputs must preserve the current downstream contracts expected by Chat-layer orchestration.

### 4) Continuation ownership
- `previous_response_id` is treated as internal continuation metadata/state.
- Continuation linkage stays within runtime/adapter-managed metadata and is not promoted as new public `Chat` API surface in this phase.

### 5) Metadata container shape
Phase 2 metadata attached to normalized completion results should include, at minimum:
- `response_id`
- `usage`
- `assistant_phase`
- `provider_extras` (opaque provider-specific details)

This container is internal runtime metadata intended for compatibility-safe evolution.

## Rollout and compatibility guardrails
- `ChatCompletionsAdapter` behavior is the rollout baseline for parity checks.
- Responses adapter behavior should be introduced incrementally behind opt-in controls.
- Any observable divergence from baseline Chat behavior requires explicit documentation and RFC follow-up.

## Approval checklist (required before implementation starts)
Implementation work for this RFC must not begin until all items are checked:

- [ ] PM sign-off recorded.
- [ ] Implementation lead sign-off recorded.
- [ ] Scope confirmation recorded: **non-stream Responses HTTP only**.
- [ ] Exclusion confirmation recorded: **no lane transport / no WebSocket / no streaming default changes**.
- [ ] Compatibility plan acknowledged with `ChatCompletionsAdapter` as baseline.
