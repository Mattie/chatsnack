# Phase 4 RFC: Responses/WebSocket Becomes the Default Runtime

## Status
Proposed.

## Summary
Phase 4 should make the modern Responses stack feel like the default chatsnack experience.

The main moves are:

- `Chat()` with no explicit runtime choice should default to the Responses runtime over WebSocket with `session="inherit"`.
- `CHATSNACK_DEFAULT_RUNTIME` should provide a process-level escape hatch, including a value that restores the legacy Chat Completions default.
- `params.responses.reasoning` should become the canonical home for reasoning request options, with a smart implicit default for reasoning-capable models.
- `params.tools` should stay the single authoring surface for built-in OpenAI tools, and the saved YAML should move to a compact chatsnack-shaped tool syntax.
- If `tool_search` is present, searchable tool surfaces should default to effective `defer_loading: true` unless they explicitly opt out with `defer_loading: false`.
- Phase 4 should assume PR 47, or equivalent rich assistant-field folding work, is available before the runtime-default flip lands.

## Why this phase is timely

The earlier phases already built most of the needed foundation:

- Phase 2 and Phase 2a gave us the official SDK-backed Responses WebSocket transport.
- Phase 3 defined the YAML contract for Responses-era chats.
- Phase 3A improved attachment ergonomics at the query boundary.
- PR 47 closes an important runtime gap by folding richer Responses output into assistant turns across HTTP and WebSocket paths.

The remaining friction is concentrated in defaults and configuration:

- the common path still starts on `ChatCompletionsAdapter`
- README and notebook examples keep repeating `runtime="responses"`
- `params.responses.reasoning` exists, though it still behaves like a mostly raw dict
- `params.tools` accepts provider-native tools, though the author-facing syntax is still too close to provider JSON
- `tool_search` is now part of the official tool surface and deserves first-class planning

Phase 4 should turn the implemented runtime work into the everyday default and tighten the configuration surface around it.

## Design goals

- Make the implicit `Chat()` path land on the modern runtime.
- Keep explicit runtime choices available and predictable.
- Preserve the existing chatsnack shape: `Chat`, YAML assets, concise notebook flows.
- Keep one authoring surface for tool availability.
- Keep saved YAML readable and compact.
- Keep advanced tool and reasoning configuration additive to the common path.
- Keep tool and reasoning config forward-compatible with OpenAI's fast-moving schema surface.
- Keep saved YAML readable while still letting advanced users pin behavior explicitly.

## Non-goals

- Removing `ChatCompletionsAdapter`.
- Replacing `params.tools` with a second built-in-tool section.
- Freezing every tool field into a hardcoded schema that must be updated on every API change.
- Coupling the runtime-default flip to a default-model change.
- Redesigning the Phase 3 transcript format again.

## Assumed base branch

Phase 4 should assume these pieces are already in place:

- [phase-2-responses-websocket-rfc.md](./phase-2-responses-websocket-rfc.md)
- [phase-2a-responses-websocket-sdk-rfc.md](./phase-2a-responses-websocket-sdk-rfc.md)
- [phase-3-responses-yaml-rfc.md](./phase-3-responses-yaml-rfc.md)
- [phase-3-natural-attachments-plan.md](../projects/phase-3-natural-attachments-plan.md)
- PR 47 or equivalent rich-output integration work

That last point matters because Phase 4 depends on assistant turns already being able to preserve reasoning, sources, generated files, and generated images across both Responses transports.

## Current state in our code

Today the runtime boundary behaves like this:

- [chatsnack/chat/__init__.py](../../chatsnack/chat/__init__.py) defaults `Chat()` to `ChatCompletionsAdapter`
- explicit `runtime="responses"` or `runtime_selector="responses"` selects the Responses family
- `session="inherit"` and `session="new"` select the WebSocket transport inside the Responses family
- `params.responses` is forwarded to the Responses API after stripping chatsnack-internal keys
- `params.tools` already accepts provider-native tool dicts alongside function tools

That means the implementation pieces are close. The main missing work is policy:

- how implicit runtime selection should work
- how the env override should interact with explicit runtime/session choices
- which reasoning defaults we want
- how much structure we want around built-in tool definitions

