import json
from typing import Dict, List, Optional

from datafiles import datafile

@datafile
class ChatMessage:
    system: Optional[str] = None
    user: Optional[str] = None
    assistant: Optional[str] = None
    include: Optional[str] = None

    @property
    def message(self) -> Dict[str, str]:
        """ Returns the message in the form of a dictionary """
        # use the format {'role': 'content'} from among its datafields
        return {field.name: getattr(self, field.name) for field in self.__dataclass_fields__.values() if getattr(self, field.name) is not None}


# Define the Message Management mixin
class ChatMessagesMixin:
    # specific message types, can be chained together
    def system(self, content: str, chat = False) -> object:
        """
        Adds or sets the system message in the chat prompt ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        self.system_message = content
        if not chat:
            return self
        else:
            return self.chat()
    def user(self, content: str, chat = False) -> object:
        """
        Message added to the chat from the user ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        return self.add_message("user", content, chat)
    def assistant(self, content: str, chat = False) -> object:
        """
        Message added to the chat from the assistant ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        return self.add_message("assistant", content, chat)
    # easy aliases
    asst = assistant

    def include(self, chatprompt_name: str = None, chat = False) -> object:
        """
        Message added to the chat that is a reference to another ChatPrompt where the messages will be inserted in this spot right before formatting ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """        
        return self.add_message("include", chatprompt_name, chat)
    def add_message(self, role: str, content: str, chat: bool = False) -> object:
        """
        Add a message to the chat, as role ('user', 'assistant', 'system' or 'include') with the content
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        # fully trim the role and left-trim the content
        role = role.strip()
        content = content.lstrip()
        self.messages.append({role: content})
        if not chat:
            return self
        else:
            return self.chat()
    def add_messages_json(self, json_messages: str, escape: bool = True):
        """ Adds messages from an OpenAI json string to the chat prompt """
        incoming_messages = json.loads(json_messages)
        for message in incoming_messages:
            # convert from the OpenAI format to the format we use
            if "role" in message and "content" in message:
                if escape:
                    # escape the { and } characters
                    message["content"] = message["content"].replace("{", "{{").replace("}", "}}")
                    message["role"] = message["role"].replace("{", "{{").replace("}", "}}")
                self.add_message(message["role"], message["content"])
            else:
                raise ValueError("Invalid message format, a 'role' or 'content' key was missing")

    # define a read-only attribute "last" that returns the last message in the list
    @property
    def last(self) -> str:
        """ Returns the value of the last message in the chat prompt (any)"""
        # last message is a dictionary, we need the last value in the dictionary
        if len(self.messages) > 0:
            last_message = self.messages[-1]
            return last_message[list(last_message.keys())[-1]]
        else:
            return None

    @property
    def response(self) -> str:
        """ Returns the value of the last assistant message in the chat prompt ⭐"""
        last_assistant_message = None
        for _message in self.messages:
            message = self._msg_dict(_message)
            if "assistant" in message:
                last_assistant_message = message["assistant"]
        return last_assistant_message

    @property
    def system_message(self) -> str:
        """ Returns the first system message, if any """
        # get the first message that has a key of "system"
        for _message in self.messages:
            message = self._msg_dict(_message)
            if "system" in message:
                return message["system"]
        return None
    
    @system_message.setter
    def system_message(self, value: str):
        """ Set the system message """
        # loop through the messages and replace the first 'system' messages with this one
        replaced = False
        for i in range(len(self.messages)):
            _message = self.messages[i]
            message = self._msg_dict(_message)
            if "system" in message:
                self.messages[i] = {"system": value}
                replaced = True
                break
        if not replaced:
            # system message always goes first
            self.messages.insert(0, {"system": value})


    def _msg_dict(self, msg: object) -> dict:
        """ Returns a message as a dictionary """
        if msg is None:
            return None
        if isinstance(msg, dict):
            return msg
        else:
            return msg.message

    def get_messages(self, includes_expanded=True) -> List[Dict[str, str]]:
        """ Returns a list of messages with any included named chat files expanded """
        new_messages = []
        for _message in self.messages:
            # if it's a dict then
            message = self._msg_dict(_message)
            for role, content in message.items():
                if role == "include" and includes_expanded:
                    # we need to load the chatprompt and get the messages from it
                    include_chatprompt = self.objects.get_or_none(content)
                    if include_chatprompt is None:
                        raise ValueError(f"Could not find 'include' prompt with name: {content}")
                    # get_expanded_messages from the include_chatprompt and add them to the new_messages, they're already formatted how we want
                    new_messages.extend(include_chatprompt.get_messages())
                else:
                    new_messages.append({"role": role, "content": content})
        return new_messages

