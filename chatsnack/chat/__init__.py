import copy
import os
import warnings
import uuid
from dataclasses import field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from snapclass import snapclass

from ..aiclient import AiClient
from ..defaults import CHATSNACK_PROMPTS
from ..runtime import (
    ChatCompletionsAdapter,
    ResponsesAdapter,
    ResponsesWebSocketAdapter,
    ResponsesWebSocketSession,
)
from .mixin_query import ChatQueryMixin
from .mixin_params import ChatParams, ChatParamsMixin
from .mixin_serialization import DatafileMixin, ChatSerializationMixin, refresh_snapclass_config_stash
from .mixin_utensil import ChatUtensilMixin 
from ..txtformat import TxtStrFormat
from ..yamlformat import YAML as ChatsnackYAMLFormatter


def _empty_runtime_metadata() -> Dict[str, object]:
    return {
        "response_id": None,
        "usage": None,
        "assistant_phase": None,
        "provider_extras": None,
    }


_RUNTIME_ENV_WARNING_EMITTED = False


def _runtime_policy_from_env() -> tuple[str, Optional[str]]:
    """Resolve implicit runtime family/session from CHATSNACK_DEFAULT_RUNTIME."""
    global _RUNTIME_ENV_WARNING_EMITTED
    raw = os.getenv("CHATSNACK_DEFAULT_RUNTIME")
    if raw is None or not raw.strip():
        return "responses", "inherit"

    value = raw.strip().lower()
    if value in {"responses_websocket", "responses_ws"}:
        return "responses", "inherit"
    if value == "responses_http":
        return "responses", None
    if value == "chat_completions":
        return "chat_completions", None

    if not _RUNTIME_ENV_WARNING_EMITTED:
        warnings.warn(
            "Invalid CHATSNACK_DEFAULT_RUNTIME value "
            f"'{raw}'. Falling back to responses_websocket.",
            stacklevel=2,
        )
        _RUNTIME_ENV_WARNING_EMITTED = True
    return "responses", "inherit"


########################################################################################################################
# Core datafile classes of Plunkychat
# (1) Chat, high-level class that symbolizes a prompt/request/response, can reference other Chat objects to chain
# (2) ChatParams, used only in Chat, includes parameters like engine name and other OpenAI params.
# (3) Text, this is a text blob we save to disk, can be used as a reference inside chat messages ('snack fillings')

@snapclass("{self.name}.txt", stash=CHATSNACK_PROMPTS, manual=True, formatter=TxtStrFormat)
class Text(DatafileMixin):
    """Reusable text asset that can be saved and expanded in other prompts."""
    name: str
    content: Optional[str] = None
    # TODO: All Text and Chat objects should automatically be added as snack fillings (even if not saved to disk)


