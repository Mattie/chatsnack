# Muse Wonder BASELINE + AUTO

The baseline lets an ordinary Chat use Wonder for text, reasoning, local Python
utensils, durable history, and SSE. AUTO supplies the connection for the exact
documented `muse-wonder-1.0` ID when the caller has omitted connection settings.

- [x] Start from public `origin/master`, commit `735f09c` (October 13, 2026).
- [x] Verify the model ID, Meta endpoint, reasoning values, and replay requirements
  against current official documentation; annotate changed capability entries.
- [x] Infer `https://api.meta.ai/v1` and `MODEL_API_KEY` on construction and load.
- [x] Preserve explicit connection pairs, SDK endpoint settings, and runtime choices.
- [x] Keep copies, continuations, and reset bound to the resolved provider/key.
- [x] Persist resolved nonsecret configuration; resolve credentials on a fresh load.
- [x] Request encrypted reasoning for stateless replay; keep authored options intact.
- [x] Warn and project out unusable reasoning in generated stateless input while
  preserving saved history, stored continuations, and raw authored input.
- [x] Add a wire-level Goal for ask, utensil execution, copy, continuation, YAML
  reload, encrypted reasoning replay, and SSE, plus Steer tests for precedence.
- [x] Cover documented effort/summary values and advisory pass-through warnings.
- [x] Add a notebook and provider guide using normal Chat authoring, readable YAML,
  save/load, fillings, and `utensils=[...]`.
- [x] Add an explicit opt-in live Goal, with credentials supplied through Joydex.
- [x] Run two live Goals successfully against Meta (October 13, 2026; 13.88 seconds).
- [x] Complete regression checks and review the final diff.
- [x] Bump the package from `0.9.3` to `1.0.0` for the requested major version.
- [x] Build and check the `1.0.0` wheel and source distribution.

AUTO deliberately recognizes one documented API ID. Full is not a Model API
model. Hosted search/tool-search, native computer tools, and file workflows are
outside this baseline; they require separate protocol work.

Official references (verified October 13, 2026):

