import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .attachment_resolver import AttachmentResolver
from .responses_common import ResponsesNormalizationMixin
from .types import RuntimeErrorPayload, RuntimeStreamEvent, RuntimeTerminalMetadata

# Minimum SDK version string for clear error messages.
_SDK_VERSION_GUIDANCE = (
    "Responses WebSocket mode requires openai>=2.29.0 with websocket support. "
    "Upgrade OpenAI or install openai[realtime]."
)


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
    """Tracks a live SDK WebSocket connection and its lifecycle state."""

    mode: str
    # SDK connection objects returned by client.responses.connect().enter()
    sync_connection: Any = None
    async_connection: Any = None
    # Session-wide mutex so inherited sessions enforce a single in-flight call
    # across every adapter instance that references the same session.
    in_flight_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    connected_at: Optional[float] = None
    last_response_id: Optional[str] = None
    in_flight: bool = False
    last_store_value: Optional[bool] = None
    last_model: Optional[str] = None


class ResponsesWebSocketAdapter(ResponsesNormalizationMixin):
    """Runtime adapter for the OpenAI Responses API over WebSocket.

    Uses the official OpenAI Python SDK ``client.responses.connect()`` to
    establish a persistent WebSocket connection, then calls
    ``connection.response.create(...)`` for each turn.  This adapter does
    **not** manually build socket JSON or open raw WebSocket connections.
    """

    _GLOBAL_SESSIONS: List[ResponsesWebSocketSession] = []

    def __init__(self, ai_client, session: Optional[ResponsesWebSocketSession] = None):
        self.ai_client = ai_client
        self.attachment_resolver = AttachmentResolver(ai_client)
        self.session = session or ResponsesWebSocketSession(mode="inherit")
        if self.session not in self._GLOBAL_SESSIONS:
            self._GLOBAL_SESSIONS.append(self.session)

    # ------------------------------------------------------------------
    # SDK availability check
    # ------------------------------------------------------------------

    @staticmethod
    def _check_sdk_support(client) -> None:
        """Fail fast if the SDK does not expose ``responses.connect()``."""
        responses = getattr(client, "responses", None)
        connect = getattr(responses, "connect", None) if responses else None
        if not callable(connect):
            raise RuntimeError(_SDK_VERSION_GUIDANCE)

    # ------------------------------------------------------------------
    # Connection management – uses SDK context managers
    # ------------------------------------------------------------------

    def _get_sync_client(self):
        """Return the synchronous OpenAI client from the ai_client wrapper."""
        return getattr(self.ai_client, "client", None)

    def _get_async_client(self):
        """Return the asynchronous OpenAI client from the ai_client wrapper."""
        return getattr(self.ai_client, "aclient", None)

    def _connect_sync(self):
        """Return an active sync SDK connection, opening one if needed."""
        conn = self.session.sync_connection
        if conn is not None and self._sync_connection_is_usable(conn):
            return conn
        self._drop_sync_connection()
        client = self._get_sync_client()
        self._check_sdk_support(client)
        conn = client.responses.connect().enter()
        self.session.sync_connection = conn
        self.session.connected_at = time.time()
        return conn

    async def _connect_async(self):
        """Return an active async SDK connection, opening one if needed."""
        conn = self.session.async_connection
        if conn is not None and self._async_connection_is_usable(conn):
            return conn
        await self._drop_async_connection()
        aclient = self._get_async_client()
        self._check_sdk_support(aclient)
        conn = await aclient.responses.connect().enter()
        self.session.async_connection = conn
        self.session.connected_at = time.time()
        return conn

    @staticmethod
    def _sync_connection_is_usable(conn) -> bool:
        """Heuristic: check whether the underlying websocket is still open."""
        inner = getattr(conn, "_connection", None)
        if inner is None:
            return True
        # websockets sync connection exposes a .protocol with state
        protocol = getattr(inner, "protocol", None)
        if protocol is not None:
            state = getattr(protocol, "state", None)
            if state is not None and str(state).lower() in {"closed", "closing"}:
                return False
        return True

    @staticmethod
    def _async_connection_is_usable(conn) -> bool:
        """Heuristic: check whether the underlying async websocket is still open."""
        inner = getattr(conn, "_connection", None)
        if inner is None:
            return True
        closed = getattr(inner, "closed", None)
        if isinstance(closed, bool):
            return not closed
        protocol = getattr(inner, "protocol", None)
        if protocol is not None:
            state = getattr(protocol, "state", None)
            if state is not None and str(state).lower() in {"closed", "closing"}:
                return False
        return True

    def _drop_sync_connection(self):
        """Close and discard the current sync SDK connection."""
        conn = self.session.sync_connection
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        self.session.sync_connection = None
        self.session.connected_at = None

    async def _drop_async_connection(self):
        """Close and discard the current async SDK connection."""
        conn = self.session.async_connection
        if conn is not None:
            try:
                result = conn.close()
                if result is not None and hasattr(result, "__await__"):
                    await result
            except Exception:
                pass
        self.session.async_connection = None
        self.session.connected_at = None

    # ------------------------------------------------------------------
    # Session shutdown
    # ------------------------------------------------------------------

    @staticmethod
    def _close_async_connection_sync(conn):
        """Best-effort close of an async SDK connection from sync context."""
        if conn is None:
            return
        try:
            result = conn.close()
        except Exception:
            return
        if result is not None and hasattr(result, "__await__"):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(result)
                else:
                    loop.run_until_complete(result)
            except Exception:
                pass

    def close_session(self):
        with self.session.in_flight_lock:
            self._drop_sync_connection()
            self._close_async_connection_sync(self.session.async_connection)
            self.session.async_connection = None
            self.session.in_flight = False

    async def close_session_a(self):
        """Async variant that properly awaits connection teardown."""
        with self.session.in_flight_lock:
            self._drop_sync_connection()
            await self._drop_async_connection()
            self.session.in_flight = False

    @classmethod
    def close_all_sessions(cls):
        for session in list(cls._GLOBAL_SESSIONS):
            with session.in_flight_lock:
                conn = session.sync_connection
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                cls._close_async_connection_sync(session.async_connection)
                session.sync_connection = None
                session.async_connection = None
                session.in_flight = False
                session.connected_at = None
                session.last_response_id = None
        cls._GLOBAL_SESSIONS = []

    @classmethod
    async def close_all_sessions_a(cls):
        """Async variant of close_all_sessions."""
        for session in list(cls._GLOBAL_SESSIONS):
            with session.in_flight_lock:
                conn = session.sync_connection
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                async_conn = session.async_connection
                if async_conn is not None:
                    try:
                        result = async_conn.close()
                        if result is not None and hasattr(result, "__await__"):
                            await result
                    except Exception:
                        pass
                session.sync_connection = None
                session.async_connection = None
                session.in_flight = False
                session.connected_at = None
                session.last_response_id = None
        cls._GLOBAL_SESSIONS = []

    # ------------------------------------------------------------------
    # Error helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # In-flight guards
    # ------------------------------------------------------------------

    def _begin_in_flight(self):
        if self.session.in_flight:
            raise ResponsesSessionBusyError(
                "Responses WebSocket session already has an in-flight response. "
                "Use a separate chat or session='new'."
            )
        self.session.in_flight = True

    def _end_in_flight(self):
        self.session.in_flight = False

    # ------------------------------------------------------------------
    # Request building helpers
    # ------------------------------------------------------------------

    def _request_with_session(self, messages, kwargs, include_prev=True):
        """Build a Responses request, injecting session continuation state."""
        request_options = dict(kwargs)
        if include_prev and self.session.last_response_id and not request_options.get("previous_response_id"):
            request_options["previous_response_id"] = self.session.last_response_id
        return self.build_responses_request(messages, request_options)

    @staticmethod
    def _create_kwargs(request: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare kwargs for ``connection.response.create(...)``
        by stripping transport-only fields that should not be sent
        over the WebSocket event body.
        """
        kw = dict(request)
        kw.pop("stream", None)
        kw.pop("background", None)
        return kw

    # ------------------------------------------------------------------
    # SDK event mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _event_type(event) -> str:
        """Return the ``type`` string from an SDK event object."""
        return getattr(event, "type", "") or ""

    @staticmethod
    def _event_dict(event) -> Dict[str, Any]:
        """Convert an SDK event to a plain dict for metadata extraction."""
        if hasattr(event, "model_dump"):
            return event.model_dump()
        return {}

    # ------------------------------------------------------------------
    # Sync streaming over SDK connection
    # ------------------------------------------------------------------

    def _stream_sync_request(self, messages, kwargs, include_prev=True):
        """Send a request over the sync SDK connection and yield runtime events."""
        request_kwargs = self._request_with_session(messages, kwargs, include_prev=include_prev)
        create_kw = self._create_kwargs(request_kwargs)
        connection = self._connect_sync()

        try:
            connection.response.create(**create_kw)
        except Exception as exc:
            self._drop_sync_connection()
            raise ResponsesWebSocketTransportError(
                "socket_send_failed", code="socket_send_failed", retriable=True,
            ) from exc

        index = 0
        terminal_response = None
        try:
            for event in connection:
                etype = self._event_type(event)

                if etype == "response.output_text.delta":
                    yield RuntimeStreamEvent(
                        type="text_delta", index=index,
                        data={"text": getattr(event, "delta", "")},
                    )
                    index += 1

                elif etype == "response.output_item.done":
                    item = getattr(event, "item", None)
                    item_type = getattr(item, "type", "")
                    if item_type == "function_call":
                        # Emit the definitive tool call with the correct call_id.
                        # We deliberately skip response.function_call_arguments.delta
                        # events because they only carry item_id, not the call_id
                        # that the API requires for function_call_output matching.
                        yield RuntimeStreamEvent(
                            type="tool_call_delta", index=index,
                            data={
                                "tool_call": {
                                    "id": getattr(item, "call_id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": getattr(item, "name", ""),
                                        "arguments": getattr(item, "arguments", ""),
                                    },
                                }
                            },
                        )
                        index += 1

                elif etype == "response.completed":
                    resp = getattr(event, "response", None)
                    resp_dict = self._event_dict(resp) if resp else {}
                    terminal_response = resp_dict
                    usage = resp_dict.get("usage")
                    if usage:
                        yield RuntimeStreamEvent(type="usage", index=index, data={"usage": usage})
                        index += 1
                    output_text = ""
                    if resp is not None:
                        output_text = getattr(resp, "output_text", "") or ""
                    terminal = RuntimeTerminalMetadata(
                        finish_reason=resp_dict.get("status"),
                        model=resp_dict.get("model"),
                        usage=usage,
                        response_text=output_text,
                        metadata={"response_id": resp_dict.get("id")},
                    )
                    yield RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})
                    break

                elif etype in {"error", "response.failed"}:
                    if etype == "error":
                        code = getattr(event, "code", None) or "response_failed"
                        message = getattr(event, "message", None) or code
                    else:
                        resp = getattr(event, "response", None)
                        resp_err = getattr(resp, "error", None) if resp else None
                        code = getattr(resp_err, "code", None) or "response_failed"
                        message = getattr(resp_err, "message", None) or code
                    if code == "previous_response_not_found":
                        raise RuntimeError(code)
                    raise ResponsesWebSocketTransportError(
                        message,
                        code=("auth_error" if self._is_auth_error_code(code) else code),
                        retriable=not self._is_auth_error_code(code),
                        details={"provider_code": code},
                    )
                # Safely ignore all other lifecycle events (response.created,
                # response.in_progress, response.content_part.added, etc.)
        except RuntimeError:
            raise
        except Exception as exc:
            self._drop_sync_connection()
            raise ResponsesWebSocketTransportError(
                "socket_receive_failed", code="socket_receive_failed", retriable=True,
            ) from exc

        if terminal_response is None:
            self._drop_sync_connection()
            raise ResponsesWebSocketTransportError(
                "socket_receive_failed",
                code="socket_receive_failed",
                retriable=True,
                details={"reason": "stream_ended_before_response_completed"},
            )

        self.session.last_response_id = terminal_response.get("id")
        self.session.last_store_value = request_kwargs.get("store")
        self.session.last_model = request_kwargs.get("model")

    # ------------------------------------------------------------------
    # Async streaming over SDK connection
    # ------------------------------------------------------------------

    async def _stream_async_request(self, messages, kwargs, include_prev=True):
        """Send a request over the async SDK connection and yield runtime events."""
        request_kwargs = self._request_with_session(messages, kwargs, include_prev=include_prev)
        create_kw = self._create_kwargs(request_kwargs)
        connection = await self._connect_async()

        try:
            await connection.response.create(**create_kw)
        except Exception as exc:
            await self._drop_async_connection()
            raise ResponsesWebSocketTransportError(
                "socket_send_failed", code="socket_send_failed", retriable=True,
            ) from exc

        index = 0
        terminal_response = None
        try:
            async for event in connection:
                etype = self._event_type(event)

                if etype == "response.output_text.delta":
                    yield RuntimeStreamEvent(
                        type="text_delta", index=index,
                        data={"text": getattr(event, "delta", "")},
                    )
                    index += 1

                elif etype == "response.output_item.done":
                    item = getattr(event, "item", None)
                    item_type = getattr(item, "type", "")
                    if item_type == "function_call":
                        # Emit the definitive tool call with the correct call_id.
                        # We deliberately skip response.function_call_arguments.delta
                        # events because they only carry item_id, not the call_id
                        # that the API requires for function_call_output matching.
                        yield RuntimeStreamEvent(
                            type="tool_call_delta", index=index,
                            data={
                                "tool_call": {
                                    "id": getattr(item, "call_id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": getattr(item, "name", ""),
                                        "arguments": getattr(item, "arguments", ""),
                                    },
                                }
                            },
                        )
                        index += 1

                elif etype == "response.completed":
                    resp = getattr(event, "response", None)
                    resp_dict = self._event_dict(resp) if resp else {}
                    terminal_response = resp_dict
                    usage = resp_dict.get("usage")
                    if usage:
                        yield RuntimeStreamEvent(type="usage", index=index, data={"usage": usage})
                        index += 1
                    output_text = ""
                    if resp is not None:
                        output_text = getattr(resp, "output_text", "") or ""
                    terminal = RuntimeTerminalMetadata(
                        finish_reason=resp_dict.get("status"),
                        model=resp_dict.get("model"),
                        usage=usage,
                        response_text=output_text,
                        metadata={"response_id": resp_dict.get("id")},
                    )
                    yield RuntimeStreamEvent(type="completed", index=index, data={"terminal": terminal.__dict__})
                    break

                elif etype in {"error", "response.failed"}:
                    if etype == "error":
                        code = getattr(event, "code", None) or "response_failed"
                        message = getattr(event, "message", None) or code
                    else:
                        resp = getattr(event, "response", None)
                        resp_err = getattr(resp, "error", None) if resp else None
                        code = getattr(resp_err, "code", None) or "response_failed"
                        message = getattr(resp_err, "message", None) or code
                    if code == "previous_response_not_found":
                        raise RuntimeError(code)
                    raise ResponsesWebSocketTransportError(
                        message,
                        code=("auth_error" if self._is_auth_error_code(code) else code),
                        retriable=not self._is_auth_error_code(code),
                        details={"provider_code": code},
                    )
        except RuntimeError:
            raise
        except Exception as exc:
            await self._drop_async_connection()
            raise ResponsesWebSocketTransportError(
                "socket_receive_failed", code="socket_receive_failed", retriable=True,
            ) from exc

        if terminal_response is None:
            await self._drop_async_connection()
            raise ResponsesWebSocketTransportError(
                "socket_receive_failed",
                code="socket_receive_failed",
                retriable=True,
                details={"reason": "stream_ended_before_response_completed"},
            )

        self.session.last_response_id = terminal_response.get("id")
        self.session.last_store_value = request_kwargs.get("store")
        self.session.last_model = request_kwargs.get("model")

    # ------------------------------------------------------------------
    # Public streaming entry points with retry logic
    # ------------------------------------------------------------------

    def stream_completion(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = self.attachment_resolver.resolve_messages(messages)
        acquired_in_flight = False
        try:
            with self.session.in_flight_lock:
                self._begin_in_flight()
                acquired_in_flight = True
            retry_kwargs = dict(kwargs)
            include_prev = True
            reopened = False
            emitted_output = False
            while True:
                try:
                    for event in self._stream_sync_request(resolved, retry_kwargs, include_prev=include_prev):
                        if event.type in ("text_delta", "tool_call_delta"):
                            emitted_output = True
                        yield event
                    break
                except RuntimeError as exc:
                    if self._is_previous_response_not_found(exc) and include_prev and not emitted_output:
                        retry_kwargs.pop("previous_response_id", None)
                        include_prev = False
                        continue
                    if isinstance(exc, ResponsesWebSocketTransportError) and exc.retriable and not reopened and not emitted_output:
                        reopened = True
                        self._drop_sync_connection()
                        continue
                    raise
        except Exception as exc:
            payload = self._error_payload_from_exception(exc)
            yield RuntimeStreamEvent(type="error", index=0, data={"error": payload.__dict__})
        finally:
            if acquired_in_flight:
                self._end_in_flight()

    async def stream_completion_a(self, messages: List[Dict[str, Any]], **kwargs: Any):
        resolved = await self.attachment_resolver.resolve_messages_async(messages)
        acquired_in_flight = False
        try:
            with self.session.in_flight_lock:
                self._begin_in_flight()
                acquired_in_flight = True
            retry_kwargs = dict(kwargs)
            include_prev = True
            reopened = False
            emitted_output = False
            while True:
                try:
                    async for event in self._stream_async_request(resolved, retry_kwargs, include_prev=include_prev):
                        if event.type in ("text_delta", "tool_call_delta"):
                            emitted_output = True
                        yield event
                    break
                except RuntimeError as exc:
                    if self._is_previous_response_not_found(exc) and include_prev and not emitted_output:
                        retry_kwargs.pop("previous_response_id", None)
                        include_prev = False
                        continue
                    if isinstance(exc, ResponsesWebSocketTransportError) and exc.retriable and not reopened and not emitted_output:
                        reopened = True
                        await self._drop_async_connection()
                        continue
                    raise
        except Exception as exc:
            payload = self._error_payload_from_exception(exc)
            yield RuntimeStreamEvent(type="error", index=0, data={"error": payload.__dict__})
        finally:
            if acquired_in_flight:
                self._end_in_flight()

    # ------------------------------------------------------------------
    # Error re-raise helper for create_completion paths
    # ------------------------------------------------------------------

    @staticmethod
    def _raise_from_stream_error(error_dict: Dict[str, Any]):
        """Re-raise a structured error from a stream error event.

        Preserves the error taxonomy so that ``ask()`` / ``chat()`` callers
        see ``ResponsesSessionBusyError`` or ``ResponsesWebSocketTransportError``
        with full metadata instead of a generic ``RuntimeError``.
        """
        code = error_dict.get("code") or ""
        message = error_dict.get("message") or code or "streaming response failed"
        retriable = error_dict.get("retriable", True)
        details = error_dict.get("details")

        if code == "session_busy":
            raise ResponsesSessionBusyError(message)
        raise ResponsesWebSocketTransportError(
            message, code=code, retriable=retriable, details=details,
        )

    # ------------------------------------------------------------------
    # Non-streaming completion (consumes stream internally)
    # ------------------------------------------------------------------

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
            self._raise_from_stream_error(stream_error)
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
            self._raise_from_stream_error(stream_error)
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
