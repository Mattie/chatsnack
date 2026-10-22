# Sampler 0.10.0: Decisions and vision

Status: implementation accepted. Compatibility boundary: 0.10.0.
Mattie approved the default switch, existing credentials for paid probes, vision,
partial refusals, nullable refusal values, and automatic image carry-forward.

October 22 follow-on: [Jev 1.14 support](../projects/jev-1-14-checklist.md) adds
Jev images and a single automatic long-context resubmission after its explicit
400 `max_tokens_exceeded` error. The October 6 probes below record the earlier
standard-context behavior. New evaluations require no experimental params.

## Intent

Keep Questions, YAML assets, named answers, and Chat fillings as the authoring
surface. A Sampler evaluates evidence; adapters assemble provider requests.
OpenAI Decisions becomes the default, with Jev available explicitly. This follows
PHILOSOPHY and chatsnack-fluency: terse experiments, readable judgments, live
authored references, and literal evaluated snapshots.

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
generic SDK POST with `Dict[str, Any]`: SDK 3.5.0 lacks the typed resource, and bare
`dict` is not a valid decoding type.

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

Construction, evaluation, and compilation accept local PNG/JPEG/WebP paths,
locally readable ChatFiles, captured references, and live fillings. Existing Chat
path conventions and asset integrity checks apply. Remote downloads and file IDs
fail before dispatch. Images keep order, use `detail=auto`, and are capped at 128.
Image-only evaluation is valid.

Resolved bytes serve both inline encoding and evaluated snapshots. Compilation
reads without capturing. Saved authoring retains paths/fillings; saved replay
retains content-addressed references. No base64 or credentials enter saved YAML
or Sample serialization. Keep the assets stash when moving replay YAML.

`Sample.images` exposes ChatFiles. `Sample.params` returns detached effective
provider/model, a captured environment endpoint when selected, and authored
nonsecret connection options. Unset SDK timeout/retry defaults remain delegated. Existing positional
Sample arguments remain supported. `from_sample()` embeds resolved questions,
literal data, image references, and settings with expansion disabled. Re-evaluation
repeats evidence, without guaranteeing identical answers.

A previous Sample used as data carries images, with precedence call images →
authored images → previous Sample images. `images=[]` explicitly clears them.
Saved follow-ups project Sample data literally and retain carried images without
changing the live in-memory inheritance rule.

An explicit `fillings` mapping escapes reserved keywords; duplicate bindings with
ordinary kwargs are errors. New reserved names: provider, images, fillings.

## October 6 probe evidence

Existing configured keys were used without saving credentials. Mixed predicate,
choice, and score questions read markers at the beginning, middle, and end of
synthetic context.

| Approximate text tokens | Decisions input tokens | Jev outcome |
| --- | ---: | --- |
| 8k | 8,394; all correct | 8,372; all correct |
| 30k | 30,394; all correct | 30,372; all correct |
| 100k | 100,387; all correct | HTTP 400 `max_tokens_exceeded` |

An image-only 64×64 red PNG selected red correctly (120 input tokens). These
establish feasibility, not maximum context or realistic long-document accuracy.
Confidence needs backend-specific calibration. Published input prices at
verification were $0.10/M for Decisions and $0.042/M for Jev; accounting differs.

Retained opt-in contracts evaluate mixed questions and vision, plus repeated
and varied long-document fixtures at 8k/30k/100k. They record actual usage and
accuracy without timing assertions. Run with configured credentials:

```powershell
$env:CHATSNACK_RUN_DECISIONS_LIVE = '1'
.venv\Scripts\python.exe -m pytest tests/test_sampler_decisions_live.py -q -s
$env:CHATSNACK_RUN_DECISIONS_CONTEXT_LIVE = '1'
.venv\Scripts\python.exe -m pytest tests/test_sampler_decisions_live.py -q -s
```

These are paid opt-ins. Ordinary tests and notebook validation stay offline.
Context fixtures use the Responses input-token count to target text length and
send identical data/questions to both backends. Jev's documented context rejection
is recorded at any size; unrelated failures remain failures. Counts differ by
provider, so an OpenAI-sized 30k fixture can exceed Jev's limit.

Implemented Sampler verification on 2026-10-06:

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

Cloudflare adapters, remote image downloads, audio/video/general files, streaming,
workflows, and release publication are outside this change. Accepted risks are
default/threshold changes, nullable callers, and retaining replay assets.

## Official references (verified 2026-10-06)

- [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
- [Decisions create contract](https://developers.openai.com/api/reference/resources/decisions/methods/create)
- [Image input contract](https://developers.openai.com/api/reference/python/resources/decisions/methods/create)
- [Jev models and limits](https://docs.typesafe.ai/models)
