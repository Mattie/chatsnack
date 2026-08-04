# Aggregate Runtime Usage Checklist

> Tracks implementation of the [aggregate runtime usage RFC](../rfcs/aggregate-runtime-usage-rfc.md).

## Public usage values

- [x] Add provider-neutral `UsageCounts`, `ResponseUsage`, and `CallUsage` values
  _Available from the `chatsnack` package root with intent-focused docstrings._
- [x] Preserve missing counts as `None` and reported zero as `0`
  _Covered for Responses and Chat Completions field shapes._
- [x] Retain a detached plain-data copy of each provider usage mapping
  _Nested provider values are deep-copied when recorded; freezing reuses those
  detached response values in an ordered tuple._
- [x] Expose response count, usage coverage, completeness, and missing sequences
  _All response positions are one-based and ordered._

## Call orchestration

- [x] Start an independent ledger for each `chat()` or `chat_a()` call
  _The sync surface delegates to the async call owner._
- [x] Record once where a normalized adapter completion first returns
  _Temporary-chat metadata propagation does not record ledger entries._
- [x] Share the ledger through utensil auto-feed follow-ups
  _A two-response utensil Goal test proves two entries and two provider requests._
- [x] Preserve partial usage on failure without wrapping the exception
  _The source chat and assignable exception expose the frozen partial call._
- [x] Keep `_last_runtime_metadata["usage"]` scoped to the latest response
  _Existing continuation behavior remains available beside aggregate usage._

## Model and persistence safety

- [x] Keep `_last_call_usage` private, unannotated, and transient
  _The public surface is the read-only `Chat.last_call_usage` property._
- [x] Clear usage on construction, copy, reset, and load
  _Lifecycle tests cover each operation._
- [x] Keep ordinary and `export_state` YAML free of the ledger
  _Runtime usage remains outside authored prompt assets._

## Adapter fidelity and compatibility

- [x] Preserve Chat Completions response IDs
  _Normalized metadata now carries the provider response ID._
- [x] Prefer the Responses payload's previous response ID
  _Request metadata remains the fallback._
- [x] Cover Responses HTTP, Responses WebSocket, and Chat Completions shapes
  _Existing adapter fixtures plus usage contract fixtures cover all current adapters._
- [x] Cover OpenRouter-compatible and Azure-compatible response shapes
  _Azure coverage is fixture-based and best-effort; live Azure remains unverified._

## Documentation and verification

- [x] Add a compact API reference example
  _The Chat reference shows totals, coverage, and per-response inspection._
- [x] Add an exploratory notebook cell
  _The artifact utensil workflow shows aggregate totals, coverage, missing usage
  sequences, and ordered per-response details after its auto-feed call._
- [ ] Run the complete test suite
  _Repository run: 555 passed, 1 skipped, and 8 existing provider-backed tests
  failed because `gpt-5-chat-latest` is deprecated in the configured live environment.
  The implicit fallback is now `gpt-5.4`, and focused offline default, listener,
  query-submission, and usage suites pass; the live full suite has not been rerun._
