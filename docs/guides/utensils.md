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

## Async local functions

Use the same decorator for an async function. Chatsnack awaits its result before
recording the tool turn or sending the result back to the model:

```python
import asyncio
from chatsnack import Chat, utensil

@utensil
async def stock(snack: str):
    """Read demo snack stock."""
    await asyncio.sleep(0)
    return {"snack": snack, "available": 12}

pantry = Chat("Use stock to check availability.", utensils=[stock])
thread = await pantry.chat_a("How much popcorn is available?")
print(thread.last)
```

The demo yields once; a real lookup might await an async HTTP client. While a
tool waits, independent chats can make progress on the same event loop. Tools
within one response still execute sequentially, in the model's requested order.
Synchronous functions keep running inline, so blocking I/O or lengthy computation
inside either kind of function can still hold up the event loop.

`chat()` also executes async utensils through its existing async bridge in a
script without an active event loop. In notebooks and async applications, use
`await chat.chat_a(...)`. This adds async execution to existing tool workflows;
it does not add automatic tool execution to `ask_a()` or streaming listeners.

### Saved async capabilities

Grouped async functions use the existing compact YAML shape. Author and save
the chat normally, then attach the Python capability again when loading it:

```python
snacks = utensil.group("snacks", "Snack stock.")

@snacks
async def stock(snack: str):
    """Read demo snack stock."""
    await asyncio.sleep(0)
    return {"snack": snack, "available": 12}

pantry = (
    Chat(name="SnackStock", utensils=[snacks])
    .system("Use stock to check availability.")
    .user("Check {snack}.")
)
print(pantry.yaml)
pantry.save()

reused = Chat(name="SnackStock", utensils=[snacks])
reused.load()
thread = await reused.chat_a(snack="popcorn")
print(thread.last)
```

The saved tool and prompt excerpt stays readable:

```yaml
params:
  tools:
    - snacks: Snack stock.
      tools:
        - stock: Read demo snack stock.
          snack: str
messages:
  - system: Use stock to check availability.
  - user: Check {snack}.
```

Python bindings stay out of YAML. Copies, continued chats, and `reset()` retain
their local bindings. Async execution needs no new saved setting or model
capability. OpenAI's model-level `async: true` declaration is a separate protocol
and is not enabled by defining a Python async utensil.

Prompt copies retain the same live Python callables, including bound methods on
services with HTTP clients or locks. Copying a prompt does not isolate a tool's
application state.

### Concurrency and failures

Ordinary exceptions, including those raised while awaiting a tool, become the
existing error result. Cancellation propagates so the application can stop a
question and the tool can release resources in `finally` blocks. Chatsnack does
not start detached background jobs or move synchronous functions into threads.

Applications own shared rate limits and validation of actions against current
game state. Context variables retain their task-local bindings; they do not make
shared mutable objects safe. Concurrent WebSocket requests need independent
sessions; the existing one-response-at-a-time guard on a shared session remains.

For manual execution, use `await chat.execute_tool_call_a(call)` or
`await handle_tool_call_a(call, local_registry=...)` from `chatsnack.utensil`.
The synchronous manual methods return an error with that guidance when a tool
returns an awaitable. Existing custom `execute_tool_call()` overrides remain
authoritative during automatic execution, and their awaitable results are awaited.
Override `execute_tool_call_a()` when writing an async execution policy that
delegates to the default async dispatcher.

When synchronous manual dispatch rejects a coroutine, it closes it. Returned
asyncio Tasks and Futures are cancelled if pending, and their failures are
collected, including failures raised by task cancellation cleanup. Cancellation
is cooperative and cannot undo side effects that already happened.

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
