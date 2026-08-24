---
name: chatsnack-fluency
description: Tips, tricks, and chatsnackian prompt composition patterns for YAML-first chat assets, text fillings, chat fillings, includes, generated ChatFiles, thin runtime loaders, and utensils. Use when building or reviewing chatsnack projects, graphical prompt builders, dynamic prompt systems, agentic coding prompts, game-master style agents, benchmark prompt morphs, context aggregation flows, reusable prompt fragments, or consumer code that is tempted to render prompts through private chatsnack hooks such as _build_final_prompt.
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
- Let a continued chat keep generated outputs. Its `.images` are the image results; its `.files` contain every returned file, including those images.
- Pass a returned `ChatFile` through `files=` or `images=` when another chat needs it. Avoid unpacking provider response dictionaries or carrying base64 through app code.
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
| generated image | call `.chat()`, then use the continued chat's `.images` |
| generated or cited file | call `.chat()`, then use the continued chat's `.files` |
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

Keep generated outputs on the chat:

```python
from chatsnack import Chat, utensil

artist = Chat(
    "Use image generation for every drawing request.",
    utensils=[utensil.image_generation(model="gpt-image-2")],
)
drawing = artist.chat("Draw a coral lantern icon.")
image = drawing.images[0]

review = Chat("Review the attached icon.").chat(images=[image])
image.save_as("lantern.png")
```

Use `.chat()` when files or images are part of the result. `.ask()` remains the text-only shortcut. Captured assets appear in saved YAML as provider-neutral `asset` references; keep the chatsnack data directory with the saved chat when moving it between machines.

For an unusually long local-utensil chain, a positive integer `auto_feed=N`
allows up to `N` automatic execution/result-feed cycles. Omitted, `None`, or
`True` keeps the legacy five-cycle behavior. `False` or `0` executes the first
pending batch without feeding its results back for another model response.
Parallel calls in one assistant response count as one cycle. Keep this numeric
knob in advanced examples; the common path should continue to omit it.

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

Smell: app code digs through `last`, provider response objects, annotations, or base64 to recover generated files.

Chatsnackian rewrite: continue with `.chat()`, take `ChatFile` values from `.images` or `.files`, and pass those values directly into the next chat.
