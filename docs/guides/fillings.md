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

## Resolve fillings directly

External assemblers such as Catsnack sometimes know the finite set of static
`text.Name` and `chat.Name` references they need before building a prompt. They
can resolve that set directly:

```python
from chatsnack import resolve_fillings

resolved = resolve_fillings(["text.SnackExplosion"])
print(resolved.context["text"]["SnackExplosion"])
```

Direct resolution follows these rules:

- Explicit values in `variables["text"]` or `variables["chat"]` take priority
  without loading a saved asset.
- Saved text can refer to other text or chat fillings. Text cycles and excessive
  nesting fail with a bounded resolver error.
- Saved chat references require `allow_chat=True` before `chatsnack` makes a model
  call. This also applies when saved text contains a chat reference.
- Saved chats resolved by the default source must be self-contained. Nested
  `text.*` or `chat.*` fillings are rejected before provider I/O so legacy
  expansion cannot bypass the resolver's invocation limits.
- Missing requested names appear in `missing_references`. A missing dependency
  inside saved text stops that text from resolving.
- Inserted values remain plain data. `chatsnack` does not scan them for more
  filling references.
- `FillingLimits` bounds nesting, resolved nodes, chat calls, and concurrent
  chat calls.

See the [Fillings API reference](../reference/api/fillings.md) for signatures,
result metadata, limits, sources, and errors.
