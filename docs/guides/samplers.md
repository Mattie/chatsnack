# Samplers and Questions

A `Sampler` asks focused questions about existing data. Every `ask()` returns a
`Sample`, with typed answers, the evaluated inputs, and model/usage information.

Install `pip install chatsnack` (0.10.0 or later) and set `OPENAI_API_KEY` in your
environment or local `.env`. Samplers use OpenAI Decisions with `gpt-6-luna` by
default. The key is needed when
you evaluate a Sampler; authoring and saving definitions require no credentials.
For Jev, set `TYPESAFE_API_KEY` and select `model="jev-latest"` or
`provider="typesafe"`. Both SDKs are included.

## Something crunchy

```python
from chatsnack import Sampler

sample = Sampler(data="buttered popcorn").ask("Is this crunchy?")
if sample.answer.yes:
    print("Crunch!")
```

`sample.answer` is always `sample.answers[0]`, even in a batch. Likewise,
`sample.question` is `sample.questions[0]`. These are the same objects, not copies.

Use `await sampler.ask_a(...)` for async code. Both methods always return a Sample.

A reusable Sampler keeps its synchronous provider connection ready for the next call:

```python
judge = Sampler(questions=["Is this crunchy?"])
first = judge.ask(data="popcorn")
second = judge.ask(data="a potato chip")
judge.close()
```

Call `close()` when a long-running synchronous application shuts down. `ask_a()`
uses a scoped async client and closes it after each evaluation, so it does not keep
an event-loop-bound connection on the Sampler. One-call endpoint, credential,
timeout, and retry overrides stay isolated from the reusable synchronous connection.

## Keep a useful question

```python
from chatsnack import Question, Sampler

crunchy = Question(
    name="crunchy",
    question="Is this crunchy?",
    yes="It makes a crisp cracking sound when bitten.",
)
print(crunchy.yaml)
crunchy.save()

review = Sampler(name="SnackCheck", data="{snack}", questions=["{question.crunchy}"])
print(review.yaml)
review.save()
```

The saved Sampler is small:

```yaml
data: "{snack}"
questions:
  - "{question.crunchy}"
```

Load it and supply a filling when you need it:

```python
review = Sampler(name="SnackCheck")
review.load()
sample = review.ask(snack="popcorn")
print(sample.answer.choice, sample.answer.score)
```

Construction stays in memory. Questions and Samplers save under `questions/` and
`samplers/` in the chatsnack data directory. Existing `CHATSNACK_BASE_DIR` and
snapclass stash configuration apply. An anonymous definition needs a name or an
explicit file path before saving. Saved Sampler names cannot contain `{`, `}`,
`!`, or `:`, because those characters have special meaning to the filling formatter.

Pass a Question object to embed its definition. Use `"{question.crunchy}"` for a
live connection to the saved asset. Saving preserves that choice; a Question's
name or save history never turns an embedded value into a reference.

## A few questions together

```python
category = Question(
    name="category",
    question="What kind of food is this?",
    choices={"snack": "A small bite between meals", "meal": "A full meal"},
)
sweetness = Question(
    name="sweetness",
    question="How sweet is this?",
    levels=["Not sweet", "A little sweet", "Very sweet"],
)

sample = review.ask(questions=["{question.crunchy}", category, sweetness], snack="popcorn")
print(sample.answers["category"].choice)
print(sample.answers["sweetness"].score)
```

Named access remains stable when you reorder questions. All collections retain
authored order; unnamed questions are available by position. Names must be
nonempty strings without the filling metacharacters `.`, `[`, `]`, `{`, `}`, `!`,
or `:`, and unique within a batch. Empty batches are rejected.

Every answer has `choice`, `score`, `probabilities`, and `confidence`:

| Kind | Choice | Score |
| --- | --- | --- |
| Yes/no | `"yes"` or `"no"` | Probability of yes |
| Choice | Selected option key | Probability of that option |
| Score | Most probable authored level name | Provider's weighted position across levels |

Yes/no answers also have Boolean `.yes` and `.no`. Confidence is the binary
probability margin for yes/no, and the provider's reported confidence for Choice
and Score. Scores have different meanings across question kinds.

## Look at a snack

