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
- [x] Final design/code review and verification receipt.

What works now: saved vision Samplers evaluate mixed judgments, retain refusals,
and save replay YAML that still reads the evaluated image after the original
file disappears. Follow-ups carry that image or explicitly clear it.

Verification: the original isolated commit passed 1,185 offline tests, with
157 skipped. After integration and review fixes, 229 focused and example tests
passed. Strict docs, lock validation, and package builds passed. Four Jev live
checks passed on 2026-10-22; see the [Jev checklist](jev-1-14-checklist.md).

Final release review on 2026-10-27 examined `74c2631`: provider routing and the
default migration, SDK request translation, refusal slots, literal replay
inputs and captured endpoint bindings, image inheritance, bounded Jev recovery, scoped
headers, errors, and cancellation. An independent reviewer found no material
release blocker and reran 181 focused tests (2 skipped). This closes the final
design/code gate; it does not establish accuracy on untested application data.

The same release target passed 1,360 offline tests (188 skipped), lock validation,
a strict docs build, wheel/sdist builds and metadata checks, and a clean wheel
installation with dependency and public-API smoke checks. Six existing
`AsyncClient.aclose` cleanup warnings remain in the full suite. Terra's 11 live
checks passed before integration; the Jev live scope remains the four cases
documented above. Release notes now include the Sampler migration and Jev/Terra
changes. Publication has not started.
