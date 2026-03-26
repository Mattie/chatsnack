# Phase 3 Responses YAML Checklist

Primary RFC: [phase-3-responses-yaml-rfc.md](../rfcs/phase-3-responses-yaml-rfc.md)

Use this as the running punch list for Phase 3. Check things off, leave short notes, and say what somebody can actually do now. The goal is to keep the YAML work easy to follow without making people dig through the full RFC every time.

## Quick Update Template

Drop a note into `## Progress Notes` whenever something meaningfully changes.

```md
### YYYY-MM-DD - Short update title
- Status: done | partial | blocked
- RFC sections: `Fidelity levels`; `Normalization rules for expanded turn blocks`
- What works for users: I can save a mixed-content assistant turn with text, sources, and files, reload it, and get the same canonical YAML back.
- Caveats: Provider-native extras only survive when the chosen fidelity mode keeps them.
- How we checked it: serializer tests, parser tests, round-trip fixture, notebook/manual check
- Follow-up: leftover edge cases, migration notes, or docs
```

## Punch List

### Basic YAML shape
- [x] `messages:` stays the main transcript surface and `params:` stays the config/runtime surface.
  RFC: `Summary`; `Canonical YAML shape`
  _Done. No structural change to the top-level YAML contract. Verified in `test_simple_text_chat_round_trip`, `test_params_responses_nested_config_round_trips`._
- [x] `params.session` round-trips cleanly when it is set, and stays omitted in the simplest saved assets when we want the default HTTP Responses path.
  RFC: `Phase 3 scope`; `What belongs in params`; `Mapping rules`; `End-User Example Acceptance Criteria`
  _Done. `test_params_session_round_trips` and `test_params_session_omitted_when_unset` cover both paths._
- [x] We have a normalized internal turn model without changing the author-facing YAML contract.
  RFC: `Internal modeling boundary`
  _Done. `chatsnack/chat/turns.py` introduces `NormalizedTurn` with fields: role, text, reasoning, encrypted_content, sources, images, files, tool_calls, tool_output, provider_extras. The author-facing YAML stays messages + params._
- [x] The canonical YAML examples save out in the shape the RFC promises.
  RFC: `Canonical YAML shape`; `Worked examples`
  _Done. Verified through RFC acceptance example tests (Examples 1–7)._

### Role aliasing and save order
- [x] `system` saves as the canonical role key.
  RFC: "`system` stays canonical, `developer` loads as an alias"
  _Done. `_normalize_message_on_save()` always emits `system`. Verified in `test_system_saves_as_canonical_key`._
- [x] `developer` loads as an alias and normalizes to the internal canonical role.
  RFC: "`system` stays canonical, `developer` loads as an alias"; `Normative parsing and save-order rules`
  _Done. `_normalize_message_on_load()` converts `developer` → `system`. `developer()` method added. Verified in `test_developer_loads_as_alias_and_saves_as_system`, `test_developer_alias_in_get_messages`, `test_developer_method_stores_as_system`._
- [x] Mixed `system` and `developer` transcripts keep their separate turn boundaries and stable ordering.
  RFC: `Normative parsing and save-order rules`
  _Done. Each turn is normalized independently, preserving order and boundaries. Verified in `test_mixed_system_and_developer_preserve_turn_boundaries`._
- [x] We do not accidentally collapse turns during parse or save.
  RFC: `Normative parsing and save-order rules`; `Serializer and parser targets`; `Tests`
  _Done. Verified in `test_no_accidental_turn_collapse`._

### Mixed turns and normalization
- [x] Scalar turns expand internally and only collapse back to scalar when the RFC allows it.
  RFC: `Messages stay scalar-first`; `Normalization rules for expanded turn blocks -> Internal normalization`
  _Done. `NormalizedTurn.from_message_dict()` normalizes scalars. `_should_collapse_to_scalar()` / `_normalize_message_on_save()` collapse text-only turns back. Verified in `test_scalar_turns_stay_scalar_after_round_trip`, `test_text_only_collapses_to_scalar`._
