# Muse model support in chatsnack

Research date: October 12, 2026. Repository baseline: `8b07921`, with the current working tree reporting version `0.10.0` and ongoing Sampler changes.

Follow-up, October 13, 2026: BASELINE + AUTO is implemented locally on
`codex/muse-wonder-auto`, based on public `master`. The intended common path is
`Chat("Invent cheerful, crunchy snacks.", model="muse-wonder-1.0")`, followed by
ordinary ask/chat, YAML inspection, save/load, fillings, and `utensils=[...]`.
Two live Goals passed through Joydex. The explicit connection/replay recipe
below records the pre-AUTO research baseline; those settings are now defaults
for the verified model, with authored overrides retained.

Muse Wonder fits our existing `Chat` and Responses HTTP path. The first delivery should add verified model advisories and a safe saved-chat example, then validate ordinary conversation and Python utensils against Meta. Hosted search and tool discovery need additional compatibility work. Wonder Full cannot currently be offered through a direct API integration.

## Model availability

| Model | Access relevant to chatsnack | Initial scope |
| --- | --- | --- |
| `muse-wonder-1.0` | Meta Model API; Standard mode only | Primary target |
| Muse Wonder Full | Muse Code subscriptions on Power Usage and Maximum Usage; unavailable on Model API | Document the access boundary |
| `muse-spark-1.3` | Meta Model API | Validate alongside Wonder where inexpensive |
| `muse-spark-1.3-contributor` | Meta Model API with Contributor mode | Explicit opt-in; different reasoning capabilities |
| Spark 1.2 and 1.1 | Meta Model API; 1.2 also has a Contributor variant | Register separately when verified |

Wonder and Spark accept the same requests. Wonder takes text, image, video, audio, and PDF input, produces text, and has a 1,048,576-token context window. Setting Wonder's reasoning effort to `max` does not select Wonder Full. [Meta model catalog](https://dev.meta.ai/docs/models).

