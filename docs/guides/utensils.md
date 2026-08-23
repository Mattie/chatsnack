# Utensils

Local Python functions and hosted OpenAI tools share one `utensils=[...]` surface.

## Local function tools

```python
from chatsnack import Chat, utensil

@utensil
def get_weather(location: str, unit: str = "celsius"):
    """Get the current weather for a location."""
    return {"temperature": 72, "condition": "sunny", "unit": unit}

chat = Chat(
    "Use tools only when useful.",
    utensils=[get_weather],
)
```

## Grouped tool namespaces

```python
from chatsnack import Chat, utensil

crm = utensil.group("crm", "CRM tools for customer lookup.")

@crm
def get_customer(customer_id: str):
    """Look up one customer by ID."""
    return {"id": customer_id}

chat = Chat(
    "Use CRM tools only when useful.",
    utensils=[crm, utensil.tool_search],
)
```

## Hosted tools

```python
from chatsnack import Chat, utensil

docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)

chat = Chat(
    "Use tools only when useful.",
    utensils=[utensil.tool_search, docs_search],
)
chat.reasoning.summary = "auto"
```

`sources=True` on `web_search(...)` automatically adds the matching `params.responses["include"]` entry.

## Apply Patch

Apply Patch can change files only through a Python executor supplied by your
application. Chatsnack carries the native Responses call and its output through
the conversation; the executor is where your application enforces path checks,
approvals, file writes, evidence, and recovery.

Copy the [local workspace example](../examples/local-apply-patch.md) when you
want a working implementation confined to one directory. Then bind it like any
other Python capability:

```python
from chatsnack import Chat, utensil
from apply_patch_workspace import LocalWorkspace

workspace = LocalWorkspace("my-project")
patch = utensil.apply_patch(execute=workspace.apply_patch)

editor = Chat(
    "Edit only files the workspace permits.",
    utensils=[patch],
)

edited = editor.chat("In menu.txt, replace `kettle corn` with `caramel corn`.")
print(edited.last)
```

The executor receives an `ApplyPatchCall`. `call.operation` says which file to
create, update, or delete. The executor must return one of these shapes:

```python
{"status": "completed", "output": "Renamed the file."}
{"status": "failed", "output": "That path is outside the workspace."}
```

Chatsnack turns exceptions and invalid return values into failed tool outputs.
Completed calls run in provider order. A call with another status stops before
the executor runs. Exception messages become output text, so catch errors that
contain sensitive local details and return a safe failed result.

### Saved chats

Copies and continued chats keep the live executor. `reset()` restores the
executor supplied when the chat was created. The executor stays out of YAML; a
saved chat keeps only the tool declaration:

```yaml
params:
  tools:
    - apply_patch
```

Pass the utensil again when loading the chat:

```python
loaded = Chat(name="PatchWriter", utensils=[patch])
loaded.load()
```

With automatic execution enabled, an independently loaded chat without that
binding fails before the provider request is sent.

### Runtime limits

Automatic Apply Patch execution requires a Responses runtime, `stream=False`,
and `chat()` or `chat_a()`. Use `allowed_callers` when the provider should limit
which invocation contexts may request a patch:

```python
patch = utensil.apply_patch(
    execute=workspace.apply_patch,
    allowed_callers=["direct", "programmatic"],
)
```

## Why this surface matters

- local Python tools stay close to Python
- grouped tools read like named capabilities
- hosted tools stay off raw provider dicts in the common path
- the `Chat(...)` constructor still reads like authored code