- [x] Mixed-content turns save as one expanded block in canonical field order.
  RFC: `Normalization rules for expanded turn blocks -> Canonical field ordering`; `Mixed-content serialization`
  _Done. `_canonical_expanded_block()` enforces order: text, reasoning, encrypted_content, sources, images, files, tool_calls, provider_extras. Verified in `test_canonical_field_ordering_on_save`._
- [x] Validation rules for `system`, `user`, `assistant`, and `tool` turns are enforced.
  RFC: `Normalization rules for expanded turn blocks -> Validation rules`
  _Done. `ALLOWED_FIELDS_BY_ROLE` restricts system to text-only, user to text/images/files/provider_extras, assistant to all canonical fields. `_normalize_message_on_load` and `_normalize_message_on_save` enforce these._
- [x] Unknown expanded-turn fields get routed into `provider_extras` instead of disappearing.
  RFC: `Normalization rules for expanded turn blocks -> Unknown provider extras`
  _Done. `_normalize_message_on_load()` and `NormalizedTurn.from_message_dict()` route unknown fields to `provider_extras`. Verified in `test_unknown_fields_routed_to_provider_extras`._
- [x] Load-save cycles are stable after canonicalization for the selected fidelity mode.
  RFC: `Normalization rules for expanded turn blocks -> Round-trip guarantees`
  _Done. Verified in `test_idempotent_save_cycles`._
- [x] The ambiguous serializer cases match the RFC examples.
  RFC: `Normalization rules for expanded turn blocks -> Ambiguous-case examples`
  _Done. Verified in `test_canonical_field_ordering_on_save`, `test_unknown_fields_routed_to_provider_extras`, `test_expanded_assistant_with_files_and_images`._

### Fidelity and persistence boundaries
- [x] Authoring fidelity gives us the readable default YAML we want.
  RFC: `Fidelity levels -> Authoring fidelity`
  _Done. Default mode drops encrypted_content, provider_extras, and state. Verified in `test_authoring_fidelity_omits_state_and_provider_extras`, `test_authoring_fidelity_drops_encrypted_content`._
- [x] Continuation fidelity keeps continuation state when `export_state: true` is on.
  RFC: `Runtime state export should be explicit`; `Fidelity levels -> Continuation fidelity`
  _Done. Verified in `test_continuation_fidelity_keeps_state`, `test_continuation_fidelity_keeps_provider_extras`, `test_continuation_fidelity_keeps_encrypted_content`._
- [x] Exported continuation state is treated as runtime metadata plus a best-effort continuation hint, with fresh-connection fallback still following the saved `session` and `store` policy.
  RFC: `Runtime state export should be explicit`
  _Done. State persists when `export_state: true`, omitted otherwise. Runtime continuation semantics follow Phase 2a rules._
- [x] Diagnostic fidelity keeps provider dumps and provider extras when enabled.
  RFC: `Fidelity levels -> Diagnostic fidelity`
  _Done. Verified in `test_diagnostic_fidelity_keeps_provider_dump`._
- [x] `assistant.provider_extras` and `params.responses.provider_dump` are used for the non-canonical fields the RFC calls out.
  RFC: `Fidelity levels`; `Mapping rules`
  _Done. Unknown turn-level fields → `assistant.provider_extras`. Whole-response dump → `params.responses.provider_dump`._
- [x] Diagnostic fidelity keeps completed response snapshots without turning YAML into a WebSocket event log.
  RFC: `Fidelity levels`; `Mapping rules`
  _Done. `provider_dump` holds completed response data, not raw WebSocket events._

### Params and tools
- [x] `params.responses` supports the documented nested fields.
  RFC: `What belongs in params`; `Implementation sketch`
  _Done. `ChatParams.responses: Optional[dict]` accepts text, reasoning, include, store, export_state, export_diagnostics, state, provider_dump. Verified in `test_params_responses_nested_fields`._
- [x] `params.tools` stays the one authoring surface for local and provider-native tools.
  RFC: "`params.tools` stays the single authoring surface"
  _Done. No structural change to `params.tools`. Existing function-tool model preserved._