```python
sample = Sampler(images=["snack.png"]).ask("Does this snack look burnt?")
if not sample.answer.refused:
    print(sample.answer.yes)
```

Use local PNG, JPEG, or WebP paths, locally readable `ChatFile` values returned
by a Chat, or captured asset references. Image-only questions work too. Up to
128 images keep their supplied order on OpenAI. URLs and provider file IDs are
rejected. Select Jev with the same `images=` surface:

```python
sample = Sampler(
    model="jev-1.14.0", images=["snack.png"],
).ask("Does this snack look burnt?")
print(sample.answer.yes)
```

The adapter enables Jev's image header automatically when images are present.
Jev accepts PNG/JPEG. Prepare the photo to meet TypeSafe's
[image limits](https://docs.typesafe.ai/images#limits); images are sent as supplied,
without conversion or resizing. Experimental vision can change between releases.

Images can stay live in a saved Sampler:

```yaml
data: Inspect this snack.
images:
  - "{photo}"
questions:
  - name: burnt
    question: Does the snack look burnt?
```

`review.ask(photo="snack.png")` resolves the path when evaluated. The resulting
`sample.images` contains locally readable `ChatFile` snapshots of those exact
bytes. `Sampler.from_sample(sample)` saves their content-addressed references,
so changing or deleting the original photo does not change the replay. Keep the
assets directory with the saved YAML when moving it to another machine.

## A question can be refused

Decisions may decline individual questions. Each refusal stays in its original
answer slot, including when the whole batch is refused. `sample.answer` still
means the first slot. Successful answers expose `.refused=False`; a
`RefusalAnswer` exposes `.refused=True`, and its choice, score, probabilities,
confidence, yes, and no values are `None`.

```python
for question, answer in zip(sample.questions, sample.answers):
    print(question.name, "refused" if answer.refused else answer.choice)
```

Transport failures, missing credentials, and malformed responses raise errors.
They do not produce refusal answers or trigger a provider fallback.

## Compose into a Chat

Keep the decision connection in the authored prompt:

```python
from chatsnack import Chat

description = Chat(
    "Describe {snack} in one sentence. "
    "Crunchy: {sampler.SnackCheck.crunchy.choice}."
)
print(description.ask(snack="popcorn"))
```

You can also read `.score`, `.confidence`, and `.refused` in result fillings. Several fields
from the same Sampler share one evaluation during that prompt expansion. A later
call evaluates again. Saved result fillings always name their answer explicitly.
An exact whole-value filling retains `None` for refused values. Embedded values
use the usual text rendering, so a refused choice in prose renders as `None`.

## Keep what was evaluated

```python
replay = Sampler.from_sample(sample, name="PopcornReview")
replay.save()
repeated = replay.ask()
```

The replay contains the resolved data, questions, image snapshots, provider, and
nonsecret execution settings, with the returned model version. Later edits to
Question assets won't change it. Evaluating again may
produce different answers.

To ask about the previous result itself, use it as new data:

```python
followup = Sampler(data=sample).ask("Do these answers describe a sweet snack?")
print(followup.answer.yes)
```

The previous Sample's images carry forward automatically. Call-time `images=`
replaces authored images, which replace inherited images. Use `images=[]` to
clear them; saving and loading preserves that explicit empty list.

Choose Jev explicitly when needed:

```python
sample = Sampler(model="jev-latest", data="popcorn").ask("Is this crunchy?")
```

Confidence thresholds need calibration for each backend. A provider change can
change judgments, token accounting, and cost. See the
[0.10 migration notes](../migration/0.10.md) before upgrading an existing app.

Larger Jev inputs need no extra authoring options. Requests start normally; if
Jev reports `max_tokens_exceeded`, chatsnack retries once with extended context,
using the same resolved evidence. Other errors, and a second context failure,
surface normally. Short requests stay unchanged. TypeSafe documents a 262k-token
experimental context with lower accuracy and higher latency on larger inputs;
see [long context](https://docs.typesafe.ai/models#long-context).

Call-time `data=` overrides the stored data without changing it. Data supplied
that way, and values injected into fillings, remain literal: braces inside a
document do not become new template expressions.

See the [advanced Sampler reference](../reference/api/sampler.md) for execution
settings, request inspection, and the public filling resolver.
