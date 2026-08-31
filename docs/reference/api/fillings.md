# Fillings

The direct filling resolver is an advanced public API for callers that already
know the finite set of saved text and chat references they need. The
[Fillings and Composition guide](../../guides/fillings.md) explains when to use
it and how resolution behaves.

## Resolve known references

::: chatsnack.resolve_fillings_a

## Errors

All direct resolver errors inherit from `FillingError`.

### `FillingError`

::: chatsnack.FillingError

### `FillingAuthorityError`

::: chatsnack.FillingAuthorityError

### `FillingLimitError`

::: chatsnack.FillingLimitError
