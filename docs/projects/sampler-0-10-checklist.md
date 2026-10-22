# Sampler 0.10.0 implementation

RFC: [Decisions and vision](../rfcs/sampler-decisions-vision.md).
Follow-on Jev work: [1.14 incremental support](jev-1-14-checklist.md).
Acceptance: terse authoring, provider-independent results, immutable evaluated
image evidence, and explicit Jev support. Publication is separate.

- [x] OpenAI default and explicit TypeSafe routing, preserving model values.
- [x] Shared preparation/decoding for direct calls and named fillings.
- [x] Wire translation, structured rubrics, stable names and strict responses.
- [x] Refusal slots, nullable views and named `.refused` fillings.
- [x] Local images, snapshots, replay, inheritance and persisted clearing.
- [x] Provider-aware clients, scoped overrides and cancellation cleanup.
- [x] Reserved-key fillings escape hatch and retry validation.
- [x] Existing TypeSafe web examples explicitly pin their backend; unrelated web UI edits remain separate.
- [x] Notebook, guides, API reference, migration notes and 0.10.0 metadata.
- [x] Opt-in implemented mixed-question/vision and long-context live checks (four Jev checks passed; OpenAI live checks remain opt-in).
- [x] Full offline suite, strict docs build and package builds.
- [ ] Final design/code review and verification receipt.

What works now: saved vision Samplers evaluate mixed judgments, retain refusals,
and save replay YAML that still reads the evaluated image after the original
file disappears. Follow-ups carry that image or explicitly clear it.

Final focused verification: 132 passed, four paid checks skipped in the isolated
commit snapshot. Strict docs build passed. The separate Jev live run passed all
four checks, including sync/async context recovery and image replay.
The final isolated commit tree passed the full offline suite: 1,185 passed,
157 skipped, with five existing async-client cleanup warnings. Existing example
Sampler definitions retain TypeSafe routing through explicit provider pins.
