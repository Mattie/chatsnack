# Chat

`Chat` is the primary unit of work in chatsnack.

::: chatsnack.Chat

## Runtime usage

Every completed `chat()` or `chat_a()` call leaves an in-memory usage snapshot
on both the source chat and the returned chat:

```python
completed = chat.chat("Make the snack plan.")
usage = completed.last_call_usage

print(usage.response_count)
print(usage.total)

for response in usage.responses:
    print(response.sequence, response.model, response.total_tokens)
```

`usage.responses` includes every provider response created during that call,
including automatic utensil follow-ups. Each `response.provider_usage` keeps a
detached copy of that provider's usage mapping for fields outside the normalized
counts.

Providers may omit usage. Those calls still complete, the corresponding
response remains in order, and `usage.is_complete` is `False`. Reported zeroes
remain `0`; missing counts remain `None`. Totals from an incomplete call are
known lower bounds.

The snapshot is call-scoped runtime data. It is cleared by copy, reset, and
load operations and does not appear in saved YAML.

::: chatsnack.UsageCounts

::: chatsnack.ResponseUsage

::: chatsnack.CallUsage
