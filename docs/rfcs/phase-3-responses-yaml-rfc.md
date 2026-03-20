# Phase 3 RFC: Responses YAML That Stays Chatsnack

## Status
Proposed.

## Summary
We are moving chatsnack toward the Responses API while keeping the YAML centered on chats, prompt assets, and notebook exploration.

The main principle is simple:

- `messages:` remains the only primary YAML transcript surface
- `params:` carries runtime configuration, tool availability, and optional exported continuation state
- a message stays `role: text` whenever a plain string is enough
- a message expands into a small block only when that turn carries meaningful extra information
- import/export should do the heavy lifting for files, images, and provider-shaped details
- a normalized internal turn model may grow under the hood while author-facing YAML stays simple

This keeps our saved chats readable, editable, and reusable.

## Phase 3 scope

Phase 3 is example-driven. We are aiming for a small set of strong flows that feel great in notebooks and serialize cleanly.

Target flows for Phase 3:

- plain text Responses chats
- `system` plus `user` plus `assistant` turns, with `developer` accepted as an alias on load
- reasoning summaries and encrypted reasoning folded into assistant turns
- user image attachments
- user file attachments
- image generation outputs
- generated files from tools such as code interpreter
- existing chatsnack local tool-call and tool-response formatting
- continuation via `params.responses.state` when state export is explicitly enabled

Areas we can leave outside the main Phase 3 YAML contract:

- exact provider dumps in the main YAML
- every provider item variant surfaced one-for-one
- transport-perfect replay requirements in the author-facing YAML

If we later want an exact raw provider export for debugging or replay research, that can exist alongside the main YAML.

## Why we are choosing this direction

chatsnack already has a strong authoring philosophy:

- `Chat` is the main abstraction
- YAML is a durable prompt asset
- saved chats should be pleasant to read
- composition through `{text.Name}`, `{chat.Name}`, `include`, and inline variables matters more than provider-shaped payloads

The Responses API gives us richer runtime data, including:

- developer messages
- reasoning summaries
- encrypted reasoning content
- web search sources
- image inputs
- file inputs
- image generation outputs
- generated files
- continuation ids such as `response_id` and `previous_response_id`

Those details are useful. Our YAML should preserve the parts that help us author, review, and continue a chat.

## Design goals

- Keep `Chat` as the center of the design.
- Keep simple chats short.
- Keep advanced Responses support additive.
- Reuse existing chatsnack message and tool-call patterns where we already have them.
- Persist continuation state only when we explicitly ask to export it.
- Make file and image handling easy enough that notebook exploration stays smooth.

## Non-goals

- Mirror the Responses JSON shape field for field in the main YAML.
- Introduce a second primary transcript structure alongside `messages:`.
- Add a top-level `fillings:` section.
- Force exhaustive serialization rules before the example set is working well.

## Internal modeling boundary

The external YAML contract should stay centered on `messages:` and `params:`. Internally, we should expect Phase 3 to introduce a normalized turn model that can bridge richer Responses data into the existing chatsnack surface.

Suggested internal turn fields:

- `role`
- `text`
- `tool_calls`
- `tool_output`
- `images`
- `files`
- `reasoning`
- `encrypted_content`
- `sources`
- `provider_extras`

This internal model is an implementation detail. The author-facing YAML remains the durable contract.

## Canonical YAML shape

```yaml
params:
  model: gpt-5.4
  runtime: responses
  responses:
    store: true
    export_state: true
    text:
      format:
        type: text
      verbosity: medium
    reasoning:
      effort: medium
      summary: auto
    include:
      - reasoning.encrypted_content
      - web_search_call.action.sources
    state:
      response_id: resp_123
      previous_response_id: resp_122
      status: completed

messages:
  - system: Support the user's request.
  - user: What's the current population of Nigeria?
  - assistant:
      reasoning: |
        Searching Wikipedia for population data.
        Clarifying the estimate and final phrasing.
      encrypted_content: gAAAAAB...trimmed...
      text: |
        Nigeria's current population is about 242.4 million; Wikipedia's
        Demographics of Nigeria page lists 242,431,841 (2026 est.).
      sources:
        - title: Demographics of Nigeria
          url: https://en.wikipedia.org/wiki/Demographics_of_Nigeria
```

## Messages stay scalar-first

The default rule is:

- if a turn is only text, use `role: text`
- if a turn carries extra turn-level data, expand it gently

Simple form:

