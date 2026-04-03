# Prompt Recipes

## Smoke test

```python
from chatsnack import Chat

print(Chat("Respond only with the word POPSICLE from now on.").ask("What is your name?"))
```

## Continue a useful thread

```python
from chatsnack import Chat

thread = Chat("Respond tersely.").chat("What is chatsnack?")
thread = thread.chat("Give me two practical examples.")
print(thread.last)
```

## Save a prompt asset

```python
from chatsnack import Chat

chat = Chat(name="SnackPoet").system("Write playful poetry about snacks.")
chat.save()
```

## Build a reusable tool-enabled chat

```python
from chatsnack import Chat, utensil

@utensil
def get_weather(location: str):
    """Return a tiny weather payload."""
    return {"location": location, "forecast": "sunny"}

weather_chat = Chat(
    "Use tools when helpful and answer briefly.",
    utensils=[get_weather],
)
```

## Compose from saved ingredients

```python
from chatsnack import Chat, Text

Text(name="SnackVoice", content="Respond like a delighted snack critic.").save()

critic = Chat().system("{text.SnackVoice}")
print(critic.ask("Review popcorn in one sentence."))
```
