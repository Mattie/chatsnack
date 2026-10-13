# Changelog

Major changes reconstructed from the public `master` history.
Tagged versions use their tag dates and commit ranges. Untagged versions use the
first `master` commit carrying that package version. Intervening changes are
grouped into the next recorded version; dates describe git history rather than
verified package publication dates.

## 0.10.0 -- 2026-10-13

- Add Muse Wonder AUTO defaults: `model="muse-wonder-1.0"` supplies Meta's endpoint
  and `MODEL_API_KEY` when connection settings are omitted.
- Preserve explicit connection and runtime choices, including provider binding
  through copies, continuations, and saved Chat loading.
- Request encrypted reasoning for Meta replay. Keep saved history intact while
  warning and omitting unusable reasoning from generated stateless requests.
- Add Wonder reasoning advisories, a notebook, and provider documentation.

## 0.9.3 -- 2026-10-12

- Support local `@utensil async def` functions and other awaitable results through
  async Chat calls and manual async dispatch. Preserve sequential tool ordering,
  automatic follow-up budgets, and cancellation behavior.
- Keep live Python callable bindings when copying prompts, without deep-copying
  the service resources they own.
- Raise an actionable error when synchronous manual dispatch receives an async
  result, instead of treating the awaitable as the tool's answer.

## 0.9.2 -- 2026-09-29

- Add known-model support for GPT-6 Sol, GPT-6 Luna, and GPT-6.1 Sol, with model
  reasoning capabilities and advisory pass-through validation.
- Forward authored `reasoning_effort="none"` through Chat Completions.
- Improve documentation typography and API reference layout.

## 0.9.1 -- 2026-09-22

- Expand the bundled chatsnack fluency guidance with Sampler and Question
  authoring, saved assets, typed results, and filling composition patterns.

## 0.9.0 -- 2026-09-22

- Add `Sampler`, reusable `Question` assets, and consistent `Sample` results for
  typed yes/no, choice, and score judgments. Include the TypeSafe SDK in the
  standard install.
- Support saved Sampler and Question YAML, batches, and named result fillings
  that compose judgments into ordinary Chats.
- Preserve portable conversation history across save/load, import/export, and
  replay, including reasoning, tool calls, attachments, and provider metadata.
- Add GPT-6 Astra baseline support and model-specific request advisories.
- Add the Sampler notebook, web examples, and Mad Hacker game.

## 0.8.1 -- 2026-09-03

- Expose `resolve_fillings_a()` for resolving a finite set of named fillings
  directly, using the same expansion engine as normal Chat calls.
- Bound direct resolution by depth, expansions, and Chat calls; require explicit
  `allow_chat=True` before evaluating saved Chat fillings, including nested ones.
- Preserve explicit values, formatter behavior, and literal inserted data while
  enforcing resolver authority and cancellation cleanup.

## 0.8.0 -- 2026-08-28

- Add authored `base_url` and `api_key_env` connection settings for
  OpenAI-compatible providers, including OpenRouter and Azure OpenAI v1.
- Keep endpoint, captured credentials, and transport bound to a Chat's lineage
  through copy, continuation, load, and reset.
- Preserve runtime and authored endpoint precedence, and reject conflicting
  legacy endpoint configuration.
- Pass temperature through without automatic local reasoning-model warnings.

## 0.7.0 -- 2026-08-25

- Keep generated images and files as durable `ChatFile` assets, exposed through
  `.images` and `.files`, reusable in later Chats and after offline reload.
- Add the native Apply Patch utensil and an Aiconographer example using generated
  assets and local tools.
- Update GPT reasoning capability profiles and keep rich Chat text views readable.
- Refresh legacy model examples and documentation styling.

## 0.6.4 -- 2026-08-05

- Add `Chat.last_call_usage` to aggregate provider completions across one public
  `chat()` or `chat_a()` call, including automatic tool follow-ups.
- Expose `CallUsage`, `ResponseUsage`, and `UsageCounts`, preserving reported
  token counts, provider payloads, and partial usage when a call fails.

## 0.6.3 -- 2026-07-15

- Allow a positive integer `auto_feed` cycle budget for longer local-utensil
  workflows; preserve the existing five-cycle default and disabled behavior.
- Upgrade persistence to snapclass `0.2.0`.

