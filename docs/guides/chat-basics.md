# Chat Basics

The common path in chatsnack starts from `Chat`.

## `ask()` versus `chat()`

Use `ask()` when we want the assistant text back immediately without creating a continuation object.

```python
from chatsnack import Chat

chat = Chat("Respond tersely.")
answer = chat.ask("What is chatsnack?")
print(answer)
```

Use `chat()` when we want the next turn as a new `Chat` object.

```python
from chatsnack import Chat

base = Chat("Respond tersely.")
thread = base.chat("What is chatsnack?")
print(thread.response)
```

## Message chaining

The object stays readable even when we chain.

```python
from chatsnack import Chat

thread = (
    Chat("Respond only with the word POPSICLE from now on.")
    .user("What is your name?")
    .chat()
)

print(thread.response)
```

## Shorthand authoring

- `Chat("...")` treats the first string as a system message.
- `.ask("...")` and `.chat("...")` treat the string as a user message.
- `.asst(...)` is an alias for `.assistant(...)`.
- Calling a chat object directly continues the conversation like `.chat(...)`.

```python
from chatsnack import Chat

popcorn = (
    Chat("Respond with the certainty and creativity of a professional writer.")
    ("Explain 3 rules to writing a clever poem that amazes your friends.")
    ("Using those tips, write a scrumptious poem about popcorn.")
)

print(popcorn.last)
```

## Attachments on the default Responses path

```python
from chatsnack import Chat

chat = Chat("Review the attachment and answer tersely.")
print(chat.ask("Summarize these.", files=["./images/chart.png", "./data/sales.csv"]))
```

Attachment-aware turns stay serialized as expanded YAML blocks while plain text turns stay scalar-first.
