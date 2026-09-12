# YAML And Saved Assets

One of chatsnack's best ideas is that chats are durable prompt assets.

## Inspect YAML early

```python
from chatsnack import Chat

chat = (
    Chat("Respond only with the word POPSICLE from now on.")
    .user("What is your name?")
    .asst("POPSICLE.")
)

print(chat.yaml)
print(chat.snapshot.path)
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
print(chat.snapshot.text)

saved = Chat(name="Popsicle")
print(saved.ask("What is your name?"))
```

## Continue a saved conversation

Responses output stays in `messages` in its original order. Reasoning and
function calls have separate entries; recorded assistant entries retain their
phase and item ID. Ordinary authored replies such as `.asst("Blah")` still save
as `assistant: Blah`.

YAML omits known empty metadata and the default `completed` status. Required API
fields are restored when making a request. Nonempty summaries, citations,
encrypted reasoning, and incomplete statuses remain saved. Empty tool results
and unknown provider payloads also remain meaningful data.

```yaml
messages:
  - user: Check stock for snack-box.
  - reasoning:
      item_id: rs_1
      encrypted_content: "..."
  - tool_call:
      name: stock
      arguments: '{"sku":"snack-box"}'
      call_id: call_1
  - tool:
      tool_call_id: call_1
      content: '{"available":12}'
  - assistant:
      text: We have 12 available.
      phase: final_answer
```

Save the continued Chat and restore it normally:

```python
thread = helper.chat(sku="snack-box")
thread.save()

restored = Chat(name=thread.name, utensils=[stock])
restored.load()
reply = restored.chat("Could I order six?")
```

Here `helper` is our prompt and `stock` is its existing Python utensil.
`export_state` is unnecessary for preserving messages. It still controls optional
response-level state exports. Old scalar messages and `assistant.tool_calls`
continue to load.

Unmapped fields live in `provider_extras`; unfamiliar items and complex assistant
content use `provider_item`. Generated image bytes stay in the existing asset
store, with references in the transcript. Keep that asset store with saved Chats
when moving them to another machine.

Copying and editing preserve later recorded entries. Authored text fillings resolve
at execution; recorded reasoning, arguments, and provider metadata remain literal.
HTTP `store=False` replays the complete history. Stored HTTP and WebSocket calls
can use a verified response ID when the history and provider binding match.
Loading a Chat rebuilds continuation from its messages.

When switching to Chat Completions, chatsnack sends supported dialogue and function
exchanges and warns once per request about omitted provider-only information.
The stored messages remain available for Responses.

The [offline conversation notebook](https://github.com/Mattie/chatsnack/blob/master/notebooks/PortableConversationHistory.ipynb)
shows the complete YAML → call → save/load → continuation flow.

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
wisechat.model = "gpt-5.4"
```

That keeps a prompt asset close to the exact runtime configuration we meant to use.
