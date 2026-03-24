# Phase 3 RFC: Responses YAML That Stays Chatsnack

## Status
Proposed.

## Summary
We are moving chatsnack toward the Responses API while keeping the YAML centered on chats, prompt assets, and notebook exploration.

The main principle is simple:

- `messages:` remains the only primary YAML transcript surface
- `params:` carries runtime configuration such as model, runtime, session, tool availability, and optional exported continuation state
- a message stays `role: text` whenever a plain string is enough
- a message expands into a small block only when that turn carries meaningful extra information
- import/export should do the heavy lifting for files, images, and provider-shaped details
- a normalized internal turn model may grow under the hood while author-facing YAML stays simple

This keeps our saved chats readable, editable, and reusable.

## Phase 3 scope

Phase 3 is example-driven. We are aiming for a small set of strong flows that feel great in notebooks and serialize cleanly.

Target flows for Phase 3:

- plain text Responses chats
- saved transport mode via `params.session` when we want WebSocket behavior to round-trip cleanly
- `system` plus `user` plus `assistant` turns, with `developer` accepted as an alias on load
- reasoning summaries and encrypted reasoning folded into assistant turns
- user image attachments
- user file attachments
- image generation outputs
- generated files from tools such as code interpreter
- existing chatsnack local tool-call and tool-response formatting
- continuation metadata via `params.responses.state` when state export is explicitly enabled

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

messages:
  - system: Support the user's request.
  - user: What's the current population of Nigeria?
  - assistant:
      text: |
        Nigeria's current population is about 242.4 million; Wikipedia's
        Demographics of Nigeria page lists 242,431,841 (2026 est.).
      reasoning: |
        Searching Wikipedia for population data.
        Clarifying the estimate and final phrasing.
      encrypted_content: gAAAAAB...trimmed...
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
      text: Nigeria's current population is about 242.4 million.
      reasoning: Looking for the most recent source-backed estimate.
      sources:
        - title: Demographics of Nigeria
          url: https://en.wikipedia.org/wiki/Demographics_of_Nigeria
```

We only expand a message when we need to preserve meaningful structure.

## Normalization rules for expanded turn blocks

Phase 3 should make mixed-content turns canonical on load so save behavior stays predictable.

### Internal normalization

- every loaded message is normalized internally to an expanded object form, even when the source YAML used a scalar `role: text` form
- a scalar source turn becomes the same internal shape as `role: { text: ... }`
- save may collapse that turn back to scalar form only when `text` is the only canonical field that remains after normalization

### Canonical field ordering

Expanded `user` and `assistant` blocks should save fields in this order:

1. `text`
2. `reasoning`
3. `encrypted_content`
4. `sources`
5. `images`
6. `files`
7. `tool_calls`
8. `provider_extras`

### Validation rules

- `system` turns are text-only after normalization
- `user` turns may contain `text`, `images`, `files`, and `provider_extras`
- `assistant` turns may contain `text`, `reasoning`, `encrypted_content`, `sources`, `images`, `files`, `tool_calls`, and `provider_extras`
- `tool` turns keep the existing chatsnack `tool:` message shape and are outside this expanded-block ordering rule
- empty canonical fields are omitted on save; serializers should not emit placeholder empty lists or `text: ""` unless a future feature requires that distinction explicitly

### Mixed-content serialization

- if any non-text canonical field is present, the serializer writes the turn as an expanded mapping
- mixed turns keep all canonical data in one block rather than splitting attachments or reasoning into separate synthetic messages
- attachments, reasoning, and sources are folded into the same expanded turn and emitted in canonical field order

### Unknown provider extras

- unknown top-level fields on an expanded turn should be moved into `provider_extras` on load rather than dropped silently
- explicitly authored `provider_extras` should survive round-trip saves
- provider-derived extras may be omitted in authoring fidelity, should survive continuation fidelity when useful, and should survive diagnostic fidelity when available, following the fidelity rules below

### Round-trip guarantees

- after one load and canonical save, repeated save cycles with the same fidelity mode should be idempotent in message ordering and field ordering
- pure text turns may collapse back to scalar form on save
- mixed-content turns should remain expanded after canonicalization
- continuation and diagnostic fidelity should preserve non-canonical data that has a defined home such as `provider_extras` or `params.responses.provider_dump`

### Ambiguous-case examples

Example: assistant text plus attachments and reasoning always saves as one expanded block.

```yaml
messages:
  - assistant:
      text: I created a cleaned CSV and a chart.
      reasoning: Grouped the rows before generating the chart.
      files:
        - file_id: file_csv_123
          filename: sales-cleaned.csv
      images:
        - file_id: file_img_456
          filename: sales-chart.png