Wonder costs $4 input, $0.20 cached input, and $20 output per million tokens. Spark costs $1.25, $0.15, and $4.25 respectively in Standard mode. Wonder has no API Contributor variant. Standard-mode content is not used to train Meta models; Spark Contributor IDs explicitly select different data-use terms. [Pricing and rate limits](https://dev.meta.ai/docs/pricing-rate-limits).

The public endpoint is `https://api.meta.ai/v1`, authenticated with a bearer token. Meta's examples use the environment-variable name `MODEL_API_KEY`. Wonder remains in preview. The team/project query parameters on the supplied documentation URL are dashboard context, and are unnecessary in API configuration. [Meta overview](https://dev.meta.ai/docs/overview).

## Existing support and concrete gaps

Responses is the appropriate default: Meta supports the OpenAI SDK and exposes HTTP/SSE Responses, Chat Completions, and Anthropic-compatible Messages. Responses supports reasoning continuity; Chat Completions does not preserve reasoning for external callers. We can reuse the installed OpenAI SDK rather than adding another SDK or a new conversation abstraction. [Choosing an API](https://dev.meta.ai/docs/protocols).

| Area | Current chatsnack behavior | Work needed |
| --- | --- | --- |
| Connection | `base_url` and `api_key_env` bind an isolated client. Custom endpoints default to Responses HTTP. Copies and continued chats retain the binding. | Use the existing connection surface. Avoid `session="inherit"` or `"new"`, which explicitly select our WebSocket path. |
| Reasoning controls | `chat.reasoning.effort` and `.summary` pass through, but Muse is absent from `_KNOWN_REASONING_MODELS`. | Add verified entries so supported settings stop producing the generic unknown-model warning. |
| Conversation replay | Ordered reasoning, calls, results, assistant phases, and provider extras survive in the transcript. Requests default to `store: false`. | Request encrypted reasoning in the supported Muse setup. Address replay of reasoning entries that lack encrypted content. |
| Python utensils | Function declarations, execution, argument streaming, and correlated results already use Responses shapes. | Validate against Meta, including parallel calls and the allowed tool choice. |
| Hosted web search | `utensil.web_search(sources=True)` injects an OpenAI-specific include path. | Adapt source retrieval for Meta without changing the public utensil call. |
| Hosted tool discovery | Groups and deferred declarations exist. Every `tool_search_call` is normalized as a local executable call. | Distinguish server execution from client execution before advertising discovery support. |
| Attachments | Image/file inputs and upload resolution exist. Upload purposes are `vision` or `assistants`. | Verify inline images and PDFs first; check Meta upload purposes before promising uploaded-file support. |
| Computer actions and custom tools | Unknown items can be preserved, but automatic execution supports a narrower set of tool types. | Add executor contracts separately if needed. Preserving a call is insufficient to execute it. |
| Samplers | The current OpenAI provider submits to `/decisions`; the alternative is TypeSafe. | Muse needs a separate structured-output adapter. Changing a Sampler's model and endpoint alone is insufficient. |

Local implementation references: [provider binding](../../chatsnack/chat/__init__.py), [model parameters](../../chatsnack/chat/mixin_params.py), [request advisories](../../chatsnack/runtime/model_advisories.py), [Responses normalization](../../chatsnack/runtime/responses_common.py), [conversation fidelity](../../chatsnack/runtime/conversation.py), [utensils](../../chatsnack/utensil.py), [attachment resolution](../../chatsnack/runtime/attachment_resolver.py), and [Sampler submission](../../chatsnack/sampler/provider.py).

## Compatibility rules

**Reasoning:** Wonder supports `minimal`, `low`, `medium`, `high`, `xhigh`, and `max`; `none` returns HTTP 400. Spark 1.3 Standard also supports `max`, but its Contributor variant does not. Responses summaries accept `auto`, `concise`, and `detailed`. Omitted effort leaves the choice to the model. Output limits and billing include reasoning tokens as well as visible text. [Reasoning guide](https://dev.meta.ai/docs/reasoning).

**Replay:** Meta omits `encrypted_content` unless requested with `include: ["reasoning.encrypted_content"]`. Its recommended stateless path combines that include with `store: false` and replays whole reasoning items. Each requires `summary`, which may be an empty list. A bare reasoning ID without encrypted content can fail with HTTP 400. Our existing mapper supplies the summary default but currently replays bare IDs too. Preserve `commentary` phases; Meta's final messages normally omit `phase`. Automatic truncation is unavailable. [Responses guide](https://dev.meta.ai/docs/protocols/responses).

**Tools:** Only `tool_choice="auto"` is currently supported; `none`, `required`, and named choices fail. Calls and results must remain correctly paired. `parallel_tool_calls` is supported, while `max_tool_calls` applies to built-in tools rather than local function execution. Function names allow at most one dot. These are useful advisory diagnostics, with caller-authored values still forwarded unchanged. [Tool calling](https://dev.meta.ai/docs/tool-calling).

**Search sources:** Meta requests raw hits with `web_search_call.results`; our `sources=True` currently requests `web_search_call.action.sources`. Cited sources arrive as `url_citation` annotations, which our normalizer already retains. Raw retrieved hits and cited sources are distinct. Meta's guide does not establish our `domains=` filtering contract, so validate that separately. [Search grounding](https://dev.meta.ai/docs/search-grounding).

**Tool discovery:** Server search emits `execution="server"` and `call_id=null`, followed by loaded definitions and ordinary function calls. Our current dispatch instead asks for a local search handler. Client search uses `execution="client"`; its result carries `call_id`, `tools`, and execution metadata. Our current helper builds `tool_call_id` and a string `output`, so that contract also needs a specific comparison and test. Namespace dispatch should preserve Meta's separate `namespace` and function name. [Tool search](https://dev.meta.ai/docs/tool-search).

**Structured output:** Responses uses `text.format`; Chat Completions uses `response_format`. Meta defaults `strict` to false. When true, every object needs `additionalProperties: false` and all properties in `required`; recursive schemas are rejected. Existing provider-option pass-through is enough to begin direct Chat validation. Sampler result normalization remains separate work. [Structured output](https://dev.meta.ai/docs/structured-output).

**Sampling:** Meta accepts temperature and top-p, unlike some of our OpenAI reasoning models. Leave them unset initially. Chat Completions rejects unsupported options including `stop` and `n > 1`. Do not reuse Astra's sampling restrictions for Muse. [Chat Completions guide](https://dev.meta.ai/docs/protocols/chat-completions).

**Files:** Meta documents uploads with `purpose="user_data"` and subsequent `file_id` references. The current resolver's purposes differ; inline inputs and uploads need separate acceptance checks. [File handling](https://dev.meta.ai/docs/file-handling).

**Computer use:** Meta declares `type="computer"` and returns action batches in `computer_call` items. The application executes them and supplies screenshots in `computer_call_output`. Our normalizer and executor do not yet implement this complete loop. Keep action execution under an explicit caller-provided utensil/executor contract. [Computer-use guide](https://dev.meta.ai/docs/computer-use).

## A chatsnack authoring path

Start with an authored asset using existing fields. Save this example as `MuseWonder.yml` in the configured chatsnack data directory after setting `MODEL_API_KEY` through the normal credential setup:

```yaml
params:
  model: muse-wonder-1.0
  base_url: https://api.meta.ai/v1
  api_key_env: MODEL_API_KEY
  runtime: responses
  responses:
    store: false
    include:
      - reasoning.encrypted_content
    reasoning:
      effort: high
      summary: auto
messages:
  - system: Answer tersely and recommend excellent snacks.
```

The notebook stays small:

```python
from chatsnack import Chat

wonder = Chat(name="MuseWonder")
print(wonder.ask("Name one movie snack."))

thread = wonder.chat("Invent a lunar popcorn flavor.")
thread = thread.chat("Give it a two-word name.")
print(thread.last)
print(thread.yaml)
```

This uses the existing API; today authored Muse reasoning emits an advisory warning. The example's provider acceptance still needs live validation. The key's environment-variable name is saved, while its value stays out of YAML.

Connection and replay settings belong with the asset; Python continues to author and compose chats. Local tools should remain `@utensil` functions passed through `utensils=[...]`. A future provider convenience should package these settings behind the same `Chat` surface if repeated setup warrants it. The first implementation does not need a new `MuseChat` class or public provider framework.

## Delivery sequence

**BASELINE — recommended first.** Register Wonder's exact verified ID and separately verified Spark variants in `mixin_params.py`, dated October 12, 2026 with direct official URLs. Review the existing defaults, role rules, every capability table, and matching policy together. Leave the global default-model decision separate: `ChatParams.model` is currently `gpt-4-turbo`, while `DEFAULT_MODEL_FALLBACK` is `gpt-5.4`.

Provide the saved Muse example with encrypted replay and a short exploratory notebook. Define safe behavior for an explicit configuration that omits encrypted reasoning: either use stored continuation when opted in, or warn and project out unusable reasoning items on the outgoing request while retaining saved history. Keep authored provider options intact. Do not silently force storage or rewrite effort.

Add endpoint-aware advisories for verified Meta limits using the resolved SDK URL. The current request-advisory helper deliberately applies only to `api.openai.com`, so a Muse registration alone cannot activate those warnings. Avoid assuming that OpenRouter aliases inherit every direct-Meta rule.

**TOOLS — next.** Keep `utensil.web_search(sources=True)` and grouped utensils as the public shapes. Translate inferred provider fields at the request boundary, preserve Meta's raw results, distinguish hosted from local tool search, and dispatch namespaced functions without collisions. Validate one hosted search and one deferred group end to end.

**ADVANCED — on demand.** Add native computer execution, custom text tools, background-job lifecycle, video/audio authoring, and a Muse Sampler adapter as separate features with concrete users. Muse Image uses different generation APIs and needs its own generated-asset assessment; Muse Voice Transcribe is speech-to-text; Glimmer is self-hosted. [Model families](https://dev.meta.ai/docs/overview).

## Acceptance and verification

Use [Three-Horizon TDD](../../3HTDD.md) for implementation. The primary Goal is a named Muse chat that asks, continues, saves, reloads, calls a Python utensil, and streams a readable answer while preserving reasoning and tool correlation. Keep a separate Goal for hosted discovery and sources so ordinary support can ship independently.

Steer checks should cover warning-free accepted efforts/summaries, advisory pass-through for `none` and unsupported tool choices, correct include merging, reasoning items with empty summaries, exact model matching, sync/async credential isolation, and save/load replay. For TOOLS, prove that server search never invokes a local handler and that client search returns Meta's required shape.

Verification completed:

- **188 existing tests passed** across provider binding, runtime defaults, Responses adaptation, conversation replay, and reasoning-summary streaming.
- An in-memory HTTP transport with OpenAI SDK **3.5.0** exercised a Wonder-configured `Chat`, a local utensil/result exchange, and another continued turn. Three outgoing requests replayed **0, 1, then 2** reasoning items, retained the encrypted-content include and `store: false`, and kept the dummy key out of YAML.
- A synthetic response without encrypted content reproduced a bare reasoning item in outgoing input.
- Meta's documented server-search shape reproduced our local-handler dispatch error.

These checks establish local request and replay behavior, not authenticated Muse inference. Before claiming provider support, run explicitly opted-in live acceptance checks for ordinary text, continuation, utensils, summaries, SSE, structured output, and attachments. Fetch `/v1/models` for the team's enabled IDs. Verify the output ceiling separately against model-specific official specifications or bounded live probes; do not infer Wonder's maximum output from a Spark quickstart or invent dated snapshots.

No runtime implementation changed during this research. Existing work in progress remains the baseline for the proposed changes.
