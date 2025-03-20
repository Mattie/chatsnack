import copy
import uuid
from dataclasses import field
from datetime import datetime
from typing import Dict, List, Optional, Union

from datafiles import datafile

from ..aiclient import AiClient
from ..defaults import CHATSNACK_BASE_DIR
from .mixin_query import ChatQueryMixin
from .mixin_params import ChatParams, ChatParamsMixin
from .mixin_serialization import DatafileMixin, ChatSerializationMixin
from .mixin_utensil import ChatUtensilMixin 


# WORKAROUND: Disable the datafiles warnings about Schema type enforcement which our users are less concerned about
import log
log.init(level=log.WARNING)
log.silence('datafiles', allow_warning=False)


########################################################################################################################
# Core datafile classes of Plunkychat
# (1) Chat, high-level class that symbolizes a prompt/request/response, can reference other Chat objects to chain
# (2) ChatParams, used only in Chat, includes parameters like engine name and other OpenAI params.
# (3) Text, this is a text blob we save to disk, can be used as a reference inside chat messages ('snack fillings')

@datafile(CHATSNACK_BASE_DIR + "/{self.name}.txt", manual=True)
class Text(DatafileMixin):
    name: str
    content: Optional[str] = None
    # TODO: All Text and Chat objects should automatically be added as snack fillings (even if not saved to disk)


@datafile(CHATSNACK_BASE_DIR + "/{self.name}.yml", manual=True, init=False)
class Chat(ChatQueryMixin, ChatSerializationMixin, ChatUtensilMixin):
    """ A chat prompt that can be expanded into a chat ⭐"""
    # title should be just like above but with a GUID at the end
    name: str = field(default_factory=lambda: f"_ChatPrompt-{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4()}")
    params: Optional[ChatParams] = None
    messages: List[Dict[str,Union[str,List[Dict[str,str]]]]] = field(default_factory=lambda: [])

    def __init__(self, *args, **kwargs):
        """ 
        Initializes the chat prompt
        :param args: if we get one arg, we'll assume it's the system message
                        if we get two args, the first is the name and the second is the system message

        :param kwargs: (keyword arguments are as follows)
        :param name: the name of the chat prompt (optional, defaults to _ChatPrompt-<date>-<uuid>)
        :param params: the engine parameters (optional, defaults to None)
        :param messages: the messages (optional, defaults to [])
        :param system: the initial system message (optional, defaults to None)
        :param engine: the engine name (optional, defaults to None, will overwrite params if specified)
        :param utensils: tools available to this chat (optional, defaults to None)
        :param auto_execute: whether to automatically execute tool calls (optional, defaults to True)
        :param auto_feed: whether to automatically feed tool results back to the model (optional, defaults to True)
        :param tool_choice: how to choose which tool to use (optional, defaults to "auto")
        """
        # Extract utensil-related parameters first
        utensils = kwargs.pop("utensils", None)
        auto_execute = kwargs.pop("auto_execute", None)
        tool_choice = kwargs.pop("tool_choice", None)
        auto_feed = kwargs.pop("auto_feed", None)
        
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
            from ..utensil import extract_utensil_functions, get_openai_tools
            
            # Store local registry of utensil functions
            self._local_registry = utensils  # Store original objects, extract when needed
            
            # Get tool definitions for OpenAI API
            tools_list = get_openai_tools(utensils)
            
            # Store and serialize tool definitions
            self.set_tools(tools_list)
        
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


   
    def reset(self) -> object:
        """ Resets the chat prompt to its initial state, returns itself """
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