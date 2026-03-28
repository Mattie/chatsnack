"""Load example YAML chats and show the utensils-first Python surface.

This script demonstrates:
1. Loading YAML chat definitions and inspecting tools/runtime/reasoning.
2. Building a mixed-utensil chat entirely through ``utensils=[...]``
   without raw ``set_tools()`` or ``params.responses`` mutation.
"""
from pathlib import Path
from ruamel.yaml import YAML

from chatsnack import Chat, utensil

yaml = YAML()
root = Path(__file__).parent / "chats"

print("=== YAML chat assets ===")
for path in sorted(root.glob("*.yaml")):
    payload = yaml.load(path.read_text())
    chat = Chat(name=f"demo_{path.stem}")
    chat.dict = payload

    params = chat.params
    model = params.model if params else "—"
    tools = params.get_tools() if params else []
    tool_types = [t.get("type", "untyped") for t in tools if isinstance(t, dict)]
    reasoning = (params.responses or {}).get("reasoning") if params else None

    print(f"  {path.name}")
    print(f"    model     : {model}")
    print(f"    runtime   : {type(chat.runtime).__name__}")
    print(f"    tools     : {', '.join(tool_types) or '—'}")
    if reasoning:
        print(f"    reasoning : {reasoning}")
    print()

# === Phase 4A: utensils-first Python surface ===
print("=== Utensils-first Python demo ===")

crm = utensil.group("crm", "CRM tools for customer lookup and order management.")

@crm
def get_customer(customer_id: str):
    """Look up one customer by ID."""
    return {"id": customer_id, "name": "Acme Corp"}

@crm
def list_open_orders(customer_id: str):
    """List open orders for a customer ID."""
    return []

docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)

chat = Chat(
    "Use tools only when useful.",
    utensils=[crm, utensil.tool_search, docs_search],
)
chat.reasoning.summary = "auto"

tools = chat.params.get_tools()
tool_types = [t.get("type", "untyped") for t in tools if isinstance(t, dict)]
includes = (chat.params.responses or {}).get("include", [])

print(f"  tools     : {', '.join(tool_types)}")
print(f"  includes  : {includes}")
print(f"  reasoning : {chat.params.responses.get('reasoning')}")
print()
