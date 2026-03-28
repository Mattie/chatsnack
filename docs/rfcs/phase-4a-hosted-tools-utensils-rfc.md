# Phase 4A RFC: Hosted OpenAI Tools Feel Like Utensils in Python

## Status
Proposed.

## Summary
Phase 4A should give hosted OpenAI tools a Python surface that feels like chatsnack.

The main moves are:

- keep `utensils=[...]` as the primary Python authoring surface for tool availability
- extend `utensil` into a callable namespace object so the same exported symbol can serve as:
  - the plain `@utensil` decorator
  - the namespace-group factory for grouped decorators
  - the hosted-tool builder namespace for built-in OpenAI tools
- let grouped local utensils form searchable namespaces through `utensil.group(name, description)`
- let zero-config hosted tools read as bare capabilities such as `utensil.tool_search`
- let configured hosted tools be created as small, named Python values such as `docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)`
- let hosted utensil builders contribute both provider tool definitions and implied `params.responses.include` entries when needed

## Why this phase matters

Phase 4 made the YAML side of built-in tools much more chatsnack-shaped.

The Python side still needs the same treatment.

Today, this kind of sample is technically possible:

```python
from chatsnack import Chat

demo = Chat("Use tools only when useful.")
demo.reasoning.effort = "low"
demo.reasoning.summary = "auto"
demo.set_tools([
    {"type": "web_search", "filters": {"allowed_domains": ["docs.python.org"]}},
    {"type": "tool_search"},
])

demo.params.responses = demo.params.responses or {}
demo.params.responses["include"] = ["web_search_call.action.sources"]
```

We should treat that shape as the low-level escape hatch.

The common Python path should stay closer to the rest of chatsnack:

- `Chat` stays the center of gravity
- `utensils` stays the public word for model-usable capabilities
- the code should read like a list of capabilities or helpers
- direct mutation of provider-shaped dicts should stay rare

## Philosophy

This RFC follows the same ideas already described in the README and philosophy docs.

### Keep one mental model

Local Python functions and hosted OpenAI tools should feel like the same kind of thing from the caller's point of view.

If we already write:

```python
from chatsnack import Chat, utensil

@utensil
def get_weather(location: str, unit: str = "celsius"):
    """Get the current weather for a location."""
    return {"temperature": 72, "condition": "sunny", "unit": unit}

chat = Chat("You can use tools when helpful.", utensils=[get_weather])
```

then hosted OpenAI tools should live naturally beside that pattern.

### Keep `Chat(..., utensils=[...])` as the common path

We already have a strong public word: `utensils`.

That argues for keeping:

```python
Chat(..., utensils=[...])
```

as the primary Python surface for:

- local Python utensils
- grouped namespace utensils
- hosted OpenAI tools
- future hybrid tool surfaces

### Keep Python close to Python

The code should read like we are passing named capabilities into a chat.

That is why this shape feels good:

```python
docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)

chat = Chat(
    "Use tools only when useful.",
    utensils=[crm, utensil.tool_search, docs_search],
)
```

The `utensils` list reads as a list of usable capabilities:

- a grouped local namespace
- hosted tool search
- a configured web-search helper

### Keep provider details behind the authoring layer

Hosted tools often need extra request wiring such as:

- provider-shaped tool dicts
- `params.responses.include`
- transport-specific metadata

We should allow those details to exist in the implementation while keeping them out of the common examples.

## Design goals

- keep `utensils=[...]` as the main Python authoring surface
- preserve `@utensil` as the standard decorator for local Python tools
- make hosted tools feel native beside local utensils
- make grouped namespaces concise enough for normal notebook use
- keep descriptions available by default without forcing the keyword `description=`
- keep configured hosted tools small enough to bind to local variables before `Chat(...)`
- keep the raw `set_tools()` path available for advanced and provider-specific cases
- keep the Python surface aligned with the compact YAML surface from Phase 4

## Non-goals

- removing `set_tools()`
- replacing compact YAML as the saved authoring format
- introducing `tools=` as a second first-class public constructor argument for the same concept
- requiring every hosted tool to be inlined directly inside the `utensils` list

## Proposed public API

### `utensil` becomes a callable namespace object

`utensil` should keep decorator behavior and also expose hosted-tool builders.

That means these should all be valid:

```python
@utensil
def get_weather(location: str):
    ...
```

```python
crm = utensil.group("crm", "CRM tools for customer lookup and order management.")
```

```python
utensil.tool_search
```

```python
utensil.web_search(domains=["docs.python.org"], sources=True)
```

Implementation-wise, this suggests that `utensil` should become a callable object whose `__call__` preserves the current decorator behavior.

### Grouped namespaces

Grouped local utensils should use a concise positional form:

```python
from chatsnack import Chat, utensil

crm = utensil.group("crm", "CRM tools for customer lookup and order management.")

@crm
def get_customer(customer_id: str):
    """Look up one customer by ID."""
    ...

@crm
def list_open_orders(customer_id: str):
    """List open orders for a customer ID."""
    ...

chat = Chat(
    "Search CRM tools when useful.",
    utensils=[crm, utensil.tool_search],
)
```

Recommended behavior:

- the first positional argument is the namespace name
- the second positional argument is the namespace description
- the first line of each function docstring remains the child-tool description
- the returned group object is itself a decorator, so `@crm` is the common child-tool authoring pattern
- the group object is directly passable inside `utensils=[...]`
- the group compiles to the compact namespace syntax in YAML when the chat is saved

### Hosted utensils

Hosted OpenAI tools should be available from the same `utensil` namespace.

Recommended zero-config surface:

- `utensil.tool_search`
- `utensil.code_interpreter`
- `utensil.image_generation`

Recommended configured surface:

- `utensil.web_search(...)`
- `utensil.file_search(...)`
- `utensil.mcp(...)`

That leads to this kind of authored code:

```python
from chatsnack import Chat, utensil

docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)

chat = Chat(
    "Use tools only when useful.",
    utensils=[utensil.tool_search, docs_search],
)
chat.reasoning.summary = "auto"
```

This keeps the `utensils` list compact while still allowing richer hosted-tool configuration.

### Implied request extras

Hosted utensil builders should be able to contribute any implied request details that keep the common path clean.

Recommended examples:

- `utensil.web_search(..., sources=True)` adds the `web_search` tool and also ensures `web_search_call.action.sources` is included
- `utensil.file_search(..., results=True)` adds the `file_search` tool and also ensures `file_search_call.results` is included

This lets examples avoid direct mutation of `params.responses["include"]`.

### Mixed local and hosted authoring

The common mixed case should feel straightforward:

```python
from chatsnack import Chat, utensil

crm = utensil.group("crm", "CRM tools for customer lookup and order management.")

@crm
def get_customer(customer_id: str):
    """Look up one customer by ID."""
    ...

@crm
def list_open_orders(customer_id: str):
    """List open orders for a customer ID."""
    ...

docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)

chat = Chat(
    "Use tools only when useful.",
    utensils=[crm, utensil.tool_search, docs_search],
)
chat.reasoning.summary = "auto"
```

That is the shape we should be comfortable putting in the README and notebooks.

This example shows the whole intended layering:

- `utensil` is still the public tool symbol
- `crm` is a namespace decorator produced by `utensil.group(...)`
- `@crm` is the common grouped-tool authoring pattern
- `utensil.tool_search` is a zero-config hosted capability
- `docs_search` is a configured hosted capability created from the same `utensil` object
- `Chat(..., utensils=[...])` receives a list that reads like named capabilities

## Relationship to Phase 4 compact YAML

Phase 4 established the compact YAML direction:

- built-ins save as small authored entries
- namespaces save as compact namespace blocks
- tool-search presence implies deferred loading for searchable surfaces

Phase 4A should make the Python authoring layer compile into those same saved shapes.

For the mixed example above, the saved YAML should land in the same compact neighborhood:

```yaml
params:
  tools:
    - tool_search
    - web_search:
        filters:
          allowed_domains:
            - docs.python.org
    - crm: CRM tools for customer lookup and order management.
      tools:
        - get_customer: Look up one customer by ID.
          customer_id: str
        - list_open_orders: List open orders for a customer ID.
          customer_id: str
  responses:
    include:
      - web_search_call.action.sources
```

## Raw escape hatch

`set_tools()` should stay available.

That surface still matters for:

- provider-specific experimentation
- temporary compatibility gaps
- advanced tests
- debugging lower-level request wiring

The intended layering should be:

- README and notebook examples use `utensils=[...]`
- advanced code can use `set_tools()` when needed

## Implementation direction

Recommended pieces:

1. Replace the exported `utensil` decorator function with a callable namespace object.
2. Preserve `@utensil` behavior through `__call__`.
3. Add `utensil.group(name, description)` returning a decorator/group object that is also passable in `utensils=[...]`.
4. Add hosted utensil spec objects/builders under the same namespace.
5. Teach `Chat(..., utensils=[...])` to accept:
   - local utensil functions
   - grouped utensil namespaces
   - hosted utensil specs
6. Let hosted utensil specs contribute:
   - provider tool definitions
   - implied `params.responses.include` entries
   - any future runtime metadata needed for execution
7. Keep serialization aligned with the compact YAML format from Phase 4.

## Testing priorities

Phase 4A should add focused tests for:

- `@utensil` continuing to work unchanged
- `utensil.group(name, description)` collecting decorated child functions
- grouped utensils serializing to compact namespace YAML
- zero-config hosted utensils such as `utensil.tool_search` serializing cleanly
- configured hosted utensils such as `utensil.web_search(domains=[...], sources=True)` contributing both tool config and implied `responses.include`
- mixed `utensils=[crm, utensil.tool_search, docs_search]` flows round-tripping cleanly through save/load
- README-style examples avoiding raw `set_tools()` and direct mutation of `params.responses`

## Acceptance target

Phase 4A is successful when these feel true:

1. Hosted OpenAI tools feel like utensils in Python.
2. Local Python functions and hosted built-ins share one clean `utensils=[...]` surface.
3. Grouped searchable namespaces are concise enough for normal notebook use.
4. Hosted tool examples do not need raw provider dicts in the common path.
5. Examples do not need direct mutation of `params.responses["include"]` in the common path.
6. Saved YAML still lands in the compact Phase 4 format.