## Grounding from current OpenAI docs

As of March 27, 2026, the official docs show:

- Responses WebSocket mode is the supported persistent Responses transport and is implemented in the official Python SDK via `client.responses.connect()`.
- `tool_search` is a built-in tool and currently requires `gpt-5.4` or later.
- web search currently documents `filters.allowed_domains`, `user_location`, `external_web_access`, and `include=["web_search_call.action.sources"]`.
- file search currently documents `vector_store_ids`, `max_num_results`, metadata filters, and `include=["file_search_call.results"]`.
- reasoning summaries are opt-in through `reasoning.summary`.
- encrypted reasoning content is opt-in through `include=["reasoning.encrypted_content"]`.
- supported reasoning effort and summary values vary by model family and sometimes by exact model.
- OpenAI's tool-search examples use provider-shaped namespace tool definitions and may set `parallel_tool_calls: false` for simpler serialized flows.

These details support a model-aware, pass-through-friendly Phase 4 design with a compact chatsnack authoring layer on top of the provider schema.

## Proposed default-runtime policy

### The main rule

The implicit path should change:

- `Chat()` with no explicit runtime choice should resolve to Responses over WebSocket with `session="inherit"`.

The explicit paths should stay stable:

- `Chat(runtime="responses")` should keep today's explicit Responses behavior
- `Chat(runtime="chat_completions")` should keep the legacy path
- explicit `session="inherit"` or `session="new"` should still force the Responses WebSocket path

This keeps the migration focused on the default experience while preserving the behavior of code that already opted into a runtime family intentionally.

### Runtime resolution order

Phase 4 should resolve runtime in this order:

1. Explicit injected runtime object
2. Explicit `runtime=` or `runtime_selector=`
3. Explicit `params.runtime`
4. Explicit `session=` when runtime is otherwise unset
5. `CHATSNACK_DEFAULT_RUNTIME`
6. Library default

Once the runtime family is chosen, transport selection should work like this:

- if `session` is explicit, honor it
- if runtime choice came from an explicit user runtime and `session` is absent, preserve today's behavior
- if runtime choice came from the env var or library default and `session` is absent, use the implicit session policy for that default

This gives us a clean migration path:

- implicit path changes
- explicit path stays familiar

### `CHATSNACK_DEFAULT_RUNTIME`

Phase 4 should use one string-valued environment variable:

```text
CHATSNACK_DEFAULT_RUNTIME
```

Recommended values:

- `responses_websocket`
- `responses_ws`
- `responses_http`
- `chat_completions`

Recommended behavior:

- unset -> library default of `responses_websocket`
- `responses_websocket` / `responses_ws` -> implicit `runtime="responses"` plus implicit `session="inherit"`
- `responses_http` -> implicit `runtime="responses"` plus implicit `session=None`
- `chat_completions` -> implicit `ChatCompletionsAdapter`
- invalid value -> warn once and fall back to `responses_websocket`

This shape gives us one migration escape hatch today and leaves room for future default-policy tuning without adding a second env var.

### Session policy for the implicit default

The implicit Responses default should use:

```yaml
params:
  runtime: responses
  session: inherit
```

at runtime resolution time, even when those fields are omitted from YAML.

Why `inherit` is the right default:

- it uses the lower-latency persistent path that Phase 2a was built around
- it keeps `chat()` continuation natural
- it aligns with chatsnack's conversation-centered philosophy
- it keeps `store=False` viable for same-socket continuation

### Explicit portability in YAML

Phase 4 should preserve two authoring modes:

- implicit/default mode: runtime and session stay omitted when the user never set them
- pinned mode: `params.runtime` and `params.session` serialize when the author wants the file to carry explicit transport intent

That means files without `runtime` and `session` can intentionally follow process defaults. Authors who need reproducibility across machines can pin both fields in YAML.

## Model compatibility note

Phase 4 should stay decoupled from the default model decision.

Current reality:

- the codebase still defaults `model` to `gpt-5-chat-latest`
- official docs currently say `tool_search` requires `gpt-5.4` or later

So the Phase 4 plan should treat model support as a capability gate:

