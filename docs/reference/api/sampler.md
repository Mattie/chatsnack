# Sampler API and execution settings

Start with the [Sampler guide](../../guides/samplers.md) for authoring and composition.

## Public definitions and results

::: chatsnack.Sampler

::: chatsnack.Question

::: chatsnack.Sample

## Execution settings

Set `provider`, `model`, `timeout`, `retry`, `base_url`, and `api_key_env` in
`SamplerParams`, on the constructor, or for one call. Call overrides take precedence
over saved params, which take precedence over environment and provider defaults.

```python
sampler = Sampler(data="popcorn", model="jev-latest")
sample = sampler.ask("Crunchy?", timeout=20, retry={"max_retries": 0})
```

An explicit `provider` wins. Otherwise, a model beginning with `jev` selects
TypeSafe; the default is OpenAI with `gpt-6-luna`. TypeSafe uses
`TYPESAFE_DEFAULT_MODEL` or `jev-latest` when no model is authored. Explicit model
names pass through unchanged. `sampler.model` and `sampler.provider` expose the
authored settings.

`timeout` is an HTTP-operation timeout in seconds. OpenAI accepts
`retry.max_retries`. TypeSafe also accepts `backoff_initial`, `backoff_max`,
`backoff_jitter`, `http_statuses`, `respect_retry_after`, `api_connection_error`,
`api_timeout_error`, and the retry-budget `timeout`. Unsupported options raise
before evaluation.

`api_key_env` names a credential variable. By default, the selected SDK uses
`OPENAI_API_KEY` or `TYPESAFE_API_KEY`. `base_url` overrides `OPENAI_BASE_URL` or
`TYPESAFE_BASE_URL` and the provider's default endpoint. Credentials are never saved.

For Jev, a 400 `max_tokens_exceeded` response triggers one retry with extended
context. It reuses the resolved evidence, images, and connection without rerunning
fillings. This retry also applies when `retry.max_retries=0`; other errors and a
second rejection propagate normally. Each new evaluation starts with standard
context. Extended context remains experimental; see TypeSafe's
[context limits](https://docs.typesafe.ai/models#long-context).

## Client lifetime

A Sampler opens its synchronous client on the first `ask()` and reuses it.
Call `close()` when finished, or `await close_a()` from async code. `ask_a()`
creates and closes an async client for each evaluation.

Call-time connection overrides use a separate client. Changing only the model
reuses the connection if the provider stays the same. If you change authored
connection settings after evaluating, close the Sampler before using them.

## Request inspection

`compile()` and `compile_a()` return the provider request body. OpenAI uses
`input`, `model`, and a `questions` array; TypeSafe uses `state`, `model`, and a
`questions` map. `Question.compile()` returns its Jev-shaped definition.

Compilation can execute dependency fillings, though it doesn't evaluate the
Sampler itself. Inspect `.yaml` to see authored references without executing them.
Compiled Jev image requests contain base64 assets; execution uses SDK uploads and
adds capability headers separately. Compilation requires no TypeSafe SDK import.

## Images and fillings

`images=` accepts local paths, locally readable `ChatFile` values, captured asset
references, or an ordered list. It works on construction, evaluation, and
compilation, including image-only requests. URLs and provider file IDs aren't supported.

| Provider | Formats | Limits |
| --- | --- | --- |
| OpenAI | PNG, JPEG, WebP | 128 images, sent with `detail="auto"` |
| TypeSafe | PNG, JPEG | 16 MiB per file; provider-validated [dimensions and request limits](https://docs.typesafe.ai/images#limits) |

Jev vision is experimental and enabled automatically by image input. Images are
sent without resizing or conversion. Use `images=` for attachments; nested images
in data, instructions, or criteria and Box questions aren't supported.

Image precedence is call override → authored images → previous Sample images.
`images=[]` clears them, including after save/load. Evaluated `Sample.images` are
readable snapshots of the bytes sent. Keep the assets directory with replay YAML.
Compilation reads images without saving snapshots.

Use `fillings={...}` when a template variable collides with an execution keyword:

```python
Sampler(data="{provider}").ask("Good?", fillings={"provider": "a bakery"})
```

Ordinary keyword fillings also work. Duplicating a key across the two forms raises
an error. `provider`, `images`, and `fillings` are reserved; see the
[migration notes](../../migration/0.10.md).

Explicit Question names must be nonempty, unique within a batch, and contain none
of `.`, `[`, `]`, `{`, `}`, `!`, or `:`. Saved Sampler names must be nonempty and
exclude `{`, `}`, `!`, and `:`.

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

The public resolver requires `allow_sampler=True` to evaluate Sampler fillings.
`allow_chat` separately controls direct and transitive Chat fillings. Ordinary
`Chat.ask()` and `Sampler.ask()` need neither flag. `question.Name` returns a
Question object. One resolver call allows up to 16 Sampler evaluations; repeated
reads of the same evaluation count once.

## Answer details and replay

Yes/no ties select yes with zero confidence. Choice retains the provider's
selection; Score selects the first level with maximal probability. Numeric
scores and confidence retain their provider-specific meanings.

A `RefusalAnswer` keeps its original answer slot, has `.refused=True`, and returns
`None` for choice, score, probabilities, confidence, yes, and no. Successful
answers have `.refused=False`. Named result fillings support `.refused` too.

`Sample.params` returns a detached copy of the provider, reported model, effective
endpoint, and authored connection settings. The endpoint includes the public
default, so later environment changes can't redirect replay. Unset SDK timeout
and retry defaults remain delegated. `Sample.to_dict()` includes these settings,
image references, and refusal markers, excluding credentials and image bytes.

`Sampler.from_sample(sample)` restores the evaluated inputs and settings for
literal replay, including after save/load. Answers can differ on re-evaluation.
A follow-up `Sampler(data=sample)` uses the prior result as literal data while its
new questions can still use fillings.

::: chatsnack.SamplerParams

::: chatsnack.Answer

::: chatsnack.YesNoAnswer

::: chatsnack.ChoiceAnswer

::: chatsnack.ScoreAnswer

::: chatsnack.RefusalAnswer

## Provider contract

Both SDKs are included. See the provider documentation for
[OpenAI Decisions](https://developers.openai.com/api/docs/guides/decisions) and
[TypeSafe](https://docs.typesafe.ai/models).