```yaml
messages:
  - system: Respond tersely.
  - user: What is chatsnack?
  - assistant: A chat-oriented prompt library.
```

Expanded assistant form:

```yaml
messages:
  - assistant:
      reasoning: Looking for the most recent source-backed estimate.
      text: Nigeria's current population is about 242.4 million.
      sources:
        - title: Demographics of Nigeria
          url: https://en.wikipedia.org/wiki/Demographics_of_Nigeria
```

We only expand a message when we need to preserve meaningful structure.

## `system` stays canonical, `developer` loads as an alias

Responses makes `developer` a real conversational role. For chatsnack, Phase 3 should treat `system` and `developer` as aliases while keeping `system` as the canonical saved key.

Recommended behavior:

- YAML export writes `system`
- YAML import accepts either `system` or `developer`
- runtime compilation may map `system` to `developer` where provider compatibility requires it

This keeps our saved assets aligned with existing chatsnack ergonomics while allowing Responses-native role handling.

## Fillings stay inline in message text

We do not add a top-level `fillings:` section.

Chatsnack composition already works well when fillings stay inside message text:

```yaml
messages:
  - system: |
      {text.WikiOnlyResearchPolicy}
      Support the user's request.
  - user: What's the current population of {country}?
```

That keeps our YAML aligned with current chatsnack usage.

## Tool formatting stays close to current chatsnack

We already have a chatsnack shape for assistant tool calls and tool responses. We should keep using it for local function-style tools.

```yaml
messages:
  - assistant:
      tool_calls:
        - name: deferred_stock_search
          arguments:
            query: energy stocks
            defer_time_seconds: 30
  - tool:
      tool_call_id: call_123
      content:
        results: []
  - assistant: No matching stocks yet.
```

This pattern already matches the existing message handling in [mixin_messages.py](/Users/matti/Documents/dev/codex/chatsnack/chatsnack/chat/mixin_messages.py).

Provider-native Responses tools should be handled differently:

- availability still lives in `params.tools`
- their useful outputs should usually be folded into the nearest assistant turn
- we do not need to mirror every provider-native intermediate call object into the main YAML

## What belongs in `params`

`params` should hold provider and runtime setup.

That includes:

- `model`
- `runtime`
- `tools`
- `params.responses.text`
- `params.responses.reasoning`
- `params.responses.include`
- `params.responses.store`
- `params.responses.export_state`
- `params.responses.state`

Example:

```yaml
params:
  model: gpt-5.4
  runtime: responses
  tools:
    - type: web_search
      user_location:
        type: approximate
        country: US
      search_context_size: medium
      filters:
        allowed_domains:
          - en.wikipedia.org
    - type: mcp
      server_label: gmail
      connector_id: connector_gmail
      allowed_tools:
        - get_recent_emails
        - search_emails
      require_approval: always
    - type: image_generation
      quality: high
    - type: code_interpreter
      container:
        type: auto
        file_ids: []
  responses:
    store: true
    export_state: true
    include:
      - reasoning.encrypted_content
      - web_search_call.action.sources
      - code_interpreter_call.outputs
    text:
      format:
        type: text
      verbosity: medium
    reasoning:
      effort: medium
      summary: auto
    state:
      response_id: resp_123
      previous_response_id: resp_122
      status: completed
```

## `params.tools` stays the single authoring surface

Phase 3 should keep one place for tool availability: `params.tools`.

There are two execution paths under that surface:

- local function tools, including utensils, keep the existing chatsnack function-tool model
- provider-native Responses tools start as raw dict pass-through definitions

That split matters because provider-native tools such as `web_search`, `image_generation`, `code_interpreter`, and `mcp` run server-side. They do not go through the local `auto_execute` and `auto_feed` loop the same way a local utensil does.

Recommended Phase 3 direction:

- keep local function tools strongly aligned with today's utensil model
- accept raw dicts in `params.tools` for the most common OpenAI provider-native tools
- add typed wrappers later once the common tool set has settled

## Runtime state export should be explicit

By default, YAML export should omit `params.responses.state`.

When we want continuation metadata in the file, we should enable it explicitly:

```yaml
params:
  responses:
    export_state: true
    state:
      response_id: resp_123
      previous_response_id: resp_122
      status: completed
      usage:
        input_tokens: 1200
        output_tokens: 140
        total_tokens: 1340
```

Recommended behavior:

