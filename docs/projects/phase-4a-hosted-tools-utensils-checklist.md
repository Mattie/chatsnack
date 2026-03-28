# Phase 4A: Hosted OpenAI Tools Feel Like Utensils in Python — Checklist

> Tracks implementation of [Phase 4A RFC](../rfcs/phase-4a-hosted-tools-utensils-rfc.md).

## Core infrastructure

- [ ] `_UtensilNamespace` callable class replaces the `utensil` function
- [ ] `@utensil` decorator behavior preserved via `__call__`
- [ ] `utensil.group(name, description)` returns decorator/group passable in `utensils=[]`
- [ ] `UtensilGroup.__call__` enables `@crm` decorator pattern for child tools

## Hosted utensil specs

- [ ] `HostedUtensil` base class with `to_tool_dict()` and `get_include_entries()`
- [ ] Zero-config hosted utensils: `utensil.tool_search`, `utensil.code_interpreter`, `utensil.image_generation`
- [ ] `utensil.web_search(...)` builder with `domains=`, `sources=`, `user_location=`, `external_web_access=`
- [ ] `utensil.file_search(...)` builder with `vector_store_ids=`, `max_num_results=`, `results=`
- [ ] `utensil.mcp(...)` builder with `server_label=`, `connector_id=`, `allowed_tools=`, `require_approval=`

## Chat integration

- [ ] `extract_utensil_functions()` / `get_openai_tools()` handles `HostedUtensil` specs
- [ ] `Chat.__init__` collects implied `include` entries from hosted utensils
- [ ] `Chat.__init__` merges include entries into `params.responses["include"]`

## YAML round-trip

- [ ] Hosted utensils serialize to compact Phase 4 YAML format
- [ ] Grouped namespaces serialize to compact namespace blocks
- [ ] Implied include entries persist through save/load cycles

## Examples and docs

- [ ] Update notebook cell to use `utensils=[...]` with hosted tool builders
- [ ] Update README example to show mixed local + hosted utensils
- [ ] Update example YAML files to match new defaults

## Tests

- [ ] `@utensil` decorator still works unchanged (backward compat)
- [ ] `utensil.group()` collects decorated child functions
- [ ] Grouped utensils serialize to compact namespace YAML
- [ ] Zero-config hosted utensils serialize cleanly
- [ ] Configured hosted utensils contribute tool config + implied `include`
- [ ] Mixed `utensils=[crm, utensil.tool_search, docs_search]` round-trips
- [ ] Goal test: README-style example works end-to-end without `set_tools()` or `params.responses` mutation