- [Models](https://dev.meta.ai/docs/models)
- [Reasoning](https://dev.meta.ai/docs/reasoning)
- [Responses and encrypted replay](https://dev.meta.ai/docs/protocols/responses)
- [Tool calling](https://dev.meta.ai/docs/tool-calling)

Validation: `tests/test_live_muse_wonder.py` uses `CHATSNACK_RUN_MUSE_LIVE=1`, with a bounded
output budget and a per-run tool fact to verify real execution and replay.
The live Goals passed using Joydex-injected `MODEL_API_KEY`, covering a model-only
ask, Python utensil execution, copy, continuation, encrypted history, save/load,
SSE, and an imported turn with an expired reasoning ID. Offline Goals also
exercise encryption opt-out and the actual notebook.

Final checks:

- 65 Wonder offline contracts passed.
- 394 focused runtime, binding, capability, and notebook metadata checks passed.
- Broad offline regression: 1,218 passed, 162 skipped. Command:
  `python -m pytest -q --ignore=tests/features/test_provider_client_configuration.py`.
  This run excludes the existing loopback-server fixture module; the Wonder
  Goals use the real SDK with an in-memory HTTP transport, plus live Meta.
- The regression run reported seven async-client cleanup warnings.
- Notebook JSON, unique cell IDs, and code syntax validated; actual cells executed
  in the offline Goal. `git diff --check` passed.
- Refetched public `origin/master` at completion; it remains `735f09c`, the branch base.
- Before committing, reran the 394 focused checks (all passed), built both package
  distributions, passed `twine check`, and verified their version and Muse AUTO
  code. `poetry check` passed; the version-only change leaves dependencies unchanged.

## Chatsnackian review — October 13, 2026

Reviewed all Muse changes against `chatsnack-fluency`, its pattern atlas,
`chatsnack-design-philosophy`, its notebook examples, README, PHILOSOPHY, and the
Getting Started and Experimenting notebooks.

The first notebook treated YAML-first authoring as Python file setup. It opened
with paths, a live flag, a YAML string, and cleanup wrappers before a useful Chat.
It also attached capabilities with `set_utensils()` instead of teaching the
constructor's `utensils=[...]` shape. That was a mismatch with the normal notebook
progression.

| Change | Review decision |
| --- | --- |
| `notebooks/MuseWonder.ipynb` | Rewritten: tiny Popsicle ask, named prompt, `.yaml`, `.save()`, `.load()`, a live filling, continued Chat, ordinary Python utensil, and streamed copy. No manual file writing, provider dictionaries, or live-flag branches in the examples. |
| `docs/guides/providers.md` | Lead with normal Chat calls and the Python-to-YAML authoring loop. Keep connection, reasoning, and replay details in compatibility notes. Move test commands to this checklist. |
| `chatsnack/chat/__init__.py` | Keep AUTO in existing construction/load binding hooks. No new provider class, wrapper, or authoring API. Persist nonsecret defaults and retain explicit choices. |
| `chatsnack/chat/mixin_params.py` | Keep the exact, documented model in the existing advisory table. Preserve caller-authored values. |
| `chatsnack/runtime/model_advisories.py` | Keep endpoint-specific warnings behind request submission; never rewrite caller options. |
| `chatsnack/runtime/responses_adapter.py` | Keep Meta replay handling inside HTTP adaptation. Preserve saved history and the existing escape hatches. |
| `tests/features/test_muse_wonder.py` | Update the notebook Goal to run its actual cells, including notebook-style await. Prove durable fillings, named reuse, utensil results, and streamed copy through the real SDK. Keep protocol assertions in tests. |
| `tests/test_live_muse_wonder.py` | Retain bounded, explicit paid-test setup and the two verified live Goals. That scaffolding belongs in tests. |
| `tests/conftest.py` | Retain the explicit Meta paid-test opt-in; environment-file loading must not enable it. |
| `pyproject.toml` | Set the requested major version to `1.0.0`; keep dependency requirements unchanged. |
| This checklist | Record the review, its correction, and concrete verification without expanding the public authoring surface. |
| Earlier `muse-support-research.md` | Retain the dated provider-contract research and mark its explicit setup example as the pre-AUTO baseline. |

The notebook's first API cell uses the existing `skip_test` metadata so the
legacy OpenAI notebook runner cannot initiate Muse calls through its OpenAI
live-test flag. Its cells and dependencies are covered by the dedicated offline
Goal; paid Meta tests keep their separate opt-in. A runner check with the OpenAI
live flag enabled verified that all eight code cells skip and issue no HTTP
requests without the dedicated Muse test path.

After the revision, 394 focused checks passed, including all 65 Wonder contracts
and execution of every actual notebook code cell. Runtime behavior did not
change in this review; the two Joydex-backed live Goals remain the implementation
evidence. Notebook JSON, cell IDs, await-capable code syntax, and diff whitespace
were checked again.

## PR review remedy — October 13, 2026

- [x] Confirm and fix the injected-runtime precedence issue: a custom runtime can
  submit a model-only Wonder Chat without `MODEL_API_KEY` or `OPENAI_API_KEY`.
  The shared model-default hook now skips SDK conveniences for custom runtime
  injection during construction and load; built-in adapters retain AUTO.
- [x] Prove ordinary construction, params, named autoload, and explicit load,
  followed by ask, copy, and continuation, without opening an SDK client.
- [x] Keep explicit connection validation and built-in adapter binding unchanged.

The four Goal variants failed with a missing Meta credential before the remedy.
They and the built-in adapter guard passed after the change.
The focused regression command from the final checks passed all 399 tests,
including 70 Wonder contracts; one existing async-client cleanup warning appeared.

- [x] Fix include ordering from the follow-up review: resolve model defaults before
  utensils merge generated includes. Explicit params and profile include overrides
  still win; no include-origin flags or new public configuration are needed.
- [x] Prove encrypted replay through generated includes, copy, continuation, and
  save/load using the actual SDK wire. This checks default composition, without
  claiming hosted Meta tool execution support.

The replay Goal failed and emitted an omission warning before the fix. It and four
explicit-override variants passed afterward; replay omission warnings are errors
in that Goal.
The expanded focused command, also including `tests/test_hosted_utensils.py`,
passed all 434 tests (75 Wonder contracts), with two existing async-client cleanup
warnings. `git diff --check` passed.
