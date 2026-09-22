# Proposed concept: Sampler and reusable Question assets

Status: accepted for 0.9.0 implementation. See [the implementation design](sampler-design.md).

Last updated: 2026-09-17.

## Purpose

`Sampler` would bring TypeSafe's Jev evaluation model into chatsnack as a small, durable intelligence primitive. It evaluates one piece of data against one or more questions and returns typed answers with probabilities.

The feature should feel like chatsnack:

- the common Python path is terse enough for a notebook;
- the useful definition can be saved as readable YAML;
- questions and samplers can be composed through fillings;
- provider discriminators and request assembly stay behind the public API;
- structured data remains structured when that is useful;
- advanced execution settings remain available without burdening ordinary use.

`Sampler` complements `Chat`. A `Chat` generates or continues a conversation. A `Sampler` makes narrow decisions about existing data. Sampler results may later help select chat or text fillings, but `Sampler` is not a replacement for `Chat` or a general workflow engine.

## Vocabulary

| Term | Meaning |
| --- | --- |
| `Sampler` | A reusable definition containing data, questions, and Jev execution parameters. |
| `Question` | A reusable question definition. Its members imply whether Jev receives a Noul, Choice, or Score question. |
| answer | The rich result for one question, including its selected `.choice`, primary numeric `.score`, normalized probability distribution, and confidence. Concrete subclasses are advanced API details. |
| `Sample` | The result of evaluating a batch: resolved data, ordered-and-named questions and answers, plus model and usage metadata. |
| `data` | The content being evaluated. It may be text, a document, a transcript, a record, an array, or application state. |

The chatsnack-facing word is `data`. TypeSafe calls the corresponding provider request member `state`; compilation performs that translation.

## Current decisions

### The simple path asks one inline yes/no question

```python
from chatsnack import Sampler

sampler = Sampler(data=mydata)
answer = sampler.ask("Is the ball on the ground?").answer

if answer.yes:
    round_end = True
```

A bare positional string is an inline, anonymous yes/no question. It is never interpreted as the name of a saved question.

The positional argument to `ask()` is the question. Evaluated content is supplied through `sampler.data` or the `data=` keyword. This removes ambiguity between a question and a text document.

### Saved questions use explicit fillings

Saved questions are referenced with the existing filling vocabulary:

```python
answer = sampler.ask("{question.ball_grounded}").answer
```

This is deliberately different from:

```python
answer = sampler.ask("ball_grounded").answer
```

The second form asks the literal inline question `ball_grounded`. It does not perform an implicit asset lookup.

An exact whole-value question filling resolves to a `Question` object. That preserves the question's structure and criteria. General chatsnack filling behavior should continue to distinguish whole-value typed resolution from interpolation inside a larger string.

### Rich inline questions use `Question`

```python
from chatsnack import Question, Sampler

is_sandwich = Question(
    question="Is `food` a sandwich?",
    yes=(
        "A sandwich has a filling such as meat, cheese, vegetables, or spread "
        "between structural starch."
    ),
    no=(
        "The food has no bread enclosing a filling, uses only one slice of "
        "bread, or uses a non-bread wrapper such as a tortilla, wafer, or cookie."
    ),
)

answer = Sampler(data={"food": "ham between two slices of rye"}).ask(is_sandwich).answer
```

`question` maps to TypeSafe's `instructions`. The authored vocabulary describes the question instead of the provider request.

For a yes/no question:

- `yes` describes what a positive answer means;
- `no` describes what a negative answer means;
- both are optional;
- the compiler maps them to TypeSafe's `criteria.true` and `criteria.false`.

The question, criteria, choice descriptions, and score levels may contain structured Python or YAML values where TypeSafe accepts structured entries. Strings remain the common path.

### Question kind is inferred from its members

Authored Python and YAML do not require a repeated `type` field.

| Authored members | Provider question |
| --- | --- |
| neither `choices` nor `levels` | Noul, TypeSafe's yes/no probability question |
| `choices` | Choice |
| `levels` | Score |

