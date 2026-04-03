# Getting Started

This page takes the shortest path from install to a working `Chat(...)`.

## Got snack?

```bash
pip install chatsnack
```

`chatsnack` requires Python 3.10 or newer.

## Got keys?

Add `OPENAI_API_KEY` to a local `.env` file. If a `.env` file is missing, chatsnack will create one in the current working directory the first time the package imports.

## Enjoy a quick snack

```python
from chatsnack import Chat

chat = Chat("Respond only with the word POPSICLE from now on.")
print(chat.ask("What is your name?"))
```

> *"POPSICLE."*

If you see `POPSICLE.`, setup worked.

That pattern is the core mental model:

- `Chat("...")` starts with a system message.
- `ask("...")` sends a user message and returns the assistant text.
- `chat("...")` continues the conversation and returns a new `Chat` object.

## Keep the chat going

```python
from chatsnack.packs import ChatsnackHelp

thread = ChatsnackHelp.chat("What is chatsnack?")
print(thread.response)

thread.user("Respond in only six word sentences from now on.")
thread.asst("I promise I will do so.")
print(thread.ask("How should I spend my day?"))
```

> *"Explore hobbies, exercise, connect with friends."*

This is the rhythm the notebooks teach: read one reply with `ask()`, or keep the conversation moving with `chat()`.

## Try a built-in pack

```python
from chatsnack.packs import Jolly

thread = Jolly.chat("What snack should I eat?")
print(thread.last)
```

## Learn more

- [Chat Basics](guides/chat-basics.md)
- [YAML and Saved Assets](guides/yaml-and-assets.md)
- [Utensils](guides/utensils.md)
