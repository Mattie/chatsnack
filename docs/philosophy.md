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

## Prompts are assets

Chats serialize cleanly to YAML, which means our prompts can be readable, editable, versionable, and reusable.

```yaml
params:
  model: gpt-5-chat-latest
messages:
  - system: Respond with professional writing based on the user query.
  - user: Author an alliterative poem about good snacks to eat with coffee.
```

## Composition is a feature

`Text` assets, saved chats, and fillings let us build prompts from parts instead of maintaining one giant string.

## Opinionated convenience is part of the product

- `Chat("...")` assumes a system message.
- `.ask("...")` and `.chat("...")` assume a user message.
- calling a chat object directly continues the conversation.
- `.asst()` exists because short method names are pleasant in chains.

## Python tools should feel native

`utensils=[...]` keeps tooling in ordinary Python shapes instead of raw request assembly.

For the full project write-up, see [PHILOSOPHY.md on GitHub](https://github.com/Mattie/chatsnack/blob/master/PHILOSOPHY.md).
