# GPT-6 Astra support in chatsnack

Research date: 2026-09-08; live validation: 2026-09-09. The repository assessment records `c1e541f`, exactly `v0.8.1`; the original investigation used `b68551d`. BASELINE is implemented on `feat/gpt-6-astra-baseline`, with offline SDK checks and successful live Astra requests. Later deliveries remain proposed.

GPT-6 Astra has a documented API model ID, `gpt-6-astra`. Offline tests now establish ordinary text and synchronous function-call wiring through our Responses adapters. Full support still requires work on tool metadata, conversation replay, and active-response control. The delivery sequence is **BASELINE**, **FIDELITY**, **ASYNC**, then **STEERING**. Reasoning updates (**EFFORT**) can follow FIDELITY independently of the async scheduler.

## Recommended scope

Keep ordinary Astra use on `.ask()` and `.chat()`/`.chat_a()`, with named Chat/Text assets, compact YAML, utensils, and continued-Chat file ownership. The examples follow [PHILOSOPHY.md](../../PHILOSOPHY.md), [GettingStartedWithChatsnack.ipynb](../../notebooks/GettingStartedWithChatsnack.ipynb), and the [Phase 3 YAML](../rfcs/phase-3-responses-yaml-rfc.md) and [Phase 4A utensil](../rfcs/phase-4a-hosted-tools-utensils-rfc.md) boundaries.

Model names select capability data; execution paths use behavior-based rules. BASELINE now groups reusable GPT-6 reasoning and request-limit values, with `exact_naming` or `family_and_aliases` matching declared in the reasoning profiles. Adapters call generic model advisories. Additional verified models can reuse or override the data without new adapter branches. Apply the same approach to the later protocol work; the model discussed in this research should not become an execution abstraction.

The ponytail review narrows three commitments: implement provider async support for existing function utensils first; settle the steering surface through one adapter prototype before adding public lifecycle methods; reuse the existing composition examples instead of adding another tutorial. Custom-tool execution, a library wait utensil, and resumable background jobs are outside the first ASYNC delivery.

Retain ordered provider replay and the proposed reasoning-history control. Those support concrete continuation and effort-update behavior; dropping them would lose information. All new syntax below remains proposed, and advanced feature deliveries are separate from BASELINE.

## Changes to the plan for 0.8.1

- **BASELINE:** preserve 0.8.1's warning-free temperature pass-through for existing models and provider aliases. Any new Astra sampling diagnostic must use verified model and resolved provider identity, rather than classifying every reasoning model as incompatible. The old `_supports_temperature()` helper has been removed.
- **FIDELITY / STEERING:** build on the release's fixed provider/transport binding and continued-Chat ownership. Select HTTP or WebSocket when constructing the Chat; any active-work owner must retain that client's credentials and the session that submitted the request. Copy, load, and reset must honor the existing binding checks.
- **ASYNC:** 0.8.1 adds bounded direct filling resolution and cancellation cleanup for that resolver. Reuse relevant cleanup patterns, while keeping prompt preparation, model-tool jobs, and their budgets separate. Resolving a saved Chat still needs explicit `allow_chat=True` in the direct resolver.
- **Validation:** add the release's provider-binding and filling-resolution suites to the regression scope. The existing model defaults, SDK requirement, tool serialization, phase/replay, and WebSocket event gaps remain, so the proposed delivery order is unchanged.

Release comparison: `git diff b68551d v0.8.1`; `master`, `origin/master`, and `v0.8.1` all resolved to `c1e541f` during this update. The Responses adapters, utensil implementation, compact tool parser, and runtime usage types are unchanged from the original investigation. See the [provider guide](../guides/providers.md), [filling guide](../guides/fillings.md), and [provider-binding tests](../../tests/test_provider_client_binding.py).

## What the official API documentation establishes

These findings come from fetched official pages, rather than Codex model-picker labels. Availability to a particular API project, Azure deployment, or OpenRouter endpoint remains untested.