@snapclass(
    "{self.name}.yml",
    stash=CHATSNACK_PROMPTS,
    manual=True,
    init=False,
    formatter=ChatsnackYAMLFormatter,
)
class Chat(ChatQueryMixin, ChatSerializationMixin, ChatUtensilMixin):
    """ A chat prompt that can be expanded into a chat ⭐"""
    # title should be just like above but with a GUID at the end
    name: str = field(default_factory=lambda: f"_ChatPrompt-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4()}")
    params: Optional[ChatParams] = None
    messages: List[Dict[str, Any]] = field(default_factory=lambda: [])

    def __init__(self, *args, **kwargs):
        """
        Initialize a chat from a terse authored shape.

        Common forms include `Chat("system message")`,
        `Chat("Name", "system message")`, `Chat(name="SavedPrompt")`, and
        `Chat(..., utensils=[...])`.
        """
        # Extract utensil-related parameters first
        utensils = kwargs.pop("utensils", None)
        auto_execute = kwargs.pop("auto_execute", None)
        tool_choice = kwargs.pop("tool_choice", None)
        auto_feed = kwargs.pop("auto_feed", None)
        runtime = kwargs.pop("runtime", None)
        runtime_selector = kwargs.pop("runtime_selector", None)
        model = kwargs.pop("model", None)
        session = kwargs.pop("session", None)
        stream = kwargs.pop("stream", None)
        tool_search_handler = kwargs.pop("tool_search_handler", None)
        if isinstance(runtime, str) and runtime_selector is None:
            runtime_selector = runtime
            runtime = None
        # Constructor runtime/model/tool options are live overrides. When the
        # legacy Chat(name=...) autoload path finds a YAML file, snapclass must
        # apply persisted params first and then reapply these overrides so an
        # explicit runtime does not get silently replaced by the saved file.
        self._chatsnack_constructor_overrides = {
            key: value
            for key, value in {
                "engine": kwargs.get("engine"),
                "model": model,
                "session": session,
                "stream": stream,
                "auto_execute": auto_execute,
                "tool_choice": tool_choice,
                "auto_feed": auto_feed,
                "runtime": runtime,
                "runtime_selector": runtime_selector,
                "tool_search_handler": tool_search_handler,
            }.items()
            if value is not None
        }
        
        # get name from kwargs, if it's there
        if "name" in kwargs:
            self.name = kwargs["name"]
        else:
            # if we get two args, the first is the name and the second is the system message
            if len(args) == 2:
                self.name = args[0]
            else:
                # get the default from the dataclass fields and use that
                self.name = self.__dataclass_fields__["name"].default_factory()
        
        if "params" in kwargs:
            self.params = kwargs["params"]
        else:
            # get the default value from the dataclass field, it's optional
            self.params = self.__dataclass_fields__["params"].default

        
        if "messages" in kwargs:
            self.messages = kwargs["messages"]
        else:
            # get the default from the dataclass fields and use that
            self.messages = self.__dataclass_fields__["messages"].default_factory()

        if "engine" in kwargs:
            self.engine = kwargs["engine"]
        if model is not None:
            self.model = model
        if session is not None:
            self.session = session
        if stream is not None:
            self.stream = stream
            
        if "system" in kwargs:
            self.system_message = kwargs["system"]
        else:
            if len(args) == 1:
                # if we only get one args, we'll assume it's the system message
                self.system_message = args[0]
            elif len(args) == 2:
                # if we get two args, the first is the name and the second is the system message
                self.system_message = args[1]

        if auto_execute is not None:
            self.auto_execute = auto_execute
        if tool_choice is not None:
            self.tool_choice = tool_choice
        if auto_feed is not None:
            self.auto_feed = auto_feed

       
        # Register utensils if provided
        if utensils:
            if self.params is None:
                self.params = ChatParams()

            # Import here to avoid circular imports
            from ..utensil import extract_utensil_functions, get_openai_tools, collect_include_entries
            
            # Store local registry of utensil functions
            self._local_registry = utensils  # Store original objects, extract when needed
            
            # Get tool definitions for OpenAI API
            tools_list = get_openai_tools(utensils)
            
            # Store and serialize tool definitions
            self.set_tools(tools_list)

            # Phase 4A: collect implied include entries from hosted utensils
            implied_includes = collect_include_entries(utensils)
            if implied_includes:
                if self.params.responses is None:
                    self.params.responses = {}
                existing = self.params.responses.get("include", [])
                merged = list(existing)
                for entry in implied_includes:
                    if entry not in merged:
                        merged.append(entry)
                self.params.responses["include"] = merged
        
        # Check if we're being loaded from a YAML file with tools
        if utensils is None:
            # ensure that tools is in params if it exists, then ensure if it is there, it's None
            if self.params is None or not hasattr(self.params, 'tools') or self.params.tools is None:
                # This is likely a deserialization case, so try loading tools from registry
                self._load_tools_from_params()
        
        # Save the initial state for reset() purposes
        self._initial_name = self.name
        self._initial_params = copy.copy(self.params)
        self._initial_messages = copy.copy(self.messages)
        self._initial_system_message = self.system_message
        # do the same for the tool registry
        self._initial_registry = getattr(self, '_local_registry', None)

        self.ai = AiClient()
        self.tool_search_handler = tool_search_handler
        profile = None
        session_mode = None
        explicit_runtime_selector = runtime_selector
        explicit_session = session is not None
        params_runtime = None
        if hasattr(self, "params") and self.params is not None:
            profile = getattr(self.params, "profile", None)
            params_runtime = getattr(self.params, "runtime", None)
            runtime_selector = runtime_selector or params_runtime
            session_mode = getattr(self.params, "session", None)

        # Phase 4 runtime resolution order:
        # explicit runtime object -> explicit runtime selector -> params.runtime
        # -> explicit session (constructor or params) -> env override -> library default.
        # Authored params.session counts as a session signal so that
        # pinned YAML assets are not overridden by CHATSNACK_DEFAULT_RUNTIME.
        session_specified = explicit_session or session_mode is not None
        runtime_source = None
        if runtime is not None:
            runtime_source = "runtime_object"
        elif explicit_runtime_selector is not None:
            runtime_source = "explicit_runtime"
        elif params_runtime is not None:
            runtime_source = "params_runtime"
        elif session_specified:
            runtime_selector = "responses"
            runtime_source = "explicit_session"
        else:
            runtime_selector, default_session = _runtime_policy_from_env()
            runtime_source = "default_policy"
            if session_mode is None:
                session_mode = default_session

        # Constructor session= keeps precedence over params.session when both exist.
        if explicit_session and runtime_source in {"default_policy", "explicit_session"} and runtime_selector == "responses":
            session_mode = self.session
        self.runtime = self._select_runtime(runtime=runtime, runtime_selector=runtime_selector, profile=profile, session_mode=session_mode)
        self._last_runtime_metadata = _empty_runtime_metadata()


   
    @staticmethod
    def _is_responses_runtime_selected(runtime_selector) -> bool:
        if runtime_selector is None:
            return False
        if isinstance(runtime_selector, str):
            return runtime_selector.strip().lower() in {"responses", "responses_api"}
        return False

    def _select_runtime(self, runtime=None, runtime_selector=None, profile=None, session_mode=None):
        if isinstance(runtime, str):
            runtime_selector = runtime_selector or runtime
            runtime = None
        if runtime is not None:
            # Recreate known adapter types bound to this chat's own ai client so
            # that cloned/continued chats are fully independent (not sharing the
            # source chat's ai_client or any adapter state).
            if isinstance(runtime, ResponsesWebSocketAdapter):
                if session_mode == "new":
                    child_session = ResponsesWebSocketSession(mode="new")
                    # Seed the new session with lineage from the parent so that
                    # the child can continue from the parent's last response.
                    parent_session = runtime.session
                    child_session.last_response_id = getattr(parent_session, "last_response_id", None)
                    child_session.last_model = getattr(parent_session, "last_model", None)
                    child_session.last_store_value = getattr(parent_session, "last_store_value", None)
                    return ResponsesWebSocketAdapter(self.ai, session=child_session)
                return ResponsesWebSocketAdapter(self.ai, session=runtime.session)
            if isinstance(runtime, (ResponsesAdapter, ChatCompletionsAdapter)):
                return type(runtime)(self.ai)
            # Unknown / custom runtime objects are passed through verbatim to
            # preserve intentional injection (e.g. test doubles).
            return runtime

        if self._is_responses_runtime_selected(runtime_selector):
            self.ai.ensure_responses_support()
            if session_mode in {"inherit", "new"}:
                return ResponsesWebSocketAdapter(self.ai, session=ResponsesWebSocketSession(mode=session_mode))
            return ResponsesAdapter(self.ai)

        if isinstance(profile, dict) and self._is_responses_runtime_selected(profile.get("runtime")):
            self.ai.ensure_responses_support()
            if session_mode in {"inherit", "new"}:
                return ResponsesWebSocketAdapter(self.ai, session=ResponsesWebSocketSession(mode=session_mode))
            return ResponsesAdapter(self.ai)

        return ChatCompletionsAdapter(self.ai)

    def close_session(self):
        """Close the active runtime session if the selected runtime supports it."""
        runtime = getattr(self, "runtime", None)
        if hasattr(runtime, "close_session"):
            runtime.close_session()

    @classmethod
    def close_all_sessions(cls):
        """Close every tracked shared Responses WebSocket session."""
        ResponsesWebSocketAdapter.close_all_sessions()

    def reset(self) -> object:
        """Restore the chat to the state captured immediately after initialization."""
        self.name = self._initial_name
        self.params = self._initial_params
        self.messages = self._initial_messages
        if self._initial_system_message is not None:
            self.system_message = self._initial_system_message
        # Reset tools if initial registry was stored
        if hasattr(self, '_initial_registry'):
            # Re-register the initial tools
            self._local_registry = self._initial_registry
            # Re-load tools from the initial registry
            self._load_tools_from_params()
        self._last_runtime_metadata = _empty_runtime_metadata()
        return self
    
    def _load_tools_from_params(self):
        """Load tool definitions from params when initializing from YAML."""
        if not hasattr(self, 'params') or self.params is None:
            return
            
        # Check if tools are defined in params
        from ..utensil import get_all_utensils
        
        # If we already have tools defined, don't override
        if hasattr(self.params, 'tools') and self.params.tools is not None:
            return
            
        # Load tools from registry based on names in params
        if hasattr(self.params, 'tools') and isinstance(self.params.tools, list):
            tool_definitions = []
            
            for tool_def in self.params.tools:
                if not isinstance(tool_def, dict) or 'name' not in tool_def:
                    continue
                    
                # Look for matching tools in the registry
                all_tools = get_all_utensils()
                for registered_tool in all_tools:
                    if registered_tool.name == tool_def['name']:
                        # Found a matching tool, add its definition
                        tool_definitions.append(registered_tool.get_openai_tool())
                        break
                else:
                    # If no matching tool was found, create a placeholder definition
                    tool_func = {
                        "name": tool_def['name'],
                        "description": tool_def.get('description', f"Tool function: {tool_def['name']}")
                    }
                    
                    # Add parameters if present
                    if 'parameters' in tool_def:
                        parameters = {
                            "type": "object",
                            "properties": {},
                            "required": tool_def.get('required', [])
                        }
                        
                        for param_name, param_details in tool_def['parameters'].items():
                            param_info = {
                                "type": param_details.get('type', 'string')
                            }
                            
                            if 'description' in param_details:
                                param_info["description"] = param_details['description']
                                
                            if 'options' in param_details:
                                param_info["enum"] = param_details['options']
                                
                            parameters["properties"][param_name] = param_info
                            
                        tool_func["parameters"] = parameters
                    
                    tool_definitions.append({
                        "type": "function",
                        "function": tool_func
                    })
            
            if tool_definitions:
                self.set_tools(tool_definitions)
                if hasattr(self.params, 'tool_choice'):
                    self.params.tool_choice = self.params.tool_choice or "auto"


