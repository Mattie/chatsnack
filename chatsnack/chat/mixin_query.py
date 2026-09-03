import asyncio
import copy
import json
import uuid
import warnings
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from ..assets import capture_asset
from ..asynchelpers import _gather_cancel_on_error, aformatter
from ..fillings import (
    FillingError,
    _filling_resolution_active,
    active_filling_stash,
    filling_machine,
)
from ..runtime import ApplyPatchCall, EVENT_SCHEMA_VERSION, ResponsesWebSocketAdapter
from ..runtime.attachment_inputs import normalize_attachment_inputs

from .mixin_messages import ChatMessagesMixin
from .mixin_params import (
    ChatParamsMixin,
    DEFAULT_MODEL_FALLBACK,
    _resolve_auto_feed_limit,
)


_active_template_vars = ContextVar(
    "chatsnack_active_query_template_vars",
    default=None,
)


def _tool_call_name(tool_call) -> str:
    """Return a useful name for an unexecuted tool-call diagnostic."""
    if isinstance(tool_call, dict):
        function = tool_call.get("function", {}) or {}
        return function.get("name") or tool_call.get("type") or "unknown"
    function = getattr(tool_call, "function", None)
    return (
        getattr(function, "name", None)
        or getattr(tool_call, "type", None)
        or "unknown"
    )


class ChatStreamListener:
    def __init__(self, ai, prompt, events=False, event_schema="legacy", runtime=None, **kwargs):
        if isinstance(prompt, list):
            self.prompt = prompt
        else:
            self.prompt = json.loads(prompt)
        self._response_gen = None
        self.is_complete = False
        self.current_content = ""
        self.response = ""
        self.ai = ai
        self.runtime = runtime
        self.events = events
        self.event_schema = event_schema
        self._chunk_index = 0
        out = kwargs.copy()
        if "model" not in out or len(out["model"]) < 2:
            if "engine" in out:
                out["model"] = out["engine"]
                del out["engine"]
            else:
                out["model"] = DEFAULT_MODEL_FALLBACK
        self.kwargs = out

    def _event_from_runtime(self, event):
        if self.events:
            if self.event_schema == "v1":
                return {
                    "schema_version": event.schema_version,
                    "type": event.type,
                    "index": event.index,
                    "data": event.data,
                }

            if event.type == "text_delta":
                return {
                    "type": "text_delta",
                    "index": event.index,
                    "text": event.data.get("text", ""),
                }
            if event.type == "completed":
                terminal = event.data.get("terminal", {})
                return {
                    "type": "done",
                    "index": event.index,
                    "response": terminal.get("response_text", self.current_content),
                }
            if event.type == "error":
                return {
                    "type": "error",
                    "index": event.index,
                    "error": event.data.get("error", {}),
                }
            return None
        if event.type == "text_delta":
            return event.data.get("text", "")
        return None

    @staticmethod
    def _runtime_error_message(event):
        error = event.data.get("error", {}) if isinstance(event.data, dict) else {}
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return message
        return "Runtime stream emitted an error event"

    def _format_text_event(self, text: str):
        if self.event_schema == "v1":
            return {
                "schema_version": EVENT_SCHEMA_VERSION,
                "type": "text_delta",
                "index": self._chunk_index,
                "data": {"text": text},
            }
        return {
            "type": "text_delta",
            "index": self._chunk_index,
            "text": text,
        }

    def _format_done_event(self):
        if self.event_schema == "v1":
            return {
                "schema_version": EVENT_SCHEMA_VERSION,
                "type": "completed",
                "index": self._chunk_index,
                "data": {"terminal": {"response_text": self.current_content}},
            }
        return {
            "type": "done",
            "index": self._chunk_index,
            "response": self.current_content,
        }

    async def start_a(self):
        if self.runtime is not None:
            self._response_gen = self.runtime.stream_completion_a(self.prompt, **self.kwargs)
            return self
        if not self.kwargs.get('stream', False):
            self.kwargs['stream'] = True
        self._response_gen = await self.ai.aclient.chat.completions.create(messages=self.prompt,**self.kwargs)
        return self

    async def _get_responses_a(self):
        try:
            async for event in self._response_gen:
                if self.runtime is not None:
                    if event.type == "text_delta":
                        self.current_content += event.data.get("text", "")
                    elif event.type == "completed":
                        terminal = event.data.get("terminal", {})
                        self.current_content = terminal.get("response_text", self.current_content)
                        self.is_complete = True
                    elif event.type == "error":
                        self.is_complete = True
                        if not self.events:
                            raise RuntimeError(self._runtime_error_message(event))
                    rendered = self._event_from_runtime(event)
                    if rendered is not None:
                        yield rendered
                    continue

                resp = event.model_dump()
                if "choices" in resp:
                    if resp['choices'][0]['finish_reason'] is not None:
                        self.is_complete = True
                    if 'delta' in resp['choices'][0]:
                        content = resp['choices'][0]['delta']['content']
                        if content is not None:
                            self.current_content += content
                        if self.events:
                            yield self._format_text_event(content if content is not None else "")
                        else:
                            yield content if content is not None else ""
                        self._chunk_index += 1
            if self.events and self.runtime is None:
                yield self._format_done_event()
        finally:
            self.is_complete = True
            self.response = self.current_content

    def __aiter__(self):
        return self._get_responses_a()

    def start(self):
        if self.runtime is not None:
            self._response_gen = self.runtime.stream_completion(self.prompt, **self.kwargs)
            return self
        if not self.kwargs.get('stream', False):
            self.kwargs['stream'] = True
        self._response_gen = self.ai.client.chat.completions.create(messages=self.prompt,**self.kwargs)
        return self

    def _get_responses(self):
        try:
            for event in self._response_gen:
                if self.runtime is not None:
                    if event.type == "text_delta":
                        self.current_content += event.data.get("text", "")
                    elif event.type == "completed":
                        terminal = event.data.get("terminal", {})
                        self.current_content = terminal.get("response_text", self.current_content)
                        self.is_complete = True
                    elif event.type == "error":
                        self.is_complete = True
                        if not self.events:
                            raise RuntimeError(self._runtime_error_message(event))
                    rendered = self._event_from_runtime(event)
                    if rendered is not None:
                        yield rendered
                    continue

                resp = event.model_dump()
                if "choices" in resp:
                    if resp['choices'][0]['finish_reason'] is not None:
                        self.is_complete = True
                    if 'delta' in resp['choices'][0]:
                        content = resp['choices'][0]['delta']['content']
                        if content is not None:
                            self.current_content += content
                        if self.events:
                            yield self._format_text_event(content if content is not None else "")
                        else:
                            yield content if content is not None else ""
                        self._chunk_index += 1
            if self.events and self.runtime is None:
                yield self._format_done_event()
        finally:
            self.is_complete = True
            self.response = self.current_content

    def __iter__(self):
        return self._get_responses()


