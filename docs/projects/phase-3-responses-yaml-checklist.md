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
- [ ] `messages:` stays the main transcript surface and `params:` stays the config/runtime surface.
  RFC: `Summary`; `Canonical YAML shape`
- [ ] `params.session` round-trips cleanly when it is set, and stays omitted in the simplest saved assets when we want the default HTTP Responses path.
  RFC: `Phase 3 scope`; `What belongs in params`; `Mapping rules`; `End-User Example Acceptance Criteria`
- [ ] We have a normalized internal turn model without changing the author-facing YAML contract.
  RFC: `Internal modeling boundary`
- [ ] The canonical YAML examples save out in the shape the RFC promises.
  RFC: `Canonical YAML shape`; `Worked examples`

### Role aliasing and save order
- [ ] `system` saves as the canonical role key.
  RFC: "`system` stays canonical, `developer` loads as an alias"
- [ ] `developer` loads as an alias and normalizes to the internal canonical role.
  RFC: "`system` stays canonical, `developer` loads as an alias"; `Normative parsing and save-order rules`
- [ ] Mixed `system` and `developer` transcripts keep their separate turn boundaries and stable ordering.
  RFC: `Normative parsing and save-order rules`
- [ ] We do not accidentally collapse turns during parse or save.
  RFC: `Normative parsing and save-order rules`; `Serializer and parser targets`; `Tests`

### Mixed turns and normalization
- [ ] Scalar turns expand internally and only collapse back to scalar when the RFC allows it.
  RFC: `Messages stay scalar-first`; `Normalization rules for expanded turn blocks -> Internal normalization`
- [ ] Mixed-content turns save as one expanded block in canonical field order.
  RFC: `Normalization rules for expanded turn blocks -> Canonical field ordering`; `Mixed-content serialization`
- [ ] Validation rules for `system`, `user`, `assistant`, and `tool` turns are enforced.
  RFC: `Normalization rules for expanded turn blocks -> Validation rules`
- [ ] Unknown expanded-turn fields get routed into `provider_extras` instead of disappearing.
  RFC: `Normalization rules for expanded turn blocks -> Unknown provider extras`
- [ ] Load-save cycles are stable after canonicalization for the selected fidelity mode.
  RFC: `Normalization rules for expanded turn blocks -> Round-trip guarantees`
- [ ] The ambiguous serializer cases match the RFC examples.
  RFC: `Normalization rules for expanded turn blocks -> Ambiguous-case examples`

### Fidelity and persistence boundaries
- [ ] Authoring fidelity gives us the readable default YAML we want.
  RFC: `Fidelity levels -> Authoring fidelity`
- [ ] Continuation fidelity keeps continuation state when `export_state: true` is on.
  RFC: `Runtime state export should be explicit`; `Fidelity levels -> Continuation fidelity`
- [ ] Exported continuation state is treated as runtime metadata plus a best-effort continuation hint, with fresh-connection fallback still following the saved `session` and `store` policy.
  RFC: `Runtime state export should be explicit`
- [ ] Diagnostic fidelity keeps provider dumps and provider extras when enabled.
  RFC: `Fidelity levels -> Diagnostic fidelity`
- [ ] `assistant.provider_extras` and `params.responses.provider_dump` are used for the non-canonical fields the RFC calls out.
  RFC: `Fidelity levels`; `Mapping rules`
- [ ] Diagnostic fidelity keeps completed response snapshots without turning YAML into a WebSocket event log.
  RFC: `Fidelity levels`; `Mapping rules`

### Params and tools
- [ ] `params.responses` supports the documented nested fields.
  RFC: `What belongs in params`; `Implementation sketch`
- [ ] `params.tools` stays the one authoring surface for local and provider-native tools.
  RFC: "`params.tools` stays the single authoring surface"
- [ ] Provider-native tools start as raw dict pass-through definitions.
  RFC: "`params.tools` stays the single authoring surface"; `Mapping rules`
- [ ] Local function-tool history keeps the chatsnack message shapes we already use.
  RFC: `Tool formatting stays close to current chatsnack`; `Mapping rules`

### Files, images, reasoning, and sources
- [ ] `images` and `files` work for the supported user and assistant turns.
  RFC: `Attachments, files, and generated assets`
- [ ] Reasoning, encrypted content, and sources land on assistant turns in the documented places.
  RFC: `How Responses concepts fold into YAML`
- [ ] Generated images and files save as stable assistant assets.
  RFC: `Attachments, files, and generated assets -> Serializer heavy lifting`; `How Responses concepts fold into YAML`
- [ ] Mapping rules are implemented without drifting from the documented YAML homes.
  RFC: `Mapping rules`

### Serializer, parser, and proof
- [ ] `chatsnack/yamlformat.py` handles canonical ordering, fidelity gating, and scalar-collapse rules.
  RFC: `Serializer and parser targets -> chatsnack/yamlformat.py`
- [ ] `chatsnack/chat/mixin_messages.py` handles alias normalization, expanded-turn parsing, and `provider_extras`.
  RFC: `Serializer and parser targets -> chatsnack/chat/mixin_messages.py`
- [ ] Round-trip tests cover authoring, continuation, and diagnostic fidelity modes.
  RFC: `Tests`
- [ ] Cross-runtime save/load checks cover the main YAML contract across `chat_completions`, HTTP `responses`, and WebSocket `responses` where user-facing behavior should stay the same.
  RFC: `Tests`; `Implementation sketch`
- [ ] Tests cover mixed-role transcripts, mixed-content ordering, and no accidental role collapse.
  RFC: `Tests`
- [ ] Worked examples and end-user acceptance examples are actually true in notebook or fixture coverage.
  RFC: `Worked examples`; `End-User Example Acceptance Criteria`

## Progress Notes

Add short dated entries here as work lands.
