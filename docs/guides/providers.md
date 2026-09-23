# OpenAI-compatible Providers

Use the same `Chat` API with OpenRouter, Azure v1, or another OpenAI-compatible
provider. Set the provider's endpoint and tell the Chat which environment
variable holds its API key. You can save those settings with the prompt; the
key itself stays out of the YAML.

## Use OpenRouter with a saved Chat

Save this as `datafiles/chatsnack/OpenRouterSnack.yml`. If you've set
`CHATSNACK_BASE_DIR`, save it in that directory instead:

```yaml
params:
  model: z-ai/glm-5.3-flash
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
messages:
  - system: Answer tersely and recommend excellent snacks.
```

Then load the Chat by name:

```python
from chatsnack import Chat

openrouter = Chat(name="OpenRouterSnack")
print(openrouter.ask("Name one movie-night snack."))

thread = openrouter.chat("Name one salty snack.")
thread = thread.chat("What drink pairs with it?")
print(thread.last)
```

Supply `base_url` and `api_key_env` together. Before loading this example, set
`OPENROUTER_API_KEY` to your key. The variable must have a nonblank value;
chatsnack reads it when the Chat loads.

## Create the Chat in Python

You can pass the same settings to `Chat()`:

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

For Azure v1, use the full URL ending in `/openai/v1/` and put your deployment
name in `model`:

```yaml
params:
  model: my-deployment
  base_url: https://my-resource.openai.azure.com/openai/v1/
  api_key_env: AZURE_OPENAI_API_KEY
messages:
  - system: Answer tersely.
```

This setup uses a static API key. The built-in provider settings don't support
Microsoft Entra authentication yet.

## Choosing a connection

Custom endpoints use Responses HTTP, with SSE for streaming. Set `runtime`
explicitly if you need a different transport. If you leave out `base_url` and
`api_key_env`, the OpenAI SDK uses `OPENAI_API_KEY` and `OPENAI_BASE_URL` as usual,
and chatsnack defaults to Responses WebSocket.

A Chat reads its connection settings when it's created or first loaded.
Continuing or copying the Chat keeps those settings, and `reset()` doesn't read
a fresh key from the environment. To change the endpoint, key, or transport,
create a new Chat.

## GPT-6

Set `model` to `gpt-6-astra`, `gpt-6-sol`, or `gpt-6-luna`. Here's a small
request using Responses:

```python
chat = Chat("Respond tersely.", model="gpt-6-astra", runtime="responses")
chat.reasoning.effort = "low"
print(chat.ask("Name one movie snack."))
```

The same Chat in YAML:

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

For Astra, choose `low`, `medium`, `high`, `xhigh`, or `max`. Sol and Luna also
support `none`; their default is `medium`. For a reasoning summary, use
`chat.reasoning.summary = "auto"`. Sol and Luna also accept `concise` and
`detailed`; chatsnack has verified only `auto` for Astra. Chatsnack's GPT-6
checks recognize these three exact model IDs.
Other variants and dated snapshots still need verification.

Use Responses for tool calls with reasoning. Pass your Python functions in
`utensils=[...]`.
If you're moving an existing Chat from Chat Completions, create a new one with
`runtime="responses"`. There's a complete example that saves a stock helper and
continues the conversation in
[ReasoningModelValidation.ipynb](https://github.com/Mattie/chatsnack/blob/master/notebooks/ReasoningModelValidation.ipynb).
To run its live calls, set `CHATSNACK_RUN_LIVE_TESTS=1` and provide an API key.

When sending these models directly to OpenAI with reasoning enabled,
remove these unsupported options:

- `temperature`, `top_p`, and `top_logprobs` on either API.
- `logprobs` on Chat Completions.
- `message.output_text.logprobs` from `include` on Responses.

Chatsnack warns about these options and sends the request as you wrote it. The
checks use the sending SDK client's URL and apply only to
`https://api.openai.com/v1`. Custom or unidentified endpoints and unrecognized
model names won't receive these request warnings. You'll also get a warning for
reasoning values outside the verified table, and those values still pass through.
See OpenAI's [migration guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters)
for the provider's requirements.

You can use Responses text calls and synchronous Python utensils today. Support
for OpenAI's async tool-calling protocol, mid-turn steering, and ordered reasoning
updates is planned. The SDK requirement remains
`openai>=3.5.0,<4.0.0`; offline serialization and adapter checks passed on 3.5.0
and 3.8.0.

## Migrate legacy Azure configuration

If your Chat still uses `api_base`, `api_type`, `api_version`, or `deployment`,
replace those fields. Chatsnack no longer accepts them. Use:

- `base_url` for the complete Azure v1 endpoint
- `api_key_env` for the name of the credential environment variable
- `model` for the Azure deployment name

The old `OPENAI_AZURE_ENDPOINT` and `OPENAI_API_BASE` environment variables also
raise a migration error unless you've supplied a new endpoint. Set `base_url`
and `api_key_env` on each Chat, or use `OPENAI_BASE_URL` to set the endpoint
through the environment.