| Area | Verified behavior | Implication for chatsnack |
| --- | --- | --- |
| Model identity | The model page lists `gpt-6-astra` as both model ID and current snapshot; it lists no dated snapshot. | Accept this exact ID. Do not invent `gpt-6`, `gpt-6-astra-pro`, or dated aliases. [Model page](https://developers.openai.com/api/docs/models/gpt-6-astra). |
| Endpoint restriction | Astra supports Chat Completions, but its tool calling requires Responses. | Explicit legacy runtimes and environment overrides need a useful compatibility warning when tools are present. [Migration guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters). |
| Reasoning | API efforts are `low`, `medium`, `high`, `xhigh`, and `max`. `none` is rejected; migration guidance directs `none`/`minimal` users to start with `low`. | Update advisory validation. Codex's `ultra` setting is not established as an API effort by these sources. [Model page](https://developers.openai.com/api/docs/models/gpt-6-astra), [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning#reasoning-effort). |
| Sampling options | Remove `temperature`, `top_p`, and `top_logprobs`; also remove Chat Completions `logprobs` and Responses `include: message.output_text.logprobs`. | Warn with actionable migration guidance while preserving caller-authored options. [Migration guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters). |
| Async tools — new | Function/custom declarations and returned call items carry `async: true`. The model can keep working before the application supplies the result. Results retain the original `call_id` and use the latest response as continuation parent. | Requires pending-job tracking. Non-streaming requests can deliver results later; dispatch during streaming gives earlier overlap. Ordinary Python `async def` support alone does not implement this protocol. [Async tool calling](https://developers.openai.com/api/docs/guides/async-tool-calling). |
| Mid-turn steering — new | Send `response.steer` on the same WebSocket after `response.created`. Acceptance queues input; the server can create a successor response automatically. | Requires control messages, response lineage, and a reader that survives the original response's terminal event. [Steering](https://developers.openai.com/api/docs/guides/steering). |
| Reasoning updates — new | Append a `configuration_update` input item between responses while keeping request-level effort unchanged. Applies to Astra in standard, single-agent mode. | Requires ordered non-message input items and separate initial/effective effort state. [Reasoning updates](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation). |
| Monitoring — new Astra rollout behavior | A stopped request uses `misalignment_policy_violation`, including HTTP 403 before streaming; errors can also arrive during streaming. Further actions must stop. | Preserve the provider code and stop dispatch; never automatically retry that blocked workflow. [Monitoring](https://developers.openai.com/api/docs/guides/safety-checks/misalignment-monitoring). |

Astra also inherits GPT-5.6 capabilities including programmatic tool calling, multi-agent orchestration, persisted reasoning, compaction, pro mode, structured output, and hosted tools. These are not all new Astra protocols. The model page reports text/image input, text output, a 1,050,000-token context window, and 128,000 maximum output tokens. Hosted image generation is a separate tool capability. [Astra guide](https://developers.openai.com/api/docs/guides/latest-model#gpt-6-astra-what-is-new), [model page](https://developers.openai.com/api/docs/models/gpt-6-astra).

Caching changes inherited from GPT-5.6 matter when migrating our older defaults: use `prompt_cache_options.ttl: "30m"`; cache writes have a distinct charge, and explicit breakpoints live on supported input content blocks. Request-level reasoning changes can alter the cached prefix. Fast mode is unavailable for Astra with EU data residency. [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching), [Astra migration guidance](https://developers.openai.com/api/docs/guides/latest-model#update-api-and-model-parameters).

The Astra guide also describes a greater tendency to seek clarification, follow loaded instructions closely, format answers extensively, and test thoroughly. These are prompt/evaluation considerations. Keep application-specific autonomy and writing guidance in authored Chat prompts or reusable packs, with examples showing desired completion behavior; a library-wide personality rewrite is unnecessary. [Prompting guidance](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices).

## v0.8.1 implementation assessment

Locations below refer to the inspected revision. Linked source files use repository-relative links so this report remains portable.

### Defaults and every capability surface

Reviewed the entire [mixin_params.py](../../chatsnack/chat/mixin_params.py), including all default fields, the historical parameter matrix, `_KNOWN_REASONING_MODELS`, `_KNOWN_REASONING_EFFORTS`, `_REASONING_SUMMARY_OPTIONS`, role support, parameter pass-through, and prefix matching; rechecked its full release diff for 0.8.1.

- `DEFAULT_MODEL_FALLBACK` is `gpt-5.4` (line 10), while `ChatParams.model` is `gpt-4-turbo` (line 426). The fallback is used when a request lacks a model; creating `ChatParams` introduces the other default. This inconsistency predates Astra and should get a separate default-policy decision.
- The reasoning table covers GPT-5.6, GPT-5.5/pro, GPT-5.4/pro, GPT-5.1, generic GPT-5, o1, o3, and o4. Astra has no entry, so valid authored Astra reasoning generates a generic warning. `ultra` is absent from the union of known API efforts.
- The GPT-5.6 entry partly cites a Codex security CLI page. Future table changes should use API-specific model sources and put distinct variants ahead of family prefixes. This investigation does not re-certify every older model's table values.
- 0.8.1 removes `_supports_temperature()` and the automatic temperature warning. `test_reasoning_model_temperature_passes_through_without_local_warning` explicitly preserves warning-free pass-through for `gpt-5.4`. Astra sampling diagnostics remain proposed work and must preserve that release behavior. `top_p` and logprob combinations also have no Astra-specific check.
- System/developer handling excludes old o1 variants; it does not force an Astra role rewrite. No new role rewrite is justified by the fetched Astra guidance.
- The historical matrix ends with older model families. It should be dated/identified as historical or maintained alongside the executable rules, rather than treated as an Astra specification.
- Reasoning is forwarded without an implicit effort in current code. [test_runtime_defaults.py](../../tests/test_runtime_defaults.py) explicitly covers that behavior. The older [Phase 4 checklist](phase-4-responses-websocket-default-checklist.md) still claims low-effort injection and opt-in encrypted reasoning; those notes need reconciliation before they guide implementation.

Our runtime default is Responses WebSocket with an inherited session; custom endpoints default to Responses HTTP. `CHATSNACK_DEFAULT_RUNTIME=chat_completions` and explicit runtime selection can still route an Astra tool request incorrectly. See [chat/__init__.py](../../chatsnack/chat/__init__.py), `_runtime_policy_from_env` (line 42).

### Request shape and tool execution

| Surface | What works structurally | Confirmed gap from source inspection |
| --- | --- | --- |
| Provider options | `params.responses` forwards provider options; HTTP moves SDK-unknown top-level options into `extra_body`. | This escape hatch cannot make the scheduler understand new events. `build_responses_request()` overwrites `input`, so a raw `params.responses.input` does not add configuration items. [Request builder](../../chatsnack/runtime/responses_common.py), line 382; [HTTP adapter](../../chatsnack/runtime/responses_adapter.py), line 32. |
| Function declarations | Adapter-level normalization preserves extra keys and flattens nested function definitions. | Public `set_tools()` converts through `ToolDefinition`/`FunctionDefinition`, which omit `async`, `allowed_callers`, and `output_schema`. `ToolDefinition.from_dict()` expects a nested `function` object; flat API examples lose their function body through this path. [Parameter types](../../chatsnack/chat/mixin_params.py), lines 296–419. |
| Compact YAML | Local functions, namespaces, hosted tools, and deferred loading already have compact forms. | `async` is absent from reserved child keys, and cleanup reconstructs a limited function field set. Adding it in compact syntax without parser work can treat it as an argument or discard it. [compact_tools.py](../../chatsnack/compact_tools.py), lines 6, 172, 500–533. |
| Local utensils | `chat_a()` obtains a completed response and executes tool batches in an automatic follow-up loop. | It awaits each tool in sequence. Function dispatch calls `func(**arguments)` synchronously and stringifies non-dicts; a coroutine-returning utensil is not awaited on that path. [Query loop](../../chatsnack/chat/mixin_query.py), lines 1248–1327; [utensil dispatch](../../chatsnack/utensil.py), line 646. |
| Streamed calls | WebSocket emits complete function calls at `response.output_item.done`, with the correct `call_id`. | The event omits `async` and other call metadata. The listener exposes events but has no pending-tool scheduler. [WebSocket adapter](../../chatsnack/runtime/responses_websocket_adapter.py), line 911; [listener](../../chatsnack/chat/mixin_query.py), line 51. |
| Custom tools | Raw non-function declarations can pass through. | `custom_tool_call` is not normalized into an executable call; generic tool results become `function_call_output`. Declaration pass-through therefore does not establish custom-tool support. [Responses normalization](../../chatsnack/runtime/responses_common.py), lines 102, 409. |

The actual automatic runtime path is `ChatQueryMixin`; the older direct Chat Completions methods in `ChatUtensilMixin` should not be mistaken for the active Responses implementation. `Chat` puts `ChatQueryMixin` first in its inheritance list.

### History, terminal events, and SDK readiness

The shared normalizer folds all assistant output text into one message. It populates metadata named `assistant_phase` from an item's **status**, rather than its `phase` (line 426). Request replay reconstructs messages without `phase`; it also does not reinsert complete ordered reasoning items. Although diagnostic metadata retains much of the provider output and the assistant can store one encrypted-content value, these do not currently provide lossless replay. [responses_common.py](../../chatsnack/runtime/responses_common.py), lines 102–238, 409–646; [mixin_messages.py](../../chatsnack/chat/mixin_messages.py), line 383.

This particularly affects HTTP `store=False` continuations, save/load, and reconnect recovery after a cached response ID is unavailable. The active WebSocket connection can preserve provider context through `previous_response_id`, which reduces exposure while that state remains available. Official guidance calls for retaining output items, including reasoning and assistant phases, when replaying manually. [Reasoning continuity](https://developers.openai.com/api/docs/guides/reasoning#preserve-reasoning-across-calls), [WebSocket continuation](https://developers.openai.com/api/docs/guides/websocket-mode#how-continuation-works).

Both WebSocket reader paths stop at `response.completed`, ignore `response.created` and steering events, and lack a `response.incomplete` terminal branch. An incomplete response can leave a reader waiting for more events on an open socket; if the stream closes, it reports a receive failure. The session also has one `last_response_id` and rejects concurrent response requests. These choices need deliberate extension for steering. Merely removing the in-flight guard would introduce competing readers and incorrect routing. [responses_websocket_adapter.py](../../chatsnack/runtime/responses_websocket_adapter.py), lines 83, 656, 713, 856.

`pyproject.toml`, `poetry.lock`, and the installed environment use an OpenAI floor/locked version of 3.5.0. Inspection of the installed package found no `steer` method or `configuration_update` type; its function declaration and call types omit `async`. The current WebSocket guide recommends `openai[realtime]>=3.8.0`. This establishes a documented candidate upgrade, not the exact first version containing every Astra feature. Verify the selected SDK's concrete methods, event types, and serialization before changing the floor. [Dependencies](../../pyproject.toml), [lock](../../poetry.lock), [SDK setup](https://developers.openai.com/api/docs/guides/websocket-mode#connect-and-create-responses).

### Inherited advanced features

- **Programmatic tool calling:** requires `allowed_callers`, `output_schema` where applicable, `program`/`program_output` items, and copying `caller` onto function outputs. Our generic function normalization drops `caller`; program items have no semantic handling. Treat this as a separate integration after FIDELITY. [Official guide](https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling).
- **Multi-agent:** the guide uses beta Responses SDK surfaces and the `responses_multi_agent=v1` header. WebSocket can inject tool results during a running response. Our adapter has no beta-mode setup or such injection path. Root/subagent provenance and final-answer selection need testing before advertising support. [Official guide](https://developers.openai.com/api/docs/guides/responses-multi-agent).
- **Caching/pro mode:** nested request dictionaries can carry these options, subject to SDK support. Explicit cache breakpoints need content-block fidelity. `last_call_usage` retains raw provider usage, but its typed aggregate has no cache-write count; do not infer billable cost from cached-input counts alone. [Usage implementation](../../chatsnack/runtime/usage.py), [caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).
- **Hosted tools:** existing web/file search, code interpreter, image generation, tool search, MCP declarations, and caller-executed apply-patch provide a useful starting point. The model listing a tool does not prove chatsnack handles every response/approval subtype. This report does not certify the entire tool catalog.

## Concrete proposals

### BASELINE — recommended first delivery

Implemented on `feat/gpt-6-astra-baseline`:

- [x] Reusable GPT-6 capabilities for `low|medium|high|xhigh|max`, registered for the verified `gpt-6-astra` ID with dated official references and an explicit exact-matching policy. Unverified variants and snapshots remain unknown; only summary `auto` is verified. Other authored values warn and pass through. The obsolete comment-only parameter matrix was removed.
- [x] Generic submission-time model advisories apply registered request limits, scoped to the actual SDK client's direct OpenAI endpoint and exact model ID. HTTP, WebSocket, sync/async, and streaming paths preserve authored options and runtime selection; another model needs only a data entry to reuse these limits.
- [x] Saved-Chat Goal test exercises the real SDK with a fake HTTP transport, callable rebinding, stock execution, and continued history. Added the opt-in notebook example and [migration guidance](../guides/providers.md#gpt-6).
- [x] Evaluated SDK 3.5.0 and 3.8.0 offline: five efforts and ordinary function-call serialization/parsing passed across sync/async HTTP and WebSocket; the existing adapter/normalization suite passed 110 tests on each version before implementation. Retain `openai>=3.5.0,<4.0.0`; BASELINE needs no newer protocol fields.
- [x] Final implementation checks: 348 passed and 12 skipped on each SDK version, including synthetic model profiles that prove matching and request advisories are data-driven. Five additional provider-configuration checks passed on 3.5.0. All six notebook code cells parsed and executed with live calls disabled. Independent implementation review completed; the Goal also verifies resolved Text and task fillings in the submitted request.
- [x] Live Astra acceptance on 2026-09-09 with SDK 3.5.0: all five efforts returned text through Responses HTTP; `medium|high|xhigh|max` also used summary `auto`. Responses WebSocket and Chat Completions text probes passed at `low`. The saved notebook helper loaded its Text asset and utensil, returned 12 units, and retained that quantity in the follow-up. The initial standalone smoke returned successfully but stalled during shutdown and was stopped; the subsequent full probe batch exited cleanly. Advanced protocols and exhaustive streaming combinations remain untested live.

The two pre-existing default-model paths remain unchanged. Construct a new Chat to change a bound transport, and use explicit Responses for utensil probes so an environment override cannot select Chat Completions.

Start the notebook with existing public syntax:

```python
from chatsnack import Chat

snack = Chat("Reply with one enthusiastic snack name.", model="gpt-6-astra")
print(snack.ask("Movie night!"))
```

Then demonstrate a named capability and a continued Chat. This uses existing authoring syntax and passed the live notebook acceptance check:

```python
from chatsnack import Chat, Text, utensil

Text(name="StockStyle", content="Answer briefly from the stock result.").save()

@utensil
def stock(sku: str):
    """Read demo stock for a product."""
    return {"sku": sku, "available": 12}

stock_chat = Chat(name="StockHelper", model="gpt-6-astra",
                  runtime="responses", utensils=[stock])
stock_chat.system("{text.StockStyle}").user("Check stock for {sku}.")
stock_chat.reasoning.effort = "low"
stock_chat.save()

thread = stock_chat.chat(sku="snack-box")
print(thread.last)
```

Compact saved asset excerpt; the associated Text asset holds the reusable wording:

```yaml
params:
  model: gpt-6-astra
  runtime: responses
  tools:
    - stock: Read demo stock for a product.
      sku: str
  responses:
    reasoning:
      effort: low
messages:
  - system: "{text.StockStyle}"
  - user: Check stock for {sku}.
```

Later application code can load this named Chat, attach `utensils=[stock]`, and pass `sku=`. YAML retains the declaration; the application supplies the callable. Keep the template's placeholders live when saving and composing it. `.ask()`/`.ask_a()` return text without advancing the source Chat; `.chat()`/`.chat_a()` return the continued Chat, which owns history, usage, and returned files.

The saved stock flow is covered offline; the live version remains opt-in. Keep explicit Astra selection, and revisit SDK requirements when implementing later protocols.

### FIDELITY — prerequisite for reliable continuation

Preserve complete ordered provider input/output items behind the readable Chat transcript. Keep `messages:` as the primary authored transcript and default YAML terse; extend the existing explicit state-export path under `params.responses.export_state` instead of adding a parallel top-level transcript. Save/load without state export preserves authored conversation meaning and captured assets. Exact replay requires the exported provider state or an available compatible provider session. Neither mode serializes live jobs or promises that they resume automatically.

Preserve per-message `phase`, reasoning items, `async`, `caller`, custom-call type, IDs, and unknown provider metadata end to end. The official Python async example reads `call.async_`, while the wire field is `async`; verify alias-aware SDK dumps and reconstruction rather than assuming attribute and JSON names coincide. Keep item status and phase separate, and update HTTP continuation eligibility, which currently consumes the misleading `assistant_phase` value. Use the ordered item history for HTTP stateless replay and WebSocket recovery. Keep generated media capture under the existing artifact policy rather than indiscriminately persisting raw image payloads.

Tradeoff: the internal provider history needs synchronization with authored assets. Bind it to the concrete resolved input used for each submitted turn, including Text/Chat fillings, included messages, and ordinary filling values. A saved Text or included Chat can change while the outer template stays identical. Preserve authored placeholders; invalidate cached continuation when its resolved prefix changes, and freeze already-submitted content in the continued Chat. Test copying, branching, save/load, and replay with those cases. Fixing individual dropped fields without preserving order will remain brittle as new item types arrive.

Generated outputs remain on the continued Chat: use `.images` and `.files`, pass a `ChatFile` through `images=` or `files=`, and retain compact `asset` references in saved YAML. Provider item preservation must cooperate with that artifact policy so apps do not need to unpack response dictionaries or carry base64 themselves. A portable saved conversation includes the referenced asset bytes.

Preserve the 0.8.1 `_assert_bound_configuration()` guard and `_inherit_authored_runtime_override()` behavior. Continuation metadata and any new item history must follow the actual submitting runtime, while construction/load overrides retain authored intent. The release shallow-copies `ChatParams` for continued Chats; new mutable history and effective-effort state need an explicit ownership policy and isolation tests rather than relying on that shallow copy. [Chat binding](../../chatsnack/chat/__init__.py), line 499; [query ownership](../../chatsnack/chat/mixin_query.py), lines 1120, 1186.

### ASYNC — let utensils run while the model works

The first async-tool example should stay on `.chat_a()`. The decorator's `async_` option and coroutine execution are proposed additions; this complete example is a design target:

```python
import asyncio
from chatsnack import Chat, Text, utensil

Text(name="ReturnPolicy", content="Unopened snacks have a 14-day return window.").save()

@utensil(async_=True)
async def delivery_eta(order_id: str):
    """Simulate a slow delivery lookup for the notebook."""
    await asyncio.sleep(1)
    return {"order_id": order_id, "days": 3}

helper = Chat(name="OrderHelper", model="gpt-6-astra",
              utensils=[delivery_eta])
helper.system("Start the lookup early. Explain returns while waiting. {text.ReturnPolicy}")
helper.user("Track order {order_id} and explain the return policy.")
helper.save()

thread = await helper.chat_a(order_id="42")
print(thread.last)
```

Proposed compact YAML excerpt, with `async` carrying capability metadata:

```yaml
params:
  model: gpt-6-astra
  tools:
    - delivery_eta: Simulate a slow delivery lookup for the notebook.
      async: true
      order_id: str
messages:
  - system: Start the lookup early. Explain returns while waiting. {text.ReturnPolicy}
  - user: Track order {order_id} and explain the return policy.
```

The application awaits one continued Chat; the runtime can overlap eligible lookup work and provider generation internally. Observing that overlap requires an event-oriented acceptance probe. Keep the caller's `stream` choice out of this introductory example. Loading stays small: `helper = Chat(name="OrderHelper", utensils=[delivery_eta])`, then `helper.load()` and `await helper.chat_a(order_id="42")`. The application rebinds executable capabilities; saved YAML carries their declarations. Preserve and validate those declarations through load.

`async_` opts into the provider protocol; coroutine-returning Python utensils must also work without that flag. Reserve YAML `async` as metadata, retaining structured `args` for an argument with that name. Keep blocking synchronous work off the socket reader; worker selection can stay internal.

Scope the first delivery to direct function utensils, using a call-scoped pending-job map in the existing query loop. Register each complete call before dispatch, retain its original `call_id` and metadata, and correlate results through the latest compatible continuation. Handle mixed batches and duplicate events. Custom-tool execution already lacks a public executor path; document that gap and add it separately when a concrete custom utensil needs it. Retaining opaque provider items does not require executing them.

`.chat()`/`.chat_a()` should drain required jobs before returning a completed Chat; `.ask()` keeps its text-returning contract. Pending tasks belong to the submitting call and stay out of copy/save/load. Define bounded concurrency, timeout, failure, and cancellation cleanup without adding a background-job service or wait utensil. Preserve `auto_execute=False`, `auto_feed=0`, and positive follow-up budgets; report unfinished work on exhaustion. Cancellation cannot undo effects or stop a synchronous worker already running, and failures must expose uncertain work without automatically redispatching it.

Finish prompt preparation before submission. Keep direct filling resolution, its authority/bounds, and its cleanup separate from model-tool jobs; the existing resolver tests cover that release contract. [Resolver](../../chatsnack/fillings.py), line 241; [cleanup helper](../../chatsnack/asynchelpers.py), line 7. Provider async supports direct function/custom tools, excludes hosted built-ins and programmatic invocation, and cannot combine with parallel tool calls in Multi-agent mode; the first delivery implements the function subset. [Async constraints](https://developers.openai.com/api/docs/guides/async-tool-calling).

Use existing composition for richer prompts: ordinary fillings for user input, Text for reusable guidance, Chat fillings for generated preparation, and `include` for selected prior messages. Keep placeholders live until submission. A pending utensil result retains its tool-call identity; it is not a Chat filling. See the [existing filling guide](../guides/fillings.md) for the complete composition examples.

### STEERING — prove the lifecycle before choosing its public API

Defer the proposed `Chat.start_a()`/run-handle family. First prototype steering through the existing adapter's single reader and the call-scoped execution loop. The current listener has neither automatic tool execution nor a final continued Chat, so reusing it needs evidence; preserve its current behavior. Publish one opt-in control surface after the prototype shows the smallest required addition. Ordinary ASYNC remains independent of that choice.

The prototype must prove these contracts:

- Snapshot the source and resolve input before becoming steerable. Later source edits cannot change submitted work; completion yields a continued Chat with applied steering in the observed conversation order.
- Send control writes on the submitting WebSocket after `response.created`. Distinguish acceptance from application, retain accepted/pending/failed IDs and successor lineage, and aggregate usage across responses.
- Keep reading through `incomplete(reason="steered")` and through an original completion that still has pending steering. Submit required tool outputs on the same connection without repeating accepted text; a normal automatic successor needs no extra `response.create`.
- End ordinary incomplete responses correctly. On disconnect, report uncertain steering and tool work; do not automatically replay it. Keep HTTP steering unsupported and distinguish one response ending from the whole call finishing.

This delivery needs no WebSocket multiplexing, persisted active-job recovery, or new general event framework. Completed Chats use the existing save/export surfaces; do not promise to resume an active correction after load. [Steering lifecycle](https://developers.openai.com/api/docs/guides/steering).

### EFFORT — change reasoning without rewriting the prefix

Keep `chat.reasoning.effort` as the request-level configuration property. Automatically changing its meaning after the first call would make the same assignment depend on hidden session state. Add an explicit history operation, proposed as:

```python
chat = Chat("Write practical migration plans.", model="gpt-6-astra")
chat.reasoning.effort = "low"
thread = chat.chat("Draft a migration plan.")
thread.reasoning.update(effort="high")
thread = thread.chat("Now examine failure recovery.")
print(thread.last)
```

Proposed saved YAML excerpt:

```yaml
params:
  model: gpt-6-astra
  responses:
    reasoning:
      effort: low
messages:
  - system: Write practical migration plans.
  - user: Draft a migration plan.
  - assistant: ...
  - reasoning: {effort: high}
  - user: Now examine failure recovery.
```

The method and standalone `reasoning` control entry do not exist today. The method would append authored configuration at that position without sending a request, matching the history-editing intent of `.user()`. During submission the entry becomes `{"type":"configuration_update","reasoning":{"effort":"high"}}`. The readable entry preserves authored order through save/load and `include`; it must survive even when provider-state export is disabled. Ordinary assistant reasoning summaries remain output metadata. They never become configuration controls.

Preserve the original request-level effort and track effective effort separately: the provider response still reports the request-level value. A small new history control is warranted because putting only the latest effort in `params` loses where it changed. Keep the full provider item available through the explicit fidelity/export path, with the existing `params.responses` escape hatch for request options.

Warn about unsupported mode combinations and adjacent updates while preserving authored provider input. Restrict the convenience method to valid Astra standard, single-agent usage; check adjacency and mode compatibility again after includes expand. Automatic compaction/truncation and standalone `/responses/compact` cannot be combined with updates; explicit `compaction_trigger` requires a fresh update after compaction. Keep this feature opt-in until those interactions are tested. [Exact compatibility rules](https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation).

### MONITORING — preserve actionable stop behavior

Recognize `misalignment_policy_violation` as a terminal, non-retriable condition across HTTP and WebSocket. Our WebSocket provider-error classifier already defaults unknown provider codes to non-retriable; preserve that behavior and add a named regression. HTTP stream normalization currently retains only a message, so retain code and request/response identity there too. Stop dispatching pending tools and expose completed/uncertain work to the application.

Project-wide safety-alert webhooks belong in the hosting application. Provide a short integration note rather than adding a webhook server to chatsnack. [Monitoring contract](https://developers.openai.com/api/docs/guides/safety-checks/misalignment-monitoring).

## Delivery and proof

Use the project's [Three-Horizon TDD approach](../../3HTDD.md). BASELINE's Goal and advisory Steers are implemented; the remaining rows are proposed acceptance scenarios.

| Delivery | Goal proof | Steer-level checks |
| --- | --- | --- |
| BASELINE | A notebook selects Astra, saves and reloads a named stock Chat, binds its utensil, and continues with its result. | All five documented efforts pass without warnings; `none`/`minimal` warn unchanged; verified direct-OpenAI Astra sampling violations receive diagnostics; existing temperature and custom-provider pass-through remain warning-free; `ultra` stays unknown; legacy Astra tool requests receive diagnostics. |
| FIDELITY | A readable saved Chat retains its authored meaning and assets; explicit state export also preserves ordered provider items for stateless replay. | Distinguish status/phase; preserve multiple reasoning items, opaque metadata, call IDs, custom types; invalidate continuation for edited or differently resolved prefixes, including changed Text/include assets. |
| ASYNC | `.chat_a()` returns one continued Chat after a slow function utensil overlaps independent model work; an event probe observes the overlap. | Compact async metadata round-trip and callable rebinding; ordinary coroutine utensils; mixed function batches, out-of-order completion, duplicate events, bounded concurrency, budget exhaustion, failures, and no orphan jobs. |
| STEERING | A user correction affects the successor answer while already-started tools retain correct result correlation. | Source snapshot isolation; accepted/pending/failed events; both original terminal outcomes; tool-result gating; disconnect ambiguity; incomplete response ends; usage includes every successor; existing listener semantics retained. |
| EFFORT | A low-effort chat saves a readable high-effort follow-up and reloads it without rewriting the request prefix. | Ordered control insertion and include expansion; assistant summaries stay metadata; adjacent-update validation, initial/effective effort separation, compaction restrictions. |
| MONITORING | A blocked response stops further tool dispatch and exposes the provider code. | HTTP before/after streaming and WebSocket errors; no retry or fresh-conversation workaround. |

Build on existing adapter fixtures and tests under `tests/runtime/`, `tests/test_responses_continuation.py`, `tests/test_responses_tool_normalization.py`, and `tests/test_runtime_defaults.py`. BASELINE now extends `notebooks/ReasoningModelValidation.ipynb`; add a short exploratory notebook for ASYNC/STEERING when implemented. Start from the smoke test, inspect a compact YAML asset, then await an ordinary `.chat_a()`; introduce active steering in its own optional cell. Reuse the existing small `.ask()`/`.chat()` and `ChatFile` patterns. Use opt-in live probes to verify account access and wire behavior; fake events establish our orchestration rules, not provider availability.

For 0.8.1 regressions, also cover `tests/test_provider_client_binding.py`, `tests/features/test_provider_client_configuration.py`, `tests/test_filling_resolution.py`, `tests/mixins/test_chatparams.py`, and `tests/test_call_usage.py`. Preserve bound credential identity through copy/reset/load, explicit runtime precedence, temporary request-session cleanup, resolver-only authority/bounds, and separate usage ownership for filling calls and the outer Chat run. These are existing release contracts to retain, not newly proposed Astra features.

## Open questions and review status

- The configured API account passed the BASELINE live probes on 2026-09-09. Access and behavior for advanced protocols still require their own acceptance checks.
- Which SDK release first supports all later Astra fields/events? BASELINE is validated offline on 3.5.0 and 3.8.0; retain its current floor and re-evaluate for ASYNC/STEERING.
- Does Astra accept `concise` and `detailed` summaries in addition to the documented `auto` example? Avoid filling in a model-specific capability set without evidence.
- Which inherited beta combinations need support: Multi-agent, programmatic tool calling, or pro mode? The dedicated reasoning/multi-agent guides still contain GPT-5.6-specific wording while the Astra guide claims inherited support; combination testing is still needed.
- What is the smallest opt-in steering surface that can return a continued Chat and preserve existing listener behavior? Resolve this with the adapter prototype before committing to public methods. Active-job persistence and custom-tool execution remain separate work.

Review checklist:

- [x] Official model identity, endpoint restrictions, and feature contracts checked against fetched pages on the research date.
- [x] Full model defaults/capability file, active query path, request/response adapters, examples, dependency declarations, and installed SDK types inspected.
- [x] Confirmed code gaps separated from provider capabilities and untested integration assumptions.
- [x] BASELINE implementation and successful live probes distinguished from proposed advanced methods.
- [x] Original independent critical review completed; corrected streaming requirements and exact-model matching. The 0.8.1 update was reviewed against the release diff and existing contracts; local links and changed code locations rechecked.
- [x] Both requested design skills applied against current notebooks and YAML/utensil RFCs. Independent design review tightened resolved-prefix identity, source snapshot isolation, callable rebinding, and ordered reasoning controls through includes.
- [x] Ponytail cuts applied: function-first async scope, deferred public steering lifecycle, and reuse of existing composition examples. Ordered replay, reasoning history, failure correlation, and 0.8.1 regression contracts retained.
- [x] BASELINE live API acceptance probes completed through the explicit notebook opt-in and focused model/transport checks; scope and shutdown observation recorded above.
