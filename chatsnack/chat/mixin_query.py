import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger
from datafiles import datafile

from ..asynchelpers import aformatter
from ..fillings import filling_machine
from ..runtime import EVENT_SCHEMA_VERSION
from ..runtime.attachment_inputs import normalize_attachment_inputs

from .mixin_messages import ChatMessagesMixin
from .mixin_params import ChatParamsMixin, DEFAULT_MODEL_FALLBACK


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
    def _serialize_tool_call(id: str, type: str, function_name: str, function_arguments: str) -> dict:
        out = {
            "id": id,
            "type": type,
        }
        if function_name:
            out["function"] = {
                "name": function_name,
                "arguments": function_arguments,
            }
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
                    )
                )
                continue

            function = getattr(tc, "function", None)
            serialized = ChatQueryMixin._serialize_tool_call(
                id=getattr(tc, "id", ""),
                type=getattr(tc, "type", "function"),
                function_name=function.name if function else "",
                function_arguments=function.arguments if function else "",
            )
            payload = getattr(tc, "payload", None)
            if isinstance(payload, dict):
                serialized["payload"] = payload
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
        new_messages = self.get_messages()
        # TODO: Allow format messages in the tool calls
        # we now apply the format_coro to the content of each message in each dictionary in the list
        coros = []
        for message in new_messages:
            async def format_key(message):
                logger.trace("formatting key: {role}", role=message['role'])
                message["role"] = await format_coro(message["role"], **kwargs)
                return
            async def format_message(message):
                logger.trace("formatting content: {content}", content=message['content'])
                message["content"] = await format_coro(message["content"], **kwargs)
                return
            coros.append(format_key(message))
            coros.append(format_message(message))
        # gather the results
        await asyncio.gather(*coros)
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
        # format the prompt text with the passed-in variables as well as doing internal expansion
        prompt = await self._gather_format(aformatter.async_format, **filling_machine(promptvars))
        return prompt

    async def _submit_for_response_and_prompt(self, track_continuation: bool = False, **additional_vars):
        """ Executes the query as-is and returns a tuple of the final prompt and the response"""
        prompter = self
        # if the user in additional_vars, we're going to instead deepcopy this prompt into a new prompt and add the .user() to it
        if "__user" in additional_vars:
            new_chatprompt = self.copy()
            new_chatprompt.user(additional_vars["__user"])
            prompter = new_chatprompt
            # remove __user from additional_vars
            del additional_vars["__user"]
        prompt = await prompter._build_final_prompt(additional_vars)
        
        kwargs = {}
        if hasattr(self, 'params') and self.params is not None:
            kwargs = self.params._get_non_none_params()

            # Phase 3: merge provider-facing Responses options (text, reasoning,
            # include, store, …) into the request kwargs so they reach the
            # Responses API.  These are lower-priority than explicit kwargs.
            # Only merge when the active runtime is a Responses-family adapter;
            # Chat Completions does not understand these keys.
            if self._runtime_supports_continuation():
                responses_opts = self.params._get_responses_api_options()
                if responses_opts:
                    merged = responses_opts.copy()
                    merged.update(kwargs)
                    kwargs = merged
        
        # Add tools if available
        if hasattr(self, 'get_tools'):
            tools = self.get_tools()
            if tools:
                kwargs['tools'] = tools
                if self.params and self.params.tool_choice:
                    kwargs['tool_choice'] = self.params.tool_choice
        
        if hasattr(self, 'params') and self.params and self.params.stream:
            # we're streaming so we need to use the wrapper object
            listener = ChatStreamListener(self.ai, prompt, runtime=getattr(self, "runtime", None), **kwargs)
            return prompt, listener
        else:
            # Route completion through the prompter instance so continuation metadata
            # is written to the chat instance that actually owns this submitted prompt.
            return prompt, await prompter._cleaned_chat_completion(
                prompt,
                track_continuation=track_continuation,
                **kwargs,
            )

    def _runtime_supports_continuation(self) -> bool:
        from ..runtime import ResponsesAdapter, ResponsesWebSocketAdapter
        runtime = getattr(self, "runtime", None)
        return isinstance(runtime, (ResponsesAdapter, ResponsesWebSocketAdapter))

    def _runtime_supports_provider_continuation(self) -> bool:
        """Return True only for runtimes with provider-side session continuation.

        The WebSocket Responses transport maintains a persistent connection
        with server-side session state, so auto-injecting previous_response_id
        is valid.  Plain HTTP Responses does not retain server-side state when
        store=False (the default), so auto-continuation would cause
        previous_response_not_found errors.  HTTP follow-ups should resend the
        local message history instead.
        """
        from ..runtime import ResponsesWebSocketAdapter
        runtime = getattr(self, "runtime", None)
        return isinstance(runtime, ResponsesWebSocketAdapter)

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

    async def _cleaned_chat_completion(self, prompt, track_continuation: bool = False, **kwargs):
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
                and self._runtime_supports_provider_continuation()
                and not request_kwargs.get("previous_response_id")
            ):
                last_response_id = (getattr(self, "_last_runtime_metadata", {}) or {}).get("response_id")
                if last_response_id:
                    request_kwargs["previous_response_id"] = last_response_id
            normalized = await adapter.create_completion_a(messages=messages, **request_kwargs)
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
        if tc_type == "tool_search":
            handler = getattr(self, "tool_search_handler", None)
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
    def response(self) -> str:
        """ Returns the value of the last assistant message in the chat prompt ⭐"""
        last_assistant_message = None
        for _message in self.messages:
            message = self._msg_dict(_message)
            if "assistant" in message:
                last_assistant_message = message["assistant"]
        # filter the response if we have a pattern
        last_assistant_message = self.filter_by_pattern(last_assistant_message)
        return last_assistant_message

    def __str__(self):
        """ Returns the most recent response from the chat prompt ⭐"""
        if self.response is None:
            return ""
        else:
            return self.response

    def __call__(self, usermsg=None, **additional_vars) -> object:
        """ Executes the query as-is and returns a Chat object with the response, shortcut for Chat.chat()"""
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
        """ Executes the query as-is, async version of ask()"""
        if self.stream:
            raise Exception("Cannot use ask() with a stream")
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        _, response = await self._submit_for_response_and_prompt(**additional_vars)
        # filter the response if we have a pattern
        response = self.filter_by_pattern(response)
        return response
    def listen(self, usermsg=None, events=False, event_schema="legacy", files=None, images=None, **additional_vars) -> ChatStreamListener:
        """
        Executes the internal chat query as-is and returns a listener object that can be iterated on for the text.
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        _, response = self._run_sync(self._submit_for_response_and_prompt(**additional_vars), "listen")
        if self.stream:
            # response is a ChatStreamListener so lets start it
            response.events = events
            response.event_schema = event_schema
            response.start()
        return response
    async def listen_a(self, usermsg=None, async_listen=True, events=False, event_schema="legacy", files=None, images=None, **additional_vars) -> ChatStreamListener:
        """ Executes the query as-is, async version of listen()"""
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
    def chat(self, usermsg=None, files=None, images=None, **additional_vars) -> object:
        """ 
        Executes the query as-is and returns a new Chat for continuation 
        If usermsg is passed in, it will be added as a user message to the chat before executing the query. ⭐
        """
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
        return self._run_sync(self.chat_a(**additional_vars), "chat")
        
    async def chat_a(self, usermsg=None, files=None, images=None, **additional_vars) -> object:
        """Executes the query as-is, and returns a ChatPrompt object that contains the response. Async version of chat()"""
        additional_vars = self._prepare_query_vars(usermsg, files=files, images=images, **additional_vars)
            
        if self.stream:
            raise Exception("Cannot use chat() with a stream")
        
        prompt, response = await self._submit_for_response_and_prompt(track_continuation=True, **additional_vars)
        
        # create a new chatprompt with the new name, copy it from this one
        new_chatprompt = self.__class__(
            params=getattr(self, "params", None),
            runtime=getattr(self, "runtime", None),
            tool_search_handler=getattr(self, "tool_search_handler", None),
        )

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
                # Recursive tool call handling with max depth
                max_tool_recursion = 5
                current_recursion = 0
                current_chat = new_chatprompt

                # trace call that we got here and begin recursion
                logger.trace("Tool call recursion, max depth: {max_depth}", max_depth=max_tool_recursion)

                while has_tool_calls and current_recursion < max_tool_recursion:
                    current_recursion += 1
                    logger.debug(f"Tool recursion {current_recursion}/{max_tool_recursion}")
                   
                    for tool_call in message.tool_calls:
                        tool_output = await self._execute_model_tool_call(tool_call)
                        current_chat = current_chat.tool(tool_output)
                        
                        # log all messages in the current_chat
                        logger.debug(f"Current chat messages: {current_chat.get_messages()}")
                    
                    # Check if we should feed tool results back to the model
                    if self.params.auto_feed is None or self.params.auto_feed:
                        # Use _submit_for_response_and_prompt for the follow-up call
                        # Since we want to use the current conversation as context, we create a temporary chat object
                        temp_chat = current_chat.copy()
                        current_chat._clone_runtime_metadata_to(temp_chat)
                        new_prompt = json.dumps(temp_chat.get_messages()) 
                        logger.trace(f"Temp chat messagesx: {temp_chat.get_messages()}")
                        follow_up = await temp_chat._cleaned_chat_completion(
                            new_prompt,
                            track_continuation=True,
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
                        # If auto_feed is False, break the tool call recursion loop
                        # The assistant's tool calls are recorded but not fed back to the model
                        has_tool_calls = False
                        logger.debug("Not feeding tool results back to model due to auto_feed=False")
                
                # Log warning if we hit max recursion
                if current_recursion >= max_tool_recursion and has_tool_calls:
                    logger.warning(f"Reached maximum tool recursion depth ({max_tool_recursion})")
                    
                # Return the chat with all tool interactions
                return current_chat
                        
            new_chatprompt._set_runtime_metadata_from_response(response)
            return new_chatprompt

    # clone function to create a new chatprompt with the same name and data
    def copy(self, name: str = None, system = None, expand_includes: bool = False, expand_fillings: bool = False, **additional_vars) -> object:
        """ Returns a new ChatPrompt object that is a copy of this one, optionally with a new name ⭐"""
        import copy
        copied_params = copy.copy(self.params)
        if name is not None:
            new_chat = self.__class__(
                name=name,
                params=copied_params,
                runtime=getattr(self, "runtime", None),
                tool_search_handler=getattr(self, "tool_search_handler", None),
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
                runtime=getattr(self, "runtime", None),
                tool_search_handler=getattr(self, "tool_search_handler", None),
            )

        # copy local registry
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