- [x] Provider-native tools start as raw dict pass-through definitions.
  RFC: "`params.tools` stays the single authoring surface"; `Mapping rules`
  _Done. `params.tools` accepts raw dict definitions for provider-native tools (web_search, image_generation, etc.)._
- [x] Local function-tool history keeps the chatsnack message shapes we already use.
  RFC: `Tool formatting stays close to current chatsnack`; `Mapping rules`
  _Done. Existing `assistant.tool_calls` and `tool:` shapes are unchanged. Verified in `test_local_function_tool_history_format`, `test_example5_local_function_tool_history`._


### Natural attachment call-site ergonomics (Phase 3A planned)
- [x] Add `files=` / `images=` convenience kwargs across query methods: `ask`, `ask_a`, `chat`, `chat_a`, `listen`, `listen_a`.
  RFC alignment: `Design goals`; `Attachments, files, and generated assets`
  _Done. `ChatQueryMixin` now routes all six query entrypoints through shared `_prepare_query_vars(...)` and supports `files=` / `images=` kwargs._
- [x] Normalize path/dict convenience inputs into canonical expanded user-turn `files`/`images` blocks at query-call boundary.
  RFC alignment: `Messages stay scalar-first`; `Normalization rules for expanded turn blocks`
  _Done. `chatsnack/runtime/attachment_inputs.py` normalizes path + canonical dict forms into expanded user-turn attachments._
- [x] Bonus: support file-object attachment inputs for `files=` using resolver-compatible temp-path handling.
  RFC alignment: `Serializer heavy lifting`; `Design goals`
  _Done. File objects are materialized to temp-backed canonical `{path, filename}` entries for resolver upload flow._
- [x] Add 3HTDD Goal/Steer/Unit tests including method-parity coverage for `listen` and `_a` equivalents.
  Project alignment: `3HTDD.md`
  _Done. Added `tests/mixins/test_query_attachments.py` with Goal/Steer/Unit-style coverage across sync/async/listen paths plus error behavior._
- [x] Update README with terse natural-attachment examples in chatsnack voice.
  Project alignment: `README.md`; `PHILOSOPHY.md`
- [x] Update `GettingStartedWithChatsnack.ipynb` with a concise “Natural Attachments” section (1–2 cells).
  Project alignment: notebook-first demonstration style

### Files, images, reasoning, and sources
- [x] `images` and `files` work for the supported user and assistant turns.
  RFC: `Attachments, files, and generated assets`
  _Done. user turns support text/images/files. assistant turns support text/reasoning/encrypted_content/sources/images/files/tool_calls/provider_extras. Verified in `test_expanded_user_turn_with_images`, `test_expanded_user_turn_with_files`, `test_expanded_assistant_with_files_and_images`._
- [x] Reasoning, encrypted content, and sources land on assistant turns in the documented places.
  RFC: `How Responses concepts fold into YAML`
  _Done. Verified in `test_expanded_assistant_turn_round_trips`, `test_continuation_fidelity_keeps_encrypted_content`._
- [x] Generated images and files save as stable assistant assets.
  RFC: `Attachments, files, and generated assets -> Serializer heavy lifting`; `How Responses concepts fold into YAML`
  _Done. `assistant.images` and `assistant.files` with file_id/filename round-trip cleanly. Verified in `test_example7_attachments_and_generated_outputs`._
- [x] Mapping rules are implemented without drifting from the documented YAML homes.
  RFC: `Mapping rules`
  _Done. All mapping rules from the RFC table are implemented in the serializer and parser._

### Serializer, parser, and proof
- [x] `chatsnack/yamlformat.py` handles canonical ordering, fidelity gating, and scalar-collapse rules.
  RFC: `Serializer and parser targets -> chatsnack/yamlformat.py`
  _Done. Added `_normalize_data_on_save()` with `_canonical_expanded_block()`, `_apply_fidelity_gate()`, `_should_collapse_to_scalar()`, and `_normalize_params_on_save()`._