- built-in tool serialization should work independently of the default model
- runtime validation should raise clear errors when a chosen model does not support a chosen built-in tool
- a default-model migration can be discussed separately if we want deeper `tool_search` coverage in the out-of-the-box path

## Reasoning configuration design

### Canonical authoring surface

Phase 4 should keep reasoning request options under:

```yaml
params:
  responses:
    reasoning:
      effort: low
      summary: auto
    include:
      - reasoning.encrypted_content
```

Reasoning outputs should keep the Phase 3 homes:

- `assistant.reasoning`
- `assistant.encrypted_content`

### What Phase 4 should treat as reasoning-related config

The reasoning-related surface spans two places:

- `params.responses.reasoning`
- `params.responses.include`

Canonical keys we should document and support clearly:

- `reasoning.effort`
- `reasoning.summary`
- `include: ["reasoning.encrypted_content"]`

### Smart default

Recommended implicit policy:

- if the selected model is reasoning-capable and the user did not set `params.responses.reasoning`, inject `{"effort": "low"}` at request time
- if the user supplied a `reasoning` dict, forward it as authored
- leave `summary` unset by default
- leave `reasoning.encrypted_content` out of `include` by default

Why this is the right default:

- `low` gives reasoning-capable models enough room for tool planning and multi-step work without pushing every request into a high-cost profile
- omitting `summary` keeps the common chatsnack path terse
- omitting encrypted reasoning keeps saved YAML cleaner unless the user has an explicit continuation or diagnostic reason to include it

### Serialization rules

Phase 4 should serialize reasoning config with these rules:

- save `params.responses.reasoning` only when the author set it explicitly or when the chat was saved in a "pinned defaults" mode we may add later
- keep `assistant.reasoning` scalar-first when a single string summary is enough
- keep `assistant.encrypted_content` gated by fidelity, following the Phase 3 rules
- preserve unknown keys under `params.responses.reasoning` instead of dropping them

That last rule matters because OpenAI's reasoning config surface may keep growing.

### Validation strategy

Validation should be capability-aware and warning-oriented.

Recommended behavior:

- maintain a lightweight model-capability table for the common built-in defaults we care about
- warn when an obviously unsupported `effort` or `summary` value is selected for a known model
- forward the authored value anyway unless chatsnack has a deterministic local reason it cannot work

This is the pragmatic balance because official model support varies:

- effort values differ across GPT-5, GPT-5.1, GPT-5.4, GPT-5 pro, and o-series models
- summary options also vary by model family

### Convenience aliases

Phase 4 can add Python-side convenience without changing the YAML home:

- `chat.reasoning_effort`
- `chat.reasoning_summary`

These should map into `params.responses.reasoning` internally.

The YAML contract stays nested under `params.responses.reasoning`.

## Built-in OpenAI tools design

### Philosophy for tool YAML

Phase 3 already set the authoring direction for chatsnack YAML:

- a saved chat should stay pleasant to read
- text-first cases should stay compact
- richer structure should expand only when it carries useful meaning
- Python-shaped authoring should stay close to Python

Phase 4 should apply those same ideas to `params.tools`.

That means:

- bare tool names should stay bare when no extra config is needed
- known built-ins should save as small chatsnack-shaped mappings
- namespace tools should read like authored prompt assets instead of provider JSON
- richer tool schemas should have an explicit escape hatch

### One authoring surface

Phase 4 should keep:

```yaml
params:
  tools: [...]
```

as the single authoring surface for:

- local function tools
- built-in OpenAI tools
- namespaces
- MCP tools

That aligns with the Phase 3 direction and keeps tool availability easy to inspect.

### Tool categories in Phase 4

Phase 4 should divide tool handling into two execution categories.

Hosted built-in tools:

- `web_search`
- `file_search`
- `code_interpreter`
- `image_generation`
- hosted `tool_search`
- hosted MCP / connectors

Client-executed built-in tools:

- `tool_search` with `execution: client`
- future built-ins whose execution loop lives in the application process

Hosted tools mainly need:

- request-time pass-through
- YAML round-trip behavior
- rich output folding into assistant turns

Client-executed tools also need:

- a callback boundary in Python
- runtime handling for provider-native tool call / tool output items

### Compact authoring tiers

