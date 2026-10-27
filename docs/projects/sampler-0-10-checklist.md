# Sampler 0.10.0 implementation

RFC: [Decisions and vision](../rfcs/sampler-decisions-vision.md).
Follow-on Jev work: [1.14 incremental support](jev-1-14-checklist.md).
Acceptance: reusable Questions, provider-independent results, captured image
evidence, and explicit Jev support.

- [x] OpenAI default and explicit TypeSafe routing, preserving model values.
- [x] Shared preparation/decoding for direct calls and named fillings.
- [x] Wire translation, structured rubrics, stable names and strict responses.
- [x] Refusal slots, nullable views and named `.refused` fillings.
- [x] Local images, snapshots, replay, inheritance and persisted clearing.
- [x] Provider-aware clients, scoped overrides and cancellation cleanup.
- [x] Reserved-key fillings escape hatch and retry validation.
- [x] Existing TypeSafe web examples explicitly pin their backend.
- [x] Notebook, guides, API reference, migration notes and 0.10.0 metadata.
- [x] Opt-in mixed-question/vision and long-context live checks.
- [x] Full offline suite, strict docs build and package builds.
- [ ] Final design/code review and verification receipt.

What works now: saved vision Samplers evaluate mixed judgments, retain refusals,
and save replay YAML that still reads the evaluated image after the original
file disappears. Follow-ups carry that image or explicitly clear it.

Verification: the original isolated commit passed 1,185 offline tests, with
157 skipped. After integration and review fixes, 229 focused and example tests
passed. Strict docs, lock validation, and package builds passed. Four Jev live
checks passed on 2026-10-22; see the [Jev checklist](jev-1-14-checklist.md).
