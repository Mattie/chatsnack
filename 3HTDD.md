---
name: three-horizon-tdd
description: Guide Three-Horizon TDD (3HTDD), an outcome-layered outside-in TDD style that uses Goal, Steer, and Unit test types. Use when Codex needs to plan or implement a feature, bug fix, refactor, or test suite in Python or JavaScript projects with Goal/Steer/Unit workflows, short test lists, or repo layouts that keep TDD focused on meaningful progress.
---

# Three-Horizon TDD

Use this skill to keep TDD pointed at meaningful progress instead of shrinking every red-green loop down to micro-goals.

Treat 3HTDD as our practical outside-in TDD model with the naming that the reference conversation settled on:

- `Goal` tests prove the real feature or bug outcome landed.
- `Steer` tests prove the next meaningful rule, subsystem behavior, or use-case step.
- `Unit` tests prove tight local logic when the current step needs a smaller loop.

The older `destination / steering / support` language maps directly to `goal / steer / unit`, and this skill should now prefer the newer naming.

## Quick Start

1. Write a short test list before writing concrete tests.
2. Pick one Goal scenario for the change.
3. Decide whether to keep that Goal test as an active red test or as a named pending target.
4. Drive toward it with one Steer test at a time.
5. Drop to one Unit test at a time only when the current Steer step needs tighter feedback.
6. Add invariants, properties, or contract checks when examples alone leave too much behavior space open.
7. Prune disposable tests after green. Keep Goal, property, and contract tests as the lasting spec.

## Working Model

Use the three horizons like this:

- `Goal`: macro proof. Ask, "Did we fix the real bug or land the real feature?"
- `Steer`: near-step proof. Ask, "What next meaningful truth moves us toward green?"
- `Unit`: micro proof. Ask, "What local mechanic needs a tighter loop right now?"

Most of the active implementation work should happen in Steer tests. Unit tests are allowed and useful, though they should enter on demand instead of leading the whole story.

A short memory aid from the reference:

- Goal keeps us honest.
- Steer keeps us moving.
- Unit keeps us precise.

## Workflow

### 1. Build the test list

Capture a lean list before touching code:

- story or bug statement
- Goal scenario candidates
- likely Steer rules
- open questions
- deferred edge cases
- property, invariant, or contract ideas

Keep the list as notes, TODOs, or pending tests. Avoid turning the whole list into concrete red tests immediately.

### 2. Choose the Goal

Write or name one Goal scenario that proves the requested behavior in the language of users, callers, or visible system effects.

Prefer the lowest boundary that still proves value:

- service or API boundary for backend work
- command or job boundary for CLI and batch work
- UI workflow boundary for interface work
- file import or export boundary for tools and media workflows

Keep Goal tests few, readable, and tied to features or regressions.

### 3. Choose the active-red style

Use one of these house styles:

- `parked Goal red`: keep the Goal test concretely red while Steer work happens underneath it
- `pending Goal`: keep the Goal as a named pending test, checklist item, or skipped scenario while driving with Steer tests first

Prefer `pending Goal` when the suite should have only one active red test at a time. Prefer `parked Goal red` when outside-in flow is clear and the broader red test is still cheap to keep visible.

### 4. Drive with Steer tests

Ask, "What is the next rule, state change, filter, contract, or use-case step that would move the Goal toward green?"

Write one Steer test for that slice. Make it green. Re-run the Goal. Repeat.

Good Steer targets:

- domain rules
- state transitions
- use-case orchestration
- persistence or query behavior
- UI component behavior with visible consequences
- transformations where mistakes would hide inside a larger workflow

Steer tests should sound like meaningful rules or behavior. They should stay above helper trivia.

### 5. Drop to Unit tests only when needed

Unit tests are the classic unit-test zone. Use them when:

- math or normalization logic is tricky
- parsing or mapping logic has many edge conditions
- a Steer test is hard to debug without a tighter loop
- a regression came from a very local rule

Treat Unit tests as disposable scaffolding unless they carry unique long-term value.

### 6. Link Steer tests lightly to their Goal

New Steer tests should usually be traceable to a Goal test or active bug or feature.

Use a lightweight link:

- folder grouping under a Goal ID
- a `goal_id` marker
- shared naming
- a short top-of-file note

This keeps `steer/` from turning into a random middle layer. Over time, a Steer test may graduate into a more general domain rule test if it proves broadly useful.

### 7. Expand authority carefully

Treat these as the long-term spec:

- Goal tests
- property or invariant tests
- contract tests at integration boundaries

Treat these as temporary or lower-authority tests:

- most Unit tests
- some Steer tests that only existed to unlock the path

If the code changes shape and Goal, property, and contract tests still pass, rewrite or delete lower-level tests freely.

### 8. Add broader guards where examples overfit

Reach for broader guards when one or two examples are too narrow:

- `properties` for input spaces, transformations, and ordering rules
- `invariants` for truths that should stay true before and after operations
- `contracts` for APIs, queues, file formats, and service boundaries
- `approvals/snapshots` for large structured outputs when hand-written assertions add noise

Default stance:

- use example tests first
- add properties or invariants for broad or failure-sensitive rules
- add contracts at external seams

### 9. Prune after green

After the Goal is green:

- delete redundant Unit tests
- merge overlapping Steer tests
- keep the clearest lasting examples
- run mutation testing or similar quality checks in critical areas if the project already uses them

## House Rules

- Start from a Goal scenario or a named Goal target for every change.
- Keep the current active red test count low. One is the default.
- Spend most test-writing effort in Steer tests.
- Prefer state and outcome assertions over interaction assertions inside the domain.
- Use mocks mainly at awkward boundaries such as email, queues, caches, browsers, and third-party services.
- Let repo organization explain test purpose.
- Separate `features` and `bugs` where that helps mirror how work enters the codebase.
- Give each Goal test a short stable ID when the repo wants lightweight traceability.

## Repo Guidance

Prefer organizing tests by intent first, then by subsystem. Start with `references/repo-layout.md` when the project needs folder or naming guidance.

For stack-specific guidance:

- use `references/python.md` for `pytest`, `Hypothesis`, markers, and Python repo patterns
- use `references/javascript.md` for `Vitest` or `Jest`, `fast-check`, Playwright, and JS repo patterns

## Prompt Pattern

When using this skill on a real task, state the current horizon explicitly:

1. Summarize the story or bug in one sentence.
2. List candidate Goal, Steer, and Unit tests.
3. Choose the current active test and explain why it is the right altitude.
4. Implement only the work needed to move that test toward green.
5. Re-evaluate the next altitude after each green step.
