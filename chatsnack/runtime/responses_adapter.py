from typing import Any, Dict, List, Optional, Tuple

from .types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
    NormalizedToolFunction,
    RuntimeErrorPayload,
    RuntimeStreamEvent,
    RuntimeTerminalMetadata,
)


class ResponsesAdapter:
    """Runtime adapter for the OpenAI Responses API."""

    def __init__(self, ai_client):
        self.ai_client = ai_client

    def _get_responses_create(self, *, async_mode: bool = False):
        client_name = "aclient" if async_mode else "client"
        client = getattr(self.ai_client, client_name, None)
        responses = getattr(client, "responses", None) if client is not None else None
        create = getattr(responses, "create", None) if responses is not None else None
        if callable(create):
            return create

        endpoint = f"{client_name}.responses.create"
        raise RuntimeError(
            "ResponsesAdapter requires an ai_client exposing "
            f"`{endpoint}`. Inject a compatible OpenAI client (openai>=1.66.0) "
            "or select the chat_completions runtime."
        )

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

        text_type = "input_text"
        return [
            {
                "type": "message",
                "role": role,
                "content": [{"type": text_type, "text": self._coerce_text(content)}],
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
        """Select incremental input for `previous_response_id` continuations.

        When continuing from a previous response id, the Responses API already
        has prior context. Sending the full replay (especially assistant
        messages rendered as input_text) can be rejected by the API.
        We therefore send only the suffix after the most recent assistant turn.
        """
        if not messages:
            return messages

        last_assistant_idx = -1
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "assistant":
                last_assistant_idx = idx
                break

        if last_assistant_idx == -1:
            # No assistant turn found – send all messages so that multi-message
            # incremental inputs (e.g. developer + user) are preserved.
            return messages

        suffix = messages[last_assistant_idx + 1 :]
        return suffix or [messages[-1]]

    def _build_responses_kwargs(self, messages: List[Dict[str, Any]], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        options = self._apply_profile_defaults(kwargs)
        input_messages = messages
        if options.get("previous_response_id"):
            input_messages = self._select_continuation_messages(messages)
        options["input"] = self._map_messages_to_input(input_messages)
        if options.get("previous_response_id") and "store" not in options:
            options["store"] = True
        else:
            options.setdefault("store", False)
        return options

    def _normalize_output(self, response_dict: Dict[str, Any]) -> Tuple[NormalizedAssistantMessage, Optional[str]]:
        content_parts: List[str] = []
        tool_calls: List[NormalizedToolCall] = []
        assistant_phase: Optional[str] = None

        for item in response_dict.get("output") or []:
            item_dict = self._to_dict(item)
            item_type = item_dict.get("type")
            if item_type == "message" and item_dict.get("role") == "assistant":
                assistant_phase = assistant_phase or item_dict.get("status")
                for part in item_dict.get("content") or []:
                    part_dict = self._to_dict(part)
                    if part_dict.get("type") == "output_text":
                        content_parts.append(part_dict.get("text", ""))
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

        if not content_parts and response_dict.get("output_text"):
            content_parts.append(self._coerce_text(response_dict.get("output_text")))

        message = NormalizedAssistantMessage(
            role="assistant",
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
        )
        return message, assistant_phase

    def _normalize_completion(self, response: Any, request_kwargs: Dict[str, Any]) -> NormalizedCompletionResult:
        response_dict = self._to_dict(response)
        message, assistant_phase = self._normalize_output(response_dict)

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

    def create_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> NormalizedCompletionResult:
        request_kwargs = self._build_responses_kwargs(messages, kwargs)
        response = self._get_responses_create(async_mode=False)(**request_kwargs)
        return self._normalize_completion(response, request_kwargs)

    async def create_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any) -> NormalizedCompletionResult:
        request_kwargs = self._build_responses_kwargs(messages, kwargs)
        response = await self._get_responses_create(async_mode=True)(**request_kwargs)
        return self._normalize_completion(response, request_kwargs)

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        """Compatibility shim over non-stream Responses requests; not true provider streaming."""
        index = 0
        try:
            result = self.create_completion(messages, **kwargs)
            text = result.message.content or ""
            if text:
                yield RuntimeStreamEvent(type="text_delta", index=index, data={"text": text})
                index += 1
            for tool_call in result.message.tool_calls:
                yield RuntimeStreamEvent(type="tool_call_delta", index=index, data={"tool_call": tool_call.__dict__})
                index += 1
            if result.usage:
                yield RuntimeStreamEvent(type="usage", index=index, data={"usage": result.usage})
                index += 1
            terminal = RuntimeTerminalMetadata(
                finish_reason=result.finish_reason,
                model=result.model,
                usage=result.usage,
                response_text=text,
                metadata=result.metadata,
            )
            yield RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc))
            yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})

    async def stream_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        """Compatibility shim over non-stream Responses requests; not true provider streaming."""
        index = 0
        try:
            result = await self.create_completion_a(messages, **kwargs)
            text = result.message.content or ""
            if text:
                yield RuntimeStreamEvent(type="text_delta", index=index, data={"text": text})
                index += 1
            for tool_call in result.message.tool_calls:
                yield RuntimeStreamEvent(type="tool_call_delta", index=index, data={"tool_call": tool_call.__dict__})
                index += 1
            if result.usage:
                yield RuntimeStreamEvent(type="usage", index=index, data={"usage": result.usage})
                index += 1
            terminal = RuntimeTerminalMetadata(
                finish_reason=result.finish_reason,
                model=result.model,
                usage=result.usage,
                response_text=text,
                metadata=result.metadata,
            )
            yield RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc))
            yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
