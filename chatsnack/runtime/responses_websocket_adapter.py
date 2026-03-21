import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .responses_common import ResponsesNormalizationMixin
from .types import RuntimeErrorPayload, RuntimeStreamEvent, RuntimeTerminalMetadata


class ResponsesSessionBusyError(RuntimeError):
    """Raised when a shared session already has an in-flight response."""


@dataclass
class ResponsesWebSocketSession:
    mode: str
    sync_socket: Any = None
    async_socket: Any = None
    # Session-wide mutex so inherited sessions enforce a single in-flight call
    # across every adapter instance that references the same session.
    in_flight_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    connected_at: Optional[float] = None
    expires_at: Optional[float] = None
    last_response_id: Optional[str] = None
    in_flight: bool = False
    last_store_value: Optional[bool] = None
    last_model: Optional[str] = None


class ResponsesWebSocketAdapter(ResponsesNormalizationMixin):
    _GLOBAL_SESSIONS: List[ResponsesWebSocketSession] = []

    def __init__(self, ai_client, session: Optional[ResponsesWebSocketSession] = None):
        self.ai_client = ai_client
        self.session = session or ResponsesWebSocketSession(mode="inherit")
        if self.session not in self._GLOBAL_SESSIONS:
            self._GLOBAL_SESSIONS.append(self.session)

    @classmethod
    def close_all_sessions(cls):
        for session in list(cls._GLOBAL_SESSIONS):
            sync_sock = getattr(session, "sync_socket", None)
            if sync_sock is not None:
                try:
                    sync_sock.close()
                except Exception:
                    pass
            async_sock = getattr(session, "async_socket", None)
            if async_sock is not None:
                try:
                    async_sock.close()
                except Exception:
                    pass
            session.sync_socket = None
            session.async_socket = None
            session.in_flight = False
            session.connected_at = None
            session.expires_at = None
            session.last_response_id = None
        cls._GLOBAL_SESSIONS = []

    def close_session(self):
        sync_sock = getattr(self.session, "sync_socket", None)
        if sync_sock is not None:
            try:
                sync_sock.close()
            except Exception:
                pass
        async_sock = getattr(self.session, "async_socket", None)
        if async_sock is not None:
            try:
                async_sock.close()
            except Exception:
                pass
        self.session.sync_socket = None
        self.session.async_socket = None
        self.session.in_flight = False

    def _build_ws_url(self) -> str:
        base = getattr(self.ai_client, "base_url", None) or "https://api.openai.com/v1"
        if base.endswith("/"):
            base = base[:-1]
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base.replace('https://', 'wss://')}/v1/responses"

    def _connect_sync(self):
        if self.session.sync_socket is not None:
            return self.session.sync_socket
        import websocket

        headers = [f"Authorization: Bearer {self.ai_client.api_key}"] if getattr(self.ai_client, "api_key", None) else []
        ws = websocket.create_connection(self._build_ws_url(), header=headers)
        self.session.sync_socket = ws
        self.session.connected_at = time.time()
        self.session.expires_at = self.session.connected_at + 3600
        return ws

    async def _connect_async(self):
        if self.session.async_socket is not None:
            return self.session.async_socket
        import websockets

        headers = {"Authorization": f"Bearer {self.ai_client.api_key}"} if getattr(self.ai_client, "api_key", None) else {}
        ws = await websockets.connect(self._build_ws_url(), additional_headers=headers)
        self.session.async_socket = ws
        self.session.connected_at = time.time()
        self.session.expires_at = self.session.connected_at + 3600
        return ws

    def _begin_in_flight(self):
        if self.session.in_flight:
            raise ResponsesSessionBusyError(
                "Responses WebSocket session already has an in-flight response. Use a separate chat or session='new'."
            )
        self.session.in_flight = True

    def _end_in_flight(self):
        self.session.in_flight = False

    def _request_with_session(self, messages, kwargs, include_prev=True):
        request_options = dict(kwargs)
        if include_prev and self.session.last_response_id and not request_options.get("previous_response_id"):
            request_options["previous_response_id"] = self.session.last_response_id
        return self.build_responses_request(messages, request_options)

    def _stream_sync_request(self, messages, kwargs, include_prev=True):
        request_kwargs = self._request_with_session(messages, kwargs, include_prev=include_prev)
        payload = self.sanitize_transport_payload(request_kwargs)
        ws = self._connect_sync()
        ws.send(json.dumps({"type": "response.create", "response": payload}))

        index = 0
        terminal_response = None
        while True:
            event = json.loads(ws.recv())
            etype = event.get("type")
            if etype == "response.output_text.delta":
                yield RuntimeStreamEvent(type="text_delta", index=index, data={"text": event.get("delta", "")})
                index += 1
            elif etype == "response.function_call_arguments.delta":
                yield RuntimeStreamEvent(
                    type="tool_call_delta",
                    index=index,
                    data={
                        "tool_call": {
                            "id": event.get("call_id", ""),
                            "type": "function",
                            "function": {"name": event.get("name", ""), "arguments": event.get("delta", "")},
                        }
                    },
                )
                index += 1
            elif etype == "response.completed":
                terminal_response = event.get("response", {})
                usage = terminal_response.get("usage")
                if usage:
                    yield RuntimeStreamEvent(type="usage", index=index, data={"usage": usage})
                    index += 1
                terminal = RuntimeTerminalMetadata(
                    finish_reason=terminal_response.get("status"),
                    model=terminal_response.get("model"),
                    usage=usage,
                    response_text=(terminal_response.get("output_text") or ""),
                    metadata={"response_id": terminal_response.get("id")},
                )
                yield RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})
                break
            elif etype in {"error", "response.failed"}:
                err = event.get("error", {})
                raise RuntimeError(err.get("code") or err.get("message") or "response failed")

        self.session.last_response_id = (terminal_response or {}).get("id")
        self.session.last_store_value = request_kwargs.get("store")
        self.session.last_model = request_kwargs.get("model")

    async def _stream_async_request(self, messages, kwargs, include_prev=True):
        request_kwargs = self._request_with_session(messages, kwargs, include_prev=include_prev)
        payload = self.sanitize_transport_payload(request_kwargs)
        ws = await self._connect_async()
        await ws.send(json.dumps({"type": "response.create", "response": payload}))

        index = 0
        terminal_response = None
        while True:
            event = json.loads(await ws.recv())
            etype = event.get("type")
            if etype == "response.output_text.delta":
                yield RuntimeStreamEvent(type="text_delta", index=index, data={"text": event.get("delta", "")})
                index += 1
            elif etype == "response.function_call_arguments.delta":
                yield RuntimeStreamEvent(
                    type="tool_call_delta",
                    index=index,
                    data={
                        "tool_call": {
                            "id": event.get("call_id", ""),
                            "type": "function",
                            "function": {"name": event.get("name", ""), "arguments": event.get("delta", "")},
                        }
                    },
                )
                index += 1
            elif etype == "response.completed":
                terminal_response = event.get("response", {})
                usage = terminal_response.get("usage")
                if usage:
                    yield RuntimeStreamEvent(type="usage", index=index, data={"usage": usage})
                    index += 1
                terminal = RuntimeTerminalMetadata(
                    finish_reason=terminal_response.get("status"),
                    model=terminal_response.get("model"),
                    usage=usage,
                    response_text=(terminal_response.get("output_text") or ""),
                    metadata={"response_id": terminal_response.get("id")},
                )
                yield RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})
                break
            elif etype in {"error", "response.failed"}:
                err = event.get("error", {})
                raise RuntimeError(err.get("code") or err.get("message") or "response failed")

        self.session.last_response_id = (terminal_response or {}).get("id")
        self.session.last_store_value = request_kwargs.get("store")
        self.session.last_model = request_kwargs.get("model")

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        acquired_in_flight = False
        try:
            with self.session.in_flight_lock:
                self._begin_in_flight()
                acquired_in_flight = True
            try:
                yield from self._stream_sync_request(messages, kwargs, include_prev=True)
            except RuntimeError as exc:
                if "previous_response_not_found" in str(exc):
                    retry_kwargs = dict(kwargs)
                    retry_kwargs.pop("previous_response_id", None)
                    yield from self._stream_sync_request(messages, retry_kwargs, include_prev=False)
                else:
                    raise
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc), code="transport_error", retriable=True)
            yield RuntimeStreamEvent(type="error", index=0, data={"error": payload.__dict__})
        finally:
            if acquired_in_flight:
                self._end_in_flight()

    async def stream_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        acquired_in_flight = False
        try:
            with self.session.in_flight_lock:
                self._begin_in_flight()
                acquired_in_flight = True
            try:
                async for event in self._stream_async_request(messages, kwargs, include_prev=True):
                    yield event
            except RuntimeError as exc:
                if "previous_response_not_found" in str(exc):
                    retry_kwargs = dict(kwargs)
                    retry_kwargs.pop("previous_response_id", None)
                    async for event in self._stream_async_request(messages, retry_kwargs, include_prev=False):
                        yield event
                else:
                    raise
        except Exception as exc:
            payload = RuntimeErrorPayload(message=str(exc), code="transport_error", retriable=True)
            yield RuntimeStreamEvent(type="error", index=0, data={"error": payload.__dict__})
        finally:
            if acquired_in_flight:
                self._end_in_flight()

    def create_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        terminal = None
        response_text_parts: List[str] = []
        tool_calls_by_id: Dict[str, Dict[str, Any]] = {}
        stream_error: Optional[Dict[str, Any]] = None
        for event in self.stream_completion(messages, **kwargs):
            if event.type == "text_delta":
                response_text_parts.append(event.data.get("text", ""))
            elif event.type == "tool_call_delta":
                tool_call = event.data.get("tool_call", {})
                call_id = tool_call.get("id", "")
                function = tool_call.get("function", {})
                existing = tool_calls_by_id.setdefault(
                    call_id,
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": function.get("name", ""),
                        "arguments": "",
                    },
                )
                if function.get("name"):
                    existing["name"] = function.get("name")
                existing["arguments"] += function.get("arguments", "")
            elif event.type == "error":
                stream_error = event.data.get("error", {})
            elif event.type == "completed":
                terminal = event.data.get("terminal", {})
        if stream_error:
            raise RuntimeError(stream_error.get("code") or stream_error.get("message") or "streaming response failed")
        response_text = (terminal or {}).get("response_text")
        if not response_text:
            response_text = "".join(response_text_parts)
        response_dict = {
            "id": (terminal or {}).get("metadata", {}).get("response_id") or self.session.last_response_id,
            "status": (terminal or {}).get("finish_reason"),
            "model": (terminal or {}).get("model"),
            "usage": (terminal or {}).get("usage"),
            "output_text": response_text or "",
            "output": [],
        }
        if response_text:
            response_dict["output"].append(
                {
                    "type": "message",
                    "role": "assistant",
                    "status": (terminal or {}).get("finish_reason"),
                    "content": [{"type": "output_text", "text": response_text}],
                }
            )
        response_dict["output"].extend(tool_calls_by_id.values())
        return self.normalize_completion(response_dict, kwargs)

    async def create_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        terminal = None
        response_text_parts: List[str] = []
        tool_calls_by_id: Dict[str, Dict[str, Any]] = {}
        stream_error: Optional[Dict[str, Any]] = None
        async for event in self.stream_completion_a(messages, **kwargs):
            if event.type == "text_delta":
                response_text_parts.append(event.data.get("text", ""))
            elif event.type == "tool_call_delta":
                tool_call = event.data.get("tool_call", {})
                call_id = tool_call.get("id", "")
                function = tool_call.get("function", {})
                existing = tool_calls_by_id.setdefault(
                    call_id,
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": function.get("name", ""),
                        "arguments": "",
                    },
                )
                if function.get("name"):
                    existing["name"] = function.get("name")
                existing["arguments"] += function.get("arguments", "")
            elif event.type == "error":
                stream_error = event.data.get("error", {})
            elif event.type == "completed":
                terminal = event.data.get("terminal", {})
        if stream_error:
            raise RuntimeError(stream_error.get("code") or stream_error.get("message") or "streaming response failed")
        response_text = (terminal or {}).get("response_text")
        if not response_text:
            response_text = "".join(response_text_parts)
        response_dict = {
            "id": (terminal or {}).get("metadata", {}).get("response_id") or self.session.last_response_id,
            "status": (terminal or {}).get("finish_reason"),
            "model": (terminal or {}).get("model"),
            "usage": (terminal or {}).get("usage"),
            "output_text": response_text or "",
            "output": [],
        }
        if response_text:
            response_dict["output"].append(
                {
                    "type": "message",
                    "role": "assistant",
                    "status": (terminal or {}).get("finish_reason"),
                    "content": [{"type": "output_text", "text": response_text}],
                }
            )
        response_dict["output"].extend(tool_calls_by_id.values())
        return self.normalize_completion(response_dict, kwargs)
