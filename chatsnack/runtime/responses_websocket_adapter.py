import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .responses_common import ResponsesNormalizationMixin
from .types import RuntimeErrorPayload, RuntimeStreamEvent, RuntimeTerminalMetadata


class ResponsesSessionBusyError(RuntimeError):
    """Raised when a shared session already has an in-flight response."""


class ResponsesWebSocketTransportError(RuntimeError):
    """Transport-level websocket error with retry classification metadata."""

    def __init__(self, message: str, *, code: str = "transport_error", retriable: bool = True, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.retriable = retriable
        self.details = details or {}


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
            with session.in_flight_lock:
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
        with self.session.in_flight_lock:
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
        if self.session.sync_socket is not None and not self._socket_expired() and self._sync_socket_is_usable(self.session.sync_socket):
            return self.session.sync_socket
        self._drop_sync_socket()
        import websocket

        headers = [f"Authorization: Bearer {self.ai_client.api_key}"] if getattr(self.ai_client, "api_key", None) else []
        ws = websocket.create_connection(self._build_ws_url(), header=headers)
        self.session.sync_socket = ws
        self.session.connected_at = time.time()
        self.session.expires_at = self.session.connected_at + 3600
        return ws

    async def _connect_async(self):
        if self.session.async_socket is not None and not self._socket_expired() and self._async_socket_is_usable(self.session.async_socket):
            return self.session.async_socket
        await self._drop_async_socket()
        import websockets

        headers = {"Authorization": f"Bearer {self.ai_client.api_key}"} if getattr(self.ai_client, "api_key", None) else {}
        ws = await websockets.connect(self._build_ws_url(), additional_headers=headers)
        self.session.async_socket = ws
        self.session.connected_at = time.time()
        self.session.expires_at = self.session.connected_at + 3600
        return ws

    def _socket_expired(self) -> bool:
        expires_at = getattr(self.session, "expires_at", None)
        return bool(expires_at and expires_at <= time.time())

    @staticmethod
    def _sync_socket_is_usable(sock: Any) -> bool:
        connected = getattr(sock, "connected", None)
        if connected is False:
            return False
        closed = getattr(sock, "closed", None)
        if closed is True:
            return False
        return True

    @staticmethod
    def _async_socket_is_usable(sock: Any) -> bool:
        closed = getattr(sock, "closed", None)
        if isinstance(closed, bool):
            return not closed
        state = getattr(sock, "state", None)
        if state is None:
            return True
        return str(state).lower() not in {"closed", "closing"}

    def _drop_sync_socket(self):
        sync_sock = getattr(self.session, "sync_socket", None)
        if sync_sock is not None:
            try:
                sync_sock.close()
            except Exception:
                pass
        self.session.sync_socket = None
        self.session.connected_at = None
        self.session.expires_at = None

    async def _drop_async_socket(self):
        async_sock = getattr(self.session, "async_socket", None)
        if async_sock is not None:
            try:
                maybe = async_sock.close()
                if hasattr(maybe, "__await__"):
                    await maybe
            except Exception:
                pass
        self.session.async_socket = None
        self.session.connected_at = None
        self.session.expires_at = None

    @staticmethod
    def _is_previous_response_not_found(exc: Exception) -> bool:
        return "previous_response_not_found" in str(exc)

    @staticmethod
    def _is_auth_error_code(code: Optional[str]) -> bool:
        return (code or "").lower() in {"authentication_error", "unauthorized", "invalid_api_key"}

    @classmethod
    def _error_payload_from_exception(cls, exc: Exception) -> RuntimeErrorPayload:
        if isinstance(exc, ResponsesSessionBusyError):
            return RuntimeErrorPayload(message=str(exc), code="session_busy", retriable=False, details={"category": "concurrency"})
        if isinstance(exc, ResponsesWebSocketTransportError):
            return RuntimeErrorPayload(message=str(exc), code=exc.code, retriable=exc.retriable, details=exc.details or None)
        if cls._is_previous_response_not_found(exc):
            return RuntimeErrorPayload(message=str(exc), code="previous_response_not_found", retriable=True)
        return RuntimeErrorPayload(message=str(exc), code="transport_error", retriable=True)

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
        try:
            ws.send(json.dumps({"type": "response.create", "response": payload}))
        except Exception as exc:
            self._drop_sync_socket()
            raise ResponsesWebSocketTransportError("socket_send_failed", code="socket_send_failed", retriable=True) from exc

        index = 0
        terminal_response = None
        while True:
            try:
                event = json.loads(ws.recv())
            except Exception as exc:
                self._drop_sync_socket()
                raise ResponsesWebSocketTransportError("socket_receive_failed", code="socket_receive_failed", retriable=True) from exc
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
                code = err.get("code") or "response_failed"
                message = err.get("message") or code
                if code == "previous_response_not_found":
                    raise RuntimeError(code)
                raise ResponsesWebSocketTransportError(
                    message,
                    code=("auth_error" if self._is_auth_error_code(code) else code),
                    retriable=not self._is_auth_error_code(code),
                    details={"provider_code": code},
                )

        self.session.last_response_id = (terminal_response or {}).get("id")
        self.session.last_store_value = request_kwargs.get("store")
        self.session.last_model = request_kwargs.get("model")

    async def _stream_async_request(self, messages, kwargs, include_prev=True):
        request_kwargs = self._request_with_session(messages, kwargs, include_prev=include_prev)
        payload = self.sanitize_transport_payload(request_kwargs)
        ws = await self._connect_async()
        try:
            await ws.send(json.dumps({"type": "response.create", "response": payload}))
        except Exception as exc:
            await self._drop_async_socket()
            raise ResponsesWebSocketTransportError("socket_send_failed", code="socket_send_failed", retriable=True) from exc

        index = 0
        terminal_response = None
        while True:
            try:
                event = json.loads(await ws.recv())
            except Exception as exc:
                await self._drop_async_socket()
                raise ResponsesWebSocketTransportError("socket_receive_failed", code="socket_receive_failed", retriable=True) from exc
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
                code = err.get("code") or "response_failed"
                message = err.get("message") or code
                if code == "previous_response_not_found":
                    raise RuntimeError(code)
                raise ResponsesWebSocketTransportError(
                    message,
                    code=("auth_error" if self._is_auth_error_code(code) else code),
                    retriable=not self._is_auth_error_code(code),
                    details={"provider_code": code},
                )

        self.session.last_response_id = (terminal_response or {}).get("id")
        self.session.last_store_value = request_kwargs.get("store")
        self.session.last_model = request_kwargs.get("model")

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        acquired_in_flight = False
        try:
            with self.session.in_flight_lock:
                self._begin_in_flight()
                acquired_in_flight = True
            retry_kwargs = dict(kwargs)
            include_prev = True
            reopened = False
            while True:
                try:
                    yield from self._stream_sync_request(messages, retry_kwargs, include_prev=include_prev)
                    break
                except RuntimeError as exc:
                    if self._is_previous_response_not_found(exc) and include_prev:
                        retry_kwargs.pop("previous_response_id", None)
                        include_prev = False
                        continue
                    if isinstance(exc, ResponsesWebSocketTransportError) and exc.retriable and not reopened:
                        reopened = True
                        self._drop_sync_socket()
                        continue
                    raise
        except Exception as exc:
            payload = self._error_payload_from_exception(exc)
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
            retry_kwargs = dict(kwargs)
            include_prev = True
            reopened = False
            while True:
                try:
                    async for event in self._stream_async_request(messages, retry_kwargs, include_prev=include_prev):
                        yield event
                    break
                except RuntimeError as exc:
                    if self._is_previous_response_not_found(exc) and include_prev:
                        retry_kwargs.pop("previous_response_id", None)
                        include_prev = False
                        continue
                    if isinstance(exc, ResponsesWebSocketTransportError) and exc.retriable and not reopened:
                        reopened = True
                        await self._drop_async_socket()
                        continue
                    raise
        except Exception as exc:
            payload = self._error_payload_from_exception(exc)
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