```

Example: a source file that arrives with fields out of order is re-saved in canonical order.

```yaml
# loaded source
messages:
  - assistant:
      images:
        - file_id: file_img_456
      text: Generated one chart.
      reasoning: Summarized the table first.

# canonical save
messages:
  - assistant:
      text: Generated one chart.
      reasoning: Summarized the table first.
      images:
        - file_id: file_img_456
```

Example: unknown provider fields are preserved through `provider_extras`.

```yaml
# loaded source
messages:
  - assistant:
      text: Here is the answer.
      debug_trace:
        cache_hit: true

# canonical internal home and save target when fidelity keeps extras
messages:
  - assistant:
      text: Here is the answer.
      provider_extras:
        debug_trace:
          cache_hit: true
```

## `system` stays canonical, `developer` loads as an alias

Responses makes `developer` a real conversational role. For chatsnack, Phase 3 should treat `system` and `developer` as aliases while keeping `system` as the canonical saved key.

Recommended behavior:

- YAML export writes `system`
- YAML import accepts either `system` or `developer`
- runtime compilation may map `system` to `developer` where provider compatibility requires it

This keeps our saved assets aligned with existing chatsnack ergonomics while allowing Responses-native role handling.

## Normative parsing and save-order rules

Phase 3 should make the `system` and `developer` alias behavior deterministic.

Required rules:

- if a transcript contains only `system`, load it as normal and save it back as `system`
- if a transcript contains only `developer`, load it into the canonical internal `system` role and save it back as `system`
- if a transcript contains both `system` and `developer`, load both turns as separate internal `system` turns in the same relative order they appeared in the file
- load never collapses adjacent alias turns into one message just because their canonical internal role is the same
- save preserves turn order exactly as loaded or edited, with each aliased turn emitted as its own `system` entry
- load followed by save produces deterministic ordering and canonical role spelling even when the source file mixed aliases

Internally, the role label is normalized to one canonical role for chatsnack's message model. The turn boundaries remain distinct.

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
- `session`
- `tools`
- `params.responses.text`
- `params.responses.reasoning`
- `params.responses.include`
- `params.responses.store`
- `params.responses.export_state`
- `params.responses.export_diagnostics`
- `params.responses.state`
- `params.responses.provider_dump`

Example:

`session` stays a top-level chatsnack runtime switch because Phase 2a made it the public transport selector. Nested `params.responses` holds Responses-specific request and export options.

```yaml
params:
  model: gpt-5.4
  runtime: responses
  session: inherit
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

That split matters because provider-native tools such as `web_search`, `image_generation`, `code_interpreter`, and `mcp` run server-side. They do not go through the local `auto_execute` and `auto_feed` loop the same way a local utensil does. Saved YAML should still treat `params.tools` as durable tool availability for the chat, and the runtime may resend those tools on each provider turn so behavior stays stable across HTTP Responses and WebSocket Responses.

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
- if `state` is present on load, hydrate it into chat runtime metadata
- if a later run has a compatible session and store policy, the runtime may continue from the exported ids directly
- if a later run is on a fresh connection without persisted state, the runtime may need full local context replay even when exported ids are present

Phase 2a makes the continuation rules narrower than a plain `response_id` snapshot. Same-socket continuation with `session: inherit` can work with `store: false` while the live connection exists. Fresh-connection or reloaded-chat continuation depends on persisted state or full local context replay. `params.responses.state` is useful runtime metadata and a best-effort continuation hint. It does not guarantee that a reloaded file can continue from `response_id` alone in every mode.

## Fidelity levels

Phase 3 should make the export fidelity explicit so we can keep default YAML readable while still offering deeper persistence when we need it.

The three levels are:

- Authoring fidelity: the default readable YAML for prompt assets and notebook reuse
- Continuation fidelity: enabled by `params.responses.export_state: true` so continuation metadata survives a save/load cycle
- Diagnostic fidelity: optional raw-provider export mode, recommended as `params.responses.export_diagnostics: true`, for debugging, replay research, or provider-specific inspection

