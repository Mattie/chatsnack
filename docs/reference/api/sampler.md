# Sampler API and execution settings

Start with the [Sampler guide](../../guides/samplers.md) for authoring and composition.

## Public definitions and results

::: chatsnack.Sampler

::: chatsnack.Question

::: chatsnack.Sample

## Execution settings

`model`, `timeout`, `retry`, `base_url`, and `api_key_env` can be authored in
`SamplerParams`, passed conveniently to the constructor, or overridden for one call.
Precedence is call override → saved params → SDK/environment defaults.

```python
sampler = Sampler(data="popcorn", model="jev-latest")
sample = sampler.ask("Crunchy?", timeout=20, retry={"max_retries": 0})
```

`sampler.model` is backed by `sampler.params.model`. Unset models follow
`TYPESAFE_DEFAULT_MODEL`, then `jev-latest`; the result retains the reported model.
Model aliases can move. Pin a provider version for calibrated applications.

```yaml
params:
  model: jev-latest
  timeout: 20
  retry:
    max_retries: 3
```

`timeout` is an HTTP-operation timeout in seconds. `retry` supports the SDK's
serializable fields: `max_retries`, `backoff_initial`, `backoff_max`,
`backoff_jitter`, `http_statuses`, `respect_retry_after`, `api_connection_error`,
`api_timeout_error`, and its total retry-budget `timeout`. Callables and exception
classes are excluded. The SDK owns retry execution.

`api_key_env` names a credential variable; credentials are never saved. Without
it, the SDK uses `TYPESAFE_API_KEY`. `base_url` selects an alternate endpoint;
otherwise the SDK honors `TYPESAFE_BASE_URL` and its default endpoint.

## Request inspection

`compile()` and `compile_a()` return the resolved `state`, `model`, and `questions`
request. They do not evaluate that Sampler, but executable dependency fillings
can make provider calls during resolution. Ordinary `.yaml` inspection preserves
live authored references and does not execute them.

Structured instructions, criteria, and data remain structured. Choice lists
compile to null descriptions; Score level names are retained locally while the
ordered descriptions go to Jev.

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

`from_sample()` records `expand: false` to keep resolved inputs literal across
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

## Provider contract

Verified on 2026-09-17 against TypeSafe's [HTTP API](https://docs.typesafe.ai/api.md),
[structured question entries](https://docs.typesafe.ai/primitives/advanced.md),
[async Python client](https://docs.typesafe.ai/sdk/python/api/clients/async/client.md),
and [retry policy](https://docs.typesafe.ai/sdk/python/api/retries.md).
The optional SDK dependency is `typesafe-sdk>=0.6.0,<0.7.0`.