- `export_state` absent or false: do not serialize `state`
- `export_state: true`: serialize `response_id`, `previous_response_id`, `status`, and optional usage
- if `state` is present on load, hydrate it into the chat object

This keeps authoring assets clean by default while still allowing durable continuation snapshots when we want them.

## Attachments, files, and generated assets

For Phase 3, we should give YAML a small, opinionated surface for attachments.

### Proposed turn-level fields

On `user` or `assistant` blocks we can support:

- `text`
- `images`
- `files`
- `reasoning`
- `encrypted_content`
- `sources`
- `tool_calls`

### `images`

Use `images:` for image inputs and image outputs.

Accepted forms in Phase 3:

- `path`
- `url`
- `file_id`

Example user image attachment:

```yaml
messages:
  - user:
      text: Describe the UI problems in this screenshot.
      images:
        - path: ./assets/dashboard.png
```

Example assistant image output:

```yaml
messages:
  - assistant:
      text: Generated one concept image.
      images:
        - file_id: file_img_123
          filename: concept.png
```

### `files`

Use `files:` for non-image file inputs and file outputs.

Accepted forms in Phase 3:

- `path`
- `url`
- `file_id`

Example user file attachment:

```yaml
messages:
  - user:
      text: Summarize this PDF.
      files:
        - path: ./reports/annual-letter.pdf
```

Example assistant file output:

```yaml
messages:
  - assistant:
      text: I created a cleaned CSV.
      files:
        - file_id: file_csv_123
          filename: cleaned-data.csv
```

### Serializer heavy lifting

The library should do the upload and export work for us.

Phase 3 behavior should aim for:

- local `path` inputs upload automatically when needed
- file ids and URLs serialize cleanly on export
- image generation base64 results materialize into a stable image reference for YAML and notebook use
- code interpreter outputs surface as `assistant.files` or `assistant.images` instead of raw provider call objects

This is one of the biggest areas where chatsnack should be opinionated and helpful.

## How Responses concepts fold into YAML

### Reasoning

Reasoning stays attached to the assistant turn it explains.

```yaml
messages:
  - assistant:
      reasoning: |
        Searching the provided material and composing the answer.
      encrypted_content: gAAAAAB...trimmed...
      text: Here is the answer.
```

### Web search

Web search availability belongs in `params.tools`. The source links used by the answer can be folded into `assistant.sources`.

```yaml
messages:
  - assistant:
      text: Nigeria's current population is about 242.4 million.
      sources:
        - title: Demographics of Nigeria
          url: https://en.wikipedia.org/wiki/Demographics_of_Nigeria
```

### Image generation

The image generation tool belongs in `params.tools`. The resulting images belong on the assistant turn.

```yaml
params:
  tools:
    - type: image_generation
      quality: high

messages:
  - user: Generate a cozy library reading room with a corgi.
  - assistant:
      text: Generated one image.
      images:
        - file_id: file_img_123
          filename: cozy-library.png
```

### Code interpreter outputs

The code interpreter tool belongs in `params.tools`. The resulting files and images belong on the assistant turn.

```yaml
params:
  tools:
    - type: code_interpreter
      container:
        type: auto
        file_ids: []
  responses:
    include:
      - code_interpreter_call.outputs

messages:
  - user:
      text: Analyze this CSV and give me a cleaned CSV plus a chart.
      files:
        - path: ./data/sales.csv
  - assistant:
      text: I created a cleaned CSV and a chart.
      files:
        - file_id: file_csv_123
          filename: sales-cleaned.csv
      images:
        - file_id: file_img_456
          filename: sales-chart.png
```

## Mapping rules

