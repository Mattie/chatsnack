# Python async utensils

## Goal

An ordinary `@utensil async def` function yields during I/O, returns its actual
result to the model, and lets independent chats progress on the same event loop.
The public authoring surface remains `Chat(..., utensils=[...])`.

## Execution

- [x] Await results before formatting or attaching call metadata
- [x] Accept coroutine and other awaitable results, including wrappers returning Futures
- [x] Preserve synchronous inline execution and sequential batch order
- [x] Keep result shapes, call IDs, execution controls, and auto-feed budgets
- [x] Copy returned dictionaries before adding call metadata
- [x] Convert ordinary exceptions into tool errors and propagate cancellation
- [x] Provide async manual dispatch and clear synchronous misuse guidance
- [x] Preserve custom synchronous execution hooks and await their async results
- [x] Update the older utensil execution path as well as the active query path
- [x] Accept general awaitables in Apply Patch and tool-search handlers

## Goal and contract coverage

- [x] G1: async results reach the model and history on all three runtimes
- [x] G2: another chat finishes while one tool awaits an event; task-local contexts stay separate
- [x] G3: grouped tools preserve local bindings through save/load, copy, reset, and continuation
- [x] Copy declarations without deep-copying live service callables or their connections
- [x] Exercise actual SDK request serialization and continuation offline with sync and async tools
- [x] Cover order, errors, cancellation cleanup, custom hooks, and execution controls

## Documentation and verification

- [x] Keep async behavior out of YAML; show the existing compact grouped form
- [x] Document blocking work, application rate limits, cancellation, and session boundaries
- [x] Add notebook authoring and continuation examples
  _The native top-level-await cell is tagged `skip_test` because the existing
  notebook runner executes script cells. Both new code cells were executed
  together with offline provider fixtures using top-level-await compilation._
- [x] Run the full offline regression suite
  _Final run: 1,152 passed, 84 skipped, 64 deselected, and 10 warnings.
  Provider-backed notebook and OpenRouter tests were excluded; other paid tests
  remained behind their existing opt-ins. The 27 focused async-tool/SDK checks
  also pass with RuntimeWarning and PytestUnraisableExceptionWarning treated as
  errors. `git diff --check` passes._

## Live provider verification

- [x] Add opt-in live mixed-tool contracts for `chat()` and `chat_a()`
- [x] Verify mixed sync/async execution and result correlation on OpenRouter Responses
- [x] Verify mixed sync/async execution and result correlation on OpenRouter Chat Completions
- [x] Verify a later turn recalls both receipts without re-executing the tools
- [x] Run the existing OpenRouter named-asset/history, sync streaming, async streaming, and local-tool checks
  _Eight distinct live checks passed against `z-ai/glm-5.3-flash`: four existing
  provider regressions and four mixed-tool contracts. All run against the real
  provider without mocked requests. The new contracts assert execution order,
  resolved results, call-ID correlation, and continuation. The initial mixed-tool
  assertion was corrected to recognize Responses' separate `tool_call` records
  alongside Chat Completions' grouped assistant calls._
- [ ] Complete direct OpenAI HTTP, WebSocket, and Chat Completions live checks
  _The first HTTP request returned `401 invalid_api_key` before any tool ran.
  The user requested finishing with OpenRouter coverage for now. Configured
  credentials and secret files were left unchanged._

## Release preparation

- [x] Bump the package version from 0.9.2 to 0.9.3
- [x] Update the packaged fluency skill and atlas with mixed sync/async authoring
- [x] Build and check the 0.9.3 wheel and source distribution
  _Both pass `twine check`. A wheel install into a temporary target imports
  version 0.9.3 and executes mixed synchronous/asynchronous local capabilities._
- [x] Verify both distributions contain the updated fluency resources
  _Skill and atlas bytes match the source in both archives. Packaged-skill and
  async-tool checks pass: 30 tests, with unawaited-coroutine and unraisable
  warnings treated as errors._

Existing synchronous utensils, constructor settings, YAML declarations, and
batch ordering retain their supported behavior. Two intentional corrections
are worth calling out in release notes: direct synchronous manual dispatch of an
async result now returns an actionable error, and prompt copies keep live Python
callable bindings instead of attempting to clone the service resources they own.

## Scope

OpenAI's model-level `async: true` calling, detached jobs, concurrent execution
within a batch, thread offloading, and application-level fairness or game-state
transactions remain separate work. Shared WebSocket session guards remain intact.
