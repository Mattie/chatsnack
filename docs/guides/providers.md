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
