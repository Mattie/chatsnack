import json
from typing import Dict, List, Optional, Union, Any

from datafiles import datafile



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
    def assistant(self, content: Union[str, List], chat = False) -> object:
        """
        Message added to the chat from the assistant ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        return self.add_message("assistant", content, chat)
    # easy aliases
    asst = assistant
    def tool(self, content: str, chat = False) -> object:
        """
        Message added to the chat which is a tool response ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        return self.add_message("tool", content, chat)
    
    def include(self, chatprompt_name: str = None, chat = False) -> object:
        """
        Message added to the chat that is a reference to another ChatPrompt where the messages will be inserted in this spot right before formatting ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """        
        return self.add_message("include", chatprompt_name, chat)
    def add_message(self, role: str, content: Union[str, List], chat: bool = False) -> object:
        """
        Add a message to the chat, as role ('user', 'assistant', 'system' or 'include') with the content
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        # fully trim the role and left-trim the content
        role = role.strip()
        if isinstance(content, str):
            content = content.lstrip()
        self.messages.append({role: content})
        if not chat:
            return self
        else:
            return self.chat()
        
    def add_messages_json(self, json_messages: str, escape: bool = True):
        incoming_messages = json.loads(json_messages)
        for message in incoming_messages:
            if "role" in message:
                role = message["role"]
                content = message.get("content")

                if role == "assistant" and "tool_calls" in message:
                    # Handle the assistant with tool calls
                    content = self.process_tool_calls(message["tool_calls"], escape)

                elif isinstance(content, list):
                    # Process list content by removing 'type' key and keeping the value
                    content = self.process_list_content(content, escape)

                elif escape:
                    content = content.replace("{", "{{").replace("}", "}}")

                self.messages.append({role: content})
            else:
                raise ValueError("Invalid message format, 'role' key is missing")

    @staticmethod
    def process_tool_calls(tool_calls, escape):
        processed_calls = []
        for call in tool_calls:
            function = call.get("function", {})
            call_data = {function.get("name"): function.get("arguments")}
            if escape:
                call_data = {k: v.replace("{", "{{").replace("}", "}}") for k, v in call_data.items()}
            processed_calls.append(call_data)
        return processed_calls

    @staticmethod
    def process_list_content(content_list, escape):
        processed_content = []
        for item in content_list:
            item_data = {k: v for k, v in item.items() if k != 'type'}
            if escape:
                item_data = {k: v.replace("{", "{{").replace("}", "}}") for k, v in item_data.items()}
            processed_content.append(item_data)
        return processed_content
            
    def add_or_update_last_assistant_message(self, content: str):
        """
        Adds a final assistant message (or appends to the end of the last assistant message)
        """
        # get the last message in the list
        last_message = self.messages[-1]
        # get the dict version
        last_message = self._msg_dict(last_message)

        # if it's an assistant message, append to it
        if "assistant" in last_message:
            last_message["assistant"] += content
            # replace the last message with the updated one
            self.messages[-1] = last_message
        else:
            # otherwise add a new assistant message
            self.assistant(content)

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


    @staticmethod
    def _escape_tool_calls(tool_calls: List[Dict[str, str]]) -> List[Dict[str, str]]:
        escaped_calls = []
        for call in tool_calls:
            escaped_call = {k: v.replace("{", "{{").replace("}", "}}") for k, v in call.items()}
            escaped_calls.append(escaped_call)
        return escaped_calls

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
