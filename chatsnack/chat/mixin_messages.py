import json
from typing import Dict, List, Optional, Union, Any
from loguru import logger
import pprint

from datafiles import datafile

from .turns import (
    CANONICAL_SYSTEM_ROLE,
    DEVELOPER_ALIAS,
    NormalizedTurn,
    normalize_messages,
    denormalize_messages,
)


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
    def assistant(self, content: Union[str, List, Dict], chat = False) -> object:
        """
        Message added to the chat from the assistant ⭐
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        return self.add_message("assistant", content, chat)
    # easy aliases
    asst = assistant
    def tool(self, content: Union[str, Dict], chat = False) -> object:
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
    
    def developer(self, content: str, chat=False) -> object:
        """Alias for `system()` that accepts a `developer` role name."""
        return self.system(content, chat=chat)

    def add_message(self, role: str, content: Union[str, List, Dict], chat: bool = False) -> object:
        """
        Add a message to the chat, as role ('user', 'assistant', 'system', 'developer', 'tool' or 'include') with the content
        Returns: If chat is False returns this object for chaining. If chat is True, submits the 
        chat and returns a new Chat object that includes the message and response
        """
        # fully trim the role and left-trim the content if it's a string
        role = role.strip()
        # ``developer`` is an alias for ``system``
        if role == DEVELOPER_ALIAS:
            role = CANONICAL_SYSTEM_ROLE
        if isinstance(content, str):
            content = content.lstrip()
        
        logger.debug(f"Adding message to chat: {role} - {pprint.pformat(content)}")

        # Special handling for tool calls in assistant messages
        if role == "assistant" and isinstance(content, dict) and "tool_calls" in content:
            self.messages.append({"assistant": content})
        elif role == "assistant" and isinstance(content, list) and all(isinstance(item, dict) for item in content):
            # This might be tool calls formatted as a list of dicts like [{"name": "func_name", "arguments": {...}}]
            self.messages.append({"assistant": {"tool_calls": content}})
        # now we need to handle the tool message the same way as the assistant message, it should have a tool_call_id and content
        elif role == "tool" and isinstance(content, dict) and "tool_call_id" in content and "content" in content:
            tool_block = {"tool_call_id": content["tool_call_id"], "content": content["content"]}
            if "output_type" in content:
                tool_block["output_type"] = content["output_type"]
            self.messages.append({"tool": tool_block})
        else:
            self.messages.append({role: content})
            
        if not chat:
            return self
        else:
            return self.chat()
        
    def add_messages_json(self, json_messages: str, escape: bool = True):
        """Add messages from a JSON string while properly handling tool calls and responses."""
        incoming_messages = json.loads(json_messages)

        logger.debug(f"Added messages to chat from JSON: {pprint.pformat(incoming_messages)}")
        
        for message in incoming_messages:
            if "role" in message:
                role = message["role"]
                content = message.get("content")

                if role == "assistant" and "tool_calls" in message:
                    # Format assistant message with tool_calls to match our internal structure
                    tool_calls = []
                    for tool_call in message["tool_calls"]:
                        # Extract the function data
                        function_data = tool_call.get("function", {})
                        
                        # Handle different formats of arguments (string or already parsed)
                        arguments = function_data.get("arguments", "{}")
                        if isinstance(arguments, str):
                            # Keep arguments as a string, which is what OpenAI expects
                            pass
                        else:
                            # Convert dict back to string for consistency
                            arguments = json.dumps(arguments)
                            
                        tool_calls.append({
                            "id": tool_call.get("id", ""),
                            "type": tool_call.get("type", "function"),
                            "function": {
                                "name": function_data.get("name", ""),
                                "arguments": arguments
                            }
                        })
                        
                    # Create the assistant message with proper structure
                    self.assistant({"content": content, "tool_calls": tool_calls})
                    
                elif role == "tool":
                    # Handle tool response messages
                    tool_call_id = message.get("tool_call_id", "")
                    tool_content = message.get("content", "")
                    output_type = message.get("output_type")
                    
                    # Add as a tool message with proper structure
                    payload = {"tool_call_id": tool_call_id, "content": tool_content}
                    if output_type:
                        payload["output_type"] = output_type
                    self.tool(payload)
                    
                else:
                    # Standard message types (user, system)
                    if escape and isinstance(content, str):
                        content = content.replace("{", "{{").replace("}", "}}")

                    attachments = {}
                    if message.get("images"):
                        attachments["images"] = message["images"]
                    if message.get("files"):
                        attachments["files"] = message["files"]

                    if role and attachments:
                        # Attachment-only turns are valid in Phase 3, so we keep
                        # the expanded structure even when there is no text field.
                        expanded = {}
                        if content:
                            expanded["text"] = content
                        expanded.update(attachments)
                        self.messages.append({role: expanded})
                    elif content and role:
                        # Generic role handling
                        self.messages.append({role: content})
                    else:
                        raise ValueError("Invalid message format, empty role or content in JSON messages")
            else:
                raise ValueError("Invalid message format, 'role' key is missing")
        # and the self.messages after it's done
        logger.debug(f"Chat messages after adding JSON: {pprint.pformat(self.messages)}")

    @staticmethod
    def process_tool_calls(tool_calls, escape):
        processed_calls = []
        for call in tool_calls:
            function = call.get("function", {})
            arguments = function.get("arguments")
            
            # Try to parse arguments as JSON if it's a string
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    pass  # Keep as string if can't parse
                    
            call_data = {
                "name": function.get("name"),
                "arguments": arguments
            }
            if escape and isinstance(arguments, str):
                call_data["arguments"] = arguments.replace("{", "{{").replace("}", "}}")
            processed_calls.append(call_data)
        return {"tool_calls": processed_calls}

    @staticmethod
    def process_list_content(content_list, escape):
        processed_content = []
        for item in content_list:
            item_data = {k: v for k, v in item.items() if k != 'type'}
            if escape:
                item_data = {k: v.replace("{", "{{").replace("}", "}}") if isinstance(v, str) else v for k, v in item_data.items()}
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
            # Only append if the current content is a string and not a tool call
            if isinstance(last_message["assistant"], str) and isinstance(content, str):
                last_message["assistant"] += content
                # replace the last message with the updated one
                self.messages[-1] = last_message
            else:
                # If it's a tool call or content is not a string, add a new message
                self.assistant(content)
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
        """ Returns the first system (or developer alias) message, if any """
        for _message in self.messages:
            message = self._msg_dict(_message)
            if "system" in message:
                return message["system"]
            if DEVELOPER_ALIAS in message:
                return message[DEVELOPER_ALIAS]
        return None
    
    @system_message.setter
    def system_message(self, value: str):
        """ Set the system message """
        # loop through the messages and replace the first 'system' or 'developer' message with this one
        replaced = False
        for i in range(len(self.messages)):
            _message = self.messages[i]
            message = self._msg_dict(_message)
            if "system" in message or DEVELOPER_ALIAS in message:
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
            # We need to ensure all string values are escaped
            escaped_call = {}
            for k, v in call.items():
                if isinstance(v, str):
                    escaped_call[k] = v.replace("{", "{{").replace("}", "}}")
                elif isinstance(v, dict):
                    # Handle nested dictionaries like arguments
                    escaped_args = {}
                    for arg_k, arg_v in v.items():
                        if isinstance(arg_v, str):
                            escaped_args[arg_k] = arg_v.replace("{", "{{").replace("}", "}}")
                        else:
                            escaped_args[arg_k] = arg_v
                    escaped_call[k] = escaped_args
                else:
                    escaped_call[k] = v
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
            message = self._msg_dict(_message)

            logger.trace(f"Processing message: {pprint.pformat(message)}")

            for role, content in message.items():
                # Normalize developer → system for API calls
                api_role = CANONICAL_SYSTEM_ROLE if role == DEVELOPER_ALIAS else role

                if role == "include" and includes_expanded:
                    include_chatprompt = self.objects.get_or_none(content)
                    if include_chatprompt is None:
                        raise ValueError(f"Could not find 'include' prompt with name: {content}")
                    new_messages.extend(include_chatprompt.get_messages())
                elif api_role == "assistant" and isinstance(content, dict) and "tool_calls" in content:
                    logger.trace(f"Assistant message found with tool calls: {pprint.pformat(content)}")
                    tool_calls = []
                    for tool_call in content["tool_calls"]:
                        if not isinstance(tool_call, dict):
                            continue
                        tc = {
                            "id": tool_call.get("id", ""),
                            "type": tool_call.get("type", "function"),
                        }
                        if isinstance(tool_call.get("function"), dict):
                            tc["function"] = {
                                "name": tool_call.get("function", {}).get("name", ""),
                                "arguments": tool_call.get("function", {}).get("arguments", "{}"),
                            }
                        if isinstance(tool_call.get("payload"), dict):
                            tc["payload"] = tool_call["payload"]
                        tool_calls.append(tc)
                    new_messages.append({"role": api_role, "content": content.get('text', content.get('content')), "tool_calls": tool_calls})
                elif api_role == "tool" and isinstance(content, dict) and "tool_call_id" in content and "content" in content:
                    tool_msg = {"role": api_role, "content": content["content"], "tool_call_id": content["tool_call_id"]}
                    if "output_type" in content:
                        tool_msg["output_type"] = content["output_type"]
                    new_messages.append(tool_msg)
                elif isinstance(content, dict) and (
                    "text" in content or "images" in content or "files" in content
                ):
                    # Expanded turn block (Phase 3) – build the API message.
                    # Carry through images and files metadata alongside the text
                    # so runtime adapters can build multi-part input items.
                    # Attachment-only turns (no text) are also valid.
                    api_msg = {"role": api_role, "content": content.get("text", "")}
                    if content.get("images"):
                        api_msg["images"] = content["images"]
                    if content.get("files"):
                        api_msg["files"] = content["files"]
                    new_messages.append(api_msg)
                else:
                    new_messages.append({"role": api_role, "content": content})

        return new_messages