Phase 4 should support four authoring tiers for built-in tools.

#### Tier 1: Bare scalar for zero-config tools

```yaml
params:
  tools:
    - tool_search
    - code_interpreter
```

This compiles to:

- `{"type": "tool_search"}`
- `{"type": "code_interpreter"}`

#### Tier 2: Single-key mapping for configured built-ins

```yaml
params:
  tools:
    - web_search:
        filters:
          allowed_domains:
            - pubmed.ncbi.nlm.nih.gov
        external_web_access: true
    - file_search:
        vector_store_ids:
          - vs_123
        max_num_results: 4
```

This compiles to provider dicts with `type` injected from the mapping key.

#### Tier 3: Namespace block with keyed child tools

```yaml
params:
  tools:
    - crm: CRM tools for customer lookup and order management.
      tools:
        - get_customer: Look up one customer by ID.
          customer_id: str
        - list_open_orders: List open orders for a customer ID.
          customer_id: str
    - tool_search
```

This compiles to a provider namespace tool with child function tools.

#### Tier 4: Structured escape hatch

When the inline compact form is not expressive enough, Phase 4 should support `description`, `args`, `required`, and `defer_loading` as explicit tool-level fields:

```yaml
params:
  tools:
    - crm: CRM tools for customer lookup and order management.
      tools:
        - update_order_status:
            description: Update an order status.
            defer_loading: false
            args:
              order_id: str
              status: Literal["pending", "packed", "shipped", "delivered", "canceled"]
              notify_customer: bool = True
            required:
              - order_id
              - status
    - tool_search
```

This still compiles to a provider function schema. The explicit fields make the intent clear when the tool needs richer control.

### Python-like type shorthand in YAML

Phase 4 should allow a small Python-like type-annotation subset inside compact tool args.

Examples:

- `customer_id: str`
- `limit: int = 10`
- `include_inactive: bool = False`
- `region: str | None = None`
- `status: Literal["pending", "packed", "shipped"]`
- `tags: list[str] = []`

Recommended supported subset:

- `str`, `int`, `float`, `bool`
- `list[T]`
- `dict[K, V]`
- `Optional[T]`
- `T | None`
- `Literal[...]`
- `= <default>` for defaults

Recommended inference rules:

- no default -> required
- any default -> optional
- `= None` -> optional and nullable
- `Literal[...]` -> enum values

Implementation note:

- this should be parsed through a small safe parser for a limited type-expression subset
- raw `eval` should not be used

### Implicit `defer_loading` policy when `tool_search` is present

If `params.tools` contains `tool_search`, searchable tool surfaces should default to effective `defer_loading: true` when the field is omitted.

Recommended behavior:

- apply the implicit default to namespace child tools
- apply the implicit default to MCP/connectors where deferred loading is meaningful
- allow explicit `defer_loading: false` to opt back into eager loading
- ignore this policy for built-ins where deferred loading has no defined meaning

Why this policy fits chatsnack:

- it removes repetitive YAML from the common tool-search case
- it makes `tool_search` read like a mode switch for searchable tool surfaces
- it keeps the saved YAML focused on the exceptions that matter

Recommended save rules:

- authoring fidelity omits implied `defer_loading: true`
- explicit `defer_loading: false` is preserved
- explicit `defer_loading: true` may be preserved if the author wrote it intentionally, though authoring fidelity can still collapse it when the value is implied by `tool_search`

### Reserved keys inside compact namespace tools

Inside a compact namespace tool entry, Phase 4 should treat these keys as reserved:

- `description`
- `args`
- `required`
- `defer_loading`

All other keys in the inline compact form should be treated as argument names.

Example:

```yaml
- search_accounts: Search accounts by name and optional region.
  query: str
  region: Literal["na", "emea", "apac"] | None = None
  include_inactive: bool = False
```

Equivalent structured form:

```yaml
- search_accounts:
    description: Search accounts by name and optional region.
    args:
      query: str
      region: Literal["na", "emea", "apac"] | None = None
      include_inactive: bool = False
```

### Canonical save rules

Phase 4 should save known built-ins in a compact canonical form when possible.

Recommended behavior:

