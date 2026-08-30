"""Prompt fillings and the public, policy-aware filling resolver.

The legacy formatter-facing catalog remains available through
``filling_machine``.  ``resolve_fillings`` and ``resolve_fillings_a`` are the
public boundary for tools that already know the finite set of static
``text.Name`` and ``chat.Name`` references they need.
"""

import asyncio
import re
import string
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol

from loguru import logger


active_filling_stash = ContextVar("chatsnack_active_filling_stash", default=None)

class _AsyncFillingMachine:
    """Used for parallel variable expansion"""
    def __init__(self, src, addl=None):
        self.src = src
        self.addl = addl

    def __getitem__(self, k):
        async def completer_coro():
            x = await self.src(k, self.addl)
            logger.trace("Filling machine: {k} filled with:\n{x}", k=k, x=x)
            return x
        return completer_coro

    __getattr__ = __getitem__


class _FillingsCatalog:
    def __init__(self):
        self.vendors = {}

    def add_filling(self, filling_name: str, filling_machine_callback: Callable):
        """Add a new filling machine to the fillings catalog"""
        self.vendors[filling_name] = filling_machine_callback
    
# singleton
snack_catalog = _FillingsCatalog()

def filling_machine(additional: Optional[Dict] = None) -> dict:
    fillings_dict = additional.copy() if additional is not None else {}
    for k, v in snack_catalog.vendors.items():
        if k not in fillings_dict:
            # don't overwrite if they had an argument with the same name
            fillings_dict[k] = _AsyncFillingMachine(v, additional)
    return fillings_dict


_STATIC_FILLING_REFERENCE = re.compile(
    r"^(?P<vendor>text|chat)\.(?P<name>[A-Za-z_][A-Za-z0-9_-]*)$"
)


class FillingError(RuntimeError):
    """Base class for public filling-resolution failures."""


class FillingAuthorityError(FillingError):
    """Raised before an unresolved chat filling can perform provider I/O."""


class FillingLimitError(FillingError):
    """Raised when a bounded filling graph exceeds an invocation limit."""


class FillingCycleError(FillingError):
    """Raised when text fillings form a recursive dependency cycle."""


class FillingResolutionError(FillingError):
    """Raised when an existing filling cannot be loaded or resolved."""


@dataclass(frozen=True)
class FillingLimits:
    """Per-invocation filling limits with finite implementation ceilings."""

    max_depth: int = 16
    max_nodes: int = 256
    max_chat_calls: int = 16
    max_chat_concurrency: int = 4

    _CEILINGS = {
        "max_depth": 64,
        "max_nodes": 4096,
        "max_chat_calls": 256,
        "max_chat_concurrency": 32,
    }

    def __post_init__(self):
        for field_name, ceiling in self._CEILINGS.items():
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{field_name} must be an integer")
            if value < 1 or value > ceiling:
                raise ValueError(
                    f"{field_name} must be between 1 and {ceiling}"
                )


@dataclass(frozen=True)
class FillingResolution:
    """Frozen result metadata plus a JSON-like filling context."""

    context: Mapping[str, Mapping[str, Any]]
    resolved_references: tuple[str, ...]
    missing_references: tuple[str, ...]
    chat_calls: int


class FillingSource(Protocol):
    """Injectable source used by the resolver and its network-free tests."""

    def load_text(self, name: str) -> Optional[str]:
        """Return text content, or ``None`` when the name is absent."""

    async def resolve_chat(
        self,
        name: str,
        variables: Mapping[str, Any],
    ) -> Optional[str]:
        """Return a chat response, or ``None`` when the name is absent."""


class ChatsnackFillingSource:
    """Resolve persisted ``Text`` and ``Chat`` objects through public APIs."""

    def __init__(self, *, stash=None):
        self.stash = stash

    def _objects(self, model):
        return model.objects(self.stash) if self.stash is not None else model.objects

    def load_text(self, name: str) -> Optional[str]:
        from .chat import Text

        prompt = self._objects(Text).get_or_none(name)
        if prompt is None:
            return None
        if not isinstance(prompt.content, str):
            raise TypeError("text filling content must be a string")
        return prompt.content

    async def resolve_chat(
        self,
        name: str,
        variables: Mapping[str, Any],
    ) -> Optional[str]:
        from .chat import Chat

        prompt = self._objects(Chat).get_or_none(name)
        if prompt is None:
            return None
        # Resolver override namespaces would replace the saved chat's built-in
        # filling machines if forwarded as query variables. Ordinary template
        # variables still belong to the nested chat call.
        query_variables = {
            key: value
            for key, value in variables.items()
            if key not in {"text", "chat"}
        }
        response = await prompt.ask_a(**query_variables)
        if not isinstance(response, str):
            raise TypeError("chat filling response must be a string")
        return response


