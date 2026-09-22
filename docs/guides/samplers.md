# Samplers and Questions

A `Sampler` asks focused questions about existing data. Every `ask()` returns a
`Sample`, with typed answers, the evaluated inputs, and model/usage information.

Install `pip install chatsnack` (0.9.0 or later) and set `TYPESAFE_API_KEY` in your
environment or local `.env`. TypeSafe support is included. The key is needed when
you evaluate a Sampler; authoring and saving definitions require no credentials.

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
explicit file path before saving.

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

You can also read `.score` and `.confidence` in result fillings. Several fields
from the same Sampler share one evaluation during that prompt expansion. A later
call evaluates again. Saved result fillings always name their answer explicitly.

## Keep what was evaluated

```python
replay = Sampler.from_sample(sample, name="PopcornReview")
replay.save()
repeated = replay.ask()
```

The replay contains the resolved data and questions, with the returned model
version. Later edits to Question assets won't change it. Evaluating again may
produce different answers.

To ask about the previous result itself, use it as new data:

```python
followup = Sampler(data=sample).ask("Do these answers describe a sweet snack?")
print(followup.answer.yes)
```

Call-time `data=` overrides the stored data without changing it. Data supplied
that way, and values injected into fillings, remain literal: braces inside a
document do not become new template expressions.

See the [advanced Sampler reference](../reference/api/sampler.md) for execution
settings, request inspection, and the public filling resolver.