Non-canonical but still valuable turn-level fields should land in `assistant.provider_extras` when they belong to a specific assistant turn. Completed provider response snapshots should land in `params.responses.provider_dump` in diagnostic mode. Diagnostic fidelity should stay out of raw WebSocket event transcripts and session transport logs so saved YAML remains deterministic and readable.

| Responses concept | Authoring fidelity | Continuation fidelity | Diagnostic fidelity | YAML home |
| --- | --- | --- | --- | --- |
| assistant text | MUST persist | MUST persist | MUST persist | scalar `assistant:` or `assistant.text` |
| system or developer instruction turns | MUST persist | MUST persist | MUST persist | canonical `system` entries in `messages:` |
| user text, images, and files | MUST persist | MUST persist | MUST persist | `user`, `user.images`, `user.files` |
| local function tool calls and tool outputs | MUST persist | MUST persist | MUST persist | existing `assistant.tool_calls` and `tool:` shapes |
| reasoning summary | SHOULD persist when available | SHOULD persist when available | SHOULD persist when available | `assistant.reasoning` |
| encrypted reasoning content | MAY be dropped | SHOULD persist when available | MUST persist when available | `assistant.encrypted_content` |
| source links and citations | SHOULD persist when available | SHOULD persist when available | SHOULD persist when available | `assistant.sources` |
| generated images and files | MUST persist | MUST persist | MUST persist | `assistant.images` and `assistant.files` |
| response continuation state (`response_id`, `previous_response_id`, `status`, `usage`) | MAY be dropped | MUST persist | MUST persist | `params.responses.state` |
| provider-native tool internals | MAY be dropped | MAY be dropped | MUST persist when available | `assistant.provider_extras` |
| completed provider response snapshot | MAY be dropped | MAY be dropped | MUST persist | `params.responses.provider_dump` |
| other non-canonical provider metadata | MAY be dropped | SHOULD persist when useful | MUST persist when available | `assistant.provider_extras` |

These rules let us keep the default file shaped like chatsnack while still giving advanced exports a clear place to put extra fidelity.

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
- `provider_extras`

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
      text: Here is the answer.
      reasoning: |
        Searching the provided material and composing the answer.
      encrypted_content: gAAAAAB...trimmed...
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
| provider-native tool internals | `assistant.provider_extras` | optional in readable modes, required in diagnostic mode when available |
| completed provider response snapshot | `params.responses.provider_dump` | diagnostic fidelity only; excludes raw WebSocket event transcripts |
| provider-native tool availability | `params.tools` | raw dict pass-through first for `web_search`, `mcp`, `code_interpreter`, `image_generation` |
| local function tool availability | `params.tools` | keep current utensil/function-tool model |
| local function call request | existing `assistant.tool_calls` shape | keep current chatsnack formatting |
| local function/tool output | existing `tool:` message shape | keep current chatsnack formatting |
| `include` request option | `params.responses.include` | advanced option |
| `session` | `params.session` | chatsnack transport mode: unset, `inherit`, or `new` |
| `store` | `params.responses.store` | response persistence |
| `export_state` | `params.responses.export_state` | gates serialization of runtime continuation state |
| `export_diagnostics` | `params.responses.export_diagnostics` | gates diagnostic fidelity fields |
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
  session: inherit

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
      text: |
        Nigeria's current population is about 242.4 million; Wikipedia's
        Demographics of Nigeria page lists 242,431,841 (2026 est.).
      reasoning: |
        Searching Wikipedia for population data.
        Clarifying the estimate and final phrasing.
      encrypted_content: gAAAAAB...trimmed...
      sources:
        - title: Demographics of Nigeria
          url: https://en.wikipedia.org/wiki/Demographics_of_Nigeria
```

### 7. Explicit continuation snapshot export

```yaml
params:
  model: gpt-5.4
  runtime: responses
  session: new
  responses:
    store: true
    export_state: true
    state:
      response_id: resp_latest
      previous_response_id: resp_prev
      status: completed

messages:
  - system: Continue the draft.
  - user: Add one more paragraph.
