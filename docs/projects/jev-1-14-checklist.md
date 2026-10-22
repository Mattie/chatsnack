# Jev 1.14 incremental support

Extends the [Sampler adapter design](../rfcs/sampler-decisions-vision.md).
The existing Sampler/Question authoring and typed Sample flow stay in place.

## First slice: execution options and attached images

- [x] Require TypeSafe SDK 0.7.5 and decode its Pydantic responses.
- [x] Infer the image header from resolved images, including follow-ups and replay.
- [x] Start Jev requests normally; on an explicit 400 context-limit code, retry once with extended context.
- [x] Remove the public `experimental` parameter; keep capability headers request-scoped.
- [x] Support ordered PNG/JPEG attachments through existing `images=`.
- [x] Keep image-count and format/file-size policy in the selected adapter.
- [x] Keep `compile()` SDK-free, returning JSON with inspectable image assets.
- [x] Snapshot inspected bytes and preserve resolved evidence in saved replay.
- [x] Add a concise notebook example, guide, API, and migration notes.
- [x] Refresh the dependency lock; pass focused contracts, strict docs, and package builds.

Goal coverage: a saved Jev image Sampler still evaluates after its original photo
is deleted; async image-only calls, carried/cleared images, and named fillings
work; experimental headers never leak between requests sharing a client.
Contracts use the real SDK against in-memory HTTP, including multipart encoding
and Pydantic decoding. The live checks below also confirm synthetic image and
long-context judgments; representative application quality remains a later slice.

Initial verification on 2026-10-22: 107 focused Sampler tests passed, two paid live tests
skipped. The full offline run had 1,162 passing tests, 157 skipped, and one
unrelated existing failure: `test_reserved_event_types_are_defined` expects the
old runtime event set, while the pre-existing runtime work adds
`reasoning_summary_delta`. That work was left unchanged. Strict MkDocs build,
wheel/sdist build, Poetry lock validation, and diff whitespace checks passed.
The wheel requires `typesafe-sdk>=0.7.5,<0.8.0` and includes both adapter modules.

The redundant image opt-in has been removed. `images=` alone enables the Jev
image header; `images=[]` clears it for that call. Tests cover alternating image
and text requests on one retained client.
After simplification: 109 focused Sampler tests passed, two paid live tests
skipped, and the strict docs build and diff whitespace checks passed.

Long context is now automatic after a 400 `max_tokens_exceeded` error. The same
resolved wire request and SDK image objects are resubmitted once, with only the
long-context header added. Future calls start normally, including replay.
No token estimates, truncation, provider switches, repeated filling work, or
public experimental flags are involved. SDK transport retries remain independent
for each submission. A second rejection surfaces normally. Contracts cover both
execution styles, strict error matching, retained clients, named filling reuse,
image preservation, error propagation, and cancellation during the second attempt.
After automatic context handling: 128 focused tests passed and two paid live
checks were skipped. Strict docs build, wheel/sdist builds, and diff whitespace
checks passed. No live context-quality claim is made by these offline contracts.

Live verification on 2026-10-22: all four Jev tests passed in 4.12 seconds,
with `CHATSNACK_RUN_TYPESAFE_LIVE=1`:

- `tests/test_sampler_provider.py::test_live_mixed_questions` checks ordinary judgments.
- `tests/test_sampler_provider.py::test_live_jev_images_and_replay` recognizes a red
  280×280 PNG and replays its saved bytes after the original is deleted.
- `tests/test_sampler_jev_live.py` checks both sync and async context recovery with
  attached images. Each receives a real 400, retries once successfully with the
  same evidence and image header, and answers all three target judgments correctly.
  Jev reported 55,646 and 55,642 input tokens. A following short request succeeds
  without image or long-context headers, and the test process exits cleanly.

The first live run exposed the actual limit response shape:
`{"detail":{"error_type":"max_tokens_exceeded"}}`. The matcher now accepts this
structured code, with offline regression coverage. These checks establish recovery
for the tested document, rather than accuracy at the extended context limit.
Existing recorded comparison probes predate this correction.
The final focused offline run passed 132 tests, with all four paid checks skipped
as intended when the live opt-in is absent.
The isolated commit tree then passed the full offline suite: 1,185 passed,
157 skipped, with five existing async-client cleanup warnings. Strict docs passed.
Unrelated runtime, web UI, skill, and research work was excluded.

Jev image state is assembled as `images` references plus original `data` when
present. These fields are adapter output; saved Sample data stays unchanged.
Execution uses SDK image uploads; inspection shows the equivalent base64 JSON
body. Headers are execution options rather than body fields. No SDK objects or
image bytes enter saved YAML. Format and per-file byte limits are checked locally;
dimension, expanded-size, and context errors remain provider errors. Images are
sent as supplied, with no implicit resizing or conversion.

## Later slices

- [ ] Image values nested in data, Question instructions, and criteria, with replay.
- [ ] Explicit spatial Question authoring, BoxAnswer, and named `.box` fillings.
- [ ] Evaluate both providers on representative saved Questions before revisiting defaults.

Official contracts verified 2026-10-22:
[SDK changelog](https://docs.typesafe.ai/sdk/python/changelog),
[images and limits](https://docs.typesafe.ai/images),
[experimental context](https://docs.typesafe.ai/models#long-context), and
[request options](https://docs.typesafe.ai/sdk/python/api/clients/sync).
