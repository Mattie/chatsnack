"""Prompt fillings and a small public adapter for resolving known references.

Chatsnack's normal prompt path and the public resolver use the same filling
catalog and async formatter. The resolver adds an invocation-local policy
around those existing callbacks so external assemblers can authorize model
work and keep recursive expansion finite.
"""

from contextvars import ContextVar
from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable, Dict, Iterable, Mapping, Optional

from loguru import logger

from .asynchelpers import aformatter


active_filling_stash = ContextVar("chatsnack_active_filling_stash", default=None)


class _AsyncFillingMachine:
    """Expose one async catalog callback through formatter field access."""

    def __init__(self, vendor, src, addl=None):
        self.vendor = vendor
        self.src = src
        self.addl = addl

    def __getitem__(self, key):
        async def completer_coro():
            reference = f"{self.vendor}.{key}"

            async def expand():
                return await self.src(key, self.addl)

            value = await _bounded_filling_expansion(
                reference,
                expand,
                is_chat=self.vendor == "chat",
                defer_chat_limit=bool(
                    getattr(
                        self.src,
                        "_chatsnack_reserves_chat_after_lookup",
                        False,
                    )
                ),
            )
            logger.trace(
                "Filling machine: {key} filled with:\n{value}",
                key=key,
                value=value,
            )
            return value

        return completer_coro

    async def _chatsnack_expand_field(self, key):
        """Force formatter fields through catalog dispatch, not attributes."""

        return await self[key]()

    __getattr__ = __getitem__


class _FillingsCatalog:
    def __init__(self):
        self.vendors = {}

    def add_filling(self, filling_name: str, filling_machine_callback: Callable):
        """Add a named async filling callback to the shared catalog."""

        self.vendors[filling_name] = filling_machine_callback


snack_catalog = _FillingsCatalog()


def filling_machine(additional: Optional[Dict] = None) -> dict:
    """Build formatter variables with registered filling vendors included."""

    fillings_dict = additional.copy() if additional is not None else {}
    for key, callback in snack_catalog.vendors.items():
        if key not in fillings_dict:
            fillings_dict[key] = _AsyncFillingMachine(key, callback, additional)
    return fillings_dict


_STATIC_FILLING_REFERENCE = re.compile(
    r"^(?P<vendor>text|chat)\.(?P<name>[A-Za-z_][A-Za-z0-9_-]*)$"
)
_MAX_DEPTH = 16
_MAX_EXPANSIONS = 256
_MAX_CHAT_CALLS = 16
_MISSING = object()


class FillingError(RuntimeError):
    """Raised when a requested filling cannot be safely resolved."""


class FillingAuthorityError(FillingError):
    """Raised before a resolver-scoped Chat filling can call a model."""


class FillingLimitError(FillingError):
    """Raised when resolver-scoped recursive expansion exceeds a fixed bound."""


@dataclass
class _ResolverState:
    allow_chat: bool
    expansions: int = 0
    chat_calls: int = 0


class _MissingFilling(FillingError):
    def __init__(self, reference: str, chain: tuple[str, ...]):
        self.reference = reference
        self.chain = chain


_active_resolver = ContextVar("chatsnack_active_filling_resolver", default=None)
_active_chain = ContextVar("chatsnack_active_filling_chain", default=())


def _filling_resolution_active() -> bool:
    """Return whether a public resolver currently owns filling expansion."""

    return _active_resolver.get() is not None


def _reserve_chat_filling_call(reference: str) -> None:
    """Reserve one resolver-authorized model call before provider dispatch."""

    state = _active_resolver.get()
    if state is None:
        return
    state.chat_calls += 1
    if state.chat_calls > _MAX_CHAT_CALLS:
        state.chat_calls -= 1
        raise FillingLimitError(
            _with_chain(
                f"chat filling call limit exceeded while resolving {reference}",
                _active_chain.get(),
            )
        )


