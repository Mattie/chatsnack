"""
Normalized internal turn model for Phase 3.

Every loaded message is normalized internally to an expanded object form,
even when the source YAML used a scalar ``role: text`` form.  The author-facing
YAML contract stays unchanged; this module is an implementation detail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# Canonical field ordering for expanded user/assistant blocks on save.
CANONICAL_FIELD_ORDER: List[str] = [
    "text",
    "reasoning",
    "encrypted_content",
    "sources",
    "images",
    "files",
    "tool_calls",
    "provider_extras",
]

# Allowed canonical fields by role.
_SYSTEM_FIELDS = {"text"}
_USER_FIELDS = {"text", "images", "files", "provider_extras"}
_ASSISTANT_FIELDS = {
    "text",
    "reasoning",
    "encrypted_content",
    "sources",
    "images",
    "files",
    "tool_calls",
    "provider_extras",
}

ALLOWED_FIELDS_BY_ROLE = {
    "system": _SYSTEM_FIELDS,
    "user": _USER_FIELDS,
    "assistant": _ASSISTANT_FIELDS,
}

# The canonical role for the developer alias.
DEVELOPER_ALIAS = "developer"
CANONICAL_SYSTEM_ROLE = "system"


@dataclass
class NormalizedTurn:
    """Internal expanded-turn representation.

    This is *not* serialized directly into the author-facing YAML.  Instead
    it serves as the bridge between the YAML parser/serializer and the
    runtime adapters, making it safe for the runtime to populate richer
    fields (reasoning, sources, images, …) while the YAML layer keeps
    control over what actually gets written to disk.
    """

    role: str
    text: Optional[str] = None
    reasoning: Optional[str] = None
    encrypted_content: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    images: Optional[List[Dict[str, Any]]] = None
    files: Optional[List[Dict[str, Any]]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_output: Optional[Dict[str, Any]] = None  # for tool role messages
    provider_extras: Optional[Dict[str, Any]] = None

    # ── construction helpers ────────────────────────────────────────────

    @classmethod
    def from_message_dict(cls, msg: Dict[str, Any]) -> "NormalizedTurn":
        """Build a NormalizedTurn from one chatsnack internal message dict.

        The dict has exactly one top-level key which is the role name, and
        its value is either a scalar string or an expanded mapping.
        """
        if not msg or not isinstance(msg, dict):
            raise ValueError(f"Expected a single-key dict, got: {msg!r}")

        role = next(iter(msg))
        content = msg[role]

        # ``developer`` is loaded as an alias for ``system``.
        canonical_role = CANONICAL_SYSTEM_ROLE if role == DEVELOPER_ALIAS else role

        # Tool messages keep their own shape.
        if canonical_role == "tool":
            if isinstance(content, dict):
                return cls(role="tool", tool_output=content)
            return cls(role="tool", text=str(content) if content is not None else None)

        # Include pseudo-messages pass through transparently.
        if canonical_role == "include":
            return cls(role="include", text=content)

        # Scalar string form.
        if isinstance(content, str):
            return cls(role=canonical_role, text=content)

        # Expanded mapping form.
        if isinstance(content, dict):
            allowed = ALLOWED_FIELDS_BY_ROLE.get(canonical_role, _ASSISTANT_FIELDS)
            extras: Dict[str, Any] = {}
            turn = cls(role=canonical_role)

            for key, value in content.items():
                if key in allowed and key != "provider_extras":
                    setattr(turn, key, value)
                elif key == "provider_extras":
                    # Merge explicit provider_extras.
                    if isinstance(value, dict):
                        extras.update(value)
                else:
                    # Unknown field → provider_extras.
                    extras[key] = value

            if extras:
                turn.provider_extras = extras

            return turn

        # Fallback: treat as text.
        return cls(role=canonical_role, text=str(content) if content is not None else None)

    # ── serialization helpers ───────────────────────────────────────────

    def has_expanded_fields(self) -> bool:
        """Return True if any canonical field beyond ``text`` is populated."""
        for fname in CANONICAL_FIELD_ORDER:
            if fname == "text":
                continue
            val = getattr(self, fname, None)
            if val is not None:
                return True
        return False

    def to_message_dict(self, fidelity: str = "authoring") -> Dict[str, Any]:
        """Convert back to the chatsnack internal message dict.

        ``fidelity`` controls how much data is emitted:

        * ``"authoring"`` – default readable YAML
        * ``"continuation"`` – includes continuation metadata hints
        * ``"diagnostic"`` – includes provider_extras
        """
        # Tool messages.
        if self.role == "tool":
            if self.tool_output is not None:
                return {"tool": self.tool_output}
            return {"tool": self.text}

        # Include pseudo-messages.
        if self.role == "include":
            return {"include": self.text}

        # Decide canonical role key for output. Always ``system``.
        out_role = CANONICAL_SYSTEM_ROLE if self.role == DEVELOPER_ALIAS else self.role

        # System turns are text-only after normalization.
        if out_role == "system":
            return {"system": self.text}

        # If this turn only has text, collapse to scalar form.
        if not self._has_non_text_canonical(fidelity):
            return {out_role: self.text}

        # Build expanded mapping in canonical field order.
        block: Dict[str, Any] = {}
        for fname in CANONICAL_FIELD_ORDER:
            value = getattr(self, fname, None)
            if value is None:
                continue

            # Fidelity gating for specific fields.
            if fname == "provider_extras":
                if fidelity not in ("continuation", "diagnostic"):
                    continue
            if fname == "encrypted_content":
                if fidelity == "authoring":
                    continue  # MAY be dropped

            block[fname] = value

        return {out_role: block}

    def _has_non_text_canonical(self, fidelity: str) -> bool:
        """Check whether any canonical field besides text is present and
        would be emitted at the given fidelity."""
        for fname in CANONICAL_FIELD_ORDER:
            if fname == "text":
                continue
            value = getattr(self, fname, None)
            if value is None:
                continue
            # Apply same gating as to_message_dict
            if fname == "provider_extras" and fidelity not in ("continuation", "diagnostic"):
                continue
            if fname == "encrypted_content" and fidelity == "authoring":
                continue
            return True
        return False


def normalize_messages(messages: List[Dict[str, Any]]) -> List[NormalizedTurn]:
    """Normalize a list of chatsnack message dicts into NormalizedTurn objects."""
    return [NormalizedTurn.from_message_dict(m) for m in messages]


def denormalize_messages(
    turns: List[NormalizedTurn],
    fidelity: str = "authoring",
) -> List[Dict[str, Any]]:
    """Convert NormalizedTurn objects back to chatsnack message dicts."""
    return [t.to_message_dict(fidelity=fidelity) for t in turns]