These are TypeSafe's three current question primitives. Structured instructions and criteria enrich them; they do not introduce additional question kinds.

Conflicting members fail before submission. For example, one question cannot define both `choices` and `levels`, and `yes` or `no` cannot accompany a Choice or Score question.

The provider discriminator appears only in the compiled request.

### `data` is ordinary authored Sampler content

`Sampler.data` is persistable content. It is not assumed to be disposable application-state noise.

```python
sampler = Sampler(name="document_review", data=document)
sampler.save()
```

The value might be a text document:

```yaml
data: |
  The receiver catches the ball near the sideline.
  His left foot lands in bounds and his right foot lands out.
```

It might instead be structured:

```yaml
data:
  play:
    description: The receiver caught the ball near the sideline.
    left_foot: in bounds
    right_foot: out of bounds
  league: NFL
```

A call-time value overrides the saved value without mutating it:

```python
sample = sampler.ask(data=other_document, questions=[urgent, topic])
```

Data precedence is:

1. `ask(data=...)`
2. `sampler.data`
3. a missing-data error

Assigning `sampler.data` changes the authored object and is persisted on its next save. Supplying `ask(data=...)` changes only that evaluation.

Call-time data and injected filling values are literal: braces inside them are
not interpreted again. Ordinary keyword fillings follow Chat's conventions;
a shared keyword-collision redesign is deferred.

### Every evaluation returns a Sample

The settled contract is:

- `sampler.ask(question)` returns a Sample containing one rich answer;
- `sampler.ask(questions=[...])` returns a `Sample` collection;
- `sampler.ask()` evaluates questions already authored on the Sampler and returns a Sample;
- supplying both a positional question and `questions=` is an error.

`sample.answer is sample.answers[0]` and `sample.question is sample.questions[0]`
for every successful Sample, including batches. These aliases always mean first;
use named access in durable multi-question examples. Empty batches fail before
submission. There is no `.sample()` execution verb or answer-property promotion.

The batch form remains useful even with one member:

```python
sample = sampler.ask(
    data=mydata,
    questions=[
        "Is the ball on the ground?",
    ],
)
```

`Sample.questions` and `Sample.answers` are ordered-and-named collections. Both preserve authored question order and support positional access:

```python
sample.questions[0]       # first resolved Question
sample.answers[0].choice  # selected outcome from the first question
```

When a question has a name, both collections also support that name:

```python
sample.questions["department"]
sample.answers["department"].choice
```

Names are optional. Explicit names must be nonempty strings without filling metacharacters (`.`, `[`, `]`, `{`, `}`, `!`, or `:`) and unique within one Sample; those characters delimit or modify named result fillings. Saved Sampler names exclude the formatter metacharacters `{`, `}`, `!`, and `:`, while dots and brackets remain valid in the asset-name segment. An unnamed question remains available by position. This works for every question kind because `.choice` is universal: it returns `"yes"` or `"no"` for yes/no, an option key for Choice, and the selected level name for Score.

TypeSafe returns answers in a map keyed by question ID. The adapter should rebuild both collections from the submitted question order rather than relying on response-object order. It may generate private provider IDs for unnamed questions, but those IDs do not become authored names.

The Sample also retains the resolved input data and response metadata:

```python
sample.data
sample.model
sample.usage.input_tokens
sample.usage.output_tokens
```

`sample.data` is the value actually evaluated after call-time precedence has been applied. It retains a structured value as structured data.

### Every answer exposes a `choice`

All three question kinds expose their selected outcome through `.choice`:

```python
yes_no.choice  # "yes" or "no"
topic.choice   # a Choice option key such as "technical"
rating.choice  # the most probable Score level key or label
```

The selected value is always one of the answer's probability keys:

```python
answer.choice in answer.probabilities
answer.probabilities[answer.choice]
```

Every answer also exposes a primary numeric `.score`, interpreted according to its question kind:

| Question kind | `.score` |
| --- | --- |
| yes/no | TypeSafe's Noul value: probability of yes from 0 to 1 |
| Choice | probability assigned to TypeSafe's returned `.choice` |
| Score | TypeSafe's returned probability-weighted score across the ordered levels |

These scores are useful within their question kind and are not intended for comparison across different kinds. `.yes` and `.no` remain Boolean conveniences derived from a yes/no answer's `.choice`.

Every answer exposes `.confidence`, with this documented distinction:

- **Noul:** chatsnack derives confidence as the binary probability margin.
- **Choice and Score:** chatsnack returns the confidence supplied directly by TypeSafe without recomputing it.

The Noul derivation is:

```python
answer.confidence = abs(2 * answer.score - 1)
```

The derived yes/no confidence is `0` at an even split and `1` at either extreme. TypeSafe's raw Noul answer does not contain a confidence field.

Because `.choice` is a nonempty key, callers should compare it or use the kind-specific Boolean views. `if answer.choice:` would be true for both `"yes"` and `"no"`.

Tie handling is deterministic:

- yes/no chooses `"yes"` when the Noul value is exactly `0.5`; its derived confidence is `0`;
- Choice preserves the `.choice` returned by TypeSafe without checking whether it is the unique or maximal probability;
- Score chooses the first maximally probable level in authored level order.

Chatsnack validates response structure needed for decoding, but it does not second-guess TypeSafe's semantic selection.

### Questions are durable snapclass assets

`Question` should be a snapclass with explicit persistence. Ordinary construction and notebook experimentation should not write files implicitly.

```python
ball_grounded = Question(
    name="ball_grounded",
    question="Is the ball on the ground?",
)
ball_grounded.save()
```

The conceptual saved asset is concise because the filename restores the name and the question kind is inferred:

```yaml
question: Is the ball on the ground?
```

A rich saved question remains provider-neutral:

```yaml
question: Is `food` a sandwich?
yes: A filling is enclosed by structural starch.
no: There is no enclosing bread, or the wrapper is not bread.
```

The 0.9.0 paths are `questions/{name}.yml` and `samplers/{name}.yml` under the
existing chatsnack root, beside chats and texts. Construction neither writes nor
loads named definitions. Anonymous definitions need a name or explicit path to save.

Passing a `Question` object directly means using that object. Writing an exact `{question.name}` filling means resolving the saved asset at expansion time. This gives callers an explicit distinction between an inline value and a live asset reference.

### Saved Samplers preserve embedded questions and references

A Sampler may mix anonymous strings, embedded Question values, and live Question references:

```yaml
questions:
  - Is the ball on the ground?
  - name: department
    question: Which department should handle this request?
    choices:
      billing: Charges, invoices, or refunds
      technical: Errors or broken functionality
  - "{question.urgent}"
```

Saving preserves the form the author chose:

- a string remains an anonymous inline yes/no question;
- a passed `Question` object is embedded, even if that Question has a name or was previously saved;
- an exact `{question.name}` filling remains a live reference and resolves when the Sampler runs.

Chatsnack should never infer a live reference from a Question's name or save history. `sampler.questions` therefore remains the authored specification, while `sample.questions` contains the resolved Question snapshots used for one execution.

### A Sample can become a new Sampler

An executed Sample contains enough resolved input to create a reproducible Sampler definition:

```python
replay = Sampler.from_sample(sample, name="support_replay")
```

`from_sample()` copies `sample.data`, embeds the resolved `sample.questions` in their original order, and uses the actual `sample.model` reported by TypeSafe. It does not copy `sample.answers` or `sample.usage`; the returned Sampler is an unevaluated definition that can be run again. Embedding the resolved questions also means later edits to saved Question assets do not silently change the replay.

Replay preserves literal evaluated inputs through save/load automatically. It
reproduces the inputs; provider outputs may differ between runs.

Using a Sample as new evaluation content is a separate composition:

```python
followup = Sampler(data=sample)
```

That treats the prior Sample, including its answers, as the next Sampler's data rather than reconstructing its original definition.