```

## Serializer and parser targets

### `chatsnack/yamlformat.py`

The serializer target should:

- emit the canonical `system` key on save
- round-trip `params.session` cleanly when it is set
- preserve message ordering exactly, including separate turns that loaded as `system` and `developer`
- support the three fidelity levels with deterministic field ordering for each mode
- collapse text-only turns back to scalar form only when no other canonical turn fields remain
- write mixed-content turns as expanded mappings in the canonical field order from this RFC
- write `params.responses.state` only when `export_state: true`
- write `params.responses.provider_dump` only when `export_diagnostics: true`
- place turn-scoped non-canonical data into `assistant.provider_extras` instead of spilling raw provider shapes into the main transcript

### `chatsnack/chat/mixin_messages.py`

The parser target should:

- accept `developer` as an alias for `system`
- normalize scalar turns into the same internal expanded-turn object shape used for mixed-content blocks
- normalize both roles to the canonical internal `system` role while preserving separate turn boundaries
- preserve transcript ordering exactly when both aliases appear in the same file
- move unknown expanded-turn fields into `provider_extras` instead of dropping them silently
- avoid accidental merging of adjacent turns that happen to share the same canonical internal role after normalization
- hydrate `assistant.provider_extras`, `params.responses.state`, and optional `params.responses.provider_dump` when those fields are present

## Tests

Phase 3 should add serializer and parser tests that cover:

- deterministic round-trip output for authoring fidelity exports
- deterministic round-trip output for continuation fidelity exports with `export_state: true`
- deterministic round-trip output for diagnostic fidelity exports when `export_diagnostics: true`
- round-trip behavior for `params.session` when it is unset, `inherit`, and `new`
- scalar text turns expanding internally and collapsing back to scalar form when no extra fields exist
- mixed-content turns saving in canonical field order and staying expanded after canonicalization
- loading a mixed `system` and `developer` transcript without collapsing turn count
- saving a mixed-alias transcript back out as ordered `system` turns
- preserving assistant turn ordering and data placement for `reasoning`, `encrypted_content`, `sources`, generated assets, and `provider_extras`
- moving unknown top-level expanded-turn fields into `provider_extras` on load
- keeping non-canonical provider-native tool internals out of the main transcript unless diagnostic fidelity is enabled
- keeping diagnostic provider dumps to completed response data rather than raw WebSocket event transcripts
- checking the main save/load examples across `chat_completions`, HTTP `responses`, and WebSocket `responses` where the user-facing YAML should behave the same

## Implementation sketch

1. Introduce a normalized internal turn model that bridges YAML import/export and richer Responses data without changing the author-facing YAML contract.
2. Keep `system` canonical on save, accept `developer` on load, normalize both to one internal role, and preserve distinct turn boundaries and ordering.
3. Add `session` to top-level params and allow `params.responses` to begin as a nested dict-shaped config surface that can hold `text`, `reasoning`, `include`, `store`, `export_state`, `export_diagnostics`, `state`, and `provider_dump`. Typed wrappers can follow later if they prove useful.
4. Keep `params.tools` as the single authoring surface, with local function tools preserving the existing utensil path and provider-native tools starting as raw dict pass-through.
5. Add turn-level `images`, `files`, and `provider_extras` support for `user` and `assistant` messages where appropriate.
6. Extend the Responses adapter so reasoning summaries, encrypted reasoning content, web search sources, image generation outputs, generated files, and useful provider extras can be folded into the nearest assistant turn when we serialize YAML, while whole-response diagnostic dumps stay scoped to completed response snapshots.
7. Update `chatsnack/yamlformat.py` and `chatsnack/chat/mixin_messages.py` to enforce the fidelity rules and deterministic alias normalization behavior in this RFC.
8. Add import/export helpers that translate local paths, URLs, file ids, and generated assets into the simple YAML forms above.
9. Use the worked examples and round-trip tests in this RFC as the acceptance targets for Phase 3 notebook usability, with cross-runtime checks limited to the overlapping YAML contract rather than every Responses-only field.

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

### Example 2: Saving an explicit transport choice

```yaml
params:
  runtime: responses
  session: inherit

messages:
  - system: Keep the reply short.
  - user: Give me one sentence on reusable prompts.
```

Acceptance criteria:

- `params.session` can be saved explicitly when we want a WebSocket transport choice to round-trip
- if `session` is omitted in a different file, normal HTTP Responses remains the default
- the saved prompt still reads like a normal chatsnack chat asset

### Example 3: Loading `developer` as an alias

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

### Example 4: Provider-native tool configuration

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

### Example 5: Local function tool history

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

### Example 6: Explicit continuation snapshot export

```yaml
params:
  runtime: responses
  session: new
  responses:
    store: true
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
- direct continuation from the exported ids depends on the saved session and store policy
- fresh-connection recovery may still replay full local context when persisted state is unavailable
- users who want clean authoring assets can leave `export_state` unset

### Example 7: Attachments and generated outputs

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



