# Fillings And Composition

Fillings let us build larger prompts from named assets.

## Reuse saved chats

```python
from chatsnack import Chat

basechat = Chat(name="ExampleIncludedChat").system(
    "Respond only with the word CARROTSTICKS from now on."
)
basechat.save()

anotherchat = Chat().include("ExampleIncludedChat")
print(anotherchat.ask("What is your name?"))
```

## Reuse saved text

```python
from chatsnack import Chat, Text

mytext = Text(
    name="SnackExplosion",
    content="Respond only in explosions of snack emojis and happy faces.",
)
mytext.save()

explosions = Chat(name="SnackSnackExplosions").system("{text.SnackExplosion}")
print(explosions.ask("What is your name?"))
```

## Compose generated outputs

```python
from chatsnack import Chat

snacknames = Chat(name="FiveSnackNames").system(
    "Respond with high creativity and confidence."
).user("Provide 5 random snacks.")
snacknames.save()

snackdunk = Chat(name="SnackDunk").system(
    "Respond with high creativity and confidence."
).user("Provide 3 dips or drinks that are great for snack dipping.")
snackdunk.save()

snackfull = Chat().system("Respond with high confidence.")
snackfull.user(
    """Choose 1 snack from this list:
{chat.FiveSnackNames}

Choose 1 dunking liquid from this list:
{chat.SnackDunk}

Recommend the best single snack and dip combo above."""
)

print(snackfull.chat().yaml)
```

This keeps the authoring surface small while still enabling multi-step prompt preparation.
