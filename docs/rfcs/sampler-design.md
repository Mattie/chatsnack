# Sampler 0.9.0 implementation design

Status: accepted implementation contract, 2026-09-17.

## Authoring and results

`Sampler`, `Question`, and `sample.answer` are the common surface. All `ask()` and
`ask_a()` forms return Sample. `.answer` and `.question` return the same first
objects as `.answers[0]` and `.questions[0]`, even in a batch. Empty batches fail.
Use named lookups in multi-question examples. Preserve the concept spec's question
forms, score/confidence semantics, and response ordering contract.

Ordinary keyword fillings follow Chat conventions. No new collision mechanism or
second execution verb. Call-time data and injected values stay literal. Authored
fillings remain live until evaluation; YAML inspection never evaluates them.

## Persistence

Manual snapclass definitions use `questions/{name}.yml` and `samplers/{name}.yml`
under the existing root. Construction does not load or write by name. Strings,
embedded Questions, and exact Question references retain their authored forms.
Custom serializers preserve JSON shapes without Chat-specific normalization.

Samples own resolved copies. `from_sample()` embeds these and pins the reported
model, quietly persisting `expand: false` for literal replay. `Sampler(data=sample)`
instead evaluates a structured projection including the prior answers.
Saving that follow-up automatically quotes literal braces in its data projection;
the new questions retain their ordinary filling behavior after reload.

## Execution and composition

One async preparation/evaluation pipeline backs sync and async methods. Optional
TypeSafe SDK import, retry handling, and per-call client cleanup live in a small
provider adapter. No Chat adapter or model capability-table changes are required.
Compilation is advanced inspection and may execute dependency fillings.

Typed whole-value resolution complements the existing string formatter. Named
result fillings expose choice/score/confidence and require explicit answer names.
The public resolver adds independent `allow_sampler=False`; its existing variable
mapping and Chat authority remain unchanged.

An expansion-local table shares tasks/results for equivalent saved Sampler
references and bindings. It lasts only for the outer expansion. Minimal dependency
checks prevent self/cross-task waits; owned tasks are cleaned up on exit. This is
not a general scheduler. Fixed evaluation budgets apply only to the public resolver.

## Delivery and acceptance

Branch `feat/sampler-0-9` starts from `origin/master` in an isolated worktree,
independent of PR #83. Track evidence in the Sampler project checklist. Tests use
Three-Horizon TDD: notebook-sized Goals, focused Steer contracts, and narrow numeric
checks. The SDK boundary uses real HTTP encoding/decoding over a fake transport;
paid testing is explicitly opt-in.

The notebook and saved YAML are the acceptance standard throughout. Put transport
settings, compilation, answer subclasses, and resolver authority in advanced docs.

Deferred: conditionals, post-evaluation text, saved Sample assets, streaming, other
providers, cross-call caches, workflow infrastructure, and a shared keyword-collision
improvement for Chat and Sampler. Version preparation does not publish a release.
