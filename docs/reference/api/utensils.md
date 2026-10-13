# Utensils

The public tool surface revolves around the module-level `utensil` helper plus the reusable grouped and hosted tool types behind it.

## `utensil`

::: chatsnack.utensil.utensil

## `UtensilGroup`

::: chatsnack.utensil.UtensilGroup

## `HostedUtensil`

::: chatsnack.utensil.HostedUtensil

## `ApplyPatchCall`

`ApplyPatchCall` is the value passed to the function you give
`utensil.apply_patch(execute=...)`.

::: chatsnack.ApplyPatchCall

## Manual local execution

Automatic tool execution uses `chat()` or `chat_a()` with `utensils=[...]`.
For applications handling individual calls, `Chat.execute_tool_call_a(call)`
and `handle_tool_call_a(call, local_registry=...)` accept synchronous results
and awaitables. The synchronous manual methods accept synchronous results only.

::: chatsnack.utensil.handle_tool_call

::: chatsnack.utensil.handle_tool_call_a
