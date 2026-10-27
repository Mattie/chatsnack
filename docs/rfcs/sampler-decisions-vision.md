# Sampler 0.10.0: Decisions and vision

Status: implementation accepted for 0.10.0.

October 22 follow-on: [Jev 1.14 support](../projects/jev-1-14-checklist.md) adds
Jev images and a single automatic long-context resubmission after its explicit
400 `max_tokens_exceeded` error. The October 6 probes below predate that retry.

## Intent

Keep Questions, YAML assets, named answers, and Chat fillings as the authoring
surface. A Sampler evaluates evidence; adapters assemble provider requests.
OpenAI Decisions becomes the default, with Jev available explicitly. Saved
authoring keeps live references; evaluated Samples capture literal inputs.

```python
sample = Sampler(images=[photo]).ask("Does this snack look burnt?")
if not sample.answer.refused:
    print(sample.answer.yes)
```

## Routing and execution

Explicit `provider` wins. Otherwise a `jev` model selects TypeSafe, and other
models select OpenAI. Defaults are OpenAI / `gpt-6-luna`. Only TypeSafe consults
`TYPESAFE_DEFAULT_MODEL`. Authored models are never rewritten. There is no fallback
or local context truncation.

The existing internal batch remains the shared validation/preparation boundary.
Adapters translate that resolved batch. Direct calls and named fillings share
decoding and snapshot capture without a backend registry or new authoring types.
Connection identity includes effective provider. Retained sync clients and scoped
async clients preserve override isolation and cancellation cleanup. OpenAI uses
generic SDK POST with `Dict[str, Any]` because SDK 3.5.0 lacks a typed resource.

Timeout maps to the selected SDK. OpenAI retry accepts `max_retries` only;
TypeSafe retains its full policy. Invalid options fail before dependencies.

## Questions and results

Question authoring and `Question.compile()` are unchanged. OpenAI predicates
receive text instructions containing authored yes/no criteria when present.
Choices become named values with optional descriptions. Scores become ordered
labels with optional descriptions. Structured values become deterministic JSON
text preserving authored order. Questions always receive explicit names, including
the existing collision-safe identifiers for anonymous questions.

Response arrays are checked before maps are built: duplicate names/probabilities,
missing/unexpected answers, mismatched kinds/options/labels, and invalid numeric
distributions raise errors. Authored order drives slots. Choices, weighted scores,
reported confidence, usage counts, and existing tie behavior are preserved.

Refusals are actual results. `RefusalAnswer` occupies its slot with `.refused=True`
and all result views `None`. Successful Answers expose `.refused=False`. Named
fillings add `.refused`; exact whole-value fillings preserve `None`, and embedded
text uses existing rendering.

## Images and replay

Images use existing Chat paths, locally readable ChatFiles, captured references,
and live fillings. Adapter validation applies provider-specific limits; see the
[API reference](../reference/api/sampler.md#images-and-fillings).

Resolved bytes serve both inline encoding and evaluated snapshots. Compilation
reads without capturing. Saved authoring retains paths/fillings; saved replay
retains content-addressed references. No base64 or credentials enter saved YAML
or Sample serialization. Keep the assets stash when moving replay YAML.

`Sample.images` exposes ChatFiles. `Sample.params` returns detached effective
provider/model, the effective endpoint including public defaults, and authored
nonsecret connection options. Unset SDK timeout/retry defaults remain delegated.
`from_sample()` embeds resolved questions,
literal data, image references, and settings with expansion disabled. Re-evaluation
repeats evidence, without guaranteeing identical answers.

A previous Sample used as data carries images, with precedence call images →
authored images → previous Sample images. `images=[]` explicitly clears them.
Saved follow-ups project Sample data literally and retain carried images without
changing the live in-memory inheritance rule.

An explicit `fillings` mapping escapes reserved keywords; duplicate bindings with
ordinary kwargs are errors. New reserved names: provider, images, fillings.

## October 6 probe evidence

Mixed predicate, choice, and score questions read markers at the beginning,
middle, and end of synthetic context. Opt-in contracts use repeated and varied
8k/30k/100k fixtures. Run with configured credentials:

```powershell
$env:CHATSNACK_RUN_DECISIONS_LIVE = '1'
.venv\Scripts\python.exe -m pytest tests/test_sampler_decisions_live.py -q -s
$env:CHATSNACK_RUN_DECISIONS_CONTEXT_LIVE = '1'
.venv\Scripts\python.exe -m pytest tests/test_sampler_decisions_live.py -q -s
```

These are paid opt-ins. Context fixtures use the Responses input-token count to
target text length and send identical data/questions to both backends. Counts
differ by provider, so an OpenAI-sized 30k fixture can exceed Jev's limit.

| Fixture | OpenAI text count | Decisions usage | Jev usage/outcome |
| --- | ---: | ---: | --- |
| Repeated 8k | 8,003 | 8,400 | 8,372 |
| Varied 8k | 8,003 | 8,400 | 9,043 |
| Repeated 30k | 30,003 | 30,400 | 30,372 |
| Varied 30k | 30,593 | 30,990 | `max_tokens_exceeded` |
| Repeated 100k | 99,996 | 100,393 | `max_tokens_exceeded` |
| Varied 100k | 103,140 | 103,537 | `max_tokens_exceeded` |

All three judgments were correct on every accepted request. The implemented
mixed-question contract used 425 input tokens; vision used 117, with successful
asset replay after deleting the source PNG. These are synthetic fixtures, not
evidence of general document accuracy or maximum context.

## Verification and limits

See the [implementation checklist](../projects/sampler-0-10-checklist.md). Goal
scenarios cover saved vision/replay after source deletion, refusal slots/fillings,
image follow-ups/clearing, existing Jev behavior, and sync/async lifetime. Focused
contracts cover translation and boundary failures.

Nested image values and spatial Questions are deferred. Callers upgrading an
existing app need to account for the changed default, refusals, and replay assets;
see the [migration notes](../migration/0.10.md).

## Official references (verified 2026-10-06)

- [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
- [Decisions create contract](https://developers.openai.com/api/reference/resources/decisions/methods/create)
- [Image input contract](https://developers.openai.com/api/reference/python/resources/decisions/methods/create)
- [Jev models and limits](https://docs.typesafe.ai/models)
