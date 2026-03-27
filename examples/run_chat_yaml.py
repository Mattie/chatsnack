from pathlib import Path
from ruamel.yaml import YAML
from chatsnack import Chat

yaml = YAML()
root = Path(__file__).parent / "chats"

for path in sorted(root.glob("*.yaml")):
    payload = yaml.load(path.read_text())
    chat = Chat(name=f"demo_{path.stem}")
    chat.dict = payload
    print(f"Loaded {path.name}: runtime={chat.params.runtime if chat.params else None}")

runtime_demo = Chat("Respond with one sentence.")
runtime_demo.reasoning.effort = "low"
runtime_demo.reasoning.summary = "auto"
print("Reasoning config:", runtime_demo.params.responses["reasoning"])