def _text_should_legacy_autoload(args, kwargs) -> bool:
    return len(args) <= 1 and "content" not in kwargs


def _chat_should_legacy_autoload(args, kwargs) -> bool:
    if args or "name" not in kwargs:
        return False
    creation_keys = {
        "messages",
        "params",
        "system",
        "utensils",
    }
    return not any(key in kwargs for key in creation_keys)


class _LegacyObjects:
    def __init__(self, cls, stash=None):
        self._cls = cls
        self._stash = stash

    @property
    def _collection(self):
        if self._stash is None:
            return self._cls.snapshots
        return self._cls.snapshots(self._stash)

    def __call__(self, stash):
        return self.__class__(self._cls, stash)

    def _postprocess(self, item):
        snapshot = getattr(item, "snapshot", None) if item is not None else None
        if item is not None and not hasattr(snapshot, "_ready"):
            after_load = getattr(item, "_refresh_after_snapshot_load", None)
            if after_load is None:
                after_load = getattr(item, "_after_legacy_autoload", None)
            if after_load is not None:
                after_load()
        return item

    def get(self, *args, **kwargs):
        return self._postprocess(self._collection.get(*args, **kwargs))

    def get_or_none(self, *args, **kwargs):
        return self._postprocess(self._collection.get_or_none(*args, **kwargs))

    def get_or_create(self, *args, **kwargs):
        return self._postprocess(self._collection.get_or_create(*args, **kwargs))

    def all(self, *args, **kwargs):
        for item in self._collection.all(*args, **kwargs):
            yield self._postprocess(item)

    def filter(self, *args, **kwargs):
        for item in self._collection.filter(*args, **kwargs):
            yield self._postprocess(item)


