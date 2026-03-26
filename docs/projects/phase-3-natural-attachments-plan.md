# Phase 3A Plan: Natural Attachment Inputs Across Query Methods

Primary context reviewed:
- [README.md](../../README.md)
- [PHILOSOPHY.md](../../PHILOSOPHY.md)
- [Phase 3 RFC](../rfcs/phase-3-responses-yaml-rfc.md)
- [Phase 3 checklist](./phase-3-responses-yaml-checklist.md)
- [Getting Started notebook](../../notebooks/GettingStartedWithChatsnack.ipynb)
- [Experimenting notebook](../../notebooks/ExperimentingWithChatsnack.ipynb)

## Phase framing

This is **Phase 3A**: call-site ergonomics for attachments.

The intent is to make attachment usage feel natural in chatsnack’s existing rhythm while preserving the Phase 3 YAML contract and current adapter semantics.

## User goal

Support this style directly:

```python
from chatsnack import Chat

chat = Chat("Review attachments for the user.", runtime="responses")
print(chat.ask("check this chart for accuracy vs the data", files=["stuff/mypic.png", "other/lister.csv"]))
```

Bonus goal: support file objects, not only path strings.

## API surface (explicit parity)

Attachment convenience should be available on **all query entrypoints**:

- sync: `ask()`, `chat()`, `listen()`
- async: `ask_a()`, `chat_a()`, `listen_a()`

### Proposed kwargs

- `files=`: list of file inputs
- `images=`: list of image inputs

Supported source forms in Phase 3A:

1. String paths (primary)
   - `files=["data/table.csv"]`
   - `images=["images/chart.png"]`
2. Canonical dicts (already familiar)
   - `{"path": ...}` / `{"file_id": ...}` / `{"url": ...}` / optional `filename`
3. Bonus file-object forms (explicitly gated as Phase 3A bonus)
   - `files=[open("data/table.csv", "rb")]`
   - `files=[{"file": fp, "filename": "table.csv"}]`

## Design adjustment after review

To maximize success of this phase, we should **not** start by adding provider-facing behavior in adapters.

Instead, Phase 3A should do one thing well:

1. normalize convenience inputs at query-call boundary,
2. append canonical expanded user turns,
3. let existing runtime + resolver code do the rest.

This keeps the change low-risk and aligned with the RFC’s scalar-first / expanded-when-needed model.

## Canonical behavior rules

- When `files` or `images` is passed, the user turn is represented as an expanded user block (`text` + `files`/`images` when present).
- Existing plain-text behavior is unchanged when no attachments are provided.
- Existing hand-authored attachment turns remain fully supported.
- `listen()` and `listen_a()` must accept the same attachment kwargs and stream from the same normalized prompt shape.
- Method parity rule: query methods should share one normalization path so behavior stays consistent.

## Implementation plan

### 1) Shared normalization helper

Add helper module:
- `chatsnack/runtime/attachment_inputs.py`

Responsibilities:
- Normalize `files=` and `images=` convenience values into canonical dict entries.
- Validate supported shapes with concise errors.
- Keep output resolver-compatible (`path`, `file_id`, `url`, optional `filename`).
- For bonus file objects: materialize stable temp-file-backed paths and return canonical `path` entries.

### 2) Query-layer wiring (single path)

Primary touchpoint:
- `chatsnack/chat/mixin_query.py`

Approach:
- Introduce a small internal preprocessor used by `ask/ask_a/chat/chat_a/listen/listen_a`.
- Preprocessor should merge `usermsg`, template vars, and attachment kwargs into one consistent expanded user-turn append flow.
- Avoid per-method special cases so sync/async/listen stay behaviorally equivalent.

Secondary touchpoint only if required:
- `chatsnack/chat/mixin_messages.py`

Use only for narrowly scoped message-append utility updates if query-layer wiring cannot stay clean otherwise.

### 3) Runtime adapter impact

Expected adapter changes: **none or minimal**.

Validation targets only:
- `chatsnack/runtime/responses_adapter.py`
- `chatsnack/runtime/responses_websocket_adapter.py`
- `chatsnack/runtime/attachment_resolver.py`

Goal: adapters receive the same canonical message shape they already handle.

## 3HTDD test plan for Phase 3A

### Goal tests

1. `ask(..., files=["x.csv"])` sends one canonical expanded user turn and returns a response.
2. `chat(..., images=["chart.png"])` persists attachment turn and returns continuation chat.
3. `listen(..., files=["x.csv"])` accepts attachments and streams successfully.
4. Async parity: `ask_a/chat_a/listen_a` match sync attachment behavior.
5. Bonus: file object input on `files=` works end-to-end.

### Steer tests

1. Shared normalizer maps string -> `{path: ...}` into correct bucket.
2. Dict validation allows canonical keys and rejects ambiguous dicts.
3. Query-method parity test ensures all six entrypoints call the same normalizer path.
4. Expanded user-turn save order remains stable with text + images + files.
5. No-attachment call path remains unchanged.

### Unit tests

1. Temp-file lifecycle for file-object normalization.
2. Error text quality for unsupported input types.
3. Bucket safety checks (`images=` should not silently become `files=` and vice versa).

## Documentation rollout (required for Phase 3A)

### README

Add concise “Natural attachments” snippet near core query examples, including:
- one `ask(..., files=[...])` example,
- one `chat(..., images=[...])` example,
- one short note that YAML uses expanded user turns when attachments are present.

### Getting Started notebook

Add a short “Natural Attachments” section in `GettingStartedWithChatsnack.ipynb`:
- one quick `ask(..., files=[...])` cell,
- one quick `listen(..., images=[...])` or `chat(..., images=[...])` cell,
- keep it terse and demo-first.

### Experimental notebook (optional)

Add one compact mixed-attachment exploratory cell only if it clearly adds value over Getting Started.

## Risks and mitigations

- Risk: method drift between sync/async/listen variants.
  - Mitigation: single query-layer normalization path + parity tests.
- Risk: file-object complexity slows core delivery.
  - Mitigation: treat file objects as explicit bonus scope after path/dict green.
- Risk: hidden adapter regressions.
  - Mitigation: keep adapters unchanged; validate with targeted runtime tests.

## Definition of done (Phase 3A)

- `ask`, `ask_a`, `chat`, `chat_a`, `listen`, and `listen_a` all support `files=` / `images=` kwargs.
- Path/dict attachment inputs work for responses HTTP + WebSocket runtimes.
- Bonus file-object input works for `files=`.
- Goal/Steer/Unit tests are added and passing.
- README and Getting Started notebook contain concise, philosophy-aligned examples.
- Phase 3 checklist reflects completion status and progress notes.