- zero-config built-ins save as scalars
- configured built-ins save as single-key mappings
- namespace entries save with the namespace name as the first key and `tools:` as the second key
- simple child tools save in inline compact form when the tool only needs a description, inline args, and any explicit `defer_loading: false`
- richer child tools save in structured form with `description`, `args`, `required`, and `defer_loading`
- unknown future built-in tool types and unknown fields on known built-ins should survive round-trip as raw provider dicts

### `web_search`

Phase 4 should treat `web_search` as a first-class hosted tool.

Recommended authoring shape:

```yaml
params:
  tools:
    - web_search:
        filters:
          allowed_domains:
            - pubmed.ncbi.nlm.nih.gov
        user_location:
          type: approximate
          country: US
          city: Minneapolis
          region: Minnesota
          timezone: America/Chicago
        external_web_access: true
  responses:
    include:
      - web_search_call.action.sources
```

Phase 4 should also update our docs and examples away from older `search_context_size` examples. If a saved file already contains older or newer provider fields, chatsnack should preserve them through the tool dict instead of dropping them.

### `file_search`

Phase 4 should treat `file_search` as a first-class hosted tool as well.

Recommended authoring shape:

```yaml
params:
  tools:
    - file_search:
        vector_store_ids:
          - vs_123
        max_num_results: 4
  responses:
    include:
      - file_search_call.results
```

Default folding behavior:

- file citations can continue to surface through assistant annotations and `assistant.sources`
- full result payloads belong in `assistant.provider_extras` or diagnostic fidelity when `include` requests them

### `tool_search`

`tool_search` deserves explicit Phase 4 treatment because it changes both tool availability and runtime flow.

Hosted `tool_search` should stay compact in YAML:

```yaml
params:
  tools:
    - crm: CRM tools for customer lookup and order management.
      tools:
        - get_customer_profile: Fetch a customer profile by customer ID.
          customer_id: str
        - list_open_orders: List open orders for a customer ID.
          customer_id: str
    - tool_search
```

Under the implicit `tool_search` policy, both namespace tools above have effective `defer_loading: true` even though the YAML omits that field.

Client-executed `tool_search` needs a Python callback surface in addition to YAML serialization.

Recommended direction:

- YAML stores the `tool_search` tool definition and any explicit overrides
- Python owns the executable handler, for example through a `tool_search_handler` callback on the chat object or params layer
- when the model emits a `tool_search_call` and no handler is configured, chatsnack raises a guidance error
- when the handler is configured, chatsnack turns the handler result into `tool_search_output` and continues the Responses loop

Client-executed `tool_search` can use a compact configured shape:

```yaml
params:
  tools:
    - tool_search:
        execution: client
        args:
          goal: str
```

### `code_interpreter` and `image_generation`

Phase 3 already established the right output homes:

- generated files -> `assistant.files`
- generated images -> `assistant.images`

Phase 4 should mainly tighten request-side docs and built-in tool ordering for these tool types.

### `mcp`

Phase 4 should keep `mcp` definitions as stable dict-shaped tool entries under `params.tools`.

Recommended authoring shape:

```yaml
params:
  tools:
    - mcp:
        server_label: github
        connector_id: connector_github
        allowed_tools:
          - search_repositories
          - get_file_contents
        require_approval: always
```

Important Phase 4 addition:

- if `tool_search` is present and deferred loading is meaningful for a connector surface, the connector should follow the same implicit `defer_loading` policy unless it explicitly opts out

### Forward-compatible pass-through

Built-in tools are evolving quickly. Phase 4 should explicitly support that reality:

- typed normalization for the common tool families above
- pass-through preservation for unknown built-in tool types and unknown fields on known tool types

That gives us a stable authoring shape without forcing every new OpenAI tool release to wait on a chatsnack patch.

## Built-in tool outputs and YAML fidelity

Phase 4 should keep the Phase 3 fidelity model and extend it for the newer built-in tools.

Recommended behavior:

- hosted `web_search` sources fold into `assistant.sources`
- hosted `file_search` result payloads live in `assistant.provider_extras` when they are included
- hosted `tool_search` call/output internals stay in `assistant.provider_extras` unless diagnostic fidelity is enabled
- client `tool_search` inputs and outputs stay runtime-native and can be surfaced in `assistant.provider_extras` for continuation or diagnostic fidelity
- generated assets from `code_interpreter` and `image_generation` keep using `assistant.files` and `assistant.images`

