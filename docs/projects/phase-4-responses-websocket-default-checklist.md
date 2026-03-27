# Phase 4 Responses/WebSocket Default Checklist

Primary RFC: [phase-4-responses-websocket-default-rfc.md](../rfcs/phase-4-responses-websocket-default-rfc.md)

Assumed prerequisite:

- PR 47 or equivalent rich assistant-field folding work is merged first.

Use this as the running punch list for Phase 4. Check things off, leave short notes, and say what somebody can actually do now.

## Quick Update Template

Drop a note into `## Progress Notes` whenever something meaningfully changes.

```md
### YYYY-MM-DD - Short update title
- Status: done | partial | blocked
- RFC sections: `Proposed default-runtime policy`; `Built-in OpenAI tools design`
- What works for users: `Chat()` now defaults to Responses WebSocket, and tool YAML saves in the compact tool syntax.
- Caveats: Client `tool_search` still needs the callback boundary, or some compact-schema edge cases still expand.
- How we checked it: runtime tests, YAML round-trip tests, notebook/manual check
- Follow-up: leftover docs, parser gaps, model-capability gaps, or handler work
```

## Punch List

### Default runtime policy

- [ ] `Chat()` defaults to the Responses WebSocket runtime when runtime and session are omitted.
  RFC: `The main rule`; `Runtime resolution order`
- [ ] Explicit `runtime="responses"` keeps its current explicit behavior.
  RFC: `The main rule`; `Runtime resolution order`
- [ ] Explicit `runtime="chat_completions"` still selects the legacy runtime.
  RFC: `The main rule`
- [ ] Explicit `session="inherit"` and `session="new"` still take precedence when runtime is otherwise unset.
  RFC: `Runtime resolution order`

### Environment override

- [ ] `CHATSNACK_DEFAULT_RUNTIME=chat_completions` restores the legacy default runtime.
  RFC: `CHATSNACK_DEFAULT_RUNTIME`
- [ ] `CHATSNACK_DEFAULT_RUNTIME=responses_http` selects implicit Responses over HTTP.
  RFC: `CHATSNACK_DEFAULT_RUNTIME`
- [ ] `CHATSNACK_DEFAULT_RUNTIME=responses_websocket` and `responses_ws` select implicit Responses over WebSocket.
  RFC: `CHATSNACK_DEFAULT_RUNTIME`
- [ ] Invalid env values warn once and fall back to the library default.
  RFC: `CHATSNACK_DEFAULT_RUNTIME`

### Reasoning defaults and serialization

- [ ] `params.responses.reasoning` is the canonical home for reasoning request options.
  RFC: `Reasoning configuration design -> Canonical authoring surface`
- [ ] `chat.reasoning.effort` and `chat.reasoning.summary` are the public Python convenience accessors for reasoning request config.
  RFC: `Reasoning configuration design -> Convenience access`
- [ ] Implicit `reasoning={"effort": "low"}` is injected only for reasoning-capable models when reasoning is otherwise unset.
  RFC: `Reasoning configuration design -> Smart default`
- [ ] Reasoning summaries stay off unless the user opts in.
  RFC: `Reasoning configuration design -> Smart default`
- [ ] `reasoning.encrypted_content` remains opt-in through `params.responses.include`.
  RFC: `Reasoning configuration design -> What Phase 4 should treat as reasoning-related config`
- [ ] Unknown keys under `params.responses.reasoning` survive round-trip saves.
  RFC: `Reasoning configuration design -> Serialization rules`
- [ ] Model-aware validation warns on impossible known values without blocking provider pass-through.
  RFC: `Reasoning configuration design -> Validation strategy`

### Built-in tool surface

- [ ] `params.tools` stays the single authoring surface for local and built-in tools.
  RFC: `Built-in OpenAI tools design -> One authoring surface`
- [ ] Zero-config built-ins save as scalars such as `- tool_search` and `- code_interpreter`.
  RFC: `Built-in OpenAI tools design -> Compact authoring tiers`
- [ ] Configured built-ins save as single-key mappings such as `- web_search:` and `- file_search:`.
  RFC: `Built-in OpenAI tools design -> Compact authoring tiers`
- [ ] Namespace blocks save with the namespace name as the key plus a `tools:` block.
  RFC: `Built-in OpenAI tools design -> Compact authoring tiers`
- [ ] Simple child tools round-trip in inline compact form when the tool only needs a description, inline args, and any explicit `defer_loading: false`.
  RFC: `Built-in OpenAI tools design -> Canonical save rules`
- [ ] Richer child tools round-trip in the structured escape-hatch form with `description`, `args`, `required`, and `defer_loading`.
  RFC: `Built-in OpenAI tools design -> Structured escape hatch`; `Canonical save rules`
