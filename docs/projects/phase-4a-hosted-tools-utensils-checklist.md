# Phase 4A: Hosted OpenAI Tools Feel Like Utensils in Python — Checklist

> Tracks implementation of [Phase 4A RFC](../rfcs/phase-4a-hosted-tools-utensils-rfc.md).

## Core infrastructure

- [x] `_UtensilNamespace` callable class replaces the `utensil` function  
  _Done in `chatsnack/utensil.py`; `utensil` is now a callable namespace singleton._
- [x] `@utensil` decorator behavior preserved via `__call__`  
  _Done and covered by backward-compat tests in `tests/test_hosted_utensils.py`._
- [x] `utensil.group(name, description)` returns decorator/group passable in `utensils=[]`  
  _Done via `UtensilGroup` and `_UtensilNamespace.group()`._
- [x] `UtensilGroup.__call__` enables `@crm` decorator pattern for child tools  
  _Done; grouped child tools can be authored with `@crm` as intended._

## Hosted utensil specs

- [x] `HostedUtensil` base class with `to_tool_dict()` and `get_include_entries()`  
  _Done with provider-shaped specs and implied include collection._
- [x] Zero-config hosted utensils: `utensil.tool_search`, `utensil.code_interpreter`, `utensil.image_generation`  
  _Done as namespace properties._
- [x] `utensil.web_search(...)` builder with `domains=`, `sources=`, `user_location=`, `external_web_access=`  
  _Done; builder emits hosted web-search config and optional include entries._
- [x] `utensil.file_search(...)` builder with `vector_store_ids=`, `max_num_results=`, `results=`  
  _Done; builder emits hosted file-search config and optional include entries._
- [x] `utensil.mcp(...)` builder with `server_label=`, `connector_id=`, `allowed_tools=`, `require_approval=`  
  _Done; builder emits hosted MCP config._

## Chat integration

- [x] `extract_utensil_functions()` / `get_openai_tools()` handles `HostedUtensil` specs  
  _Done; mixed local/group/hosted utensil lists compile through one path._
- [x] `Chat.__init__` collects implied `include` entries from hosted utensils  
  _Done via `collect_include_entries(utensils)`._
- [x] `Chat.__init__` merges include entries into `params.responses["include"]`  
  _Done with de-duplication before merge._

## YAML round-trip

- [x] Hosted utensils serialize to compact Phase 4 YAML format  
  _Done through the shared compact tool authoring path._
- [x] Grouped namespaces serialize to compact namespace blocks  
  _Done; grouped Python utensils save as compact namespace YAML._
- [x] Implied include entries persist through save/load cycles  
  _Done; hosted-tool includes survive YAML round-trip._

## Examples and docs

- [x] Update notebook cell to use `utensils=[...]` with hosted tool builders  
  _Done in the notebook examples and follow-up default-runtime cleanups._
- [x] Update README example to show mixed local + hosted utensils  
  _Done in the Utensils section._
- [x] Update example YAML files to match new defaults  
  _Done; example YAML assets no longer pin `runtime: responses` unless demonstrating non-default behavior._

## Tests

- [x] `@utensil` decorator still works unchanged (backward compat)  
  _Covered in `tests/test_hosted_utensils.py`._
- [x] `utensil.group()` collects decorated child functions  
  _Covered in `tests/test_hosted_utensils.py`._
- [x] Grouped utensils serialize to compact namespace YAML  
  _Covered in the hosted utensil YAML round-trip tests._
- [x] Zero-config hosted utensils serialize cleanly  
  _Covered for `tool_search`, `code_interpreter`, and `image_generation`._
- [x] Configured hosted utensils contribute tool config + implied `include`  
  _Covered for hosted web/file search builders._
- [x] Mixed `utensils=[crm, utensil.tool_search, docs_search]` round-trips  
  _Covered in the mixed-list round-trip tests._
- [x] Goal test: README-style example works end-to-end without `set_tools()` or `params.responses` mutation  
  _Covered by the README-style goal test in `tests/test_hosted_utensils.py`._
