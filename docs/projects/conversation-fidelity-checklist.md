# Conversation fidelity

Implementation follows [the conversation history RFC](../rfcs/conversation-fidelity-rfc.md).

- [x] Record SEPARATE / KEEP / PROJECT and the default persistence contract.
- [x] Goal: saved tool conversation replays its ordered items after load.
- [x] Reversible typed entries, alias-aware provider conversion, unknown items.
- [x] Default YAML/JSON preservation; old message shapes remain supported.
- [x] Ordered initial/follow-up responses; existing execution and asset behavior.
- [x] Copy/reset/include isolation and literal submitted history.
- [x] Verified continuation prefixes, stateless replay, safe WebSocket fallback.
- [x] Chat Completions projection with warnings and unchanged stored messages.
- [x] SDK floor/newer SDK regressions, notebook, strict documentation build.
- [x] Independent implementation and test review; remedy material findings.
- [x] Omit known metadata defaults; retain scalar assistant authoring and required native tool statuses.

Current result: ordinary saved Chats retain ordered reasoning, replies, calls,
results, and unfamiliar provider items. Users can reload or branch a conversation,
edit earlier text, and continue from the preserved transcript. Generated images
replay from their existing asset references.

Review remedies cover effective profile defaults, external conversation ancestry,
credential changes, asset capture before fingerprinting, CC tool correlation,
and usage accounting when local preparation fails. A same-binding edit test proves
that prefix changes alone invalidate cached response IDs.

Validation: SDK 3.5.0 focused runtime/Goal/asset/usage/utensil checks passed
(203 tests); YAML/import/attachment checks passed (96 tests). Every code cell in
`PortableConversationHistory.ipynb` ran offline, and `mkdocs build --strict` passed.
The full SDK 3.8.0 suite passed: **824 passed, 122 skipped**. Three existing
async-client cleanup warnings remain in the test doubles. Independent focused
review also passed 17 replay/usage tests. Live probes remain opt-in.

Live validation on 2026-09-10, OpenAI SDK 3.5.0: **6 passed** in
`tests/test_live_conversation_history.py`. GPT-6 Astra and GPT-5.4 each passed
stateless HTTP, stored HTTP, and WebSocket cases. Every case executes a real
stock utensil once, uses warm continuation, saves and loads ordinary YAML, and
recovers a random proof token from the original tool result. Cold replay must
match the complete original request and response sequence, allowing only the
documented omission of known defaults and retaining the exact tool-output string.
The HTTP response oracle uses the SDK's own wire serializer;
WebSocket equality is checked at the adapter boundary alongside offline raw-event tests.

The original medium-effort READY-only prompt emitted no GPT-6 reasoning items.
The revised contract uses **high** effort on both models and asks them to solve a
constrained selection problem supplied by the stock utensil. An exhaustive local
oracle checks the optimum and tie-break. Each case requires positive reported
reasoning-token usage and nonempty encrypted reasoning in the problem-solving
response itself; the complete provider items must survive YAML and cold replay.
JUnit properties record effort, reasoning-item count, total initial reasoning
tokens, and problem-solving reasoning tokens. Missing reasoning fails the test.

The final eight-offer, high-effort matrix passed **all 6 cases in 103.23 seconds**
on 2026-09-10. Problem-solving reasoning tokens (stateless HTTP / stored HTTP /
WebSocket) were **248 / 301 / 299** for GPT-6 Astra and **1169 / 1692 / 822** for
GPT-5.4. Every case preserved encrypted reasoning through exact cold replay.
The default offline invocation still skipped all six cases.

Compact-YAML follow-up: **6 live cases passed in 107.96 seconds**. Known empty
summary/content/annotation/logprob fields and completed-status defaults no longer
appear in compact message entries. The real GPT-6 run also returned a nonempty
public summary, which survived replay unchanged along with encrypted reasoning.
Native Apply Patch success stays explicit because its protocol requires it.
New Goal checks cover scalar dialogue, older noisy messages, no mutation on save,
nondefault metadata, unknown empty payloads, and native tool result replay.
The independent review confirmed the status/role-scope and live-oracle remedies.
Final compaction validation: SDK 3.8.0 **828 passed, 129 skipped**; four existing
async-client cleanup warnings remain in test doubles. SDK 3.5.0 focused checks
passed (154 runtime/YAML tests plus 29 final provider/Goal/Apply Patch tests).
All five notebook code cells ran offline, and the strict documentation build passed.

Pre-push critical review (GPT-6 Astra, high reasoning) found and resolved:

- Unfinished function calls could execute after an incomplete WebSocket response.
  The whole batch now stays pending while its items remain saved.
- Latest-result accessors could expose older text/images after opaque or tool-only
  output. Compact and opaque assistant boundaries now agree, and final multipart
  assistants own their asset views.
- CC projection could interleave commentary between a call and its result.
  Matching results now follow their requesting assistant in the projected list;
  original messages, content, metadata, and persisted order remain intact.

The review also caught and fixed explicit `tool_calls: null` compatibility.
The remote base matched current `origin/master`. Final verification: SDK 3.8.0
**845 passed, 129 skipped** (six existing async-client cleanup warnings), plus
**30 final focused replay checks** including the last unknown-phase boundary
regression. All **6 live history assertions passed again in 108.14 seconds**,
but the process lingered after pytest's summary and required interruption.
The live fixture now closes chats with `Chat.close_a()`; a three-transport rerun
passed in 54.34 seconds but still lingered at shutdown. The cause remains
unresolved, so these live runs do not establish a clean process exit.
The notebook and strict documentation build passed. Contiguous unphased output
without input boundaries remains one group, as documented in the RFC.

Run this feature's live contracts explicitly in PowerShell:

```powershell
$env:CHATSNACK_RUN_LIVE_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_live_conversation_history.py -q
```

`CHATSNACK_LIVE_MODEL` and `CHATSNACK_LIVE_REASONING_MODEL` override the two
models. Without the live opt-in, all six cases skip; normal test runs remain offline.