This keeps the default transcript readable and still gives deeper exports a clear home.

## Proposed implementation order

### Step 1

Land PR 47 or equivalent rich-output folding work on the base branch.

### Step 2

Add a default-runtime resolver in [chatsnack/chat/__init__.py](../../chatsnack/chat/__init__.py) that can distinguish:

- explicit runtime choice
- explicit session choice
- env-driven default
- library default

### Step 3

Add `CHATSNACK_DEFAULT_RUNTIME` parsing plus tests for:

- unset env
- `chat_completions`
- `responses_http`
- `responses_websocket`
- invalid value fallback

### Step 4

Add reasoning-default logic in [chatsnack/chat/mixin_params.py](../../chatsnack/chat/mixin_params.py) and/or the Responses request builder so reasoning-capable models get implicit `effort="low"` when the user left reasoning unset.

### Step 5

Add compact tool parsing and serialization for:

- bare built-in tool scalars
- single-key built-in mappings
- namespace blocks keyed by namespace name
- inline Python-like arg shorthand
- structured tool escape hatch with `description`, `args`, `required`, and `defer_loading`

### Step 6

Add implicit `defer_loading` resolution for searchable surfaces when `tool_search` is present.

### Step 7

Extend the runtime handling for provider-native tool execution where needed, starting with hosted tools and then adding client-executed `tool_search`.

### Step 8

Update README and notebook examples so the common path uses `Chat()` without `runtime="responses"` boilerplate and the built-in tool examples use the compact Phase 4 tool syntax.

## Testing priorities

Phase 4 should add focused tests for:

- `Chat()` defaulting to Responses WebSocket when runtime/session are omitted
- `CHATSNACK_DEFAULT_RUNTIME=chat_completions` restoring the legacy default
- explicit `runtime="responses"` continuing to behave the same way it does today
- explicit `session="inherit"` and `session="new"` still taking precedence
- reasoning-capable models receiving implicit `effort="low"` only when reasoning is otherwise unset
- explicit reasoning dicts surviving round-trip unchanged
- zero-config built-ins saving as scalars
- configured built-ins saving as single-key mappings
- namespace blocks round-tripping in compact form
- inline Python-like arg syntax compiling to the expected provider schema
- structured `description` / `args` escape-hatch blocks round-tripping cleanly
- unknown tool fields surviving save/load cycles
- hosted `tool_search` config round-tripping cleanly with implicit `defer_loading`
- explicit `defer_loading: false` overriding the implicit `tool_search` policy
- client `tool_search` raising a clear error when no handler is configured
- client `tool_search` continuing correctly when a handler is configured

## Acceptance target for Phase 4

Phase 4 is successful when these feel true:

1. `Chat()` lands on the Responses WebSocket runtime with no extra boilerplate.
2. One env var restores the legacy default for teams that need a slower migration.
3. Reasoning config has a clear home, a useful implicit default, and stable YAML.
4. Built-in OpenAI tools feel like a supported first-class surface in `params.tools`.
5. Saved tool YAML feels like chatsnack YAML instead of provider JSON.
6. Hosted `web_search` and hosted `tool_search` work cleanly as serialized tool definitions.
7. Client `tool_search` has a clear callback boundary and predictable runtime behavior.

## End-user example acceptance criteria

### Example 1: New default path

```python
from chatsnack import Chat

chat = Chat("Respond tersely.")
reply = chat.ask("What is chatsnack?")
```

Acceptance criteria:

- with no env override, this uses the Responses WebSocket runtime
- the chat inherits a live session for later `chat()` continuation
- the user does not need `runtime="responses"` for the common path

### Example 2: Legacy default escape hatch

```text
CHATSNACK_DEFAULT_RUNTIME=chat_completions
```

```python
from chatsnack import Chat

chat = Chat("Respond tersely.")
reply = chat.ask("What is chatsnack?")
```

Acceptance criteria:

- this uses `ChatCompletionsAdapter`
- explicit `runtime="responses"` still opts into Responses when requested

