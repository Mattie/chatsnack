"""Provider-neutral usage snapshots for one Chatsnack call."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .types import NormalizedCompletionResult


@dataclass(frozen=True)
class UsageCounts:
    """Known token counts, preserving absence separately from reported zero."""

    input_tokens: Optional[int] = None
    cached_input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass(frozen=True)
class ResponseUsage:
    """Usage and provider identity captured from one completed response."""

    sequence: int
    response_id: Optional[str]
    previous_response_id: Optional[str]
    model: Optional[str]
    input_tokens: Optional[int]
    cached_input_tokens: Optional[int]
    output_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    total_tokens: Optional[int]
    usage_reported: bool
    provider_usage: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class CallUsage:
    """Immutable ordered usage snapshot for one ``chat()`` or ``chat_a()`` call."""

    responses: Tuple[ResponseUsage, ...] = ()

    @property
    def total(self) -> UsageCounts:
        """Sum every reported value while leaving wholly absent fields unknown."""
        return UsageCounts(
            input_tokens=_sum_known(self.responses, "input_tokens"),
            cached_input_tokens=_sum_known(self.responses, "cached_input_tokens"),
            output_tokens=_sum_known(self.responses, "output_tokens"),
            reasoning_tokens=_sum_known(self.responses, "reasoning_tokens"),
            total_tokens=_sum_known(self.responses, "total_tokens"),
        )

    @property
    def response_count(self) -> int:
        """Number of normalized provider responses observed during the call."""
        return len(self.responses)

    @property
    def usage_response_count(self) -> int:
        """Number of responses that supplied a non-null usage payload."""
        return sum(response.usage_reported for response in self.responses)

    @property
    def is_complete(self) -> bool:
        """Whether every observed response supplied a usage payload."""
        return bool(self.responses) and self.usage_response_count == self.response_count

    @property
    def missing_usage_sequences(self) -> Tuple[int, ...]:
        """One-based response positions whose provider usage payload was absent."""
        return tuple(
            response.sequence
            for response in self.responses
            if not response.usage_reported
        )


def _sum_known(responses: Sequence[ResponseUsage], field_name: str) -> Optional[int]:
    values = [
        value
        for response in responses
        if (value := getattr(response, field_name)) is not None
    ]
    return sum(values) if values else None


_MISSING = object()


def _value_at(mapping: Mapping[str, Any], path: Tuple[str, ...]):
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _known_count(
    usage: Mapping[str, Any],
    *paths: Tuple[str, ...],
) -> Optional[int]:
    for path in paths:
        value = _value_at(usage, path)
        if value is _MISSING:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value
    return None


def _plain_usage_mapping(usage: Any) -> Dict[str, Any]:
    """Detach an SDK/provider usage object into ordinary nested Python data."""
    if isinstance(usage, Mapping):
        value = dict(usage)
    elif hasattr(usage, "model_dump"):
        value = usage.model_dump()
    elif hasattr(usage, "__dict__"):
        value = vars(usage)
    else:
        try:
            value = dict(usage)
        except (TypeError, ValueError):
            value = {}
    return deepcopy(value) if isinstance(value, dict) else {}


def _response_usage_from_completion(
    completion: NormalizedCompletionResult,
    sequence: int,
) -> ResponseUsage:
    usage_reported = getattr(completion, "usage", None) is not None
    provider_usage = (
        _plain_usage_mapping(completion.usage)
        if usage_reported
        else None
    )
    usage = provider_usage or {}
    metadata = getattr(completion, "metadata", None) or {}

    return ResponseUsage(
        sequence=sequence,
        response_id=metadata.get("response_id"),
        previous_response_id=metadata.get("previous_response_id"),
        model=getattr(completion, "model", None),
        input_tokens=_known_count(
            usage,
            ("input_tokens",),
            ("prompt_tokens",),
        ),
        cached_input_tokens=_known_count(
            usage,
            ("input_tokens_details", "cached_tokens"),
            ("prompt_tokens_details", "cached_tokens"),
            ("cached_input_tokens",),
            ("input_cached_tokens",),
        ),
        output_tokens=_known_count(
            usage,
            ("output_tokens",),
            ("completion_tokens",),
        ),
        reasoning_tokens=_known_count(
            usage,
            ("output_tokens_details", "reasoning_tokens"),
            ("completion_tokens_details", "reasoning_tokens"),
            ("reasoning_tokens",),
        ),
        total_tokens=_known_count(usage, ("total_tokens",)),
        usage_reported=usage_reported,
        provider_usage=provider_usage,
    )


class _CallUsageLedger:
    """Mutable call-local collector that freezes into a public ``CallUsage``."""

    def __init__(self):
        self._responses: list[ResponseUsage] = []

    def record(self, completion: NormalizedCompletionResult) -> None:
        """Record the normalized result at the adapter-return boundary once."""
        self._responses.append(
            _response_usage_from_completion(
                completion,
                sequence=len(self._responses) + 1,
            )
        )

    def snapshot(self) -> CallUsage:
        """Freeze the current order of already-detached response values."""
        return CallUsage(responses=tuple(self._responses))


__all__ = ["UsageCounts", "ResponseUsage", "CallUsage"]