| Responses concept | Chatsnack YAML home | Notes |
| --- | --- | --- |
| system or developer input message | `messages: - system:` | export uses `system`; load accepts `developer` as an alias |
| user text | `messages: - user:` | scalar when possible |
| assistant output text | `messages: - assistant:` or `assistant.text` | scalar first |
| reasoning summary | `assistant.reasoning` | fold into assistant turn |
| reasoning encrypted content | `assistant.encrypted_content` | only when requested with `include` |
| web search sources | `assistant.sources` | fold useful links into the answer turn |
| user image attachment | `user.images` | accepts `path`, `url`, or `file_id` |
| user file attachment | `user.files` | accepts `path`, `url`, or `file_id` |
| image generation output | `assistant.images` | serializer should surface stable image refs |
| generated file output | `assistant.files` | serializer should surface stable file refs |
| provider-native tool availability | `params.tools` | raw dict pass-through first for `web_search`, `mcp`, `code_interpreter`, `image_generation` |
| local function tool availability | `params.tools` | keep current utensil/function-tool model |
| local function call request | existing `assistant.tool_calls` shape | keep current chatsnack formatting |
| local function/tool output | existing `tool:` message shape | keep current chatsnack formatting |
| `include` request option | `params.responses.include` | advanced option |
| `store` | `params.responses.store` | response persistence |
| `export_state` | `params.responses.export_state` | gates serialization of runtime continuation state |
| `text.*` options | `params.responses.text` | output controls |
| `reasoning.*` options | `params.responses.reasoning` | reasoning controls |
| `response_id` | `params.responses.state.response_id` | continuation state when export is enabled |
| `previous_response_id` | `params.responses.state.previous_response_id` | continuation state when export is enabled |
| final status | `params.responses.state.status` | optional persisted runtime state |
| usage | `params.responses.state.usage` | optional persisted runtime state |

## Worked examples

### 1. Simple text chat

```yaml
params:
  model: gpt-5.4
  runtime: responses

messages:
  - system: Respond tersely.
  - user: What is chatsnack?
  - assistant: A chat-oriented prompt library.
```

### 2. User image attachment

```yaml
messages:
  - user:
      text: What is wrong with this mockup?
      images:
        - path: ./mockups/checkout-screen.png
  - assistant:
      text: The hierarchy is weak, and the primary action does not stand out.
```

### 3. User file attachment

```yaml
messages:
  - user:
      text: Summarize this PDF.
      files:
        - path: ./reports/annual-letter.pdf
  - assistant:
      text: The letter focuses on long-term capital allocation and insurance float.
```

### 4. Generated image

```yaml
params:
  tools:
    - type: image_generation
      quality: high

messages:
  - user: Generate a gray tabby cat hugging an otter with an orange scarf.
  - assistant:
      text: Generated one image.
      images:
        - file_id: file_img_123
          filename: otter.png
```

### 5. Generated files from code interpreter

```yaml
params:
  tools:
    - type: code_interpreter
      container:
        type: auto
        file_ids: []
  responses:
    include:
      - code_interpreter_call.outputs

messages:
  - user:
      text: Analyze this CSV and give me a cleaned CSV plus a chart.
      files:
        - path: ./data/sales.csv
  - assistant:
      text: I created a cleaned CSV and a chart.
      files:
        - file_id: file_csv_123
          filename: sales-cleaned.csv
      images:
        - file_id: file_img_456
          filename: sales-chart.png
```

### 6. Source-backed lookup with reasoning

```yaml
params:
  model: gpt-5.4
  runtime: responses
  tools:
    - type: web_search
      user_location:
        type: approximate
        country: US
      search_context_size: medium
      filters:
        allowed_domains:
          - en.wikipedia.org
  responses:
    store: true
    include:
      - reasoning.encrypted_content
      - web_search_call.action.sources
    text:
      format:
        type: text
      verbosity: medium
    reasoning:
      effort: medium
      summary: auto

messages:
  - system: |
      {text.WikiOnlyResearchPolicy}
      Support the user's request.
      Restrict sourced claims to en.wikipedia.org.
  - user: What's the current population of Nigeria?
  - assistant:
      reasoning: |
        Searching Wikipedia for population data.
        Clarifying the estimate and final phrasing.
      encrypted_content: gAAAAAB...trimmed...
      text: |
        Nigeria's current population is about 242.4 million; Wikipedia's
        Demographics of Nigeria page lists 242,431,841 (2026 est.).
      sources:
        - title: Demographics of Nigeria
          url: https://en.wikipedia.org/wiki/Demographics_of_Nigeria
```

### 7. Explicit continuation snapshot export

```yaml
params:
  model: gpt-5.4
  runtime: responses
  responses:
    export_state: true
    state:
      response_id: resp_latest
      previous_response_id: resp_prev
      status: completed

messages:
  - system: Continue the draft.
  - user: Add one more paragraph.
```

## Implementation sketch