- [x] `chatsnack/chat/mixin_messages.py` handles alias normalization, expanded-turn parsing, and `provider_extras`.
  RFC: `Serializer and parser targets -> chatsnack/chat/mixin_messages.py`
  _Done. `get_messages()` normalizes developer→system. `developer()` method added. Expanded turns extract text for API calls._
- [x] Round-trip tests cover authoring, continuation, and diagnostic fidelity modes.
  RFC: `Tests`
  _Done. 48 tests in `tests/test_phase3_yaml.py` cover all three fidelity modes._
- [ ] Cross-runtime save/load checks cover the main YAML contract across `chat_completions`, HTTP `responses`, and WebSocket `responses` where user-facing behavior should stay the same.
  RFC: `Tests`; `Implementation sketch`
  _Partial. YAML contract tests are in place. Live cross-runtime checks depend on API access._
- [x] Tests cover mixed-role transcripts, mixed-content ordering, and no accidental role collapse.
  RFC: `Tests`
  _Done. `TestRoleAliasing` and `TestMixedTurnsAndNormalization` classes cover these._
- [x] Worked examples and end-user acceptance examples are actually true in notebook or fixture coverage.
  RFC: `Worked examples`; `End-User Example Acceptance Criteria`
  _Done. `TestRFCAcceptanceExamples` covers Examples 1–7 from the RFC._

## Progress Notes

Add short dated entries here as work lands.

### 2026-03-24 – Phase 3 core implementation
- Status: done
- RFC sections: All sections implemented
- What works for users:
  - Save/load expanded assistant turns with text, reasoning, sources, images, files, encrypted_content, and provider_extras
  - `developer` accepted as alias for `system` on load, saved back as `system`
  - Mixed `system`/`developer` transcripts preserve separate turn boundaries
  - `params.responses` nested config for store, export_state, export_diagnostics, text, reasoning, include, state, provider_dump
  - `params.session` round-trips when set, omitted when unset
  - Expanded user turns with images and files
  - Canonical field ordering on save (text → reasoning → encrypted_content → sources → images → files → tool_calls → provider_extras)
  - Scalar collapse: text-only turns revert to `role: text` form
  - Three fidelity levels: authoring (default, clean), continuation (keeps state/extras), diagnostic (keeps provider_dump)
  - Unknown expanded-turn fields route to provider_extras
  - Existing tool-call format preserved
  - Round-trip stability verified
- Caveats:
  - Cross-runtime live tests require API access
  - Automatic local-path upload via `AttachmentResolver` is implemented and wired into both adapters
  - Typed wrappers for `params.responses` fields can follow later if useful
- How we checked it: 52 tests in `tests/test_phase3_yaml.py`, all existing tests still passing
- Follow-up: Runtime adapter integration for folding reasoning/sources/images from Responses API output into YAML turns; notebook examples; typed `params.responses` wrappers if needed

### 2026-03-25 – Runtime-boundary wiring
- Status: done
- RFC sections: `What belongs in params`; `Mapping rules`; `Implementation sketch`; `Fidelity levels`; `params.tools stays the single authoring surface`
- What works for users:
  - `params.responses` config (text, reasoning, include, store, etc.) now reaches the Responses API at request time via `_get_responses_api_options()` and merged kwargs
  - Expanded user turns with images/files produce `input_image` and `input_file` content parts in the Responses request, not just flattened text
  - Runtime metadata (response_id, status) automatically written into `params.responses.state` when `export_state: true` – live state export, not just hand-authored round-trip
  - `store` policy respects the explicit `params.responses.store` value – no more auto-enable for continuation (preserves Phase 2a store=false WebSocket continuation)
  - Provider-native tool dicts (web_search, code_interpreter, image_generation, mcp) pass through unchanged via `set_tools()`/`get_tools()` – no longer wrapped in invalid function-tool schema
- How we checked it: 23 new tests in `tests/test_phase3_runtime.py`, updated 2 existing continuation tests for new store policy

### 2026-03-25 – Attachment-only turns, previous_response_id production path
- Status: done
- What works for users:
  - `get_messages()` now handles attachment-only expanded turns (images/files with no text key)
  - `_normalize_runtime_metadata()` preserves `previous_response_id` as a top-level key, completing the full production flow from adapter through to `params.responses.state`
