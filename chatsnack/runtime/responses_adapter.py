from typing import Any, Dict, List

from .attachment_resolver import AttachmentResolver
from .responses_common import ResponsesNormalizationMixin
from .types import RuntimeErrorPayload, RuntimeStreamEvent, RuntimeTerminalMetadata


class ResponsesAdapter(ResponsesNormalizationMixin):
    """Runtime adapter for the OpenAI Responses API over HTTP."""

    def __init__(self, ai_client):
        self.ai_client = ai_client
        self.attachment_resolver = AttachmentResolver(ai_client)

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
            f"`{endpoint}`. Inject a compatible OpenAI client (openai>=2.29.0) "
            "or select the chat_completions runtime."
        )

    def create_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = self.attachment_resolver.resolve_messages(messages)
        request_kwargs = self.build_responses_request(resolved, kwargs)
        response = self._get_responses_create(async_mode=False)(**request_kwargs)
        return self.normalize_completion(response, request_kwargs)

    async def create_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = await self.attachment_resolver.resolve_messages_async(messages)
        request_kwargs = self.build_responses_request(resolved, kwargs)
        response = await self._get_responses_create(async_mode=True)(**request_kwargs)
        return self.normalize_completion(response, request_kwargs)

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
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