- [ ] Python-like arg shorthand such as `customer_id: str`, `include_inactive: bool = False`, and `status: Literal[...]` compiles to the expected provider schema.
  RFC: `Built-in OpenAI tools design -> Python-like type shorthand in YAML`
- [ ] Reserved keys inside compact namespace tools are handled deterministically.
  RFC: `Built-in OpenAI tools design -> Reserved keys inside compact namespace tools`
- [ ] Unknown built-in tool fields survive load/save cycles unchanged.
  RFC: `Built-in OpenAI tools design -> Forward-compatible pass-through`
- [ ] `web_search` round-trips current documented fields such as `filters.allowed_domains`, `user_location`, and `external_web_access`.
  RFC: `Built-in OpenAI tools design -> web_search`
- [ ] `file_search` round-trips current documented fields such as `vector_store_ids`, `max_num_results`, and `filters`.
  RFC: `Built-in OpenAI tools design -> file_search`
- [ ] Hosted `tool_search` tool definitions round-trip cleanly in compact namespace syntax.
  RFC: `Built-in OpenAI tools design -> tool_search`
- [ ] Searchable namespace child tools receive effective implicit `defer_loading: true` when `tool_search` is present and the field is omitted.
  RFC: `Built-in OpenAI tools design -> Implicit defer_loading policy when tool_search is present`
- [ ] Explicit `defer_loading: false` overrides the implicit `tool_search` policy.
  RFC: `Built-in OpenAI tools design -> Implicit defer_loading policy when tool_search is present`
- [ ] Connector or MCP surfaces follow the same implicit deferred-loading policy when it is meaningful.
  RFC: `Built-in OpenAI tools design -> mcp`; `Implicit defer_loading policy when tool_search is present`
- [ ] Client `tool_search` has a clear callback boundary and a clear guidance error when the handler is missing.
  RFC: `Built-in OpenAI tools design -> tool_search`

### Output folding and fidelity

- [ ] Hosted `web_search` sources fold into `assistant.sources`.
  RFC: `Built-in tool outputs and YAML fidelity`
- [ ] Hosted `file_search` result payloads have a clear home in `assistant.provider_extras` or diagnostic fidelity.
  RFC: `Built-in tool outputs and YAML fidelity`
- [ ] Hosted `tool_search` internals stay out of the default transcript and have a clear home in `assistant.provider_extras`.
  RFC: `Built-in tool outputs and YAML fidelity`
- [ ] Generated files and images from built-in tools continue to land in `assistant.files` and `assistant.images`.
  RFC: `Built-in tool outputs and YAML fidelity`

### Example assets and implementation naming

- [ ] We ship descriptive example YAML chats for the default runtime path, reasoning access, hosted `web_search`, hosted `tool_search`, and a mixed tool surface.
  RFC: `Example assets and implementation naming`
- [ ] At least one notebook or small CLI loads those example YAML chats directly and exercises them in a concise chatsnackian flow.
  RFC: `Example assets and implementation naming`
- [ ] New production code, tests, helper files, notebooks, CLIs, and example assets use descriptive phase-agnostic names.
  RFC: `Example assets and implementation naming`; `Proposed implementation order -> Step 10`

### Docs, examples, and proof

- [ ] README common-path examples no longer need `runtime="responses"` boilerplate.
  RFC: `Proposed implementation order -> Step 9`
- [ ] Notebook or CLI coverage shows the new default runtime path, the `chat.reasoning` convenience surface, and at least one built-in tool example in the compact syntax.
  RFC: `Proposed implementation order -> Step 8`; `Proposed implementation order -> Step 9`
- [ ] Runtime tests cover default-runtime selection, env overrides, explicit runtime preservation, and reasoning defaults.
  RFC: `Testing priorities`
- [ ] YAML tests cover reasoning round-trip behavior plus compact-tool scalar, mapping, namespace, and escape-hatch round trips.
  RFC: `Testing priorities`
- [ ] Python API tests cover `chat.reasoning.effort` and `chat.reasoning.summary`.
  RFC: `Testing priorities`
- [ ] Hosted `tool_search` and client `tool_search` both have acceptance-level coverage.
  RFC: `Testing priorities`
- [ ] The mixed-surface Example 7 from the RFC round-trips as one readable YAML asset.
  RFC: `End-user example acceptance criteria -> Example 7: Mixed tool surface`
- [ ] The educational Example 8 assets load cleanly through the paired notebook or CLI flow.
  RFC: `End-user example acceptance criteria -> Example 8: Educational example assets`

## Progress Notes

Add short dated entries here as work lands.
