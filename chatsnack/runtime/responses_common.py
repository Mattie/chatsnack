import warnings
import json
from typing import Any, Dict, List, Optional, Tuple

from .attachment_resolver import AttachmentResolver
from .types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
    NormalizedToolFunction,
)


class ResponsesNormalizationMixin:
    """Shared request-building and normalization for Responses transports."""

    @staticmethod
    def _to_dict(obj: Any) -> Dict[str, Any]:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "__dict__"):
            return vars(obj)
        return dict(obj)

    @staticmethod
    def _coerce_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return str(content)

    def _message_to_input_items(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        role = message.get("role")
        content = message.get("content")

        if role == "tool":
            output_type = message.get("output_type")
            if output_type == "tool_search_output":
                return [
                    {
                        "type": "tool_search_output",
                        "tool_call_id": message.get("tool_call_id", ""),
                        "output": self._coerce_text(content),
                    }
                ]
            return [
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": self._coerce_text(content),
                }
            ]

        items: List[Dict[str, Any]] = []
        tool_calls = message.get("tool_calls") or []
        if tool_calls and role == "assistant":
            text_content = self._coerce_text(content)
            if text_content:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "input_text", "text": text_content}],
                    }
                )
            for tool_call in tool_calls:
                function = self._to_dict(tool_call.get("function") or {})
                items.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.get("id", ""),
                        "name": function.get("name", ""),
                        "arguments": function.get("arguments", ""),
                    }
                )
            return items

        if role not in {"system", "developer", "user", "assistant"}:
            role = "user"

        # Build content parts – start with text, then images and files.
        content_parts: List[Dict[str, Any]] = []
        text = self._coerce_text(content)
        if text:
            content_parts.append({"type": "input_text", "text": text})

        # Phase 3: images on user/assistant turns → input_image items.
        for img in message.get("images") or []:
            if isinstance(img, dict):
                if img.get("url"):
                    content_parts.append({"type": "input_image", "image_url": img["url"]})
                elif img.get("file_id"):
                    content_parts.append({"type": "input_image", "file_id": img["file_id"]})
                elif img.get("path"):
                    # Local paths require an upload step that chatsnack does not
                    # yet perform.  Silently dropping them would hide authoring
                    # errors, so we warn and skip.
                    warnings.warn(
                        f"Skipping local-path image '{img['path']}': upload to file_id is not yet implemented. Use a url or file_id entry instead.",
                        stacklevel=2,
                    )

        # Phase 3: files on user turns → input_file items.
        for f in message.get("files") or []:
            if isinstance(f, dict):
                if f.get("file_id"):
                    content_parts.append({"type": "input_file", "file_id": f["file_id"]})
                elif f.get("path"):
                    # Local paths require an upload step that chatsnack does not
                    # yet perform.  Warn and skip.
                    warnings.warn(
                        f"Skipping local-path file '{f['path']}': upload to file_id is not yet implemented. Use a file_id entry instead.",
                        stacklevel=2,
                    )

        # Fall back to at least one input_text part even if empty.
        if not content_parts:
            content_parts.append({"type": "input_text", "text": ""})

        return [
            {
                "type": "message",
                "role": role,
                "content": content_parts,
            }
        ]

    def _map_messages_to_input(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        input_items: List[Dict[str, Any]] = []
        for message in messages:
            input_items.extend(self._message_to_input_items(message))
        return input_items

    @staticmethod
    def _apply_profile_defaults(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        out = kwargs.copy()
        profile = out.pop("profile", None)
        if not isinstance(profile, dict):
            return out

        defaults = profile.get("defaults")
        if isinstance(defaults, dict):
            merged = defaults.copy()
            merged.update(out)
            out = merged

        model = out.get("model")
        model_overrides = profile.get("model_defaults")
        if model and isinstance(model_overrides, dict) and isinstance(model_overrides.get(model), dict):
            merged = model_overrides[model].copy()
            merged.update(out)
            out = merged

        return out

    @staticmethod
    def _select_continuation_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not messages:
            return messages

        last_assistant_idx = -1
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "assistant":
                last_assistant_idx = idx
                break

        if last_assistant_idx == -1:
            return messages

        suffix = messages[last_assistant_idx + 1 :]
        return suffix or [messages[-1]]

    # Provider-native tool types that must pass through unchanged.
    _NATIVE_TOOL_TYPES = frozenset({
        "web_search", "file_search", "tool_search",
        "code_interpreter", "image_generation", "mcp",
        "namespace",
    })

    @classmethod
    def _normalize_tools_for_responses_request(cls, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Flatten nested Chat Completions function tools into the Responses API shape.

        The internal chatsnack tool model (and Chat Completions) uses::

            {"type": "function", "function": {"name": ..., "description": ..., ...}}

        The Responses API expects the flat shape::

            {"type": "function", "name": ..., "description": ..., ...}

        Provider-native tools (web_search, file_search, mcp, namespace, etc.)
        and tools that are already flat pass through unchanged.  Original list
        order is preserved exactly.
        """
        normalized: List[Dict[str, Any]] = []
        for tool in tools:
            tool_type = tool.get("type", "function")

            # Namespace tools may contain nested Chat Completions–shaped tools under
            # "tools". Normalize those children recursively but otherwise passthrough.
            if tool_type == "namespace":
                ns_tool = dict(tool)
                child_tools = tool.get("tools")
                if isinstance(child_tools, list):
                    ns_tool["tools"] = cls._normalize_tools_for_responses_request(child_tools)
                normalized.append(ns_tool)
                continue

            # Other provider-native tools: pass through as-is.
            if tool_type in cls._NATIVE_TOOL_TYPES:
                normalized.append(tool)
                continue

            # Function tool with a nested "function" payload → flatten.
            nested = tool.get("function")
            if tool_type == "function" and isinstance(nested, dict):
                flat: Dict[str, Any] = {"type": "function"}
                # Carry over any unknown top-level keys already on the dict
                # (future-proofing), but skip "type" and "function".
                for k, v in tool.items():
                    if k not in ("type", "function"):
                        flat[k] = v
                # Merge nested function fields (name, description, parameters, strict, …).
                flat.update(nested)
                normalized.append(flat)
                continue

            # Already-flat function tool or unknown shape: pass through.
            normalized.append(tool)
        return normalized

    def build_responses_request(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        options = self._apply_profile_defaults(kwargs)
        input_messages = messages
        if options.get("previous_response_id"):
            input_messages = self._select_continuation_messages(messages)
        options["input"] = self._map_messages_to_input(input_messages)
        # Normalize function tools from Chat Completions shape to Responses shape.
        if options.get("tools"):
            options["tools"] = self._normalize_tools_for_responses_request(options["tools"])
        # Default store to False.  Callers (or params.responses.store from the
        # YAML config) can set it explicitly.  Phase 2a WebSocket continuation
        # with store=False is valid and must not be overridden.
        options.setdefault("store", False)
        return options

    @staticmethod
    def sanitize_transport_payload(request: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(request)
        payload.pop("stream", None)
        payload.pop("background", None)
        return payload

    def normalize_output(self, response_dict: Dict[str, Any]) -> Tuple[NormalizedAssistantMessage, Optional[str]]:
        content_parts: List[str] = []
        reasoning_parts: List[str] = []
        sources: List[Dict[str, Any]] = []
        images: List[Dict[str, Any]] = []
        files: List[Dict[str, Any]] = []
        encrypted_content: Optional[str] = None
        tool_calls: List[NormalizedToolCall] = []
        hosted_tool_calls: List[Dict[str, Any]] = []
        assistant_phase: Optional[str] = None

        for item in response_dict.get("output") or []:
            item_dict = self._to_dict(item)
            item_type = item_dict.get("type")
            if item_type == "message" and item_dict.get("role") == "assistant":
                assistant_phase = assistant_phase or item_dict.get("status")
                for part in item_dict.get("content") or []:
                    part_dict = self._to_dict(part)
                    part_type = part_dict.get("type")
                    if part_type == "output_text":
                        content_parts.append(part_dict.get("text", ""))
                        for ann in part_dict.get("annotations") or []:
                            ann_dict = self._to_dict(ann)
                            if ann_dict:
                                sources.append(ann_dict)
                    elif part_type == "reasoning":
                        reasoning_text = part_dict.get("text") or ""
                        if not reasoning_text:
                            summary = part_dict.get("summary")
                            if isinstance(summary, list):
                                reasoning_text = " ".join(
                                    self._to_dict(chunk).get("text", "")
                                    for chunk in summary
                                    if self._to_dict(chunk).get("text")
                                )
                        if reasoning_text:
                            reasoning_parts.append(reasoning_text)
                    elif part_type == "output_image":
                        image: Dict[str, Any] = {}
                        if part_dict.get("file_id"):
                            image["file_id"] = part_dict["file_id"]
                        if part_dict.get("image_url"):
                            image["url"] = part_dict["image_url"]
                        if image:
                            images.append(image)
                    elif part_type == "output_file":
                        output_file: Dict[str, Any] = {}
                        if part_dict.get("file_id"):
                            output_file["file_id"] = part_dict["file_id"]
                        if part_dict.get("filename"):
                            output_file["filename"] = part_dict["filename"]
                        if output_file:
                            files.append(output_file)
                    elif part_type == "encrypted_content":
                        encrypted_content = part_dict.get("encrypted_content") or part_dict.get("text")
            elif item_type == "function_call":
                tool_calls.append(
                    NormalizedToolCall(
                        id=item_dict.get("call_id", ""),
                        type="function",
                        function=NormalizedToolFunction(
                            name=item_dict.get("name", ""),
                            arguments=item_dict.get("arguments", ""),
                        ),
                    )
                )
            elif item_type == "tool_search_call":
                call_id = item_dict.get("call_id") or item_dict.get("id") or ""
                payload = {k: v for k, v in item_dict.items() if k not in {"type", "call_id", "id"}}
                tool_calls.append(
                    NormalizedToolCall(
                        id=call_id,
                        type="tool_search",
                        function=NormalizedToolFunction(
                            name="tool_search",
                            arguments=json.dumps(payload),
                        ),
                        payload=payload,
                    )
                )
            elif item_type in ("web_search_call", "file_search_call"):
                # Hosted tool calls are informational — the model already
                # handled them. Keep canonical web-search sources in
                # assistant.sources and park the raw hosted call payload in
                # assistant.provider_extras for continuation/diagnostic fidelity.
                if item_type == "web_search_call":
                    action = self._to_dict(item_dict.get("action") or {})
                    for source in action.get("sources") or []:
                        source_dict = self._to_dict(source)
                        if source_dict and source_dict not in sources:
                            sources.append(source_dict)
                hosted_tool_calls.append(item_dict)

        if not content_parts and response_dict.get("output_text"):
            content_parts.append(self._coerce_text(response_dict.get("output_text")))
        encrypted_content = encrypted_content or response_dict.get("encrypted_content")

        provider_extras = None
        if hosted_tool_calls:
            provider_extras = {"hosted_tool_calls": hosted_tool_calls}

        message = NormalizedAssistantMessage(
            role="assistant",
            content="".join(content_parts) or None,
            reasoning="\n".join(reasoning_parts) or None,
            encrypted_content=encrypted_content,
            sources=sources,
            images=images,
            files=files,
            tool_calls=tool_calls,
            provider_extras=provider_extras,
        )
        return message, assistant_phase

    def normalize_completion(self, response: Any, request_kwargs: Dict[str, Any]) -> NormalizedCompletionResult:
        response_dict = self._to_dict(response)
        message, assistant_phase = self.normalize_output(response_dict)

        metadata = {
            "response_id": response_dict.get("id"),
            "previous_response_id": request_kwargs.get("previous_response_id"),
            "assistant_phase": assistant_phase,
            "provider_extras": {
                "status": response_dict.get("status"),
                "incomplete_details": response_dict.get("incomplete_details"),
                "output": response_dict.get("output"),
            },
        }

        return NormalizedCompletionResult(
            message=message,
            finish_reason=response_dict.get("status"),
            model=response_dict.get("model"),
            usage=response_dict.get("usage"),
            metadata=metadata,
        )
