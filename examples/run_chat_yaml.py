"""Load example YAML chats and show how chatsnack resolves them.

This script demonstrates loading YAML chat definitions and inspecting their
runtime resolution, tool setup, and reasoning config — all exercised through
chatsnack's default runtime path (Responses WebSocket).
"""
from pathlib import Path
from ruamel.yaml import YAML

from chatsnack import Chat

yaml = YAML()
root = Path(__file__).parent / "chats"

for path in sorted(root.glob("*.yaml")):
    payload = yaml.load(path.read_text())
    chat = Chat(name=f"demo_{path.stem}")
    chat.dict = payload

    params = chat.params
    model = params.model if params else "—"
    tools = params.get_tools() if params else []
    tool_types = [t.get("type", "?") for t in tools if isinstance(t, dict)]
    reasoning = (params.responses or {}).get("reasoning") if params else None

    print(f"  {path.name}")
    print(f"    model     : {model}")
    print(f"    runtime   : {type(chat.runtime).__name__}")
    print(f"    tools     : {', '.join(tool_types) or '—'}")
    if reasoning:
        print(f"    reasoning : {reasoning}")
    print()

# Quick inline demo: create a chat with compact tools + reasoning
demo = Chat("Respond with one terse sentence.")
demo.reasoning.effort = "low"
demo.reasoning.summary = "auto"
print("  inline demo")
print(f"    runtime   : {type(demo.runtime).__name__}")
print(f"    reasoning : {demo.params.responses['reasoning']}")
print()
