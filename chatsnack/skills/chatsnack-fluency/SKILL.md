---
name: chatsnack-fluency
description: Tips, tricks, and chatsnackian prompt composition patterns for YAML-first chat assets, text fillings, chat fillings, includes, thin runtime loaders, and utensils. Use when building or reviewing chatsnack projects, graphical prompt builders, dynamic prompt systems, agentic coding prompts, game-master style agents, benchmark prompt morphs, context aggregation flows, reusable prompt fragments, or consumer code that is tempted to render prompts through private chatsnack hooks such as _build_final_prompt.
---

# Chatsnack Fluency

This is a fluency pack, not a workflow. Use it to think like a chatsnackian: prompts are authored assets, placeholders are sockets, fillings are composition, and runtime code is the small adapter that brings data and tools to the chat.

Read `references/pattern-atlas.md` for larger copyable examples.

## Think Like A Chatsnackian

- Keep the `Chat` as the unit of thought. A prompt is not just a string; it is conversation state with identity.
- Prefer YAML-first prompt assets for stable behavior. If another agent should understand or edit it, it probably belongs in YAML.
- Treat `{name}`, `{text.Name}`, and `{chat.Name}` as live connections. Do not render them early just to glue strings together.
- Let `Text` hold reusable language: policies, voices, rubrics, output contracts, style guides, safety notes, table rules.
- Let saved `Chat` assets hold reusable behavior: a planner, critic, scene seeder, summarizer, classifier, benchmark base, handoff reader.
- Let `include` bring in message-shaped context: prior transcripts, house rules, examples, handoffs, side-chat selections.
- Let `utensils=[...]` bring capabilities. The model gets named tools; Python stays Python.
- Keep runtime loaders thin. Load the asset, pass fillings, attach utensils, set runtime knobs, call `ask()` or `chat()`.

## Primitive Map

When a prompt feels dynamic, name the changing part:

| Dynamic need | Chatsnackian move |
| --- | --- |
| user-provided value | ordinary filling like `{task}` |
| reusable prose | `{text.OutputContract}` |
| generated prep content | `{chat.SceneSeed}` |
| prior conversation or handoff | `include: PriorThread` |
| selectable side context | save a narrow chat, then `include` it |
| callable capability | `utensils=[save_note, search_docs]` |
| external fragment catalog | custom filling namespace, after `Text` and `Chat` stop being enough |
| persistent behavior | named YAML `Chat` asset |

For canvas or whiteboard UIs, these map naturally to nodes: chat node, text node, transcript node, file context node, side-chat node, utensil node, and runtime filling node. The final prompt should still be a composed chat asset, not a pre-rendered blob.

## YAML-First Tricks

Leave holes until the last responsible moment:

```yaml
messages:
  - system: |
      {text.System}
  - user: |
      Task:
      {task}

      Output:
      {text.CodingOutputContract}
```

Splice message-shaped context with `include` instead of copying rendered text:

```yaml
messages:
  - include: CodingHouseRules
  - include: SelectedPriorThread
  - user: |
      New task: {task}
```

Use a chat filling when part of the prompt should be generated just in time:

```yaml
messages:
  - user: |
      Research seed:
      {chat.ResearchSeed}

      Now draft the answer for {audience}.
```

Keep app code boring:

```python
from chatsnack import Chat

chat = Chat(name="CodingTask")
chat.load()
thread = chat.chat(task="Preserve parser comments.")
```

Attach capabilities at the edge:

```python
from chatsnack import Chat, utensil

@utensil
def save_note(title: str, body: str):
    """Save one note for later review."""
    return {"title": title, "saved": True}

chat = Chat("Use save_note when a note should persist.", utensils=[save_note])
```

## Good Patterns

Agentic coding prompt builder:

```yaml
messages:
  - include: CodingHouseRules
  - user: |
      Task:
      {task}

      Relevant files:
      {file_context}

      Output:
      {text.CodingOutputContract}
```

Custom agentic DM:

```yaml
messages:
  - system: |
      {text.DMVoice}
      Campaign tone: {campaign_tone}
  - user: |
      Scene seed:
      {chat.SceneSeed}

      Continue play from the current party state.
```

Benchmark morph without early render:

```yaml
messages:
  - include: BenchBase
  - user: |
      Additional framing:
      {morph_frame}
```

## Smells And Rewrites

Smell: consumer code calls `_build_final_prompt`, splits messages, then rebuilds a chat.

Chatsnackian rewrite: keep the base chat raw and compose around it:

```yaml
messages:
  - include: BasePrompt
  - user: |
      Extra framing:
      {frame}
```

Smell: literal brace escaping becomes a central design problem.

Chatsnackian rewrite: the prompt was rendered too early. Preserve `{text.*}`, `{chat.*}`, and ordinary fillings until final execution.

Smell: app code owns a giant prompt string with many conditional branches.

Chatsnackian rewrite: move stable branches into named chats and texts, then choose which assets to include or fill at runtime.
