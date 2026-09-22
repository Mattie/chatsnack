# Sampler 0.9.0 implementation

Branch: `feat/sampler-0-9`, based on `origin/master`; independent of PR #83.

Acceptance standard: short notebook cells and readable saved YAML. `ask()` always
returns a Sample; `.answer` and `.question` are its first existing collection items.

- [x] Authored models and request compilation: inferred questions, structured inputs, stable results.
  Inline, stored, and batch calls return Sample; aliases preserve identity and named lookup survives reordering.
- [x] Provider execution: included SDK, async/sync parity, decoding and cleanup.
  Real SDK HTTP contracts run with deterministic transports, including retries, errors, and cancellation.
  Reusable Samplers retain a lazy synchronous client like Chat; async evaluations use
  loop-scoped clients that close after each call, while connection overrides remain scoped.
- [x] Persistence and replay: explicit writes, preserved authoring forms, literal reconstruction.
  Live references, embedded values, custom stashes, and Sample-valued follow-ups survive save/load.
- [x] Fillings: typed Questions, named results, expansion-local reuse and authority.
  Tests cover repeated reads, separate bindings/stashes, cycles, cancellation, and the resolver's 16-call budget.
- [x] Notebook and guides: simple → durable → composable.
  `TastySamplersWithChatsnack.ipynb` executes offline in a dedicated test, checking the actual saved YAML.
- [x] Validation: offline contracts, optional live test, compatibility, package/docs builds.
  Strict MkDocs build, Poetry lock check, wheel/sdist builds, and a fresh plain wheel install pass.
- [x] Critical review and 0.9.0 version preparation.
  Independent review found two persistence defects; both were fixed and regression-tested.
  Version is 0.9.0. Publication remains separate.

## Verification

- Full offline compatibility suite after simplification: 844 passed, 125 skipped.
- Focused Sampler, notebook, SDK, and resolver contracts after dependency promotion:
  103 passed, 1 opt-in live test skipped.
- TypeSafe is included in the standard 0.9.0 install. A fresh plain wheel install
  automatically installs SDK 0.6.0, msgspec, and tenacity. Package metadata confirms
  the SDK is required without an extra; `pip check` passes.
- Plain-wheel Sampler execution and client cleanup pass with an in-memory HTTP
  transport. SDK imports remain lazy; authoring requires no provider credentials.
- The paid live contract is opt-in via `CHATSNACK_RUN_TYPESAFE_LIVE=1`.
  Verified against the live provider on 2026-09-17: 1 passed in 1.76s.
  The first live run exposed pending AnyIO worker-stop callbacks after synchronous
  execution. The sync bridge now drains completion callbacks; subprocess regression
  tests verify clean exit on success/failure in ordinary and notebook-style calls.
  Follow-up focused validation: 43 passed, 1 opt-in test skipped.
- Poetry reports existing metadata deprecations; package checks and builds succeed.

## Deferred

Conditional branches, post-evaluation text, saved Sample assets, workflow infrastructure,
global caching, streaming, other providers, and shared Chat/Sampler keyword-collision handling.
