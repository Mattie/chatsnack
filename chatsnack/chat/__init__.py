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
class Chat(ChatQueryMixin, ChatSerializationMixin):
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
        """

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
        
        self._initial_name = self.name
        self._initial_params = copy.copy(self.params)
        self._initial_messages = copy.copy(self.messages)
        self._initial_system_message = self.system_message

        self.ai = AiClient()
   
    def reset(self) -> object:
        """ Resets the chat prompt to its initial state, returns itself """
        self.name = self._initial_name
        self.params = self._initial_params
        self.messages = self._initial_messages
        if self._initial_system_message is not None:
            self.system_message = self._initial_system_message
        return self