1. Introduce a normalized internal turn model that bridges YAML import/export and richer Responses data without changing the author-facing YAML contract.
2. Keep `system` canonical on save, accept `developer` on load, and let runtime compilation map roles for provider compatibility.
3. Extend `ChatParams` with a nested `responses` object that can hold `text`, `reasoning`, `include`, `store`, `export_state`, and `state`.
4. Keep `params.tools` as the single authoring surface, with local function tools preserving the existing utensil path and provider-native tools starting as raw dict pass-through.
5. Add turn-level `images` and `files` support for `user` and `assistant` messages.
6. Extend the Responses adapter so reasoning summaries, encrypted reasoning content, web search sources, image generation outputs, and generated files can be folded into the nearest assistant turn when we serialize YAML.
7. Add import/export helpers that translate local paths, URLs, file ids, and generated assets into the simple YAML forms above.
8. Use the worked examples in this RFC as the acceptance targets for Phase 3 notebook usability.

## References

- [Responses vs Chat Completions](https://platform.openai.com/docs/guides/responses-vs-chat-completions)
- [Responses API reference](https://platform.openai.com/docs/api-reference/responses)
- [Conversation state guide](https://platform.openai.com/docs/guides/conversation-state)
- [Reasoning guide](https://platform.openai.com/docs/guides/reasoning)
- [File inputs guide](https://developers.openai.com/api/docs/guides/file-inputs)
- [Image generation guide](https://platform.openai.com/docs/guides/image-generation)
- [Code interpreter guide](https://platform.openai.com/docs/guides/tools-code-interpreter)
- [Web search tool guide](https://platform.openai.com/docs/guides/tools-web-search)
- [MCP tools guide](https://platform.openai.com/docs/guides/tools-connectors-mcp)

## End-User Example Acceptance Criteria

### Example 1: Simple saved prompt asset

```yaml
params:
  model: gpt-5.4
  runtime: responses

messages:
  - system: Respond tersely.
  - user: What is chatsnack?
  - assistant: A chat-oriented prompt library.
```

Acceptance criteria:

- the YAML remains short and readable
- the saved system instruction uses the canonical `system` key
- a plain assistant answer stays in scalar form
- the file works as a reusable prompt asset without runtime state noise

### Example 2: Loading `developer` as an alias

```yaml
messages:
  - developer: Follow the house style guide.
  - user: Draft a release note.
```

Acceptance criteria:

- chatsnack accepts the file on load
- the role is treated the same as `system`
- a later save exports the canonical `system` key
- runtime compilation can still map to provider-compatible roles as needed

### Example 3: Provider-native tool configuration

```yaml
params:
  runtime: responses
  tools:
    - type: web_search
      search_context_size: medium
    - type: image_generation
      quality: high

messages:
  - system: Support the user's request.
  - user: Research the topic and create an illustration.
```

Acceptance criteria:

- `params.tools` accepts the raw provider-native tool dicts
- the tool definitions serialize cleanly without forcing a function-tool wrapper
- provider-native tools stay available to the Responses runtime
- the YAML authoring surface stays the same for end users

### Example 4: Local function tool history

```yaml
messages:
  - assistant:
      tool_calls:
        - name: get_weather
          arguments:
            location: Austin
  - tool:
      tool_call_id: call_123
      content:
        forecast: sunny
  - assistant: It is sunny in Austin.
```

Acceptance criteria:

- local function tools keep the existing chatsnack message format
- tool-call history remains readable in YAML
- tool outputs remain attached to the matching `tool_call_id`
- follow-up assistant text can stay scalar when no extra structure is needed

### Example 5: Explicit continuation snapshot export

```yaml
params:
  runtime: responses
  responses:
    export_state: true
    state:
      response_id: resp_latest
      previous_response_id: resp_prev
      status: completed

messages:
  - system: Continue the draft.
  - user: Add one more paragraph.
```

Acceptance criteria:

- runtime state is omitted unless `export_state: true` is present
- when exported, `response_id`, `previous_response_id`, and `status` serialize in `params.responses.state`
- the file can be reloaded with the same continuation metadata
- users who want clean authoring assets can leave `export_state` unset

### Example 6: Attachments and generated outputs

```yaml
messages:
  - user:
      text: Analyze this CSV and give me a cleaned CSV plus a chart.
      files:
        - path: ./data/sales.csv
  - assistant:
      text: I created a cleaned CSV and a chart.
      files:
        - file_id: file_csv_123
          filename: sales-cleaned.csv
      images:
        - file_id: file_img_456
          filename: sales-chart.png
```

Acceptance criteria:

- user file inputs stay compact in YAML
- generated files and images land on the assistant turn
- the serializer handles upload and export mechanics behind the scenes
- the saved file remains understandable without a raw provider dump