class ChatQueryMixin(ChatMessagesMixin, ChatParamsMixin):
    @staticmethod
    def _prepare_query_vars(usermsg=None, files=None, images=None, **additional_vars):
        """Build query vars with a canonical ``__user`` payload.

        Phase 3A centralizes natural attachment ergonomics so every query
        entrypoint (sync/async/listen) routes through the same normalization
        logic and produces the same expanded user-turn shape.
        """
        prepared = dict(additional_vars)
        attachments = normalize_attachment_inputs(files=files, images=images)

        if usermsg is None and not attachments:
            return prepared

        if attachments:
            # Merge into any pre-existing __user payload (e.g. set by __call__)
            # rather than replacing it, so callers like chat("hi", files=[...])
            # don't silently lose the text that __call__ already put in __user.
            existing = prepared.pop("__user", None)
            if isinstance(existing, dict):
                user_block = dict(existing)
            elif isinstance(existing, str) and existing:
                user_block = {"text": existing}
            else:
                user_block = {}
            # Explicit usermsg always wins over any existing __user text.
            if usermsg is not None:
                user_block["text"] = usermsg
            user_block.update(attachments)
            prepared["__user"] = user_block
        elif usermsg is not None:
            prepared["__user"] = usermsg

        return prepared

    @staticmethod
    def _serialize_tool_call(
        id: str,
        type: str,
        function_name: str,
        function_arguments: str,
        *,
        item_id: Optional[str] = None,
        status: Optional[str] = None,
        payload: Optional[Dict] = None,
        provider_extras: Optional[Dict] = None,
    ) -> dict:
        """Store provider call identity and payload without binding runtime code."""
        out = {
            "id": id,
            "type": type,
        }
        if function_name:
            out["function"] = {
                "name": function_name,
                "arguments": function_arguments,
            }
        if item_id:
            out["item_id"] = item_id
        if status:
            out["status"] = status
        if isinstance(payload, dict):
            out["payload"] = payload
        if isinstance(provider_extras, dict):
            out["provider_extras"] = provider_extras
        return out

    @staticmethod
    def _tool_response_to_dict(response) -> dict:
        """Convert a tool-bearing assistant response into canonical turn shape.

        This preserves the assistant text plus any richer normalized fields so
        tool-call responses can round-trip through chatsnack chat state/YAML
        without discarding reasoning, sources, files, images, or encrypted
        content.
        """
        out = {}
        text = response.content if hasattr(response, "content") else None
        if text:
            out["text"] = text
        for field in ("reasoning", "sources", "images", "files", "encrypted_content"):
            value = getattr(response, field, None)
            if value:
                out[field] = value
        tool_calls = []
        for tc in response.tool_calls:
            if isinstance(tc, dict):
                function = tc.get("function", {}) or {}
                tool_calls.append(
                    ChatQueryMixin._serialize_tool_call(
                        id=tc.get("id", ""),
                        type=tc.get("type", "function"),
                        function_name=function.get("name", ""),
                        function_arguments=function.get("arguments", ""),
                        item_id=tc.get("item_id"),
                        status=tc.get("status"),
                        payload=tc.get("payload"),
                        provider_extras=tc.get("provider_extras"),
                    )
                )
                continue

            function = getattr(tc, "function", None)
            serialized = ChatQueryMixin._serialize_tool_call(
                id=getattr(tc, "id", ""),
                type=getattr(tc, "type", "function"),
                function_name=function.name if function else "",
                function_arguments=function.arguments if function else "",
                item_id=getattr(tc, "item_id", None),
                status=getattr(tc, "status", None),
                payload=getattr(tc, "payload", None),
                provider_extras=getattr(tc, "provider_extras", None),
            )
            tool_calls.append(serialized)
        out["tool_calls"] = tool_calls
        return out

    @staticmethod
    def _assistant_response_to_turn(response_message) -> object:
        """Convert a normalized assistant response into chatsnack turn shape.

        Returns plain text when no rich assistant fields are present so the
        common scalar YAML form stays terse. When reasoning/sources/images/
        files/encrypted_content/provider_extras exists, returns an expanded
        assistant block.
        """
        text = response_message.content if hasattr(response_message, "content") else None
        expanded = {}
        if text:
            expanded["text"] = text
        for field in ("reasoning", "sources", "images", "files", "encrypted_content", "provider_extras"):
            value = getattr(response_message, field, None)
            if value:
                expanded[field] = value
        if expanded and (len(expanded) > 1 or "text" not in expanded):
            return expanded
        return text

    @staticmethod
    def _pending_output_matches(reference, pending) -> bool:
        """Match one provider file reference to its pending download."""
        if not isinstance(reference, dict):
            return False
        return bool(
            pending.file_id
            and reference.get("file_id") == pending.file_id
            and (
                not pending.container_id
                or not reference.get("container_id")
                or reference.get("container_id") == pending.container_id
            )
        )

    async def _capture_assistant_outputs(self, response_message) -> None:
        """Capture pending generated outputs before a continued Chat adopts them."""
        pending_outputs = list(getattr(response_message, "pending_outputs", None) or [])
        if not pending_outputs:
            return

        runtime_client = getattr(getattr(self, "runtime", None), "ai_client", None)
        download_client = runtime_client or self.ai

        for pending in pending_outputs:
            try:
                data = pending.data
                if data is None and pending.file_id and pending.container_id:
                    data = await download_client.download_container_file_async(
                        pending.container_id,
                        pending.file_id,
                    )
                if data is None:
                    raise RuntimeError("The provider output did not include retrievable bytes.")
                reference = capture_asset(
                    data,
                    filename=pending.filename,
                    kind=pending.kind,
                )
            except Exception as exc:
                warnings.warn(
                    f"Could not capture generated {pending.kind}: {exc}",
                    RuntimeWarning,
                )
                continue

            bucket_name = "images" if pending.kind == "image" else "files"
            bucket = list(getattr(response_message, bucket_name, None) or [])
            if pending.kind == "file":
                bucket = [
                    item
                    for item in bucket
                    if not self._pending_output_matches(item, pending)
                ]
            bucket.append(reference)
            setattr(response_message, bucket_name, bucket)

        response_message.pending_outputs = []

    def _run_sync(self, coro, method_name: str):
        try:
            return asyncio.run(coro)
        except RuntimeError as exc:
            if "asyncio.run() cannot be called from a running event loop" in str(exc):
                raise RuntimeError(
                    f"Cannot call sync {method_name}() from an active event loop. "
                    f"Use {method_name}_a() instead."
                ) from None
            raise

    # async method that gathers will execute an async format method on every message in the chat prompt and gather the results into a final json string
    async def _gather_format(self, format_coro, **kwargs) -> str:
        async def format_mapping(value, variables):
            return await format_coro(value, **variables)

        return await self._gather_formatted_messages(
            format_mapping,
            kwargs,
            asyncio.gather,
        )

    async def _gather_format_mapping(self, format_coro, format_vars) -> str:
        """Format every message while keeping variables in a positional map."""

        return await self._gather_formatted_messages(
            format_coro,
            format_vars,
            _gather_cancel_on_error,
        )

    async def _gather_formatted_messages(
        self,
        format_coro,
        format_vars,
        gather_messages,
    ) -> str:
        """Format messages with the sibling-failure policy chosen by the caller."""

        new_messages = self.get_messages()
        # TODO: Allow format messages in the tool calls
        # we now apply the format_coro to the content of each message in each dictionary in the list
        coros = []
        for message in new_messages:
            async def format_key(message):
                logger.trace("formatting key: {role}", role=message['role'])
                if isinstance(message["role"], str):
                    message["role"] = await format_coro(
                        message["role"],
                        format_vars,
                    )
                return
            async def format_message(message):
                logger.trace("formatting content: {content}", content=message['content'])
                if message.get("role") == "tool":
                    return
                if isinstance(message["content"], str):
                    try:
                        message["content"] = await format_coro(
                            message["content"],
                            format_vars,
                        )
                    except FillingError:
                        if (
                            _filling_resolution_active()
                            or message.get("role") != "assistant"
                        ):
                            raise
                    except Exception:
                        if message.get("role") != "assistant":
                            raise
                return
            coros.append(format_key(message))
            coros.append(format_message(message))
        # gather the results
        await gather_messages(*coros)
        logger.trace(new_messages)
        
        # if the current model is a reasoning model, we need the role of "system" to become "developer" in the json dump messages
        if self.params is not None and not self.params._supports_system_messages():
            for message in new_messages:
                if message["role"] == "system":
                    if self.params._supports_developer_messages():
                        message["role"] = "developer"
                    else:
                        # thanks OpenAI for having a model that doesn't support system or developer messages (i.e. o1-mini and o1-preview)
                        message["role"] = "user"

        # return the json version of the expanded messages
        return json.dumps(new_messages)
     
    async def _build_final_prompt(self, additional_vars = {}):
        promptvars = {}
        promptvars.update(additional_vars)
        token = active_filling_stash.set(self.snapshot_lookup_stash if hasattr(self, "snapshot_lookup_stash") else None)
        try:
            # format the prompt text with the passed-in variables as well as doing internal expansion
            active_template_vars = _active_template_vars.get()
            if active_template_vars is not None and active_template_vars[0] is self:
                promptvars = dict(active_template_vars[1])
                prompt = await self._gather_format_mapping(
                    aformatter.async_format_mapping,
                    filling_machine(promptvars),
                )
            else:
                prompt = await self._gather_format(
                    aformatter.async_format,
                    **filling_machine(promptvars),
                )
            return prompt
        finally:
            active_filling_stash.reset(token)

    def _build_completion_request_kwargs(self) -> Dict[str, object]:
        """Build provider-facing kwargs for one completion request."""
        kwargs = {}
        params = getattr(self, "params", None)
        if params is not None:
            kwargs = params._get_non_none_params()

            # Phase 3: merge provider-facing Responses options into the
            # request kwargs only for Responses-family runtimes.
            if self._runtime_supports_continuation():
                responses_opts = params._get_responses_api_options()
                if responses_opts:
                    merged = responses_opts.copy()
                    merged.update(kwargs)
                    kwargs = merged

        if hasattr(self, "get_tools"):
            tools = self.get_tools()
            if tools:
                kwargs["tools"] = tools
                if params and params.tool_choice:
                    kwargs["tool_choice"] = params.tool_choice

        return kwargs

    def _caller_executed_tool_types(self) -> List[str]:
        """Return caller-executed native declarations currently owned by the Chat."""
        from ..utensil import CALLER_EXECUTED_NATIVE_TOOL_TYPES

        tools = self.get_tools() if hasattr(self, "get_tools") else []
        return [
            tool.get("type")
            for tool in tools
            if isinstance(tool, dict)
            and tool.get("type") in CALLER_EXECUTED_NATIVE_TOOL_TYPES
        ]

    def _runtime_binding(self, tool_type: str):
        """Look up live application code while honoring the tool_search shim."""
        if tool_type == "tool_search":
            return getattr(self, "tool_search_handler", None)
        bindings = getattr(self, "_runtime_bindings", None) or {}
        return bindings.get(tool_type)

    def _validate_caller_executed_batch(self, tool_calls) -> None:
        """Validate a native batch before any caller-owned effect can run."""
        for tool_call in tool_calls:
            if getattr(tool_call, "type", None) == "apply_patch":
                self._apply_patch_executor_for(tool_call)

    def _apply_patch_executor_for(self, tool_call):
        """Return the executor only when a native call is safe to correlate."""
        status = getattr(tool_call, "status", None)
        if status != "completed":
            raise RuntimeError(
                f"Apply Patch call status {status!r} is not executable; "
                "only completed calls may run."
            )
        if not getattr(tool_call, "id", None):
            raise RuntimeError(
                "Apply Patch call is missing call_id; the executor did not run."
            )
        handler = self._runtime_binding("apply_patch")
        if handler is None:
            raise RuntimeError(
                "Missing runtime binding for apply_patch. Rebind with "
                "utensil.apply_patch(execute=...) before chat()."
            )
        return handler

    def _validate_caller_executed_tools(self, method_name: str) -> None:
        """Fail before provider I/O when a query cannot honor native calls safely."""
        tool_types = self._caller_executed_tool_types()
        if not tool_types:
            return

        runtime = getattr(self, "runtime", None)
        if getattr(runtime, "runtime_family", None) != "responses":
            raise RuntimeError(
                "Caller-executed native utensils require a Responses runtime; "
                "Chat Completions cannot carry Apply Patch calls."
            )
        if method_name != "chat":
            raise RuntimeError(
                "Apply Patch requires chat()/chat_a() so the continued Chat can "
                "retain the call and its output."
            )
        if getattr(self, "stream", False):
            raise RuntimeError(
                "Apply Patch automatic execution requires stream=False and chat()/chat_a()."
            )

        params = getattr(self, "params", None)
        auto_execute = getattr(params, "auto_execute", None) if params is not None else None
        if auto_execute is False:
            return
        missing = [tool_type for tool_type in tool_types if self._runtime_binding(tool_type) is None]
        if missing:
            names = ", ".join(sorted(set(missing)))
            raise RuntimeError(
                f"Missing runtime binding for {names}. Rebind with "
                "utensil.apply_patch(execute=...) before chat()."
            )

    def _build_tool_followup_request_kwargs(self) -> Dict[str, object]:
        """Build kwargs for an auto-fed tool-output follow-up request."""
        kwargs = self._build_completion_request_kwargs()
        if self._runtime_supports_continuation() and "tool_choice" in kwargs:
            # Responses-family runtimes treat tool_choice="required" literally
            # even after the requested tool output has been supplied. Leaving it
            # on the follow-up forces another tool call instead of allowing the
            # final assistant answer the auto-feed path exists to collect.
            kwargs.pop("tool_choice", None)
        return kwargs

    async def _submit_for_response_and_prompt(
        self,
        track_continuation: bool = False,
        _call_usage_ledger=None,
        _submitted_runtime_out=None,
        **additional_vars,
    ):
        """ Executes the query as-is and returns a tuple of the final prompt and the response"""
        active_template_vars = _active_template_vars.get()
        resolver_template_dispatch = (
            active_template_vars is not None and active_template_vars[0] is self
        )
        if resolver_template_dispatch:
            track_continuation = False
            _call_usage_ledger = None
            _submitted_runtime_out = None
            additional_vars = dict(active_template_vars[1])

        assert_binding = getattr(self, "_assert_bound_configuration", None)
        if assert_binding is not None:
            assert_binding()
        self._provider_binding_locked = True
        prompter = self
        # if the user in additional_vars, we're going to instead deepcopy this prompt into a new prompt and add the .user() to it
        if "__user" in additional_vars and not resolver_template_dispatch:
            new_chatprompt = self.copy(_share_ai_client=True)
            new_chatprompt.user(additional_vars["__user"])
            prompter = new_chatprompt
            # remove __user from additional_vars
            del additional_vars["__user"]
        if (
            track_continuation
            and prompter is not self
            and isinstance(getattr(self, "runtime", None), ResponsesWebSocketAdapter)
            and isinstance(getattr(prompter, "runtime", None), ResponsesWebSocketAdapter)
            and prompter.runtime.session is not self.runtime.session
        ):
            # An internal first-turn copy gets its own request session. Carry
            # only provider lineage into it so session="new" can continue.
            for attribute in (
                "last_response_id",
                "last_model",
                "last_store_value",
            ):
                setattr(
                    prompter.runtime.session,
                    attribute,
                    getattr(self.runtime.session, attribute, None),
                )
        prompt = await prompter._build_final_prompt(additional_vars)
        
        kwargs = self._build_completion_request_kwargs()
        
        if hasattr(self, 'params') and self.params and self.params.stream:
            # we're streaming so we need to use the wrapper object
            listener = ChatStreamListener(self.ai, prompt, runtime=getattr(self, "runtime", None), **kwargs)
            return prompt, listener
        else:
            # Route completion through the prompter instance so continuation metadata
            # is written to the chat instance that actually owns this submitted prompt.
            temporary_websocket_runtime = (
                prompter is not self
                and isinstance(getattr(prompter, "runtime", None), ResponsesWebSocketAdapter)
            )
            try:
                response = await prompter._cleaned_chat_completion(
                    prompt,
                    track_continuation=track_continuation,
                    _call_usage_ledger=_call_usage_ledger,
                    **kwargs,
                )
            except BaseException:
                if temporary_websocket_runtime:
                    await prompter.runtime.close_session_a()
                raise
            if _submitted_runtime_out is not None:
                _submitted_runtime_out.append(getattr(prompter, "runtime", None))
            if temporary_websocket_runtime and not track_continuation:
                await prompter.runtime.close_session_a()
            return prompt, response

    def _runtime_supports_continuation(self) -> bool:
        runtime = getattr(self, "runtime", None)
        return getattr(runtime, "runtime_family", None) == "responses"

    def _runtime_supports_provider_continuation(self, request_kwargs: Optional[Dict[str, object]] = None) -> bool:
        """Return True when provider-side continuation is safe for this turn.

        WebSocket Responses keeps server-side session state, so continuation
        via ``previous_response_id`` is always valid there.

        HTTP Responses is more constrained. We should still continue there when
        the prior response was explicitly stored, and while we are still inside
        an in-progress tool-recursion chain. Outside those cases, HTTP should
        fall back to local message replay instead of auto-injecting a previous
        response id.
        """
        from ..runtime import ResponsesAdapter, ResponsesWebSocketAdapter

        runtime = getattr(self, "runtime", None)
        if isinstance(runtime, ResponsesWebSocketAdapter):
            return True
        if not isinstance(runtime, ResponsesAdapter):
            return False

        request_kwargs = request_kwargs or {}
        if request_kwargs.get("store") is True:
            return True

        metadata = (getattr(self, "_last_runtime_metadata", None) or {})
        assistant_phase = metadata.get("assistant_phase")
        return assistant_phase not in (None, "completed")

    def _normalize_runtime_metadata(self, normalized_response) -> Dict[str, object]:
        metadata = {}
        if normalized_response is not None:
            metadata = getattr(normalized_response, "metadata", None) or {}

        return {
            "response_id": metadata.get("response_id"),
            "previous_response_id": metadata.get("previous_response_id"),
            "usage": getattr(normalized_response, "usage", None) if normalized_response is not None else None,
            "assistant_phase": metadata.get("assistant_phase"),
            "provider_extras": metadata.get("provider_extras"),
        }

    def _set_last_runtime_metadata(self, metadata: Optional[Dict[str, object]] = None):
        empty = {
            "response_id": None,
            "previous_response_id": None,
            "usage": None,
            "assistant_phase": None,
            "provider_extras": None,
        }
        if metadata:
            empty.update(metadata)
        self._last_runtime_metadata = empty

        # Phase 3: when export_state is enabled, bridge live runtime metadata
        # into params.responses.state so it persists on save.
        self._sync_runtime_metadata_to_params(empty)

    def _clone_runtime_metadata_to(self, other):
        source = getattr(self, "_last_runtime_metadata", None) or {}
        if hasattr(other, "_set_last_runtime_metadata"):
            other._set_last_runtime_metadata(source.copy())

    def _sync_runtime_metadata_to_params(self, metadata: Dict[str, object]):
        """Write runtime metadata into params.responses.state when export_state is true.

        This bridges the live continuation metadata from adapter responses into
        the YAML-persistent params surface, so that ``chat.save()`` serializes
        the current response_id, previous_response_id, and status when the
        user has opted into explicit state export.
        """
        params = getattr(self, "params", None)
        if params is None:
            return
        responses_cfg = getattr(params, "responses", None)
        if not isinstance(responses_cfg, dict) or not responses_cfg.get("export_state"):
            return

        state = {}
        if metadata.get("response_id"):
            state["response_id"] = metadata["response_id"]
        provider_extras = metadata.get("provider_extras")
        if isinstance(provider_extras, dict):
            if provider_extras.get("status"):
                state["status"] = provider_extras["status"]
        # Carry forward previous_response_id if we have one.
        prev_id = metadata.get("previous_response_id")
        if prev_id is None:
            # Check if it was in a nested metadata dict (from normalize_runtime_metadata).
            prev_id = (metadata.get("provider_extras") or {}).get("previous_response_id")
        if prev_id:
            state["previous_response_id"] = prev_id

        if state:
            params.responses["state"] = state

    def _set_runtime_metadata_from_response(self, response):
        """Extract and store runtime metadata from an adapter response object."""
        meta = self._normalize_runtime_metadata(response)
        self._set_last_runtime_metadata(meta)

    async def _cleaned_chat_completion(
        self,
        prompt,
        track_continuation: bool = False,
        _call_usage_ledger=None,
        **kwargs,
    ):
        # if there's no model specified, use the default
        if "model" not in kwargs:
            # if there's an engine in the kwargs, use that as the model
            if "engine" in kwargs:
                kwargs["model"] = kwargs["engine"]
                # remove engine from kwargs
                del kwargs["engine"]
            else:
                kwargs["model"] = DEFAULT_MODEL_FALLBACK
        if isinstance(prompt, list):
            messages = prompt
        else:
            messages = json.loads(prompt)            

        adapter = getattr(self, "runtime", None)
        if adapter is not None:
            request_kwargs = kwargs.copy()
            # Phase 3: do NOT auto-enable store=True for continuation.
            # Let the explicit params.responses.store value flow through
            # from the YAML config.  Phase 2a WebSocket continuation with
            # store=False is a valid and important path.
            if (
                track_continuation
                and self._runtime_supports_provider_continuation(request_kwargs)
                and not request_kwargs.get("previous_response_id")
            ):
                last_response_id = (getattr(self, "_last_runtime_metadata", {}) or {}).get("response_id")
                if last_response_id:
                    request_kwargs["previous_response_id"] = last_response_id
            normalized = await adapter.create_completion_a(messages=messages, **request_kwargs)
            if _call_usage_ledger is not None:
                _call_usage_ledger.record(normalized)
            response = normalized
            if track_continuation:
                self._set_last_runtime_metadata(self._normalize_runtime_metadata(normalized))
        else:
            if track_continuation:
                self._set_last_runtime_metadata()
            response = await self.ai.aclient.chat.completions.create(
                messages=messages,
                **kwargs
            )
        # trace log for the messages and the kwargs
        logger.trace("Messages: {messages}", messages=messages)
        logger.trace("Kwargs: {kwargs}", kwargs=
                     {k: v for k, v in kwargs.items() if k != 'stream'})

        if adapter is not None:
            message = response.message
            logger.trace("Response content: {content}", content=message.content)
            has_tool_calls = bool(message.tool_calls)
            if has_tool_calls:
                logger.debug("Tool calls detected in response: {num_calls}", num_calls=len(message.tool_calls))
                if track_continuation:
                    # Return full normalized response so callers can extract
                    # both the message and the runtime metadata.
                    return response
                return message
            if track_continuation:
                return response
            return message.content

        # trace log of the message content, if it exists
        if hasattr(response, "choices") and len(response.choices) > 0:
            if hasattr(response.choices[0], "message") and hasattr(response.choices[0].message, "content"):
                logger.trace("Response content: {content}", content=response.choices[0].message.content)
                import pprint
                logger.trace(pprint.pformat(response))
            else:
                logger.warning("No response content for prompt: {prompt}", prompt=prompt[:15])
        else:
            logger.warning("Response content: No response for prompt: {prompt}", prompt=prompt[:15])

        has_tool_calls = (hasattr(response.choices[0].message, "tool_calls") and response.choices[0].message.tool_calls)
        if has_tool_calls:
            logger.debug("Tool calls detected in response: {num_calls}", num_calls=len(response.choices[0].message.tool_calls))
            return response.choices[0].message

        return response.choices[0].message.content

    async def _execute_model_tool_call(self, tool_call):
        """Execute one normalized tool call and return a tool turn payload."""
        tc_type = getattr(tool_call, "type", None)
        tc_id = getattr(tool_call, "id", "")
        if tc_type == "apply_patch":
            handler = self._apply_patch_executor_for(tool_call)
            try:
                result = handler(ApplyPatchCall.from_normalized(tool_call))
                if asyncio.iscoroutine(result):
                    result = await result
                if not isinstance(result, Mapping):
                    raise TypeError(
                        "Apply Patch executor must return a mapping with status and output."
                    )
                output_status = result.get("status")
                if output_status not in {"completed", "failed"}:
                    raise ValueError(
                        "Apply Patch executor status must be 'completed' or 'failed'."
                    )
                output = result.get("output")
                if output is not None and not isinstance(output, str):
                    raise TypeError("Apply Patch executor output must be a string or None.")
            except Exception as exc:
                output_status = "failed"
                output = f"{type(exc).__name__}: {exc}"
            return {
                "tool_call_id": tc_id,
                "output_type": "apply_patch_call_output",
                "status": output_status,
                "content": output or "",
            }

        if tc_type == "tool_search":
            handler = self._runtime_binding("tool_search")
            if handler is None and getattr(self, "params", None) is not None:
                handler = getattr(self.params, "tool_search_handler", None)
            if handler is None:
                raise RuntimeError(
                    "Model emitted tool_search_call but no tool_search handler is configured. "
                    "Set chat.tool_search_handler=<callable> before chat()."
                )
            payload = getattr(tool_call, "payload", None)
            if payload is None:
                payload = {"arguments": getattr(getattr(tool_call, "function", None), "arguments", "")}
            result = handler(payload)
            if asyncio.iscoroutine(result):
                result = await result
            return {
                "tool_call_id": tc_id,
                "output_type": "tool_search_output",
                "content": json.dumps(result) if isinstance(result, (dict, list)) else str(result),
            }

        function = getattr(tool_call, "function", None)
        tool_call_dict = {
            "id": tc_id,
            "type": "function",
            "function": {
                "name": function.name if function else "",
                "arguments": function.arguments if function else "",
            },
        }
        result = self.execute_tool_call(tool_call_dict)
        return {
            "tool_call_id": tc_id,
            "content": json.dumps(result) if isinstance(result, dict) else str(result),
        }

    @property
    def response(self) -> Optional[str]:
        """Return the text from the last assistant message, when it has any. ⭐"""
        last_assistant_message = None
        for _message in self.messages:
            message = self._msg_dict(_message)
            if "assistant" in message:
                last_assistant_message = message["assistant"]
        if isinstance(last_assistant_message, dict):
            last_assistant_message = last_assistant_message.get("text")
        if not isinstance(last_assistant_message, str):
            last_assistant_message = None
        # Filter only assistant text; rich output-only turns have no string to filter.
        if last_assistant_message is not None:
            last_assistant_message = self.filter_by_pattern(last_assistant_message)
        return last_assistant_message

    def __str__(self):
        """ Returns the most recent response from the chat prompt ⭐"""
        if self.response is None:
            return ""
        else:
            return self.response

    def __call__(self, usermsg=None, **additional_vars) -> object:
        """Continue the conversation, matching the behavior of `chat()`."""
        if usermsg is not None:
            additional_vars["__user"] = usermsg
        return self.chat(**additional_vars)
 
    def ask(self, usermsg=None, files=None, images=None, **additional_vars) -> str:
        """
        Executes the internal chat query as-is and returns only the string response.
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        return self._run_sync(self.ask_a(**additional_vars), "ask")
    async def ask_a(self, usermsg=None, files=None, images=None, **additional_vars) -> str:
        """Async form of `ask()`."""
        active_template_vars = _active_template_vars.get()
        if active_template_vars is None or active_template_vars[0] is not self:
            template_vars = self._prepare_query_vars(
                usermsg,
                files=files,
                images=images,
                **additional_vars,
            )
        else:
            template_vars = dict(active_template_vars[1])

        self._validate_caller_executed_tools("ask")
        if self.stream:
            raise Exception("Cannot use ask() with a stream")
        if active_template_vars is None or active_template_vars[0] is not self:
            _, response = await self._submit_for_response_and_prompt(**template_vars)
        else:
            _, response = await self._submit_for_response_and_prompt()
        # filter the response if we have a pattern
        response = self.filter_by_pattern(response)
        return response

    async def _ask_a_with_template_vars(self, template_vars) -> str:
        """Dispatch through ``ask_a`` while preserving formatter variable names.

        Filling adapters use this path so names that overlap query controls,
        such as ``usermsg`` or ``files``, remain data without bypassing an
        overridden ``ask_a`` implementation. ``self`` stays context-only
        because Python bound methods cannot receive it again as a keyword.
        """
        token = _active_template_vars.set((self, dict(template_vars)))
        try:
            forwarded_vars = {
                name: value
                for name, value in template_vars.items()
                if name != "self"
            }
            return await self.ask_a(**forwarded_vars)
        finally:
            _active_template_vars.reset(token)
    def listen(self, usermsg=None, events=False, event_schema="legacy", files=None, images=None, **additional_vars) -> ChatStreamListener:
        """
        Executes the internal chat query as-is and returns a listener object that can be iterated on for the text.
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        self._validate_caller_executed_tools("listen")
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        _, response = self._run_sync(self._submit_for_response_and_prompt(**additional_vars), "listen")
        if self.stream:
            # response is a ChatStreamListener so lets start it
            response.events = events
            response.event_schema = event_schema
            response.start()
        return response
    async def listen_a(self, usermsg=None, async_listen=True, events=False, event_schema="legacy", files=None, images=None, **additional_vars) -> ChatStreamListener:
        """Async form of `listen()`."""
        self._validate_caller_executed_tools("listen")
        if not self.stream:
            raise Exception("Cannot use listen() without a stream")
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        _, response = await self._submit_for_response_and_prompt(**additional_vars)
        if self.stream:
            # response is a ChatStreamListener so lets start it
            response.events = events
            response.event_schema = event_schema
            await response.start_a()
        return response

    def _inherit_authored_runtime_override(self, child) -> None:
        """Preserve runtime intent without promoting an internal adapter to authoring."""
        source_overrides = getattr(
            self,
            "_chatsnack_constructor_overrides",
            {},
        )
        if "runtime" in source_overrides:
            child._chatsnack_constructor_overrides["runtime"] = child.runtime
        else:
            child._chatsnack_constructor_overrides.pop("runtime", None)

    def chat(self, usermsg=None, files=None, images=None, **additional_vars) -> object:
        """ 
        Executes the query as-is and returns a new Chat for continuation 
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        return self._run_sync(self.chat_a(**additional_vars), "chat")
        
    async def chat_a(self, usermsg=None, files=None, images=None, **additional_vars) -> object:
        """Return a continued chat with call-scoped provider usage attached."""
        from ..runtime.usage import _CallUsageLedger

        self._validate_caller_executed_tools("chat")
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)

        ledger = _CallUsageLedger()
        try:
            completed = await self._chat_a_with_usage(
                _call_usage_ledger=ledger,
                **additional_vars,
            )
        except BaseException as exc:
            snapshot = ledger.snapshot()
            self._last_call_usage = snapshot
            try:
                setattr(exc, "last_call_usage", snapshot)
            except Exception:
                pass
            raise

        snapshot = ledger.snapshot()
        self._last_call_usage = snapshot
        completed._last_call_usage = snapshot
        return completed

    async def _chat_a_with_usage(self, _call_usage_ledger, **additional_vars) -> object:
        """Run one chat orchestration while sharing its private response ledger."""
        if self.stream:
            raise Exception("Cannot use chat() with a stream")
        
        submitted_runtime = []
        prompt, response = await self._submit_for_response_and_prompt(
            track_continuation=True,
            _call_usage_ledger=_call_usage_ledger,
            _submitted_runtime_out=submitted_runtime,
            **additional_vars,
        )
        response_runtime = (
            submitted_runtime[0]
            if submitted_runtime
            else getattr(self, "runtime", None)
        )
        
        # create a new chatprompt with the new name, copy it from this one
        new_chatprompt = self.__class__(
            params=copy.copy(getattr(self, "params", None)),
            runtime=response_runtime,
            _ai_client=getattr(self, "ai", None),
            tool_search_handler=getattr(self, "tool_search_handler", None),
            _runtime_bindings=getattr(self, "_runtime_bindings", None),
        )
        self._inherit_authored_runtime_override(new_chatprompt)
        if (
            isinstance(response_runtime, ResponsesWebSocketAdapter)
            and response_runtime.session.mode == "new"
            and isinstance(new_chatprompt.runtime, ResponsesWebSocketAdapter)
            and new_chatprompt.runtime.session is not response_runtime.session
        ):
            # session="new" intentionally gives the returned Chat a fresh
            # connection. The temporary request session is no longer owned.
            await response_runtime.close_session_a()

        logger.trace("Expanded prompt: " + prompt)
        new_chatprompt.add_messages_json(prompt)
        # append the recent message

        # Handle different response types (string vs object with tool_calls)
        if isinstance(response, str):
            # Add the response as an assistant message
            new_chatprompt.add_or_update_last_assistant_message(response)
            # Legacy path – no adapter metadata to propagate.
            return new_chatprompt
        else:
            # Adapter path: response is a NormalizedCompletionResult with
            # .message (content/tool_calls) and .metadata for continuation.
            message = response.message if hasattr(response, "message") else response
            await self._capture_assistant_outputs(message)
            content = message.content if hasattr(message, "content") else None
            has_tool_calls = hasattr(message, "tool_calls") and message.tool_calls
            
            if not has_tool_calls:
                # trace log
                logger.trace("No tool calls in response")
                # Just a regular response with content but no tool calls
                assistant_turn = self._assistant_response_to_turn(message)
                if assistant_turn is not None:
                    new_chatprompt = new_chatprompt.assistant(assistant_turn)
                # Propagate metadata from the adapter response (not from self,
                # which may be the source chat that did not run the completion).
                new_chatprompt._set_runtime_metadata_from_response(response)
                return new_chatprompt
            else:
                logger.debug("Tool calls detected in response: {num_calls}",
                             num_calls=len(message.tool_calls))
                
            # Add the assistant response with tool calls
            msg = self._tool_response_to_dict(message)
            new_chatprompt = new_chatprompt.assistant(msg)
            # Seed new_chatprompt with the metadata from the initial tool-bearing response.
            new_chatprompt._set_runtime_metadata_from_response(response)
            logger.debug(f"Tool calls in response: {message.tool_calls}")
            
            # debug dump new_chatprompt.yaml
            logger.debug(f"New chat prompt: {new_chatprompt.yaml}")

            # Check if we should auto-execute tools, default is we will
            if has_tool_calls and (self.params.auto_execute is None or self.params.auto_execute):
                max_auto_feed_cycles = _resolve_auto_feed_limit(self.params.auto_feed)
                auto_feed_cycles = 0
                current_chat = new_chatprompt

                # trace call that we got here and begin recursion
                logger.trace(
                    "Tool call recursion, auto-feed limit: {max_depth}",
                    max_depth=max_auto_feed_cycles,
                )

                # A zero limit still executes the already-requested batch. It
                # only suppresses the automatic follow-up submission.
                while has_tool_calls and (
                    auto_feed_cycles < max_auto_feed_cycles
                    or max_auto_feed_cycles == 0
                ):
                    if max_auto_feed_cycles > 0:
                        auto_feed_cycles += 1
                        logger.debug(
                            "Tool recursion {current}/{maximum}",
                            current=auto_feed_cycles,
                            maximum=max_auto_feed_cycles,
                        )
                    else:
                        logger.debug("Executing pending tool calls without auto-feed")
                   
                    self._validate_caller_executed_batch(message.tool_calls)
                    for tool_call in message.tool_calls:
                        tool_output = await self._execute_model_tool_call(tool_call)
                        current_chat = current_chat.tool(tool_output)
                        
                        # log all messages in the current_chat
                        logger.debug(f"Current chat messages: {current_chat.get_messages()}")
                    
                    # Check if we should feed tool results back to the model
                    if max_auto_feed_cycles > 0:
                        # Use _submit_for_response_and_prompt for the follow-up call
                        # Since we want to use the current conversation as context, we create a temporary chat object
                        temp_chat = current_chat.copy(_share_ai_client=True)
                        current_chat._clone_runtime_metadata_to(temp_chat)
                        new_prompt = json.dumps(temp_chat.get_messages()) 
                        logger.trace(f"Temp chat messagesx: {temp_chat.get_messages()}")
                        follow_up = await temp_chat._cleaned_chat_completion(
                            new_prompt,
                            track_continuation=True,
                            _call_usage_ledger=_call_usage_ledger,
                            **temp_chat._build_tool_followup_request_kwargs(),
                        )
                        
                        # Check if the follow-up response has tool calls
                        if isinstance(follow_up, str):
                            # Text response - no tool calls
                            current_chat = current_chat.assistant(follow_up)
                            temp_chat._clone_runtime_metadata_to(current_chat)
                            has_tool_calls = False
                        else:
                            # follow_up is a NormalizedCompletionResult; extract message.
                            follow_msg = follow_up.message if hasattr(follow_up, "message") else follow_up
                            await temp_chat._capture_assistant_outputs(follow_msg)
                            has_tool_calls = hasattr(follow_msg, "tool_calls") and follow_msg.tool_calls
                            
                            if has_tool_calls:
                                # More tool calls - add to chat and continue loop
                                msg = self._tool_response_to_dict(follow_msg)
                                current_chat = current_chat.assistant(msg)
                                current_chat._set_runtime_metadata_from_response(follow_up)
                                logger.debug(f"Tool calls in follow-up response: {follow_msg.tool_calls}")
                                message = follow_msg  # Update for next iteration
                            else:
                                # Final response with content but no more tool calls
                                assistant_turn = self._assistant_response_to_turn(follow_msg)
                                if assistant_turn is not None:
                                    current_chat = current_chat.assistant(assistant_turn)
                                current_chat._set_runtime_metadata_from_response(follow_up)
                    else:
                        # The pending tool batch executed, but its results are
                        # not submitted for another model response.
                        has_tool_calls = False
                        logger.debug("Not feeding tool results back because auto_feed is disabled")
                
                if (
                    max_auto_feed_cycles > 0
                    and auto_feed_cycles >= max_auto_feed_cycles
                    and has_tool_calls
                ):
                    pending_names = ", ".join(
                        _tool_call_name(tool_call)
                        for tool_call in message.tool_calls
                    )
                    logger.warning(
                        "Reached auto_feed limit ({maximum}); pending tool calls "
                        "were recorded but not executed: {tool_names}",
                        maximum=max_auto_feed_cycles,
                        tool_names=pending_names,
                    )
                    
                # Return the chat with all tool interactions
                return current_chat
                        
            new_chatprompt._set_runtime_metadata_from_response(response)
            return new_chatprompt

    # clone function to create a new chatprompt with the same name and data
    def copy(
        self,
        name: str = None,
        system=None,
        expand_includes: bool = False,
        expand_fillings: bool = False,
        _share_ai_client: bool = False,
        **additional_vars,
    ) -> object:
        """ Returns a new ChatPrompt object that is a copy of this one, optionally with a new name ⭐"""
        copied_params = copy.copy(self.params)
        copied_runtime = getattr(self, "runtime", None)
        copied_runtime_selector = None
        copied_session = None
        from ..runtime import ResponsesWebSocketAdapter, ResponsesWebSocketSession

        # Template-style chats (for example default packs) should not leak a
        # stale WebSocket session into fresh copies when they have never owned
        # a response of their own. Keep session lineage only once response
        # metadata exists on the source chat.
        if isinstance(copied_runtime, ResponsesWebSocketAdapter):
            response_id = (getattr(self, "_last_runtime_metadata", None) or {}).get("response_id")
            if not response_id:
                source_session = copied_runtime.session
                authored_session = (
                    copied_params.get("session") if isinstance(copied_params, dict)
                    else getattr(copied_params, "session", None)
                )
                copied_runtime = ResponsesWebSocketAdapter(
                    self.ai,
                    session=ResponsesWebSocketSession(
                        mode=authored_session or getattr(source_session, "mode", None) or "inherit"
                    ),
                    **copied_runtime._retry_options(),
                )
        if name is not None:
            new_chat = self.__class__(
                name=name,
                params=copied_params,
                runtime=copied_runtime,
                _ai_client=self._ai_client_for_copy(share=_share_ai_client),
                runtime_selector=copied_runtime_selector,
                session=copied_session,
                tool_search_handler=getattr(self, "tool_search_handler", None),
                _runtime_bindings=getattr(self, "_runtime_bindings", None),
            )
        else:
            # if the existing name ends with _{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4()}" then we need to trim that off and add a new one
            # use a regex to match at the end of the name
            import re
            match = re.search(r"_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-([a-f0-9]{8}-([a-f0-9]{4}-){3}[a-f0-9]{12})", self.name)
            if match is not None:
                # trim off the end
                name = self.name[:match.start()]
            else:
                name = self.name
            new_chat = self.__class__(
                name=name + f"_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4()}",
                params=copied_params,
                runtime=copied_runtime,
                _ai_client=self._ai_client_for_copy(share=_share_ai_client),
                runtime_selector=copied_runtime_selector,
                session=copied_session,
                tool_search_handler=getattr(self, "tool_search_handler", None),
                _runtime_bindings=getattr(self, "_runtime_bindings", None),
            )

        self._inherit_authored_runtime_override(new_chat)

        # Keep the established local-utensil copy behavior. Caller-executed
        # services retain identity through the separate runtime binding map.
        new_chat._local_registry = copy.deepcopy(self._local_registry) if hasattr(self, '_local_registry') else None
        #new_chat.set_tools(self.get_tools())

        if expand_fillings:
            if not expand_includes:
                raise NotImplementedError("Cannot expand fillings without expanding includes")
            prompt = asyncio.run(self._build_final_prompt(additional_vars))
            new_chat.add_messages_json(prompt, escape=True)
        else:
            new_chat.add_messages_json(self.json if expand_includes else self.json_unexpanded, escape=False)
        if system is not None:
            new_chat.system(system)
        self._clone_runtime_metadata_to(new_chat)
        return new_chat
