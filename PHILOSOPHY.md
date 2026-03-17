# Chatsnack Philosophy

## The short version

chatsnack treats prompt work as something we author, save, remix, and compose.

The library is built around a few clear ideas:

- A `Chat` object is the primary unit of work.
- Prompt assets deserve a readable file format.
- Reuse should be easy enough for experiments and strong enough for real systems.
- Composition matters more than giant prompt strings.
- Good defaults and terse syntax help us stay in flow.
- Python code should stay close to Python when we add tools.

That combination is what gives chatsnack its personality.

## `Chat` is the center of gravity

The notebooks make this very clear. Users are meant to think in terms of chats.

Typical flows look like this:

```python
from chatsnack import Chat

chat = Chat("Respond tersely.")
answer = chat.ask("What is chatsnack?")
thread = chat.chat("Continue with two examples.")
```

That design carries a few opinions with it:

- A conversation has identity and shape.
- Prompt state should stay easy to inspect.
- Continuation should feel natural.
- One-shot queries and continuing threads should both start from the same object.

The distinction between `ask()` and `chat()` is especially important.

- `ask()` is for a response we want to read immediately without mutating the current chat state.
- `chat()` is for progressing the conversation and getting a new `Chat` object back.

This makes experimentation pleasant because the semantics stay simple and visible.

## Prompts are assets

One of chatsnack's best ideas is that chats serialize cleanly to YAML.

That means our prompts can live as files that are:

- readable
- editable
- versionable
- reusable
- portable across scripts and notebooks

The durable artifact is a prompt asset we can inspect, version, and keep.

Example:

```yaml
params:
  engine: gpt-4
  temperature: 0.8
messages:
  - system: Respond with professional writing based on the user query.
  - user: Author an alliterative poem about good snacks to eat with coffee.
```

That is a practical design choice and a philosophical one. chatsnack assumes prompt authoring deserves first-class treatment.

## Composition is a feature

Fillings are one of the most distinctive parts of chatsnack.

They let us expand prompt ingredients into other prompts:

- `{text.Name}` for reusable text assets
- `{chat.Name}` for reusable or dynamic chat outputs
- keyword replacement for common templating cases
- include messages for chat-level composition

This turns chatsnack into a lightweight prompt composition system.

Instead of maintaining one massive prompt, we can build from parts:

- system guidance
- reusable snippets
- generated intermediate outputs
- stored prompt assets
- inline values

That composability is what enables many of the more advanced notebook examples.

## Fillings support dynamic prompt generation

The advanced examples push past static templating.

Saved chats can generate content that becomes part of another prompt. Multiple fillings can resolve in parallel before the final chat is submitted. This gives us a compact way to express multi-step prompt preparation.

That is a strong idea because it keeps the authoring surface small while enabling richer workflows.

We can think about it this way:

- chats define behavior
- texts define reusable snippets
- fillings wire them together

From those few pieces, we get a lot of expressive power.

## Opinionated convenience is part of the product

chatsnack is intentionally willing to make a few bets on ergonomics.

Examples:

- `Chat("...")` assumes the first string is a system message.
- `.ask("...")` and `.chat("...")` assume the string is a user message.
- calling a chat object directly is shorthand for continuing the conversation.
- `.asst()` exists because short method names are pleasant in chains.
- built-in snack packs are singleton presets ready to use immediately.

These shortcuts give the library its rhythm. The code reads like an experimenter's notebook, which is exactly the point.

The goal is to make structure compact enough that we keep using it.

## Snack packs express reusable behavior

Snack packs are opinionated reusable chat presets.

They show how chatsnack expects us to build higher-level behavior:

- define a useful voice or directive once
- save or package it
- reload and reuse it everywhere

This works for personalities, task specialists, domain assistants, and prompt libraries.

The idea scales naturally from a built-in helper bot to our own collection of prompt assets.

## The notebooks show the intended ceiling

The notebooks are more than tutorials. They reveal the design target.

### Getting Started notebook

This notebook shows the baseline workflow:

- start from `Chat`
- use `ask()` and `chat()` intentionally
- inspect YAML
- save prompt assets
- load them later
- compose prompts with `Text` and `Chat` fillings

### Experimental notebook

This notebook shows the upper edge of the same philosophy:

- autonomous conversations between bots
- sleeper prompts inserted into existing history
- identity generation feeding into later prompts
- multi-step transformations over previous outputs

Nothing in those examples requires a different mental model. That is the important part.

The same primitives that make a quick prompt pleasant also make complex prompt workflows possible.

## chatsnack encourages iterative prompt craft

There is a quiet but important stance behind the API:

- try something quickly
- inspect the resulting chat
- keep the useful version
- reuse it as an asset
- compose it into the next thing

This encourages prompt craft and keeps the workflow close to the prompts themselves.

The library helps us move from a disposable experiment to a reusable prompt artifact without changing tools halfway through.

## Python tools should feel native

Utensils continue the same philosophy on the tool side.

We write normal Python functions, annotate them, and hand them to a chat:

```python
from chatsnack import Chat, utensil

@utensil
def get_weather(location: str, unit: str = "celsius"):
    """Get the current weather for a location."""
    return {"temperature": 72, "condition": "sunny", "unit": unit}

chat = Chat("You can use tools when helpful.", utensils=[get_weather])
```

The important design choice here is proximity. Tooling stays close to the host language and keeps authoring in a familiar Python shape.

## Playful language, serious underlying ideas

The snack theme is playful, and the underlying design ideas are strong:

- prompt assets as files
- composable prompt ingredients
- reusable personas and packs
- terse multi-step authoring
- Python-native tool integration

That combination is why chatsnack feels distinctive. The tone is light, and the workflow is thoughtful.

## A useful mental model

When we work with chatsnack, it helps to think in layers:

1. `Chat` defines the conversational unit.
2. YAML makes that unit durable.
3. `Text` and saved chats become reusable ingredients.
4. Fillings compose those ingredients into new prompts.
5. Snack packs package recurring behaviors.
6. Utensils connect prompt flows to Python functions.

Everything else in the library grows out of those layers.

## What to keep in mind when extending chatsnack

If we want future work to still feel like chatsnack, these qualities matter:

- Keep `Chat` as the main abstraction.
- Keep saved prompt assets human-readable.
- Keep composition central.
- Keep advanced flows additive to the common path.
- Keep experimentation fast.
- Keep reusable behavior easy to package and reload.

That is the philosophy that shows up across the README, notebooks, examples, and runtime code.
