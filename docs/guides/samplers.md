# Samplers and Questions

A `Sampler` asks focused questions about data. `ask()` returns a `Sample` with
typed answers and the evaluated inputs.

Install `chatsnack` and set `OPENAI_API_KEY` in your environment or `.env`.
Samplers default to OpenAI Decisions with `gpt-6-luna`. To use Jev, set
`TYPESAFE_API_KEY` and choose `model="jev-latest"` or `provider="typesafe"`.
Keys are needed for evaluation; you can author and save definitions offline.

## Something crunchy

```python
from chatsnack import Sampler

sample = Sampler(data="buttered popcorn").ask("Is this crunchy?")
if sample.answer.yes:
    print("Crunch!")
```

`sample.answer` and `sample.question` refer to the first answer and question,
even in a batch.

Use `await sampler.ask_a(...)` for async code.

A reusable Sampler keeps its synchronous provider connection ready for the next call:

```python
judge = Sampler(questions=["Is this crunchy?"])
first = judge.ask(data="popcorn")
second = judge.ask(data="a potato chip")
judge.close()
```

Close a reusable Sampler when finished. Async evaluations close their own clients.

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

Questions and Samplers save under `questions/` and `samplers/` in the chatsnack
data directory. Give a definition a name or explicit file path before saving.

Pass a Question object to embed its definition. Use `"{question.crunchy}"` to
read the saved Question each time the Sampler runs.

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

Named access stays stable when you reorder questions. Unnamed questions are
available by position. Names must be unique within a batch.

Every answer has `choice`, `score`, `probabilities`, and `confidence`:

| Kind | Choice | Score |
| --- | --- | --- |
| Yes/no | `"yes"` or `"no"` | Probability of yes |
| Choice | Selected option key | Probability of that option |
| Score | Most probable authored level name | Provider's weighted position across levels |

Yes/no answers also have `.yes` and `.no`. Their confidence is the probability
margin; Choice and Score use the provider's reported confidence.

## Look at a snack

```python
sample = Sampler(images=["snack.png"]).ask("Does this snack look burnt?")
if not sample.answer.refused:
    print(sample.answer.yes)
```

Pass local paths or readable `ChatFile` values, including images returned by a
Chat. Image-only questions work too. Jev uses the same `images=` argument:

```python
sample = Sampler(
    model="jev-1.14.0", images=["snack.png"],
).ask("Does this snack look burnt?")
print(sample.answer.yes)
```

Jev vision is experimental. It accepts PNG/JPEG; OpenAI also accepts WebP.
Prepare images to meet the [provider limits](../reference/api/sampler.md#images-and-fillings);
chatsnack sends them without resizing or conversion.

Images can stay live in a saved Sampler:

```yaml
data: Inspect this snack.
images:
  - "{photo}"
questions:
  - name: burnt
    question: Does the snack look burnt?
```

Supply `photo="snack.png"` when evaluating it. The resulting `sample.images`
contains readable snapshots for replay.

## A question can be refused

Decisions may decline individual questions. A refused answer keeps its place in
the batch, has `.refused=True`, and returns `None` for its answer values.

```python
for question, answer in zip(sample.questions, sample.answers):
    print(question.name, "refused" if answer.refused else answer.choice)
```

Connection and response errors still raise exceptions.

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

Result fillings also expose `.score`, `.confidence`, and `.refused`, and always
name their answer. Reading several fields from one Sampler shares an evaluation
within that prompt; the next call evaluates again. A refused value embedded in
prose renders as `None`.

## Keep what was evaluated

```python
replay = Sampler.from_sample(sample, name="PopcornReview")
replay.save()
repeated = replay.ask()
```

Replay keeps the evaluated data, questions, image bytes, and connection settings.
Editing a Question or deleting the original photo won't change its inputs.
Answers may still differ. Keep the assets directory with the YAML when moving a replay.

To ask about the previous result itself, use it as new data:

```python
followup = Sampler(data=sample).ask("Do these answers describe a sweet snack?")
print(followup.answer.yes)
```

Follow-ups inherit the previous Sample's images. Supply new `images=` to replace
them, or `images=[]` to clear them.

Call-time `data=` overrides the stored data without changing it. Data supplied
that way, and values injected into fillings, remain literal: braces inside a
document do not become new template expressions.

See the [advanced Sampler reference](../reference/api/sampler.md) for execution
settings, request inspection, and the public filling resolver.