def _install_datafiles_compat(cls, should_autoload):
    original_init = cls.__init__

    def __init__(self, *args, **kwargs):
        autoload = should_autoload(args, kwargs)
        refresh_snapclass_config_stash(cls)
        original_init(self, *args, **kwargs)
        # snapclass attaches snapshot after the model's custom __init__ returns.
        # Install chatsnack's load/save hooks here so direct chat.snapshot.load()
        # gets the same runtime refresh as Chat.load() and Chat.objects.get().
        install_hooks = getattr(self, "_install_snapshot_compat_hooks", None)
        if install_hooks is not None:
            install_hooks()
        refresh_stash = getattr(self, "_refresh_snapshot_stash", None)
        if refresh_stash is not None:
            refresh_stash()
        snapshot = getattr(self, "snapshot", None)
        if autoload and snapshot is not None and snapshot.exists:
            snapshot.load(_initial=True)
            if not hasattr(snapshot, "_ready"):
                after_load = getattr(self, "_refresh_after_snapshot_load", None)
                if after_load is None:
                    after_load = getattr(self, "_after_legacy_autoload", None)
                if after_load is not None:
                    after_load()

    cls.__init__ = __init__
    cls.objects = _LegacyObjects(cls)


def _runtime_config_from_chat_params(chat):
    profile = getattr(chat.params, "profile", None) if chat.params is not None else None
    runtime_selector = getattr(chat.params, "runtime", None) if chat.params is not None else None
    session_mode = getattr(chat.params, "session", None) if chat.params is not None else None
    if runtime_selector is None and session_mode is None:
        runtime_selector, session_mode = _runtime_policy_from_env()
    elif runtime_selector is None and session_mode is not None:
        runtime_selector = "responses"
    return runtime_selector, profile, session_mode


