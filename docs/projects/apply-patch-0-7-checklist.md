# Apply Patch handled by the app

## Goal

A `Chat` can offer OpenAI's Apply Patch tool while the app decides which files
may change and makes the approved changes.

## Goal tests

- [x] G1: a completed HTTP Responses Apply Patch call executes once and continues with one canonical output
- [x] G2: WebSocket continuation sends only the Apply Patch output after the provider call
- [x] G3: saved YAML stays scalar-first and a loaded chat must receive the Python function again

## Steer tests

- [x] `utensil.apply_patch(execute=...)` emits `{"type": "apply_patch"}`
- [x] `allowed_callers` preserves the current beta declaration when configured
- [x] the Python function stays attached through `copy()`, `chat()`, and `reset()` without entering YAML
- [x] normalization preserves item ID, call ID, operation, status, caller/agent fields, and provider metadata
- [x] rejection by the Python function, invalid results, and exceptions become one failed output
- [x] in-progress calls fail clearly and are never executed
- [x] multiple calls execute sequentially in provider order
- [x] Chat Completions, `ask()`, and streaming fail with direct guidance
- [x] existing `tool_search_handler` behavior remains unchanged

## Live contracts

- [x] HTTP Responses executes one real Apply Patch call in a temporary workspace and continues with its output
- [x] WebSocket Responses does the same through provider-owned session state
- [x] live tests stay opt-in behind `OPENAI_API_KEY` and `CHATSNACK_RUN_LIVE_TESTS=1`

## Documentation

- [x] Keep the README change to a short link into the Utensils guide
- [x] Add the Python, YAML, reload, and runtime examples to the Utensils guide
- [x] Add a compact Getting Started notebook example
- [x] Explain that the app's Python code checks paths and changes files
- [x] Link the Utensils guide to a copyable local workspace example

## Local workspace example

- [x] `LocalWorkspace` creates, updates, and deletes UTF-8 text files below one existing root
- [x] the self-contained parser handles current V4A anchors, hunks, EOF markers, and newline styles
- [x] absolute paths, traversal, symlinks, directories, malformed operations, and patch conflicts fail without unsafe writes
- [x] focused tests cover the parser, filesystem outcomes, and model-safe failures
- [x] live HTTP and WebSocket contracts apply the provider's real V4A diff

## Deferred

- declaration options introduced after the current `allowed_callers` beta surface
- a supported package-level patch parser or workspace API
- application approvals, evidence, backups, transactions, and recovery
- manual execution of pending Apply Patch calls when `auto_execute=False`