### Example 3: Reasoning defaults

```python
from chatsnack import Chat

chat = Chat("Solve carefully.", model="gpt-5.4")
reply = chat.ask("Plan a rollout for a websocket default migration.")
```

Acceptance criteria:

- chatsnack injects `reasoning={"effort": "low"}` when reasoning config is otherwise unset
- reasoning summaries remain off unless the user opts in

### Example 4: Hosted web search

```yaml
params:
  tools:
    - web_search:
        filters:
          allowed_domains:
            - pubmed.ncbi.nlm.nih.gov
  responses:
    include:
      - web_search_call.action.sources
```

Acceptance criteria:

- the tool config round-trips cleanly
- source links can be folded into the assistant turn
- unknown future `web_search` fields survive load/save cycles

### Example 5: Hosted tool search

```yaml
params:
  tools:
    - crm: CRM tools for customer lookup and order management.
      tools:
        - list_open_orders: List open orders for a customer ID.
          customer_id: str
        - update_order_status: Update an order status.
          defer_loading: false
          order_id: str
          status: Literal["pending", "packed", "shipped", "delivered", "canceled"]
    - tool_search
```

Acceptance criteria:

- the namespace and `tool_search` entries serialize cleanly
- namespace child tools have effective `defer_loading: true` unless they explicitly set `false`
- the runtime can pass the hosted tool-search config through to Responses

### Example 6: Client-executed tool search

```yaml
params:
  tools:
    - tool_search:
        execution: client
        args:
          goal: str
```

Acceptance criteria:

- the YAML tool config round-trips
- chatsnack raises a clear error when the model emits `tool_search_call` and no handler is registered
- chatsnack can return `tool_search_output` and continue the conversation when a handler is registered

### Example 7: Mixed tool surface

```yaml
params:
  tools:
    - tool_search
    - web_search:
        filters:
          allowed_domains:
            - docs.python.org
            - pandas.pydata.org
        external_web_access: true
    - file_search:
        vector_store_ids:
          - vs_docs
        max_num_results: 5
    - code_interpreter
    - image_generation:
        quality: medium
        size: 1024x1024
    - crm: CRM tools for customer lookup and order management.
      tools:
        - get_customer: Look up one customer by ID.
          customer_id: str
        - list_open_orders: List open orders for a customer ID.
          customer_id: str
        - search_accounts: Search accounts by name and optional region.
          query: str
          region: Literal["na", "emea", "apac"] | None = None
          include_inactive: bool = False
        - update_order_status: Update an order status.
          defer_loading: false
          order_id: str
          status: Literal["pending", "packed", "shipped", "delivered", "canceled"]
          notify_customer: bool = True
    - analytics: Reporting and warehouse tools.
      tools:
        - run_sales_report: Run a sales report for a date range.
          start_date: str
          end_date: str
          group_by: Literal["day", "week", "month"]
        - export_csv: Export a report as CSV.
          report_id: str
          filename: str
    - mcp:
        server_label: github
        connector_id: connector_github
        allowed_tools:
          - search_repositories
          - get_file_contents
        require_approval: always
  responses:
    include:
      - web_search_call.action.sources
      - file_search_call.results
```

Acceptance criteria:

- the file stays readable as one authored YAML asset
- built-ins and namespaces share one coherent tool surface
- inline Python-like arg syntax compiles cleanly
- implicit `defer_loading` keeps the common tool-search path concise

## References

- [Responses API reference](https://platform.openai.com/docs/api-reference/responses?api-mode=responses)
- [WebSocket mode guide](https://developers.openai.com/api/docs/guides/websocket-mode)
- [Reasoning models guide](https://developers.openai.com/api/docs/guides/reasoning)
- [Web search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
- [File search guide](https://developers.openai.com/api/docs/guides/tools-file-search)
- [Tool search guide](https://developers.openai.com/api/docs/guides/tools-tool-search)
- [Function calling guide](https://platform.openai.com/docs/guides/function-calling?api-mode=responses)
- [GPT-5.4 model page](https://developers.openai.com/api/docs/models/gpt-5.4)
- [GPT-5.4 pro model page](https://developers.openai.com/api/docs/models/gpt-5.4-pro)