async def _bounded_filling_expansion(
    reference: str,
    expand: Callable[[], Awaitable[str]],
    *,
    is_chat: bool = False,
    defer_chat_limit: bool = False,
) -> str:
    """Apply resolver-only authority and recursion bounds to one callback.

    Outside :func:`resolve_fillings_a`, this delegates directly so the normal
    Chat prompt path retains its existing behavior.
    """

    state = _active_resolver.get()
    if state is None:
        return await expand()

    chain = _active_chain.get()
    if reference in chain:
        start = chain.index(reference)
        cycle = chain[start:] + (reference,)
        raise FillingError(f"filling cycle: {' -> '.join(cycle)}")
    current_chain = chain + (reference,)
    if len(current_chain) > _MAX_DEPTH:
        raise FillingLimitError(
            _with_chain(
                f"filling depth limit exceeded while resolving {reference}",
                current_chain,
            )
        )

    state.expansions += 1
    if state.expansions > _MAX_EXPANSIONS:
        raise FillingLimitError(
            _with_chain(
                f"filling expansion limit exceeded while resolving {reference}",
                current_chain,
            )
        )

    chat_call_reserved = False
    if is_chat:
        if not state.allow_chat:
            raise FillingAuthorityError(
                _with_chain(
                    f"chat filling authority is required for {reference}",
                    current_chain,
                )
            )
        if not defer_chat_limit:
            _reserve_chat_filling_call(reference)
            chat_call_reserved = True

    token = _active_chain.set(current_chain)
    try:
        return await expand()
    except _MissingFilling:
        if chat_call_reserved:
            state.chat_calls -= 1
        raise
    except FillingError:
        raise
    except Exception:
        raise FillingError(
            _with_chain(f"could not resolve {reference}", current_chain)
        ) from None
    finally:
        _active_chain.reset(token)


def _missing_filling(reference: str) -> Exception:
    """Create the internal missing-asset signal for a resolver callback."""

    return _MissingFilling(reference, _active_chain.get())


async def resolve_fillings_a(
    references: Iterable[str],
    *,
    variables: Mapping[str, Any] | None = None,
    allow_chat: bool = False,
) -> dict[str, dict[str, Any]]:
    """Resolve known static Text and Chat references with the main formatter.

    ``references`` must contain static ``text.Name`` or ``chat.Name`` values.
    Explicit values in the matching ``variables`` namespace are returned as
    opaque data. Saved assets expand through the same callbacks used by
    :meth:`Chat.ask_a`. Missing requested assets are omitted after any required
    Chat authority check. Chat fillings, including transitive ones, require
    explicit authority for this invocation.
    """

    if variables is None:
        variables = {}
    if not isinstance(variables, Mapping):
        raise TypeError("variables must be a mapping")
    if not isinstance(allow_chat, bool):
        raise TypeError("allow_chat must be a bool")

    requested: list[str] = []
    seen: set[str] = set()
    for reference in references:
        if not isinstance(reference, str) or not _STATIC_FILLING_REFERENCE.fullmatch(
            reference
        ):
            raise ValueError(
                "filling references must be static text.Name or chat.Name values"
            )
        if reference not in seen:
            requested.append(reference)
            seen.add(reference)

    ordinary_variables = {
        key: value for key, value in variables.items() if key not in {"text", "chat"}
    }
    resolved: dict[str, dict[str, Any]] = {}
    state_token = _active_resolver.set(_ResolverState(allow_chat=allow_chat))
    chain_token = _active_chain.set(())
    try:
        for reference in requested:
            vendor, name = reference.split(".", 1)
            namespace = resolved.setdefault(vendor, {})
            explicit = _explicit_filling(variables, vendor, name)
            if explicit is not _MISSING:
                namespace[name] = explicit
                continue

            try:
                namespace[name] = await aformatter.async_format_mapping(
                    "{" + reference + "}",
                    filling_machine(ordinary_variables),
                )
            except _MissingFilling as error:
                if error.reference == reference and len(error.chain) == 1:
                    continue
                raise FillingError(
                    _with_chain(
                        f"could not resolve {error.reference}",
                        error.chain,
                    )
                ) from None
            except FillingError:
                raise
            except Exception:
                raise FillingError(f"could not resolve {reference}") from None
    finally:
        _active_chain.reset(chain_token)
        _active_resolver.reset(state_token)

    return resolved


def _explicit_filling(
    variables: Mapping[str, Any], vendor: str, name: str
) -> Any:
    namespace = variables.get(vendor, _MISSING)
    if not isinstance(namespace, Mapping):
        return _MISSING
    return namespace.get(name, _MISSING)


def _with_chain(message: str, chain: tuple[str, ...]) -> str:
    if len(chain) <= 1:
        return message
    return f"{message} (via {' -> '.join(chain)})"