- How we checked it: 6 new tests in `tests/test_phase3_runtime.py` (29 total runtime tests)

### 2026-03-25 – Local file upload via AttachmentResolver
- Status: done
- RFC section: `Serializer heavy lifting`
- What works for users:
  - Local `path:` entries in `user.images` and `user.files` are automatically uploaded via the OpenAI Files API before the Responses request is built
  - Upload results are cached in memory by `(absolute_path, size, mtime_ns, kind)` so repeated prompts do not re-upload the same asset during a session or notebook run
  - Cache invalidates when file content changes (size or mtime differs)
  - Both HTTP Responses and WebSocket Responses adapters share the same `AttachmentResolver` instance and upload path
  - Original `path:` entries in YAML are never mutated – the resolver returns new dicts for the API call
  - `url:` and `file_id:` entries pass through unchanged
  - Upload failures warn and skip gracefully (no crash)
  - New `upload_file()` and `upload_file_async()` helpers on `AiClient`
- How we checked it: 15 new tests in `tests/test_phase3_runtime.py` (44 total runtime tests) covering unit, caching, integration, async, and YAML preservation

### 2026-03-25 – Live and WebSocket attachment coverage
- Status: done
- What works for users:
  - Opt-in live Responses tests now cover local file attachments, local image attachments, attachment-only turns, provider-native tools, and WebSocket attachment/session continuation
  - WebSocket adapter tests now verify sync + async attachment resolution happens before request streaming
  - WebSocket continuation tests now cover attachment-only suffix turns (`previous_response_id` + attachment input item)
  - WebSocket request tests now cover provider-native tool passthrough on the SDK event-body path
  - `Chat.copy()` / JSON message import now preserve attachment-only expanded turns instead of failing on empty text content
- Follow-up refinement:
  - HTTP live continuation coverage now sets `responses.store: true` before the first turn, matching the provider continuation contract for `previous_response_id`
  - Image-path uploads now use the Files API `purpose="vision"` while regular files continue using the model-input file path
- Caveats:
  - Live tests require both `OPENAI_API_KEY` and `CHATSNACK_RUN_LIVE_TESTS` to be set, so they are safe in CI/sandbox environments with blocked network egress
- How we checked it: `pytest -q tests/runtime/ tests/test_phase2_sessions.py tests/test_phase3_runtime.py tests/test_phase3_yaml.py tests/mixins/test_query.py` → 206 passed, 20 skipped


### 2026-03-26 – Phase 3A plan drafted for natural attachment query ergonomics
- Status: planned (Phase 3A)
- RFC sections: `Design goals`; `Messages stay scalar-first`; `Attachments, files, and generated assets`
- What this enables for users:
  - More natural attachment usage across `ask/chat/listen` plus async `_a` equivalents with terse `files=` and `images=` kwargs
  - Preserves the same Phase 3 YAML shape (expanded user turns when needed)
  - Includes a bonus path for file-object inputs, not only filesystem paths
- Planning artifact: `docs/projects/phase-3-natural-attachments-plan.md`
- Follow-up: implement helper + query wiring + tests + README + Getting Started notebook cells

### 2026-03-26 – Phase 3A implemented: natural attachment query ergonomics
- Status: done
- RFC sections: `Design goals`; `Attachments, files, and generated assets`; `Messages stay scalar-first`
- What works for users:
  - `ask`, `ask_a`, `chat`, `chat_a`, `listen`, and `listen_a` now accept `files=` and `images=` directly
  - Paths and canonical dict inputs normalize into expanded user turns at query boundary through one shared path
  - `files=` supports file objects, materializing temp-backed path entries with filename metadata
  - Sync/async/listen parity is covered, including streaming `listen` + `listen_a` call paths
- How we checked it: targeted mixin tests for natural attachments and full `tests/mixins` run
- Caveats: file-object support currently applies to `files=` only (intentional); `images=` file objects are rejected with concise errors
