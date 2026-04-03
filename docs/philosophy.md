# Philosophy

chatsnack treats prompt work as something we author, save, remix, and compose.

## The short version

- `Chat` is the primary unit of work.
- Prompt assets deserve a readable file format.
- Reuse should be easy enough for experiments and strong enough for real systems.
- Composition matters more than giant prompt strings.
- Good defaults and terse syntax help us stay in flow.
- Python tools should stay close to Python.

## `Chat` is the center of gravity

Typical flows look like this:

```python
from chatsnack import Chat

chat = Chat("Respond tersely.")
answer = chat.ask("What is chatsnack?")
thread = chat.chat("Continue with two examples.")
```

That keeps one-shot prompts and ongoing threads on the same object model.

The distinction between `ask()` and `chat()` matters:

- `ask()` is for a response we want to read immediately.
- `chat()` is for progressing the conversation and getting a new `Chat` back.

That is one of the reasons experimentation feels pleasant in chatsnack. The semantics stay simple and visible.

## Prompts are assets

Chats serialize cleanly to YAML, which means our prompts can be readable, editable, versionable, and reusable.

```yaml
params:
  model: gpt-5-chat-latest
messages:
  - system: Respond with professional writing based on the user query.
  - user: Author an alliterative poem about good snacks to eat with coffee.
```

The durable artifact is a prompt asset we can inspect, keep, and compose into the next thing.

## Composition is a feature

`Text` assets, saved chats, and fillings let us build prompts from parts instead of maintaining one giant string.

That keeps advanced behavior additive to the common path. We still start from `Chat`, then scale up through saved ingredients and prompt composition.

## Opinionated convenience is part of the product

- `Chat("...")` assumes a system message.
- `.ask("...")` and `.chat("...")` assume a user message.
- calling a chat object directly continues the conversation.
- `.asst()` exists because short method names are pleasant in chains.

Those shortcuts give chatsnack its rhythm. The code reads like an experimenter's notebook.

## Snack packs express reusable behavior

Snack packs package useful voices and directives so we can reach for them quickly, then keep chatting with the same `Chat` mental model.

That is why the jump from a built-in helper pack to our own saved prompt assets feels natural.

## The notebooks show the intended ceiling

The notebooks are more than tutorials. They show the design target:

- start from `Chat`
- use `ask()` and `chat()` intentionally
- inspect YAML early
- save prompts as assets
- compose with fillings
- keep advanced examples on the same mental model

The same primitives that make a quick smoke test pleasant are meant to support richer prompt workflows later.

## chatsnack encourages iterative prompt craft

The workflow has a quiet but important loop:

- try something quickly
- inspect the resulting chat
- keep the useful version
- reuse it as an asset
- compose it into the next thing

That is a big part of the product philosophy. chatsnack helps us move from a disposable experiment to a reusable prompt artifact without switching tools halfway through.

## Python tools should feel native

`utensils=[...]` keeps tooling in ordinary Python shapes instead of raw request assembly.

## Playful language, serious ideas

The snack theme is playful, and the underlying ideas are serious:

- prompt assets as files
- composable prompt ingredients
- reusable behavior through packs and saved chats
- terse multi-step authoring
- Python-native tools

That mix is why chatsnack feels distinctive.

For the full project write-up, see [PHILOSOPHY.md on GitHub](https://github.com/Mattie/chatsnack/blob/master/PHILOSOPHY.md).
