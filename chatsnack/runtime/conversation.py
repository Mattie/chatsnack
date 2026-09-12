"""Reversible Responses items inside the ordinary chatsnack message list.

Compact entries own their editable fields. Extras contain only fields that are
not mapped, so replay never chooses between two copies of conversation text.
"""

from copy import deepcopy
import base64
import json
import hashlib
import warnings
from typing import Any


ITEM_ROLES = frozenset({"reasoning", "tool_call", "provider_item"})


def copy_value(value):
    """Detach message containers without copying snapclass's persistence owners."""
    if isinstance(value, dict):
        return {key: copy_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [copy_value(item) for item in value]
    return deepcopy(value)


def wire_dict(value: Any) -> dict:
    """Copy SDK values using wire aliases, preserving explicit nulls and extras."""
    if isinstance(value, dict):
        return copy_value(value)
    if hasattr(value, "model_dump"):
        try:
            # New provider item types may predate the installed SDK's union.
            # Their wire dictionaries are still valid history to preserve.
            return value.model_dump(by_alias=True, exclude_unset=True, warnings=False)
        except TypeError:
            # Small custom adapters and older test doubles may expose no kwargs.
            return value.model_dump()
    return deepcopy(vars(value)) if hasattr(value, "__dict__") else dict(value)


def _extract(item, fields):
    """Move mapped fields into a compact block and retain the remainder once."""
    remaining = copy_value(item)
    remaining.pop("type", None)
    block = {}
    for wire_name, name in fields.items():
        if wire_name in remaining:
            block[name] = remaining.pop(wire_name)
    if remaining:
        block["provider_extras"] = remaining
    return block


def compact_message(entry):
    """Omit known empty metadata and completed status, keeping authored data intact.

    Required wire defaults are restored by ``message_to_item``. Unknown extras,
    opaque items, and message/tool text can give emptiness meaning, so they are
    never recursively filtered by truthiness.
    """
    role, original = next(iter(entry.items()))
    if role not in {"system", "user", "assistant", "reasoning", "tool_call", "tool"} or not isinstance(original, dict):
        return copy_value(entry)
    block = copy_value(original)
    optional = {
        "system": set(),
        "user": {"images", "files"},
        "assistant": {"item_id", "phase", "status", "reasoning", "encrypted_content",
                      "sources", "images", "files", "tool_calls"},
        "reasoning": {"item_id", "status", "summary", "content", "encrypted_content"},
        "tool_call": {"item_id", "status"},
        "tool": {"item_id"},
    }[role] | {"provider_extras"}
    # Native tool outputs have their own status contract. In particular, a
    # missing Apply Patch status means failure, so success must stay explicit.
    if role == "tool" and block.get("output_type") in (None, "function_call_output"):
        optional.add("status")
    for name in optional:
        if name in block and block[name] in (None, "", [], {}):
            block.pop(name)
    if "status" in optional and block.get("status") == "completed":
        block.pop("status")
    extras = block.get("provider_extras")
    parts = extras.get("content") if isinstance(extras, dict) else None
    if role == "assistant" and "text" in block and isinstance(parts, list) and len(parts) == 1:
        part = parts[0]
        if isinstance(part, dict) and part.get("type", "output_text") == "output_text":
            for name in ("annotations", "logprobs"):
                if part.get(name) in (None, []):
                    part.pop(name, None)
            # IDs also mark recorded text as literal. Without an ID, keep this
            # content marker so it cannot be mistaken for an authored template.
            if block.get("item_id"):
                part.pop("type", None)
                if not part:
                    extras.pop("content")
            if not extras:
                block.pop("provider_extras")
    return {role: block}


def item_to_message(value):
    """Represent one provider item as one transcript entry, without reordering."""
    item = wire_dict(value)
    kind = item.get("type")
    if kind == "reasoning":
        return compact_message({"reasoning": _extract(item, {
            "id": "item_id", "summary": "summary", "content": "content",
            "encrypted_content": "encrypted_content", "status": "status",
        })})
    if kind == "function_call":
        return compact_message({"tool_call": _extract(item, {
            "name": "name", "arguments": "arguments", "call_id": "call_id",
            "id": "item_id", "status": "status",
        })})
    if kind == "function_call_output":
        if not isinstance(item.get("output"), str):
            # A provider output list is multimodal content, not a JSON string.
            return {"provider_item": item}
        return compact_message({"tool": _extract(item, {
            "call_id": "tool_call_id", "output": "content", "id": "item_id",
            "status": "status",
        })})
    if kind == "message" and item.get("role") == "assistant":
        parts = item.get("content")
        if (isinstance(parts, list) and len(parts) == 1
                and parts[0].get("type") == "output_text"
                and isinstance(parts[0].get("text"), str)):
            compact = deepcopy(item)
            compact.pop("role")
            compact.pop("content")
            block = {"text": parts[0]["text"]}
            block.update(_extract(compact, {
                "id": "item_id", "phase": "phase", "status": "status",
            }))
            part_extras = {k: deepcopy(v) for k, v in parts[0].items() if k != "text"}
            block.setdefault("provider_extras", {})["content"] = [part_extras]
            return compact_message({"assistant": block})
    # Complex content and new item types remain one complete opaque entry.
    return {"provider_item": item}


def _restore(block, kind, fields):
    """Restore mapped values over their provider extras without inventing IDs."""
    result = copy_value(block.get("provider_extras") or {})
    result["type"] = kind
    for name, wire_name in fields.items():
        if name in block:
            result[wire_name] = copy_value(block[name])
    return result


def message_to_item(role, block):
    """Restore a typed or recorded assistant entry; return None for legacy turns."""
    if role == "provider_item":
        result = copy_value(block["item"] if "item" in block and "type" not in block else block)
        if "type" not in block and block.get("result_asset"):
            # Rehydrate media at the request boundary; YAML keeps the asset reference.
            from ..assets import resolve_asset_path
            asset = block["result_asset"]
            path = resolve_asset_path(asset["asset"], asset.get("filename"))
            result["result"] = base64.b64encode(path.read_bytes()).decode("ascii")
        return result
    if not isinstance(block, dict):
        return None
    if role == "reasoning":
        result = _restore(block, "reasoning", {
            "item_id": "id", "summary": "summary", "content": "content",
            "encrypted_content": "encrypted_content", "status": "status",
        })
        if isinstance(result.get("summary"), str):
            result["summary"] = [{"type": "summary_text", "text": result["summary"]}]
        result.setdefault("summary", [])
        return result
    if role == "tool_call":
        result = _restore(block, "function_call", {
            "name": "name", "arguments": "arguments", "call_id": "call_id",
            "item_id": "id", "status": "status",
        })
        if isinstance(result.get("arguments"), (dict, list)):
            result["arguments"] = json.dumps(result["arguments"], ensure_ascii=False)
        return result
    if role == "assistant" and "tool_calls" not in block and any(
        key in block for key in ("item_id", "phase", "status", "provider_extras")
    ) and "text" in block:
        result = _restore(block, "message", {
            "item_id": "id", "phase": "phase", "status": "status",
        })
        result["role"] = "assistant"
        result.setdefault("status", "completed")
        parts = result.get("content", [{"type": "output_text"}])
        if not isinstance(parts, list):
            # Imported extras can contain null or another non-part value. The
            # mapped text owns replay; keep the original extra in saved history.
            parts = [{"type": "output_text"}]
        if len(parts) == 1:
            parts[0].setdefault("type", "output_text")
            parts[0].setdefault("annotations", [])
            parts[0]["text"] = block["text"]
        result["content"] = parts
        return result
    return None


def _provider_item(entry):
    """Read the wire item beneath an optional asset/convenience wrapper."""
    item = entry.get("provider_item") or {}
    return item["item"] if "item" in item and "type" not in item else item


def is_assistant_entry(entry):
    """Recognize assistant boundaries even when the output has no text."""
    if "assistant" in entry:
        return True
    item = _provider_item(entry)
    return item.get("type") == "message" and item.get("role") == "assistant"


def latest_response_entries(entries):
    """Find the latest output group without mistaking trailing input for a reply.

    Authored messages and tool results delimit output groups. An older explicit
    final_answer also ends a group; contiguous unphased output has no persisted
    response boundary, so it remains one group.
    """
    group = []
    for entry in reversed(entries):
        role = next(iter(entry))
        item = _provider_item(entry)
        kind = item.get("type", "")
        is_input = role not in {"assistant", "reasoning", "tool_call", "provider_item"}
        if role == "provider_item":
            is_input = (kind.endswith("_call_output") or kind == "tool_search_output"
                        or item.get("role") in {"user", "system", "developer"})
        if is_input:
            if group:
                break
            continue
        block = entry.get("assistant") if "assistant" in entry else item
        if group and is_assistant_entry(entry) and isinstance(block, dict) and block.get("phase") == "final_answer":
            break
        group.append(entry)
    return list(reversed(group))


def entry_text(entry):
    """Read assistant text from compact or opaque message entries."""
    if "assistant" in entry:
        value = entry["assistant"]
        return value.get("text") if isinstance(value, dict) else value
    item = _provider_item(entry)
    if item.get("type") == "message" and item.get("role") == "assistant":
        return "".join(part.get("text", "") for part in item.get("content", [])
                       if part.get("type") == "output_text") or None
    return None


def entries_to_bridge(entries):
    """Expand canonical entries into the existing role/content JSON bridge."""
    result = []
    for entry in entries:
        role, block = next(iter(entry.items()))
        if role in ITEM_ROLES or not isinstance(block, dict):
            result.append({"role": role, "content": copy_value(block)})
        else:
            value = copy_value(block)
            text = value.pop("text", value.pop("content", ""))
            result.append({"role": role, "content": text, **value})
    return result


def prefix_fingerprint(messages):
    """Fingerprint resolved message values without retaining a duplicate history."""
    data = json.dumps(messages, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _adjacent_tool_results(messages):
    """Place available results after their CC call without merging assistant data.

    Responses may interleave commentary with calls. Reordering only the projected
    results satisfies CC's exchange ordering and leaves the saved transcript intact.
    """
    ordered, moved = [], set()
    for index, message in enumerate(messages):
        if index in moved:
            continue
        ordered.append(message)
        if message.get("role") != "assistant":
            continue
        pending = {call["id"] for call in (message.get("tool_calls") or []) if call.get("id")}
        if not pending:
            continue
        for position in range(index + 1, len(messages)):
            result = messages[position]
            call_id = result.get("tool_call_id")
            if position not in moved and result.get("role") == "tool" and call_id in pending:
                ordered.append(result)
                moved.add(position)
                pending.remove(call_id)
                if not pending:
                    break
    return ordered


def project_chat_completions(messages):
    """Project a transcript for CC without changing its saved provider items."""
    projected, omitted = [], set()
    metadata_fields = {"item_id", "phase", "status", "reasoning", "encrypted_content", "provider_extras", "sources"}
    for original in messages:
        message = copy_value(original)
        role = message.get("role")
        if role == "tool_call":
            block = message.get("content") or {}
            arguments = block.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            call = {"id": block.get("call_id", ""), "type": "function",
                    "function": {"name": block.get("name", ""), "arguments": arguments}}
            if projected and projected[-1].get("role") == "assistant":
                projected[-1].setdefault("tool_calls", []).append(call)
            else:
                projected.append({"role": "assistant", "content": None, "tool_calls": [call]})
            if metadata_fields.intersection(block):
                omitted.add("tool-call metadata")
            continue
        if role in {"reasoning", "provider_item"}:
            omitted.add(role)
            if role == "provider_item":
                block = message.get("content") or {}
                item = block.get("item", block) if "type" not in block else block
                if item.get("type") == "function_call_output":
                    # Keep the correlation even when CC cannot consume image parts.
                    output = item.get("output")
                    text = (output if isinstance(output, str) else "".join(
                        part.get("text", "") for part in output or []
                        if isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}
                    ))
                    projected.append({"role": "tool", "tool_call_id": item.get("call_id", ""), "content": text})
                    continue
                text = entry_text({"provider_item": block})
                if text is not None:
                    projected.append({"role": "assistant", "content": text})
            continue
        if role == "tool" and message.get("output_type") not in (None, "function_call_output"):
            omitted.add(message["output_type"])
            continue
        for key in metadata_fields:
            if key in message:
                omitted.add("message metadata")
                message.pop(key)
        message.pop("output_type", None)
        for key in ("images", "files"):
            attachments = message.pop(key, None)
            if not attachments:
                continue
            parts = []
            for attachment in attachments:
                if role == "user" and key == "images" and attachment.get("url"):
                    parts.append({"type": "image_url", "image_url": {"url": attachment["url"]}})
                elif role == "user" and key == "files" and attachment.get("file_id"):
                    parts.append({"type": "file", "file": {"file_id": attachment["file_id"]}})
                else:
                    omitted.add(key)
            if parts:
                content = message.get("content")
                if not isinstance(content, list):
                    content = [{"type": "text", "text": content}] if content else []
                message["content"] = content + parts
        projected.append(message)
    if omitted:
        warnings.warn(
            "Chat Completions omits provider-only history (" + ", ".join(sorted(omitted))
            + "); the Chat's stored messages are preserved.",
            UserWarning, stacklevel=3,
        )
    return _adjacent_tool_results(projected)