_MISSING = object()
_FORMATTER = string.Formatter()


def _static_reference(field_name: str) -> Optional[str]:
    match = _STATIC_FILLING_REFERENCE.fullmatch(field_name)
    return match.group(0) if match is not None else None


def _lookup_mapping_path(values: Mapping[str, Any], path: str):
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _explicit_filling(values: Mapping[str, Any], reference: str):
    vendor, name = reference.split(".", 1)
    namespace = values.get(vendor, _MISSING)
    if not isinstance(namespace, Mapping) or name not in namespace:
        return _MISSING
    return namespace[name]


def _parse_fields(template: str, reference: str) -> list[str]:
    try:
        return [
            field_name
            for _, field_name, _, _ in _FORMATTER.parse(template)
            if field_name is not None
        ]
    except ValueError:
        raise FillingResolutionError(f"could not resolve {reference}") from None


async def resolve_fillings_a(
    references: Iterable[str],
    *,
    variables: Optional[Mapping[str, Any]] = None,
    allow_chat: bool = False,
    limits: Optional[FillingLimits] = None,
    source: Optional[FillingSource] = None,
) -> FillingResolution:
    """Resolve a finite sequence of static filling references.

    Explicit values under ``variables["text"]`` or ``variables["chat"]`` win
    without catalog access.  Unresolved chat references require
    ``allow_chat=True`` before the source is called.  Text dependencies are
    discovered transitively, while inserted results remain opaque.
    """

    variables = variables or {}
    if not isinstance(variables, Mapping):
        raise TypeError("variables must be a mapping")
    limits = limits or FillingLimits()
    source = source or ChatsnackFillingSource()

    requested: list[str] = []
    seen_requested: set[str] = set()
    for reference in references:
        if not isinstance(reference, str) or _static_reference(reference) is None:
            raise ValueError(
                "filling references must be static text.Name or chat.Name values"
            )
        if reference not in seen_requested:
            requested.append(reference)
            seen_requested.add(reference)

    raw_text: dict[str, str] = {}
    missing: set[str] = set()
    discovered: set[str] = set()
    chat_references: list[str] = []
    reference_chains: dict[str, tuple[str, ...]] = {}
    node_count = 0

    def count_node(reference: str):
        nonlocal node_count
        node_count += 1
        if node_count > limits.max_nodes:
            raise FillingLimitError(
                f"filling node limit exceeded while resolving {reference}"
            )

    def discover(reference: str, chain: tuple[str, ...] = ()):  # noqa: C901
        if _explicit_filling(variables, reference) is not _MISSING:
            return
        if reference in missing or reference in discovered:
            return
        if reference in chain:
            start = chain.index(reference)
            cycle = chain[start:] + (reference,)
            raise FillingCycleError(f"filling cycle: {' -> '.join(cycle)}")
        if len(chain) + 1 > limits.max_depth:
            raise FillingLimitError(
                f"filling depth limit exceeded while resolving {reference}"
            )
        current_chain = chain + (reference,)
        reference_chains.setdefault(reference, current_chain)

        vendor, name = reference.split(".", 1)
        if vendor == "chat":
            if not allow_chat:
                raise FillingAuthorityError(
                    _with_chain(
                        f"chat filling authority is required for {reference}",
                        current_chain,
                    )
                )
            count_node(reference)
            if len(chat_references) >= limits.max_chat_calls:
                raise FillingLimitError(
                    f"chat filling call limit exceeded while resolving {reference}"
                )
            chat_references.append(reference)
            discovered.add(reference)
            return

        try:
            content = source.load_text(name)
        except Exception:
            raise FillingResolutionError(
                _with_chain(f"could not resolve {reference}", current_chain)
            ) from None
        if content is None:
            missing.add(reference)
            return
        if not isinstance(content, str):
            raise FillingResolutionError(f"could not resolve {reference}")

        count_node(reference)
        raw_text[reference] = content
        fields = _parse_fields(content, reference)
        seen_dependencies: set[str] = set()
        for field_name in fields:
            dependency = _static_reference(field_name)
            if dependency is None or dependency in seen_dependencies:
                continue
            seen_dependencies.add(dependency)
            discover(dependency, current_chain)
        discovered.add(reference)

    for reference in requested:
        discover(reference)

    chat_values: dict[str, str] = {}
    semaphore = asyncio.Semaphore(limits.max_chat_concurrency)

    async def resolve_chat(reference: str):
        _, name = reference.split(".", 1)
        async with semaphore:
            try:
                value = await source.resolve_chat(name, variables)
            except Exception:
                raise FillingResolutionError(
                    _with_chain(
                        f"could not resolve {reference}",
                        reference_chains[reference],
                    )
                ) from None
        if value is None:
            return reference, _MISSING
        if not isinstance(value, str):
            raise FillingResolutionError(f"could not resolve {reference}")
        return reference, value

    if chat_references:
        chat_results = await asyncio.gather(
            *(resolve_chat(reference) for reference in chat_references)
        )
        for reference, value in chat_results:
            if value is _MISSING:
                missing.add(reference)
            else:
                chat_values[reference] = value

    text_values: dict[str, str] = {}
    resolved_references: list[str] = []
    resolved_seen: set[str] = set()

    def mark_resolved(reference: str):
        if reference not in resolved_seen:
            resolved_references.append(reference)
            resolved_seen.add(reference)

    for reference in chat_references:
        if reference in chat_values:
            mark_resolved(reference)

    def reference_value(reference: str):
        explicit = _explicit_filling(variables, reference)
        if explicit is not _MISSING:
            return explicit
        if reference in chat_values:
            return chat_values[reference]
        if reference in raw_text:
            return render_text(reference)
        return _MISSING

    def render_text(reference: str) -> str:
        if reference in text_values:
            return text_values[reference]
        template = raw_text[reference]
        parts: list[str] = []
        try:
            parsed = list(_FORMATTER.parse(template))
        except ValueError:
            raise FillingResolutionError(f"could not resolve {reference}") from None
        for literal_text, field_name, _, _ in parsed:
            parts.append(literal_text)
            if field_name is None:
                continue
            dependency = _static_reference(field_name)
            value = (
                reference_value(dependency)
                if dependency is not None
                else _lookup_mapping_path(variables, field_name)
            )
            if value is _MISSING:
                failed_reference = dependency or reference
                raise FillingResolutionError(
                    _with_chain(
                        f"could not resolve {failed_reference}",
                        reference_chains.get(failed_reference, (reference,)),
                    )
                ) from None
            parts.append(str(value))
        value = "".join(parts)
        text_values[reference] = value
        mark_resolved(reference)
        return value

    for reference in requested:
        if reference in raw_text:
            render_text(reference)

    result_context: dict[str, dict[str, Any]] = {}
    missing_requested: list[str] = []
    for reference in requested:
        vendor, name = reference.split(".", 1)
        namespace = result_context.setdefault(vendor, {})
        value = reference_value(reference)
        if value is _MISSING:
            missing_requested.append(reference)
        else:
            namespace[name] = value

    frozen_context = MappingProxyType(
        {
            vendor: MappingProxyType(dict(namespace))
            for vendor, namespace in result_context.items()
        }
    )
    return FillingResolution(
        context=frozen_context,
        resolved_references=tuple(resolved_references),
        missing_references=tuple(missing_requested),
        chat_calls=len(chat_references),
    )


def resolve_fillings(
    references: Iterable[str],
    **kwargs,
) -> FillingResolution:
    """Synchronous form of :func:`resolve_fillings_a`."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(resolve_fillings_a(references, **kwargs))
    raise RuntimeError(
        "Cannot call resolve_fillings() from an active event loop. "
        "Use resolve_fillings_a() instead."
    )


def _with_chain(message: str, chain: tuple[str, ...]) -> str:
    if len(chain) <= 1:
        return message
    return f"{message} (via {' -> '.join(chain)})"
