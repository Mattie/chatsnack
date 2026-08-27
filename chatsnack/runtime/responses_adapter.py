import inspect
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
            f"`{endpoint}`. Inject a compatible OpenAI client (openai>=3.5.0) "
            "or select the chat_completions runtime."
        )

    @staticmethod
    def _prepare_sdk_create_kwargs(create, request_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Route provider extensions through the SDK's ``extra_body`` escape hatch."""
        try:
            parameters = inspect.signature(create).parameters
        except (TypeError, ValueError):
            return request_kwargs
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return request_kwargs

        prepared = dict(request_kwargs)
        extensions = dict(prepared.get("extra_body") or {})
        for key in list(prepared):
            if key not in parameters:
                extensions[key] = prepared.pop(key)
        if extensions:
            prepared["extra_body"] = extensions
        return prepared

    def create_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = self.attachment_resolver.resolve_messages(messages)
        request_kwargs = self.build_responses_request(resolved, kwargs)
        self._debug_responses_payload("Responses HTTP create payload", request_kwargs)
        create = self._get_responses_create(async_mode=False)
        response = create(**self._prepare_sdk_create_kwargs(create, request_kwargs))
        return self.normalize_completion(response, request_kwargs)

    async def create_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = await self.attachment_resolver.resolve_messages_async(messages)
        request_kwargs = self.build_responses_request(resolved, kwargs)
        self._debug_responses_payload("Responses HTTP create payload", request_kwargs)
        create = self._get_responses_create(async_mode=True)
        response = await create(**self._prepare_sdk_create_kwargs(create, request_kwargs))
        return self.normalize_completion(response, request_kwargs)

    @staticmethod
    def _event_type(event: Any) -> str:
        if isinstance(event, dict):
            return str(event.get("type") or "")
        direct = getattr(event, "type", "")
        if direct:
            return str(direct)
        if hasattr(event, "model_dump"):
            return str((event.model_dump() or {}).get("type") or "")
        return ""

    def _stream_event_data(self, event: Any) -> Dict[str, Any]:
        return self._to_dict(event)

    @staticmethod
    def _stream_error_message(event_data: Dict[str, Any]) -> str:
        error = event_data.get("error") or {}
        if not isinstance(error, dict):
            error = ResponsesAdapter._to_dict(error)
        response = event_data.get("response") or {}
        if not isinstance(response, dict):
            response = ResponsesAdapter._to_dict(response)
        response_error = response.get("error") or response.get("incomplete_details") or {}
        if not isinstance(response_error, dict):
            response_error = ResponsesAdapter._to_dict(response_error)
        return (
            event_data.get("message")
            or error.get("message")
            or response_error.get("message")
            or response_error.get("reason")
            or "Responses stream failed"
        )

    def _normalize_stream_event(
        self,
        sdk_event: Any,
        *,
        index: int,
        request_kwargs: Dict[str, Any],
        full_text: str,
        tool_call_state: Dict[str, Dict[str, Any]],
    ):
        """Normalize one SDK SSE event and return events plus terminal state."""
        event_type = self._event_type(sdk_event)
        event_data = self._stream_event_data(sdk_event)
        events = []
        completed = False
        failed = False

        if event_type in {
            "response.output_text.delta",
            "response.content_part.delta",
        }:
            part = self._to_dict(event_data.get("part") or {})
            delta = event_data.get("delta") or part.get("text") or ""
            if delta:
                full_text += str(delta)
                events.append(
                    RuntimeStreamEvent(type="text_delta", index=index, data={"text": str(delta)})
                )
                index += 1
        elif event_type == "response.output_item.added":
            item = self._to_dict(event_data.get("item") or {})
            if item.get("type") == "function_call":
                item_id = item.get("id") or event_data.get("item_id") or ""
                tool_call_state[item_id] = {
                    "call_id": item.get("call_id") or "",
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "",
                    "emitted": False,
                }
        elif event_type == "response.function_call_arguments.delta":
            item_id = event_data.get("item_id") or event_data.get("call_id") or ""
            state = tool_call_state.setdefault(
                item_id,
                {"call_id": "", "name": "", "arguments": "", "emitted": False},
            )
            state["call_id"] = state["call_id"] or event_data.get("call_id") or ""
            state["name"] = state["name"] or event_data.get("name") or ""
            delta = event_data.get("delta") or ""
            state["arguments"] += delta
            if state["call_id"] and delta:
                events.append(
                    RuntimeStreamEvent(
                        type="tool_call_delta",
                        index=index,
                        data={
                            "tool_call": {
                                "id": state["call_id"],
                                "type": "function",
                                "function": {
                                    "name": state["name"],
                                    "arguments": delta,
                                },
                            }
                        },
                    )
                )
                state["emitted"] = True
                index += 1
        elif event_type == "response.output_item.done":
            item = self._to_dict(event_data.get("item") or {})
            if item.get("type") == "function_call":
                item_id = item.get("id") or event_data.get("item_id") or ""
                state = tool_call_state.pop(item_id, None)
                if not state or not state.get("emitted"):
                    events.append(
                        RuntimeStreamEvent(
                            type="tool_call_delta",
                            index=index,
                            data={
                                "tool_call": {
                                    "id": item.get("call_id") or item_id,
                                    "type": "function",
                                    "function": {
                                        "name": item.get("name")
                                        or (state or {}).get("name")
                                        or "",
                                        "arguments": item.get("arguments")
                                        or (state or {}).get("arguments")
                                        or "",
                                    },
                                }
                            },
                        )
                    )
                    index += 1
        elif event_type in {
            "response.completed",
            "response.done",
            "response.incomplete",
        }:
            response = event_data.get("response")
            normalized = self.normalize_completion(response, request_kwargs)
            if not full_text and normalized.message.content:
                full_text = normalized.message.content
                events.append(
                    RuntimeStreamEvent(
                        type="text_delta",
                        index=index,
                        data={"text": full_text},
                    )
                )
                index += 1
            if normalized.usage:
                events.append(
                    RuntimeStreamEvent(
                        type="usage",
                        index=index,
                        data={"usage": normalized.usage},
                    )
                )
                index += 1
            terminal = RuntimeTerminalMetadata(
                finish_reason=normalized.finish_reason,
                model=normalized.model,
                usage=normalized.usage,
                response_text=full_text,
                metadata=normalized.metadata,
            )
            events.append(
                RuntimeStreamEvent(
                    type="completed",
                    index=index,
                    data={"terminal": terminal.__dict__},
                )
            )
            index += 1
            completed = True
        elif event_type in {
            "error",
            "response.error",
            "response.failed",
        }:
            payload = RuntimeErrorPayload(message=self._stream_error_message(event_data))
            events.append(
                RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
            )
            index += 1
            failed = True

        return events, index, full_text, completed, failed

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = self.attachment_resolver.resolve_messages(messages)
        request_kwargs = self.build_responses_request(resolved, kwargs)
        request_kwargs["stream"] = True
        self._debug_responses_payload("Responses HTTP SSE create payload", request_kwargs)
        stream = None
        index = 0
        full_text = ""
        terminal_seen = False
        tool_call_state: Dict[str, Dict[str, Any]] = {}
        try:
            create = self._get_responses_create(async_mode=False)
            stream = create(**self._prepare_sdk_create_kwargs(create, request_kwargs))
            for sdk_event in stream:
                if terminal_seen:
                    continue
                events, index, full_text, completed, failed = self._normalize_stream_event(
                    sdk_event,
                    index=index,
                    request_kwargs=request_kwargs,
                    full_text=full_text,
                    tool_call_state=tool_call_state,
                )
                yield from events
                if completed or failed:
                    terminal_seen = True
                    break
            if not terminal_seen:
                payload = RuntimeErrorPayload(message="Responses stream ended before a terminal event.")
                yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc))
            yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

    async def stream_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = await self.attachment_resolver.resolve_messages_async(messages)
        request_kwargs = self.build_responses_request(resolved, kwargs)
        request_kwargs["stream"] = True
        self._debug_responses_payload("Responses HTTP SSE create payload", request_kwargs)
        stream = None
        stream_iterator = None
        index = 0
        full_text = ""
        terminal_seen = False
        tool_call_state: Dict[str, Dict[str, Any]] = {}
        try:
            create = self._get_responses_create(async_mode=True)
            stream = await create(**self._prepare_sdk_create_kwargs(create, request_kwargs))
            stream_iterator = stream.__aiter__()
            async for sdk_event in stream_iterator:
                if terminal_seen:
                    continue
                events, index, full_text, completed, failed = self._normalize_stream_event(
                    sdk_event,
                    index=index,
                    request_kwargs=request_kwargs,
                    full_text=full_text,
                    tool_call_state=tool_call_state,
                )
                for event in events:
                    yield event
                if completed or failed:
                    terminal_seen = True
                    break
            if not terminal_seen:
                payload = RuntimeErrorPayload(message="Responses stream ended before a terminal event.")
                yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc))
            yield RuntimeStreamEvent(type="error", index=index, data={"error": payload.__dict__})
        finally:
            closed_iterators = set()
            for iterator in (stream_iterator, getattr(stream, "_iterator", None)):
                if iterator is None or id(iterator) in closed_iterators:
                    continue
                closed_iterators.add(id(iterator))
                close_iterator = getattr(iterator, "aclose", None)
                if callable(close_iterator):
                    try:
                        await close_iterator()
                    except Exception:
                        pass
            aclose = getattr(stream, "aclose", None)
            if callable(aclose):
                await aclose()
            else:
                close = getattr(stream, "close", None)
                if callable(close):
                    result = close()
                    if inspect.isawaitable(result):
                        await result