## Jev parameters

Jev's semantic request is intentionally small. The documented request body contains `state`, `model`, and `questions`. Jev does not currently document chat-generation controls such as temperature, `top_p`, token limits, seed, or reasoning effort.

`Sampler` should still follow chatsnack's established `params` configuration surface:

```python
sampler = Sampler(
    data=mydata,
    model="jev-latest",
)
```

`model=` is the convenient constructor and property surface, backed by `sampler.params.model` and saved as:

```yaml
params:
  model: jev-latest
```

The current TypeSafe aliases are:

- `jev-latest`, the stable SDK default;
- `jev-preview`, the newest preview release;
- versioned IDs such as `jev-1.13.0` for pinned behavior.

As verified on 2026-09-17, both aliases resolve to `jev-1.13.0`. Aliases move when TypeSafe releases a model. A pinned version is appropriate when code has calibrated decision thresholds against a particular release. The response reports the model version that answered.

The SDK also exposes execution and client settings. These may be authored when needed:

```yaml
params:
  model: jev-1.13.0
  timeout: 20
  retry:
    max_retries: 3
```

`SamplerParams` members are:

| Member | Purpose |
| --- | --- |
| `model` | Jev alias or pinned model ID. |
| `timeout` | Per-operation HTTP timeout. |
| `retry` | Optional serializable retry policy. |
| `base_url` | Alternate TypeSafe-compatible endpoint. |
| `api_key_env` | Name of the environment variable containing the API key. |

Secrets are never saved. Advanced SDK escape hatches such as custom transports, clients, arbitrary headers, and `extra_body` should not be part of the common authored surface.

Call-time overrides follow the same pattern as data:

```python
sample = sampler.ask(
    "Is the ball on the ground?",
    model="jev-preview",
    timeout=30,
)
```

Their precedence is:

1. `ask()` override
2. `sampler.params`
3. TypeSafe SDK or environment default

## Example saved Sampler

Python authoring:

```python
from chatsnack import Question, Sampler

ball_grounded = Question(
    name="ball_grounded",
    question="Is the ball on the ground?",
    yes="The ball is touching the playing surface.",
    no="The ball is airborne or held by a player.",
)
ball_grounded.save()

review = Sampler(
    name="play_review",
    model="jev-1.13.0",
    data={
        "description": "The ball bounced near the sideline.",
        "frame": 1842,
    },
    questions=["{question.ball_grounded}"],
)
review.save()
```

Conceptual YAML:

```yaml
params:
  model: jev-1.13.0
data:
  description: The ball bounced near the sideline.
  frame: 1842
questions:
  - "{question.ball_grounded}"
```

The provider adapter resolves the filling and compiles a request resembling:

```json
{
  "state": {
    "description": "The ball bounced near the sideline.",
    "frame": 1842
  },
  "model": "jev-1.13.0",
  "questions": {
    "ball_grounded": {
      "type": "noul",
      "instructions": "Is the ball on the ground?",
      "criteria": {
        "true": "The ball is touching the playing surface.",
        "false": "The ball is airborne or held by a player."
      }
    }
  }
}
```

Provider compilation is inspectable for debugging, but the JSON request is not the authoring format.

## Yes/no answer direction

TypeSafe returns a Noul value from `0` to `1`, representing the probability of yes. Noul does not include the separate confidence statistic returned for Choice and Score answers.

The desired common path is readable branching:

```python
answer = sampler.ask("Is the ball on the ground?").answer

if answer.yes:
    result = sampler.ask("Is the ball out of bounds?").answer
    if result.no:
        legit_throw = True
```

The rich result should expose the same probability collection used by the other answer kinds:

```python
answer.choice                # "yes" or "no"
answer.probabilities["yes"]  # Jev's returned Noul value
answer.probabilities["no"]   # derived as 1 - the Noul value
answer.score                 # the same value as answer.probabilities["yes"]
answer.confidence            # abs(2 * answer.score - 1)
```

