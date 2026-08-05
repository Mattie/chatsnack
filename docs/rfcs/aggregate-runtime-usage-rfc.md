# RFC: Aggregate Runtime Usage Across One Chat Call

## Status

Accepted and implemented.

## Decision

Chatsnack records one provider-neutral usage item for every normalized provider
completion returned during a public `chat()` or `chat_a()` call. The ordered,
frozen result is exposed as `Chat.last_call_usage` on the source chat and the
returned chat.

Collection happens at the adapter-return boundary. Metadata setters and
temporary chats may propagate the latest response state without creating more
usage entries.

## Public contract

`CallUsage.responses` contains one-based `ResponseUsage` values. Each response
includes provider IDs, model, normalized counts, coverage, and a deep-copied
plain mapping of the original usage payload.

Responses and Chat Completions usage names share these normalized fields:

| Normalized field | Responses | Chat Completions |
| --- | --- | --- |
| `input_tokens` | `input_tokens` | `prompt_tokens` |
| `cached_input_tokens` | `input_tokens_details.cached_tokens` | `prompt_tokens_details.cached_tokens` |
| `output_tokens` | `output_tokens` | `completion_tokens` |
| `reasoning_tokens` | `output_tokens_details.reasoning_tokens` | `completion_tokens_details.reasoning_tokens` |
| `total_tokens` | `total_tokens` | `total_tokens` |

Every aggregate field sums reported values and remains `None` when no response
reported that field. A non-null empty usage object counts as reported usage.
An absent usage payload creates a response item with `usage_reported=False` and
makes the call incomplete.

## Lifecycle

Each public call owns an independent private ledger. Success freezes one
snapshot for the source and returned chats. Failure freezes the partial ledger
on the source chat and attaches it to the original exception when that exception
accepts attributes.

`_last_call_usage` is unannotated live state. Construction, manual copy, reset,
and load begin with `None`, and YAML serialization stays unchanged.

## Provider and transport coverage

Normalization follows response shape. It covers Chatsnack's existing Responses
HTTP, Responses WebSocket, and Chat Completions adapters, including compatible
OpenRouter response shapes. Azure OpenAI uses the same fixture-backed paths and
is best-effort because no live Azure environment was available for this change.

Provider work without a completed payload reaching Chatsnack cannot appear in
the ledger. This RFC adds no provider request, local token estimate, pricing,
budget, session total, or new transport.
