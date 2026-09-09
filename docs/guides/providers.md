# OpenAI-compatible Providers

A saved `Chat` can name its OpenAI-compatible endpoint and the environment
variable that holds its key. The saved YAML contains only the environment
variable name, so the key value stays out of the file.

## Use OpenRouter with a saved Chat

Save this as `datafiles/chatsnack/OpenRouterSnack.yml`, or place it under the
directory named by `CHATSNACK_BASE_DIR`:

```yaml
params:
  model: z-ai/glm-5.3-flash
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
messages:
  - system: Answer tersely and recommend excellent snacks.
```

Load it and use it like any other named Chat:

```python
from chatsnack import Chat

openrouter = Chat(name="OpenRouterSnack")
print(openrouter.ask("Name one movie-night snack."))

thread = openrouter.chat("Name one salty snack.")
thread = thread.chat("What drink pairs with it?")
print(thread.last)
```

`base_url` and `api_key_env` belong together. `api_key_env` names a nonblank
environment variable; its value is never written to the Chat YAML.

## Configure a dynamic Chat

Applications that construct Chats dynamically can use the same fields directly:

```python
from chatsnack import Chat

openrouter = Chat(
    "Answer tersely and recommend excellent snacks.",
    model="z-ai/glm-5.3-flash",
    base_url="https://openrouter.ai/api/v1",
    api_key_env="OPENROUTER_API_KEY",
)
```

## Use Azure v1

Azure v1 uses the same saved-Chat shape. Give it the complete `/openai/v1/`
base URL and put the Azure deployment name in `model`:

```yaml
params:
  model: my-deployment
  base_url: https://my-resource.openai.azure.com/openai/v1/
  api_key_env: AZURE_OPENAI_API_KEY
messages:
  - system: Answer tersely.
```

This path uses a static API key. Microsoft Entra authentication is outside the
current built-in provider configuration.

## Understand transport and client binding

Custom endpoints use Responses HTTP, including SSE streaming, unless a runtime
is selected explicitly. Chats without `base_url` and `api_key_env` keep the
standard `OPENAI_API_KEY` / `OPENAI_BASE_URL` SDK behavior and Chatsnack's
Responses WebSocket default.

Client settings are bound when a Chat is created or first loaded. Continued and
copied Chats keep that binding, and `reset()` does not re-read the credential
environment variable. Create a new Chat to use a different endpoint, credential,
or transport.

## GPT-6

The verified GPT-6 profile currently covers `gpt-6-astra`. Select that model
explicitly. Its documented API efforts are `low`, `medium`,
`high`, `xhigh`, and `max`; `auto` is the verified summary setting. The advisory
table recognizes the exact model ID. Additional snapshots and variants need
their own verification.

```python
chat = Chat("Respond tersely.", model="gpt-6-astra", runtime="responses")
chat.reasoning.effort = "low"
print(chat.ask("Name one movie snack."))
```

The corresponding saved configuration stays compact:

```yaml
params:
  model: gpt-6-astra
  runtime: responses
  responses:
    reasoning:
      effort: low
messages:
  - system: Respond tersely.
```

For this model, tools require Responses. When migrating an existing Chat, construct a new
one with the desired runtime and pass its Python capabilities in `utensils=[...]`.
See the saved stock-helper example in
[ReasoningModelValidation.ipynb](https://github.com/Mattie/chatsnack/blob/master/notebooks/ReasoningModelValidation.ipynb).
Live notebook calls require `CHATSNACK_RUN_LIVE_TESTS=1` and an API key.

For this model on direct OpenAI requests, remove `temperature`, `top_p`, and `top_logprobs`;
also remove Chat Completions `logprobs` and Responses
`include: message.output_text.logprobs`. Chatsnack warns at submission and forwards
the authored options unchanged. Sampling and endpoint advisories use the submitting
SDK client's resolved `https://api.openai.com/v1` URL; custom or unidentified
endpoints and unverified model aliases keep their existing behavior. Reasoning
values outside the verified table also warn and pass through.
[Official migration guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters).

This baseline covers ordinary Responses text and synchronous function utensils.
SDK 3.5.0 and 3.8.0 passed offline serialization and adapter checks; the existing
`openai>=3.5.0,<4.0.0` requirement remains. Provider async tools, mid-turn steering,
and ordered reasoning updates are separate planned work.

## Migrate legacy Azure configuration

Legacy Azure fields (`api_base`, `api_type`, `api_version`, and `deployment`) are
no longer accepted. Replace them with:

- `base_url` for the complete Azure v1 endpoint
- `api_key_env` for the name of the credential environment variable
- `model` for the Azure deployment name

The legacy endpoint variables `OPENAI_AZURE_ENDPOINT` and `OPENAI_API_BASE`
raise a migration error when no new endpoint is authored. Use per-Chat
`base_url` and `api_key_env`, or use the SDK-standard `OPENAI_BASE_URL` for
ordinary environment-wide configuration.
