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

## Why this surface matters

- local Python tools stay close to Python
- grouped tools read like named capabilities
- hosted tools stay off raw provider dicts in the common path
- the `Chat(...)` constructor still reads like authored code