This mapping is lossless even though Jev returns only the probability of yes. `.yes` means `answer.choice == "yes"`, while `.no` means `answer.choice == "no"`. `.score` preserves the provider's directional probability of yes. `.confidence` measures distance from an even split without changing that direction.

At an exact `0.5` tie, `.choice` is `"yes"`, `.yes` is true, `.no` is false, and `.confidence` is `0`. Application action thresholds can be stricter than the ordinary selected answer; those thresholds are application policy rather than Jev inference parameters.

## Named Sampler result fillings

A saved Sampler can expose a named answer directly through a filling:

```text
{sampler.support_needs.department.choice}
{sampler.support_needs.department.score}
{sampler.support_needs.department.confidence}
```

The `sampler.support_needs` portion already means “execute this Sampler and inspect its result,” so an extra `.answers` segment would add noise without resolving ambiguity. The next segment is always a named answer. Positional result lookup remains available in Python through `sample.answers[0]`; the initial filling syntax requires a question name so the saved prompt stays readable when question order changes.

Sampler metadata such as model and usage is not exposed through this first result-filling namespace. This allows an answer named `model` or `usage` without a reserved-name collision. Repeated result fillings for the same Sampler and resolved data during one expansion share one execution.

## Future post-evaluation text and conditional branches

Declarative conditional branches are outside the first implementation. A later design may give Sampler an authored post-evaluation template, tentatively called `text`:

```yaml
data: "{message}"
questions:
  - name: department
    question: Which department should handle this request?
    choices: [billing, technical, general]
text: |
  Route to {answer.department.choice}.
```

The example answer namespace is illustrative rather than settled syntax. The template would resolve only after all questions have been answered, and its final resolved string would be available as `sample.text`. An exact Sampler filling could eventually insert that final text, making a Sampler useful as a decision-backed text filling without turning it into a general workflow engine.

If declarative branches are added inside this post-evaluation text, they should satisfy these constraints:

- a selected branch may resolve its nested chat, text, question, or sampler fillings;
- an unselected branch makes no provider calls;
- repeated references to the same Sampler evaluation during one expansion share its result;
- data supplied to a Sampler can remain structured;
- the resulting saved prompt remains readable without provider-shaped request objects.

This lazy branch behavior is more involved than named result interpolation because the current formatter expands fillings before it understands conditional selection. It should be designed separately after the direct Sampler and result-filling behavior have proved useful.

## Validation rules

The public layer should reject invalid authored questions before making a provider request:

- missing or empty question instructions;
- both `choices` and `levels` on one question;
- `yes` or `no` combined with `choices` or `levels`;
- empty Choice options;
- fewer than two Score levels;
- duplicate Choice option keys or Score level identifiers;
- invalid or duplicate explicit question names in one batch;
- a missing saved Question referenced by an exact filling;
- missing data after call and Sampler precedence are applied;
- both a positional question and `questions=` on the same call.

The response adapter validates the structure it needs to decode an answer, including that a returned Choice key exists in the returned probability map. It does not check that TypeSafe selected a unique or maximal probability.

Provider errors and transport failures should remain recognizable rather than being converted into plausible answers.

## Choice and Score authoring

The following shapes are the current proposed contract.

### Choice

Choice accepts either a list of option names or a mapping from names to descriptions. This keeps the simple case short while preserving TypeSafe's richer criteria when an option needs explanation.

Simple options:

```python
topic = Question(
    name="topic",
    question="What is the main topic?",
    choices=["billing", "technical", "general"],
)
```

```yaml
question: What is the main topic?
choices:
  - billing
  - technical
  - general
```

The compiler turns each list member into a TypeSafe criterion with a null description.

Described options:

```python
topic = Question(
    name="topic",
    question="What is the main topic?",
    choices={
        "billing": "Charges, invoices, or refunds",
        "technical": "Errors or broken functionality",
        "general": "Everything else",
    },
)
```

```yaml
question: What is the main topic?
choices:
  billing: Charges, invoices, or refunds
  technical: Errors or broken functionality
  general: Everything else
```

