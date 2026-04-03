# chatsnack

chatsnack treats prompt work as something we author, save, remix, and compose.

![chatsnack features](chatsnack_features_smaller.jpg)

{:.hero-copy}
It's snack time. These docs start with a tiny smoke test, then move into YAML-backed chats, saved prompt assets, fillings, and utensils.

<div class="callout-grid" markdown>
<div>
### Start Snacking

- [Getting Started](getting-started.md)
- [Chat Basics](guides/chat-basics.md)
</div>
<div>
### Save Ingredients

- [YAML and Saved Assets](guides/yaml-and-assets.md)
- [Fillings and Composition](guides/fillings.md)
</div>
<div>
### Reach For Utensils

- [Utensils](guides/utensils.md)
- [API Reference](reference/index.md)
</div>
</div>

## Enjoy a quick snack

```python
from chatsnack import Chat

chat = Chat("Respond only with the word POPSICLE from now on.")
print(chat.ask("What is your name?"))
```

> *"POPSICLE."*

If that works, chatsnack is up and ready.

## Why chatsnack feels like chatsnack

- `Chat` is the center of gravity for one-shot prompts and continuing threads.
- Chats serialize cleanly to YAML, so prompt work can live in version control.
- Reusable `Text` and saved chats make composition part of the product.
- `utensils=[...]` keeps local functions and hosted tools on one authored surface.
- The same small mental model scales from a tiny snack to more ambitious prompt craft.

## Learn more

- **Getting Started** trims the README and notebook flow into one short first run.
- **Guides** explain the product story in the order people tend to need it.
- **Examples** collect a few compact patterns pulled from the notebooks and scripts.
- **API Reference** covers the stable public surface used in the guides.

## Raw source material

- [README on GitHub](https://github.com/Mattie/chatsnack/blob/master/README.md)
- [Getting Started notebook](https://github.com/Mattie/chatsnack/blob/master/notebooks/GettingStartedWithChatsnack.ipynb)
- [Experimenting notebook](https://github.com/Mattie/chatsnack/blob/master/notebooks/ExperimentingWithChatsnack.ipynb)
