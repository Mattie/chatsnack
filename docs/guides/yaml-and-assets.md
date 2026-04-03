# YAML And Saved Assets

One of chatsnack's best ideas is that chats are durable prompt assets.

## Inspect YAML early

```python
from chatsnack import Chat

chat = (
    Chat("Respond only with the word POPSICLE from now on.")
    .user("What is your name?")
    .chat()
)

print(chat.yaml)
```

```yaml
messages:
  - system: Respond only with the word POPSICLE from now on.
  - user: What is your name?
  - assistant: POPSICLE.
```

## Save and reload a chat

```python
from chatsnack import Chat

chat = Chat("Respond only with the word POPSICLE from now on.")
chat.name = "Popsicle"
chat.save()

saved = Chat(name="Popsicle")
print(saved.ask("What is your name?"))
```

## Save reusable text

```python
from chatsnack import Text

voice = Text(
    name="SnackExplosion",
    content="Respond only in explosions of snack emojis and happy faces.",
)
voice.save()
```

`Text` objects let us keep prompt fragments in files instead of large strings embedded in Python code.

## Parameter changes also serialize

```python
from chatsnack import Chat

wisechat = Chat("Respond with professional writing based on the user query.")
wisechat.user("Author an alliterative poem about good snacks to eat with coffee.")
wisechat.model = "gpt-5-chat-latest"
```

That keeps a prompt asset close to the exact runtime configuration we meant to use.