## 0.6.2 -- 2026-07-02

- Harden sync and async WebSocket retries for connection-opening failures,
  handshake timeouts, and retryable provider errors.
- Reconnect on connection-limit errors before output; fail fast on provider
  validation and authentication errors, and do not retry after partial output.

## 0.6.1 -- 2026-07-02

- Improve WebSocket completion retries and recovery before streamed output.
- Package chatsnack fluency guidance with the library.
- Correct README documentation of the default Responses/WebSocket workflow.

## 0.6.0 -- 2026-06-25

- Migrate Chat and Text persistence from datafiles to snapclass while preserving
  readable YAML/TXT assets, saved names, and chatsnack base-directory behavior.
- Add trusted package publishing and release verification workflows.

## 0.5.1 -- 2026-06-23

- Make Responses over WebSocket with `session="inherit"` the default Chat runtime,
  retaining explicit HTTP Responses and Chat Completions choices.
- Expand YAML support for developer messages, mixed content, attachments,
  Responses options, and richer assistant turns.
- Accept `files=` and `images=` directly at query time, upload local attachments,
  and preserve rich provider outputs in continued Chats.
- Bring local functions, grouped namespaces, and hosted tools together through
  `utensils=[...]`, with compact YAML and reasoning authoring support.
- Fix function-tool schema normalization, namespace replay, continuation behavior,
  async WebSocket call deduplication, and request options during auto-feed.
- Add the documentation site and notebook-derived test coverage.
- Raise the minimum Python version to **3.11**.

## 0.5.0 -- 2026-03-24

- Add selectable Chat Completions, HTTP Responses, and WebSocket Responses
  runtimes while retaining ordinary `ask()`, `chat()`, and listener authoring.
- Use the official OpenAI SDK's `responses.connect()` for WebSocket sessions,
  with sync/async streaming, tool calls, session reuse, and recovery.
- Preserve runtime, profile, and continuation ownership when creating continued
  Chats; keep one-shot calls from inheriting unintended continuation state.
- Normalize runtime metadata and improve listener completion and error handling.

## 0.4.6 -- 2026-03-10

- Refresh missing-model fallback references to `gpt-5-chat-latest` across ordinary
  requests, streaming, and utensil follow-ups.

## 0.4.5 -- 2025-06-29

- Add `AiClient.base_url` configuration for alternative OpenAI-compatible
  endpoints.

## 0.4.4 -- 2025-05-24

- Add `auto_feed` to execute local tool results and continue the model exchange
  automatically.
- Improve utensil response handling and serialization.
- Fix Windows path comparisons and saved-asset deletion behavior.

## 0.4.0 -- 2025-03-15

- Introduce utensils for Python function tools, including tool declarations,
  execution, result handling, and YAML serialization.

## 0.3.0 -- 2025-02-03

- Refresh model parameter compatibility, including reasoning-model token budgets
  and sampling restrictions.
- Improve the `model` authoring property and deprecated `engine` compatibility;
  translate legacy `max_tokens` into `max_completion_tokens`.

## 0.2.0 -- 2023-11-14

- Migrate to the OpenAI Python SDK v1 client interfaces, including synchronous
  and asynchronous OpenAI and Azure clients.
- Introduce `model` and `seed` parameters as the API moves away from `engine`.

## 0.1.7 -- 2023-06-15

- Broaden retryable API errors and add randomized retry delays.
- Improve assistant message preparation and remove the preliminary `ready` state
  from streaming response handling.

## 0.1.6 -- 2023-05-27

- Add Azure OpenAI Service support and deployment configuration.
- Accept `engine` in Chat construction and return the response when converting a
  Chat to a string.

## 0.1.5 -- 2023-05-12

- Add initial streamed Chat responses through `listen()` and `listen_a()`.

## 0.1.4 -- 2023-05-07

- Fix response-pattern matching for multiline responses.

## 0.1.3 -- 2023-05-03

- Add response filtering through regex patterns or prefix/suffix delimiters.
- Fix introspection compatibility across Python versions.

## 0.1.2 -- 2023-04-23

- Introduce Chat authoring with `ask()`, `chat()`, and terse message chaining.
- Save and reload YAML prompt assets, compose saved Chat and Text fillings, and
  provide reusable snack packs and introductory notebooks.
