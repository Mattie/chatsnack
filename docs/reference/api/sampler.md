# Sampler API and execution settings

Start with the [Sampler guide](../../guides/samplers.md) for authoring and composition.

## Public definitions and results

::: chatsnack.Sampler

::: chatsnack.Question

::: chatsnack.Sample

## Execution settings

`provider`, `model`, `timeout`, `retry`, `base_url`, and `api_key_env` can be authored in
`SamplerParams`, passed conveniently to the constructor, or overridden for one call.
Precedence is call override → saved params → SDK/environment defaults.

```python
sampler = Sampler(data="popcorn", model="jev-latest")
sample = sampler.ask("Crunchy?", timeout=20, retry={"max_retries": 0})
```

`sampler.model` and `sampler.provider` expose their authored params. An explicit
provider (`openai` or `typesafe`) wins. Otherwise, a model beginning with `jev`
selects TypeSafe; all other models select OpenAI. With neither setting, defaults
are OpenAI / `gpt-6-luna`. Only TypeSafe consults `TYPESAFE_DEFAULT_MODEL`, then
`jev-latest`. Explicit model strings pass through unchanged; provider/model
mismatches surface provider errors. The result retains the reported model.
Model aliases can move. Pin a provider version for calibrated applications.

```yaml
params:
  provider: typesafe
  model: jev-latest
  timeout: 20
  retry:
    max_retries: 3
```

`timeout` is an HTTP-operation timeout in seconds. OpenAI supports only
`retry.max_retries`, translated to the SDK's `max_retries`; other members raise
an actionable error before dispatch. TypeSafe's `retry` supports the SDK's
serializable fields: `max_retries`, `backoff_initial`, `backoff_max`,
`backoff_jitter`, `http_statuses`, `respect_retry_after`, `api_connection_error`,
`api_timeout_error`, and its total retry-budget `timeout`. Callables and exception
classes are excluded. The SDK owns transport retries for each submission.

`api_key_env` names a credential variable; credentials are never saved. Without
it, the SDK uses `OPENAI_API_KEY` or `TYPESAFE_API_KEY` for the selected provider.
`base_url` selects an alternate endpoint; otherwise the SDK honors
`OPENAI_BASE_URL` or `TYPESAFE_BASE_URL` and its default endpoint. No provider
fallback occurs.

Jev requests start with the provider's standard context limits. On an HTTP 400
with the explicit `max_tokens_exceeded` error code, chatsnack resubmits once with
the long-context header. The same resolved data, questions, image bytes, and
client are reused; dependency fillings do not run again. The second submission
preserves the image header when present. A second context failure surfaces
normally, and unrelated errors never trigger this correction.

