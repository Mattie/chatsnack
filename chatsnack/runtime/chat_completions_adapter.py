from typing import Any, Dict, List, Optional

from .types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
    NormalizedToolFunction,
    RuntimeErrorPayload,
    RuntimeStreamEvent,
    RuntimeTerminalMetadata,
)


class ChatCompletionsAdapter:
    # Keys that belong to the Responses API surface and must never reach
    # chat.completions.create().  Acts as a defensive backstop in case the
    # request-compilation layer accidentally leaks them.
    _RESPONSES_ONLY_KEYS = frozenset({
        "reasoning",
        "include",
        "store",
        "previous_response_id",
        "conversation",
        "text",
        "prompt_cache_key",
        "prompt_cache_retention",
        "input",
    })

    def __init__(self, ai_client):
        self.ai_client = ai_client

    @classmethod
    def _strip_responses_keys(cls, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Remove Responses-only keys so they never reach the CC SDK call."""
        return {k: v for k, v in kwargs.items() if k not in cls._RESPONSES_ONLY_KEYS}

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

    def _normalize_message(self, message: Any) -> NormalizedAssistantMessage:
        message_dict = self._to_dict(message)
        tool_calls = []
        for tc in message_dict.get("tool_calls") or []:
            tc_dict = self._to_dict(tc)
            function = self._to_dict(tc_dict.get("function") or {})
            tool_calls.append(
                NormalizedToolCall(
                    id=tc_dict.get("id", ""),
                    type=tc_dict.get("type", "function"),
                    function=NormalizedToolFunction(
                        name=function.get("name", ""),
                        arguments=function.get("arguments", ""),
                    ),
                )
            )
        return NormalizedAssistantMessage(
            role=message_dict.get("role", "assistant"),
            content=message_dict.get("content"),
            tool_calls=tool_calls,
        )

    def _normalize_completion(self, response: Any) -> NormalizedCompletionResult:
        response_dict = self._to_dict(response)
        raw_choices = response_dict.get("choices") or [{}]
        choice = self._to_dict(raw_choices[0]) if raw_choices else {}
        message = self._normalize_message(choice.get("message") or {})
        return NormalizedCompletionResult(
            message=message,
            finish_reason=choice.get("finish_reason"),
            model=response_dict.get("model"),
            usage=response_dict.get("usage"),
        )

    def create_completion(self, messages: List[Dict[str, Any]], **kwargs: Any) -> NormalizedCompletionResult:
        kwargs.pop("profile", None)
        kwargs = self._strip_responses_keys(kwargs)
        response = self.ai_client.client.chat.completions.create(messages=messages, **kwargs)
        return self._normalize_completion(response)

    async def create_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any) -> NormalizedCompletionResult:
        kwargs.pop("profile", None)
        kwargs = self._strip_responses_keys(kwargs)
        response = await self.ai_client.aclient.chat.completions.create(messages=messages, **kwargs)
        return self._normalize_completion(response)

    def _build_completed_event(self, index: int, text: str, finish_reason: Optional[str], model: Optional[str], usage: Optional[Dict[str, Any]]):
        terminal = RuntimeTerminalMetadata(
            finish_reason=finish_reason,
            model=model,
            usage=usage,
            response_text=text,
        )
        return RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})

    def _normalize_chunk_to_events(self, chunk: Any, index: int):
        events = []
        chunk_dict = self._to_dict(chunk)
        raw_choices = chunk_dict.get("choices") or [{}]
        choice = self._to_dict(raw_choices[0]) if raw_choices else {}
        delta = self._to_dict(choice.get("delta") or {})

        content = delta.get("content")
        if content is not None:
            events.append(RuntimeStreamEvent(type="text_delta", index=index, data={"text": content}))
            index += 1

        for tc in delta.get("tool_calls") or []:
            events.append(RuntimeStreamEvent(type="tool_call_delta", index=index, data={"tool_call": tc}))
            index += 1

        if chunk_dict.get("usage"):
            events.append(RuntimeStreamEvent(type="usage", index=index, data={"usage": chunk_dict.get("usage")}))
            index += 1

        return events, index, choice.get("finish_reason"), chunk_dict.get("model")

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        kwargs = kwargs.copy()
        kwargs.pop("profile", None)
        kwargs = self._strip_responses_keys(kwargs)
        kwargs["stream"] = True
        response_gen = self.ai_client.client.chat.completions.create(messages=messages, **kwargs)

        index = 0
        full_text = ""
        finish_reason = None
        model = None
        usage = None

        try:
            for chunk in response_gen:
                events, index, finish_reason, model = self._normalize_chunk_to_events(chunk, index)
                for event in events:
                    if event.type == "text_delta":
                        full_text += event.data.get("text", "")
                    if event.type == "usage":
                        usage = event.data.get("usage")
                    yield event
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc))
            yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
            return

        yield self._build_completed_event(index, full_text, finish_reason, model, usage)

    async def stream_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        kwargs = kwargs.copy()
        kwargs.pop("profile", None)
        kwargs = self._strip_responses_keys(kwargs)
        kwargs["stream"] = True
        response_gen = await self.ai_client.aclient.chat.completions.create(messages=messages, **kwargs)

        index = 0
        full_text = ""
        finish_reason = None
        model = None
        usage = None

        try:
            async for chunk in response_gen:
                events, index, finish_reason, model = self._normalize_chunk_to_events(chunk, index)
                for event in events:
                    if event.type == "text_delta":
                        full_text += event.data.get("text", "")
                    if event.type == "usage":
                        usage = event.data.get("usage")
                    yield event
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc))
            yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
            return

        yield self._build_completed_event(index, full_text, finish_reason, model, usage)