def _apply_chat_constructor_overrides(chat):
    """Reapply live constructor knobs after a saved YAML load."""
    overrides = getattr(chat, "_chatsnack_constructor_overrides", {})
    if not overrides:
        return overrides
    if "engine" in overrides:
        chat.engine = overrides["engine"]
    if "model" in overrides:
        chat.model = overrides["model"]
    if "session" in overrides:
        chat.session = overrides["session"]
    if "stream" in overrides:
        chat.stream = overrides["stream"]
    if "auto_execute" in overrides:
        chat.auto_execute = overrides["auto_execute"]
    if "tool_choice" in overrides:
        chat.tool_choice = overrides["tool_choice"]
    if "auto_feed" in overrides:
        chat.auto_feed = overrides["auto_feed"]
    if "tool_search_handler" in overrides:
        chat.tool_search_handler = overrides["tool_search_handler"]
    return overrides


def _capture_chat_reset_state(chat):
    chat._initial_name = chat.name
    chat._initial_params = copy.copy(chat.params)
    chat._initial_messages = copy.copy(chat.messages)
    chat._initial_system_message = chat.system_message
    chat._initial_registry = getattr(chat, "_local_registry", None)


def _ensure_chat_live_state(self):
    # Native snapclass collection loaders materialize with __new__, bypassing
    # Chat.__init__. Keep that object usable without treating readiness as an
    # authoritative YAML load refresh.
    self._install_snapshot_compat_hooks()
    if not hasattr(self, "ai"):
        self.ai = AiClient()
    if not hasattr(self, "tool_search_handler"):
        self.tool_search_handler = None
    if not hasattr(self, "runtime"):
        runtime_selector, profile, session_mode = _runtime_config_from_chat_params(self)
        self.runtime = self._select_runtime(
            runtime_selector=runtime_selector,
            profile=profile,
            session_mode=session_mode,
        )
    if not hasattr(self, "_last_runtime_metadata"):
        self._last_runtime_metadata = _empty_runtime_metadata()
    if not hasattr(self, "_initial_name"):
        _capture_chat_reset_state(self)


def _refresh_chat_after_snapshot_load(self):
    # params/messages are persisted; runtime, reset baselines, and tool handler
    # state are live derivations. Rebuild them after any YAML-backed load.
    _ensure_chat_live_state(self)
    self._load_tools_from_params()
    overrides = _apply_chat_constructor_overrides(self)
    runtime_selector, profile, session_mode = _runtime_config_from_chat_params(self)
    if "runtime_selector" in overrides:
        runtime_selector = overrides["runtime_selector"]
    self.runtime = self._select_runtime(
        runtime=overrides.get("runtime"),
        runtime_selector=runtime_selector,
        profile=profile,
        session_mode=session_mode,
    )
    self._last_runtime_metadata = _empty_runtime_metadata()
    _capture_chat_reset_state(self)


Chat._refresh_after_snapshot_load = _refresh_chat_after_snapshot_load
Chat._after_legacy_autoload = _refresh_chat_after_snapshot_load
Chat._ready_after_snapshot_attached = _ensure_chat_live_state
_install_datafiles_compat(Text, _text_should_legacy_autoload)
_install_datafiles_compat(Chat, _chat_should_legacy_autoload)
