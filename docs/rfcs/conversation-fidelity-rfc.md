# Portable conversation history

Status: implemented; validation recorded in the project checklist.

## Contract

`messages` is the authoritative, portable conversation. Responses output items
become separate entries, in provider order. Normal save/load preserves them;
`export_state` is not required. Ordinary authored dialogue remains scalar-first.

```yaml
messages:
  - user: Check stock for snack-box.
  - reasoning:
      item_id: rs_1
      encrypted_content: "..."
  - assistant:
      text: I'll check the inventory.
      phase: commentary
  - tool_call:
      name: stock
      arguments: {sku: snack-box}
      call_id: call_1
  - tool:
      tool_call_id: call_1
      content: '{"available":12}'
  - assistant:
      text: We have 12 available.
      phase: final_answer
```

Mattie's decisions:

- **SEPARATE:** individual reasoning, assistant, tool-call, and tool-result entries.
- **KEEP:** editing an earlier message keeps every remaining recorded entry.
- **PROJECT:** Chat Completions receives supported dialogue/tool exchanges and
  warns about omitted provider-only information; the stored Chat stays intact.

## Representation and compatibility

Known items map reversibly to compact entries. Optional `item_id`, `status`,
`phase`, and `provider_extras` preserve item details; phase never means status.
Known empty metadata and completed-status defaults are omitted from saved entries.
Native tool result statuses remain explicit when required by their protocol.
The request compiler supplies required empty `summary`/`annotations` arrays and
the default assistant status. Optional empty reasoning content and logprobs need
not be replayed. This is semantic preservation of known defaults; unknown fields,
opaque items, nonempty metadata, and literal payloads remain unchanged.
Scalar `assistant: Blah` stays valid; only meaningful metadata requires a block.
`provider_item` retains an unfamiliar or otherwise unrepresentable item without
a second raw copy of mapped conversation text. Generated argument/output strings
remain literal; authored argument mappings compile to JSON.

Existing scalar and expanded messages, including `assistant.tool_calls`, still
load. We cannot recover ordering or fields lost by older saved files. Default
saves now preserve message extras and encrypted content. Existing export flags
still govern response-level cache metadata and diagnostic dumps.

`.ask()` remains text-only. `.chat()` returns a continued Chat with the ordered
entries. Normalized results gain an optional `messages` list and retain their
aggregate `message` compatibility view. `.response`, `.last`, `.images`, and
`.files` retain their existing roles. Generated media uses the existing local
asset policy rather than putting base64 copies into the transcript.
Latest-result accessors recognize compact and opaque assistant entries alike.
Input/tool-result boundaries and an older explicit `final_answer` separate output
groups, so pending calls and image-only replies cannot reuse earlier answers or
assets. Contiguous unphased output has no saved response boundary and is treated
as one group. Asset views belong to the last actual assistant in a response.
An image-generation `provider_item` can wrap its wire `item` with a
`result_asset` reference. The request builder restores `result` from verified
local bytes. `images`, `files`, and `sources` are convenience views attached to
an existing entry; they never create an extra assistant message.

## Compilation and continuation

Copy/reset isolate nested message values. Includes and JSON import/export carry
typed entries. Source fillings stay live until submission; resolved history in
the returned Chat stays literal. Opaque items and recorded call data never enter
the template formatter. Only newly returned executable calls enter auto-feed.

HTTP `store=False` sends the complete history, including tool follow-ups.
Automatically managed response IDs require a matching resolved prefix and
provider binding. Live caches contain IDs, lengths, and fingerprints, not a
second transcript. An edited or different branch replays its current messages.
WebSocket missing-parent fallback remains guarded against retry after output.
Caller-authored `previous_response_id` remains an advanced, caller-owned option.
Profile defaults participate in the same check. Server-side `conversation` and
request-body overrides disable automatic caching because their full ancestry is
not locally known. Authentication scope is represented only by a fingerprint.

HTTP and WebSocket share item normalization. Completed/incomplete responses keep
their distinct terminal status. Streaming retains the existing listener surface.
An explicitly unfinished function call keeps its whole execution batch pending;
all items remain recorded, and no partial batch is executed or auto-fed.
Chat Completions projection places available tool results immediately after the
assistant that requested them. This changes only the projected order, leaving
the saved Responses transcript and individual assistant messages untouched.

## Validation and boundaries

The Goal test runs a real Chat with a mocked SDK tool exchange, saves/loads it,
then inspects the next actual request body for ordered item equality. It proves
tool execution occurs once and source templates remain reusable. Steer tests
cover codecs, literal data, aliases, unknown items, old YAML, branching, retries,
projection, assets, and binding/usage/tool-budget regressions.

Run relevant checks on the supported SDK floor and the previously checked newer
SDK. Add an offline notebook example and validate documentation. Live probes
remain opt-in. Async scheduling, steering, effort updates, new executors, and
model capability changes are outside this work.

This supersedes the folded-history and message-field export gating portions of
the Phase 3 YAML RFC and the earlier FIDELITY proposal in the model research.

Provider contract verified 2026-09-09:
[reasoning continuity](https://developers.openai.com/api/docs/guides/reasoning#preserve-reasoning-across-calls)
and [function calling](https://developers.openai.com/api/docs/guides/function-calling).
Generated-image replay follows the
[image-generation guide](https://developers.openai.com/api/docs/guides/tools-image-generation).
