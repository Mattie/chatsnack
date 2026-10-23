# Jev 1.14 support

Builds on the [Sampler adapter design](../rfcs/sampler-decisions-vision.md).

- [x] Require TypeSafe SDK 0.7.5 and decode its Pydantic responses.
- [x] Accept ordered PNG/JPEG attachments through `images=` and infer the image header.
- [x] Retry an explicit 400 `max_tokens_exceeded` once with extended context.
- [x] Reuse resolved inputs and images on retry; keep headers scoped to the request.
- [x] Preserve image snapshots in replay, follow-ups, and named fillings.
- [x] Keep `compile()` SDK-free, with inspectable JSON assets.
- [x] Update notebook examples, documentation, and dependency lock.

A saved Jev image Sampler can evaluate after the original photo is deleted.
`images=[]` clears attachments for a call. Long-context recovery needs no authoring
flag and doesn't rerun fillings; other errors and a second rejection propagate.
Images are sent as supplied, with provider-specific format and size checks.

## Verification

- Full offline suite on the original isolated commit: 1,185 passed, 157 skipped.
- After integration with master and the replay-endpoint fix: 229 focused and example
  tests passed; strict docs, lock validation, and whitespace checks passed.
- Wheel and sdist builds include the adapters and require `typesafe-sdk>=0.7.5,<0.8.0`.

Four Jev live checks passed on 2026-10-22 with `CHATSNACK_RUN_TYPESAFE_LIVE=1`:
ordinary judgments, image replay after source deletion, and sync/async context
recovery with images. The context tests received a real 400, retried successfully
at about 55,600 input tokens, and answered all three target questions correctly.
Following short calls had no extra headers. This verifies those synthetic cases;
representative application quality and accuracy at the context limit remain untested.

Live contracts are in `tests/test_sampler_provider.py` and
`tests/test_sampler_jev_live.py`. Offline regressions cover the provider's actual
`{"detail":{"error_type":"max_tokens_exceeded"}}` response shape.

## Later slices

- [ ] Image values nested in data, Question instructions, and criteria, with replay.
- [ ] Spatial Questions, BoxAnswer, and named `.box` fillings.
- [ ] Compare both providers on representative saved Questions.

Provider contracts verified 2026-10-22:
[SDK changelog](https://docs.typesafe.ai/sdk/python/changelog),
[image limits](https://docs.typesafe.ai/images),
[long context](https://docs.typesafe.ai/models#long-context), and
[request options](https://docs.typesafe.ai/sdk/python/api/clients/sync).