This correction is independent of SDK transport retries, including when
`retry.max_retries` is zero. Each submission keeps the configured SDK timeout
and retry policy. It does not change retained client headers or future calls.
Saved/replayed Samplers need no context flags: every evaluation starts normally.
No token-count estimate, local truncation, provider switch, or public
`experimental` parameter is involved. Extended context remains an experimental
Jev capability, currently 262k tokens, with reduced accuracy and increased latency
on larger inputs. See [context limits](https://docs.typesafe.ai/models#long-context)
and [error codes](https://docs.typesafe.ai/api/errors).

## Client lifetime

Like `Chat`, a reusable `Sampler` opens its synchronous provider client lazily and
retains it across `ask()` calls. Call `sampler.close()` when a long-running
synchronous application shuts down. `ask_a()` creates and closes a scoped async
client for each evaluation so event-loop-bound transports are never retained on the
Sampler. `close_a()` remains the async-compatible way to close any retained sync
client when code uses both execution styles.

Changing `model` for one call reuses the connection when the effective provider
stays the same. Provider changes and call-time `timeout`, `retry`, `base_url`, or `api_key_env`
settings use a scoped client for that call. They do not replace the Sampler's
authored synchronous connection. If authored connection settings change after a
synchronous evaluation, close the Sampler before evaluating with the new settings.
An automatic long-context correction reuses the connection for that evaluation.

## Request inspection

`compile()` and `compile_a()` return the selected wire request: OpenAI uses
`input`, `model`, and a `questions` array; TypeSafe uses `state`, `model`, and a
`questions` map. They do not evaluate that Sampler, but executable dependency fillings
can make provider calls during resolution. Ordinary `.yaml` inspection preserves
live authored references and does not execute them.
For Jev images the inspected body contains base64 `assets`; execution instead
uses SDK image objects and multipart uploads. Experimental headers are execution
options, so they do not appear in the compiled body. Compilation needs no
TypeSafe SDK imports.

`Question.compile()` keeps its existing Jev-shaped inspection behavior. For
OpenAI, strings remain strings; structured data, instructions, and descriptions
become deterministic JSON text preserving authored order. Yes/no criteria become
a JSON instruction with the question and `yes`/`no` criteria. Choices become named
values; score levels keep authored labels and order. Anonymous questions keep
generated collision-safe identifiers.

## Images and fillings

`images=` accepts a local path, locally readable ChatFile, captured reference, or
ordered list, on construction, evaluation, and compilation. Image fillings
resolve once with expansion enabled. PNG, JPEG, and WebP are supported; URLs,
remote-only references, and file IDs fail before dispatch. OpenAI uses inline
data URLs with `detail="auto"` and a 128-image limit. Image-only evaluation works.
TypeSafe's image header is inferred from resolved image input, including inherited
or replayed images. `images=[]` removes both image assets and the image header
for that call.
No image opt-in is saved in params. TypeSafe accepts PNG/JPEG up to 16 MiB per
file. WebP is rejected before dispatch. Image dimensions, decoded/expanded
request sizes, and context limits are validated by the provider; images are
never resized or converted locally. See TypeSafe's
[limits](https://docs.typesafe.ai/images#limits).

When Jev images are present, the adapter wraps original data under `state.data`
(omitted for image-only requests), adds ordered references under `state.images`,
and uploads their bytes once per attachment. Text-only state is unchanged.
Images nested inside data, Question instructions, or criteria, and Box questions
are not supported in this slice.

Paths follow existing Chat conventions. Evaluation uses the same verified bytes
for request encoding and a content-addressed snapshot. Compilation reads images
without capturing assets or evaluating this Sampler. Base64 appears only in
inspected/wire requests, never saved YAML or `Sample.to_dict()`.

Image precedence is call override → authored images → previous Sample images.
An empty list clears them, including after save/load. `Sample.images` returns
locally readable ChatFile snapshots; keep the assets stash with replay YAML.

Use `fillings={...}` for variables colliding with execution keywords:

```python
Sampler(data="{provider}").ask("Good?", fillings={"provider": "a bakery"})
```

Ordinary keyword fillings remain supported. Duplicate keys across the explicit
mapping and ordinary kwargs raise an ambiguity error. New reserved names are
`provider`, `images`, and `fillings`; see the [migration notes](../../migration/0.10.md).

Explicit Question names must be nonempty strings without the filling
metacharacters `.`, `[`, `]`, `{`, `}`, `!`, or `:`. Those characters delimit
parts of named result fillings or have special meaning to the filling formatter.
Saved Sampler names similarly exclude `{`, `}`, `!`, and `:`; dots and brackets
remain valid in the asset-name segment.

## Advanced resolver

```python
from chatsnack import resolve_fillings_a

values = await resolve_fillings_a(
    ["sampler.SnackCheck.crunchy.score"],
    variables={"snack": "popcorn"},
    allow_sampler=True,
)
score = values["sampler"]["SnackCheck.crunchy.score"]
```

`allow_sampler=False` is the default for this public resolver. `allow_chat`
independently authorizes direct/transitive Chat fillings. Ordinary `Chat.ask()`
and `Sampler.ask()` need no authority flags. `question.Name` resolution returns
a typed Question. Explicit namespace overrides retain the resolver's opaque-value
behavior. Resolver-scoped Sampler work has a 16-evaluation limit; repeated reads
of one evaluation count once. Existing depth and expansion bounds still apply.

## Answer details and replay

Yes/no ties select yes with confidence zero. Choice preserves the provider's
selection even if another probability is larger. Score selects the first maximal
probability in authored level order. Provider numeric values are not rewritten.

Successful answers expose `.refused=False`. `RefusalAnswer` has `.refused=True`
and `None` for choice, score, probabilities, confidence, yes, and no. Refusals
retain original positions and named access even in all-refused batches. Named
Sampler fillings support the `.refused` leaf.

`Sample.params` returns a detached copy of effective provider/model, the selected
backend's environment endpoint when set, and authored nonsecret connection settings.
SDK timeout/retry defaults remain delegated when unset. `Sample.to_dict()` includes provider, params,
image references, and refusal markers, excluding credentials and image bytes.
The existing five positional Sample arguments remain valid; params and images
are keyword-only additions.

`from_sample()` restores these inputs/settings and records `expand: false` to keep resolved inputs literal across
save/load. Ordinary callers need no expansion controls. Samples hold results in
memory; this release does not introduce independently saved Sample assets.

Saving a follow-up `Sampler(data=sample)` automatically quotes literal braces in
the projected data. Reloading preserves that data while its newly authored
questions can still use fillings.

::: chatsnack.SamplerParams

::: chatsnack.Answer

::: chatsnack.YesNoAnswer

::: chatsnack.ChoiceAnswer

::: chatsnack.ScoreAnswer

::: chatsnack.RefusalAnswer

## Provider contract

Verified on 2026-09-17 against TypeSafe's [HTTP API](https://docs.typesafe.ai/api.md),
[structured question entries](https://docs.typesafe.ai/primitives/advanced.md),
[async Python client](https://docs.typesafe.ai/sdk/python/api/clients/async/client.md),
and [retry policy](https://docs.typesafe.ai/sdk/python/api/retries.md).
Verified on 2026-10-06 against OpenAI's [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
and [create contract](https://developers.openai.com/api/reference/resources/decisions/methods/create).
The existing OpenAI SDK generic `post("/decisions", body=..., cast_to=Dict[str, Any])`
avoids requiring a typed Decisions resource. Both SDKs remain included. No local
text context ceiling or truncation is imposed; oversized Jev requests receive
the single context correction described above before any remaining error surfaces.

Jev experimental images and long context verified on 2026-10-22 against
[images](https://docs.typesafe.ai/images), [models](https://docs.typesafe.ai/models),
and the [Python SDK changelog](https://docs.typesafe.ai/sdk/python/changelog).
TypeSafe SDK 0.7.5 or later in the 0.7 series is required; responses are decoded
from Pydantic models at the provider boundary.