A Choice answer's working shape is:

```python
answer.choice                     # "technical"
answer.score                      # probability of "technical"
answer.probabilities["technical"] # probability for one option
answer.confidence                 # TypeSafe's distribution confidence
```

For Choice, `answer.score == answer.probabilities[answer.choice]`.

Dynamic option attributes such as `answer.technical` are not proposed. Option names may collide with answer members, contain spaces, or be invalid Python identifiers.

### Score

```python
frustration = Question(
    name="frustration",
    question="How frustrated does the customer appear?",
    levels=[
        "Calm",
        "Concerned",
        "Clearly frustrated",
        "Extremely angry",
    ],
)
```

```yaml
question: How frustrated does the customer appear?
levels:
  - Calm
  - Concerned
  - Clearly frustrated
  - Extremely angry
```

Each level has a stable, unique name. In the simple form, the scalar text is both its name and its provider description. A richer level keeps the same visible order and maps one stable name to its description or structured rubric:

```yaml
levels:
  - calm: No visible frustration
  - concerned: Expresses concern without blame
  - frustrated: Clearly dissatisfied or impatient
  - angry:
      description: Hostile, accusatory, or threatening
      examples:
        - This is completely unacceptable.
```

The adapter keeps those names while compiling TypeSafe's ordered criteria array, then maps the returned numeric level indices back to them.

TypeSafe returns both a probability distribution over levels and a probability-weighted numeric score. The most probable level and weighted score can differ.

The result uses the universal selected outcome while retaining Score vocabulary:

```python
answer.choice                        # "Clearly frustrated"
answer.score                         # probability-weighted numeric position
answer.probabilities[answer.choice]  # probability of the selected level
answer.confidence
```

There is no `.level` alias. The authored question calls the ordered rubric `levels`; the answer consistently calls its selected outcome `.choice`, while `.score` retains TypeSafe's returned Score value.

## Deferred composition decisions

The direct Python API, persistence shape, reconstruction behavior, and named result fillings no longer depend on the conditional design. Later composition work still needs to settle:

1. Whether the post-evaluation template is named `text` and how it refers to answers internally.
2. What an exact whole-value `{sampler.name}` filling returns when a Sampler has post-evaluation text.
3. The declarative branch syntax and its lazy evaluation rules.

## Implementation outline

The likely implementation can stay layered:

1. Add `Question`, `SamplerParams`, `Sampler`, and answer models.
2. Compile inferred questions and `data` into the TypeSafe request.
3. Add sync and async provider execution with TypeSafe SDK support included by default.
4. Add snapclass persistence and concise Sampler/Question YAML formatting.
5. Add exact `{question.name}` typed filling resolution.
6. Add `Sampler.from_sample()` with resolved snapshot semantics.
7. Add direct named Sampler result fillings with per-expansion execution reuse.
8. Consider post-evaluation text and lazy conditional composition as a later design.

The direct single-question API is modest. Durable question references, typed whole-value filling resolution, mixed batch results, and per-expansion execution reuse account for most of the initial integration complexity. Lazy conditional branches remain the larger future formatter change.

## Source contract

The provider behavior in this concept was checked against TypeSafe's current documentation on 2026-09-17:

- [HTTP API request and answer types](https://docs.typesafe.ai/api.md)
- [Jev models and aliases](https://docs.typesafe.ai/models.md)
- [Python synchronous client](https://docs.typesafe.ai/sdk/python/api/clients/sync/client.md)
- [Python retry policy](https://docs.typesafe.ai/sdk/python/api/retries.md)
- [Noul](https://docs.typesafe.ai/primitives/noul.md)
- [Choice](https://docs.typesafe.ai/primitives/choice.md)
- [Score](https://docs.typesafe.ai/primitives/score.md)
- [Structured question entries](https://docs.typesafe.ai/primitives/advanced.md)
- [Confidence](https://docs.typesafe.ai/confidence.md)
