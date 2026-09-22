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
`text.Name`, `chat.Name`, `question.Name`, and named Sampler result references
they need before building a prompt. They can resolve that set directly:

```python
from chatsnack import resolve_fillings_a

resolved = await resolve_fillings_a(["text.SnackExplosion"])
print(resolved["text"]["SnackExplosion"])
```

Direct resolution follows these rules:

- Explicit values in the matching `variables["text"]`, `variables["chat"]`,
  `variables["question"]`, or `variables["sampler"]` namespace take priority for
  the requested names without loading a saved asset.
- Saved assets expand through the same formatter and filling callbacks used by
  ordinary Chat and Sampler calls. A `question.Name` result remains a typed
  Question; `sampler.Name.answer.choice`, `.score`, and `.confidence` return the
  corresponding named result field.
- Saved chat references require `allow_chat=True` before `chatsnack` makes a model
  call. This also applies when saved Text or Chat assets contain a chat filling.
- Saved Sampler result references independently require `allow_sampler=True`.
  Equivalent result fields share one evaluation during that resolver call.
- Missing directly requested assets are omitted after any required authority
  check. A missing transitive dependency stops the requested filling from
  resolving.
- Inserted values remain plain data. `chatsnack` does not scan them for more
  filling references.
- Fixed resolver-only bounds cap recursive depth, filling expansions, Chat calls,
  and Sampler evaluations. They do not change ordinary Chat or Sampler expansion.

See the [Fillings API reference](../reference/api/fillings.md) for the signature
and errors.
