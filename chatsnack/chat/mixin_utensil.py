import asyncio
import json
from typing import Dict, List, Optional, Union, Any

from datafiles import datafile
from loguru import logger

from ..utensil import get_openai_tools, handle_tool_call, UtensilFunction, UtensilGroup
from .mixin_params import ChatParams  # Changed to import from mixin_params instead


class ChatUtensilMixin:
    """Mixin for handling tools in chat."""
    
    def __init__(self, *args, **kwargs):
        # Extract utensils from kwargs if present
        if "utensils" in kwargs:
            self.set_utensils(kwargs.pop("utensils"))
        
        # Extract tool execution settings - we'll set these in the main params object
        # Note: We don't need to initialize params here as the Chat constructor does that
        if "auto_execute" in kwargs and hasattr(self, 'params'):
            self.params.auto_execute = kwargs.pop("auto_execute")
            
        if "tool_choice" in kwargs and hasattr(self, 'params'):
            self.params.tool_choice = kwargs.pop("tool_choice")
            
        # Continue with regular initialization
        super().__init__(*args, **kwargs)
        
        # After initialization, load tools from params if available
        self._load_tools_from_params()

    def __post_init__(self):
        """Called after the chat is initialized from a datafile."""
        super().__post_init__()
        
        # Initialize AI client if needed
        if not hasattr(self, 'ai'):
            from ..aiclient import AiClient
            self.ai = AiClient()
        
        # Load tools from params
        self._load_tools_from_params()

    def _load_tools_from_params(self):
        """Load tool definitions from params when initializing from YAML."""
        if not hasattr(self, 'params') or self.params is None:
            return
            
        # Check if tools are defined in params - nothing to do if they aren't
        if not hasattr(self.params, 'tools') or self.params.tools is None:
            return
            
        # Load tools from registry based on names in params if needed
        tools_list = self.params.tools
        if not isinstance(tools_list, list) or not tools_list:
            return
            
        # If tools are already deserialized properly, no further action needed
        if hasattr(self.params, 'get_tools'):
            return
            
        # Ensure tools are properly deserialized
        from ..utensil import get_all_utensils
        
        tool_definitions = []
        all_tools = get_all_utensils()
        
        for tool_def in tools_list:
            if not isinstance(tool_def, dict) or 'name' not in tool_def:
                continue
                
            # Look for matching tools in the registry
            tool_found = False
            for registered_tool in all_tools:
                if registered_tool.name == tool_def['name']:
                    # Found a matching tool, add its definition
                    tool_definitions.append(registered_tool.get_openai_tool())
                    tool_found = True
                    break
                    
            if not tool_found:
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
        
        # Store the deserialized tools
        if tool_definitions and hasattr(self, 'params') and self.params is not None:
            self.params.set_tools(tool_definitions)
            if hasattr(self.params, 'tool_choice') and self.params.tool_choice is None:
                self.params.tool_choice = "auto"

    def set_utensils(self, utensils):
        """
        Set the utensils available for this chat.
        
        Args:
            utensils: Can be a list of functions, UtensilFunction objects,
                     UtensilGroup objects, or a dictionary mapping names to functions.
        """
        if utensils is None or not hasattr(self, 'params'):
            return
            
        if isinstance(utensils, dict):
            # Convert dictionary of name -> function to list of functions
            utensils = list(utensils.values())
            
        # Import here to avoid circular imports
        from ..utensil import get_tool_definitions
        
        # Get ToolDefinition objects directly
        tool_definitions = get_tool_definitions(utensils)
        
        # Store the tools directly
        if not self.params:
            self.params = ChatParams()
        self.params.tools = tool_definitions
        
        # Set default tool_choice if not already set
        if self.params.tool_choice is None:
            self.params.tool_choice = "auto"
    
    async def _submit_for_response_and_prompt(self, **additional_vars):
        """Override to add tools handling to the API calls."""
        prompter = self
        # if the user in additional_vars, we're going to instead deepcopy this prompt into a new prompt and add the .user() to it
        if "__user" in additional_vars:
            new_chatprompt = self.copy()
            new_chatprompt.user(additional_vars["__user"])
            prompter = new_chatprompt
            # remove __user from additional_vars
            del additional_vars["__user"]
            
        prompt = await prompter._build_final_prompt(additional_vars)
        
        # Handle parameters including tools
        kwargs = {}
        if hasattr(self, 'params') and self.params is not None:
            kwargs = self.params._get_non_none_params()
            
            # Add tools if available
            if hasattr(self.params, 'tools') and self.params.tools:
                # Use get_tools to deserialize any serialized JSON
                kwargs['tools'] = self.params.get_tools()
                if self.params.tool_choice:
                    kwargs['tool_choice'] = self.params.tool_choice
            
        if hasattr(self, 'params') and self.params and self.params.stream:
            # we're streaming so we need to use the wrapper object
            listener = self.ChatStreamListener(self.ai, prompt, **kwargs)
            return prompt, listener
        else:
            # Use the modified completion method that handles tools
            return prompt, await self._handle_tool_calls(prompt, **kwargs)
    
    async def _handle_tool_calls(self, prompt, **kwargs):
        """Handle potential tool calls in the API response."""
        if isinstance(prompt, list):
            messages = prompt
        else:
            messages = json.loads(prompt)
            
        response = await self.ai.aclient.chat.completions.create(
            messages=messages,
            **kwargs
        )
        
        # Check if the model responded with a tool call
        choice = response.choices[0]
        message = choice.message
        
        if hasattr(message, 'tool_calls') and message.tool_calls:
            # The model wants to call a tool
            tool_calls = message.tool_calls
            
            # Add the assistant's tool call to the messages
            tool_call_list = []
            for tool_call in tool_calls:
                try:
                    args_dict = json.loads(tool_call.function.arguments)
                    tool_call_list.append({
                        "name": tool_call.function.name,
                        "arguments": args_dict
                    })
                except json.JSONDecodeError:
                    # Handle invalid JSON
                    tool_call_list.append({
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    })
                    
            self.assistant({"tool_calls": tool_call_list})
            
            # Check if we should auto-execute the tool
            if hasattr(self, 'params') and self.params.auto_execute:
                # Execute the tool call and get the result
                for tool_call in tool_calls:
                    tool_call_dict = {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    
                    result = self.execute_tool_call(tool_call_dict)
                    # result = handle_tool_call(tool_call_dict)
                    
                    # Add the tool response to the messages
                    self.tool_response(result)
                    
                    # Add the tool result to the API messages for a follow-up
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result) if isinstance(result, dict) else str(result)
                    })
                
                # Get the AI's response to the tool result
                follow_up_response = await self.ai.aclient.chat.completions.create(
                    messages=messages,
                    **{k: v for k, v in kwargs.items() if k != 'tools' and k != 'tool_choice'}
                )
                
                # Return the AI's final response
                return follow_up_response.choices[0].message.content
            
            # Return a message about the tool call if not auto-executing
            return f"Tool call requested: {tool_calls[0].function.name}. Execute manually with .tool_response(result)"
            
        # Regular response (no tool calls)
        return message.content
        
    # Add a class for stream handling within the mixin to avoid circular imports
    class ChatStreamListener:
        """Stream listener for handling streamed responses."""
        
        def __init__(self, ai, prompt, **kwargs):
            """Initialize the stream listener."""
            if isinstance(prompt, list):
                self.prompt = prompt
            else:
                self.prompt = json.loads(prompt)
            self._response_gen = None
            self.is_complete = False
            self.current_content = ""
            self.response = ""
            self.ai = ai
            out = kwargs.copy()
            if "model" not in out or len(out["model"]) < 2:
                # if engine is set, use that
                if "engine" in out:
                    out["model"] = out["engine"]
                    # remove engine for newest models as of Nov 13 2023
                    del out["engine"]
                else:
                    out["model"] = "chatgpt-4o-latest"
            self.kwargs = out

        async def start_a(self):
            """Start the stream in async mode."""
            # if stream=True isn't in the kwargs, add it
            if not self.kwargs.get('stream', False):
                self.kwargs['stream'] = True
            self._response_gen = await self.ai.aclient.chat.completions.create(messages=self.prompt,**self.kwargs)
            return self

        async def _get_responses_a(self):
            """Get responses in async mode."""
            try:
                async for respo in self._response_gen:
                    resp = respo.model_dump()
                    if "choices" in resp:
                        if resp['choices'][0]['finish_reason'] is not None:
                            self.is_complete = True
                        if 'delta' in resp['choices'][0]:
                            content = resp['choices'][0]['delta']['content']
                            if content is not None:
                                self.current_content += content
                            yield content if content is not None else ""
            finally:
                self.is_complete = True
                self.response = self.current_content

        def __aiter__(self):
            """Make the object iterable in async mode."""
            return self._get_responses_a()

        def start(self):
            """Start the stream in sync mode."""
            # if stream=True isn't in the kwargs, add it
            if not self.kwargs.get('stream', False):
                self.kwargs['stream'] = True        
            self._response_gen = self.ai.client.chat.completions.create(messages=self.prompt,**self.kwargs)
            return self

        def _get_responses(self):
            """Get responses in sync mode."""
            try:
                for respo in self._response_gen:
                    resp = respo.model_dump()
                    if "choices" in resp:
                        if resp['choices'][0]['finish_reason'] is not None:
                            self.is_complete = True
                        if 'delta' in resp['choices'][0]:
                            content = resp['choices'][0]['delta']['content']
                            if content is not None:
                                self.current_content += content
                            yield content if content is not None else ""
            finally:
                self.is_complete = True
                self.response = self.current_content

        def __iter__(self):
            """Make the object iterable in sync mode."""
            return self._get_responses()

    def _serialize_tools(self, tools_list: List[Dict]) -> List[Dict]:
        """
        Convert tools to a serializable format for datafiles.
        """
        if not tools_list:
            return None
            
        # Create a serializable version of the tools
        serializable_tools = []
        
        for tool in tools_list:
            # Make a shallow copy of the tool
            tool_copy = dict(tool)
            
            # Handle function field
            if "function" in tool_copy and isinstance(tool_copy["function"], dict):
                function_copy = dict(tool_copy["function"])
                
                # Serialize the parameters field to a string if it's a dict
                if "parameters" in function_copy and isinstance(function_copy["parameters"], dict):
                    function_copy["parameters_json"] = json.dumps(function_copy["parameters"])
                    del function_copy["parameters"]
                
                tool_copy["function"] = function_copy
                
            # Convert any other complex nested structures to JSON strings
            # Collect keys to modify first to avoid modifying during iteration
            keys_to_modify = []
            for key, value in tool_copy.items():
                if isinstance(value, (dict, list)):
                    keys_to_modify.append(key)
            
            # Now apply the changes
            for key in keys_to_modify:
                tool_copy[key + "_json"] = json.dumps(tool_copy[key])
                del tool_copy[key]
            
            serializable_tools.append(tool_copy)
            
        return serializable_tools

    def _deserialize_tools(self, tools: List[Dict]) -> List[Dict]:
        """
        Convert serialized tools back to their original structure.
        """
        if not tools:
            return []
            
        # Create a deserialized version of the tools
        deserialized_tools = []
        
        for tool in tools:
            # Make a shallow copy of the tool
            tool_copy = dict(tool)
            
            # Handle function field
            if "function" in tool_copy and isinstance(tool_copy["function"], dict):
                function_copy = dict(tool_copy["function"])
                
                # Deserialize the parameters field from string
                if "parameters_json" in function_copy:
                    function_copy["parameters"] = json.loads(function_copy["parameters_json"])
                    del function_copy["parameters_json"]
                
                tool_copy["function"] = function_copy
            
            # Deserialize any other JSON strings
            keys_to_process = [k for k in tool_copy.keys() if k.endswith("_json")]
            for key in keys_to_process:
                original_key = key[:-5]  # Remove the _json suffix
                tool_copy[original_key] = json.loads(tool_copy[key])
                del tool_copy[key]
                
            deserialized_tools.append(tool_copy)
            
        return deserialized_tools
    
    def execute_tool_call(self, tool_call):
        """Process a tool call and return the result"""
        from ..utensil import handle_tool_call
        
        # log this call
        logger.debug(f"Processing tool call: {tool_call}")
        # Use the local registry if available
        local_registry = getattr(self, '_local_registry', None)
        # log the local registry if it exists
        if local_registry:
            logger.debug(f"Local registry: {local_registry}")
        else:
            logger.debug("No local registry found")

        return handle_tool_call(tool_call, local_registry=local_registry)

    def set_tools(self, tools_list: List[Dict]):
        """
        Set the tools with proper serialization for nested structures.
        """
        if not hasattr(self, 'params') or tools_list is None:
            return
            
        # Store tools in params
        self.params.set_tools(tools_list)
            
    def get_tools(self) -> List[Dict]:
        """
        Get the tools with complex structures deserialized.
        """
        if not hasattr(self, 'params') or self.params is None:
            return []
        tools = self.params.get_tools() 
        # log the deserialized tools
        logger.debug(f"Deserialized tools: {tools}")
        # Deserialize from params
        return tools
        
    def handle_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a tool call response from the LLM.
        
        Args:
            tool_call: The tool call information from the API
            
        Returns:
            Result of the tool execution
        """
        # This is a placeholder for the actual implementation
        # which would typically:
        # 1. Find the appropriate tool executor
        # 2. Parse and validate arguments
        # 3. Execute the tool or prompt for confirmation
        # 4. Format and return results
        
        logger.debug(f"Tool call received: {tool_call}")
        
        # Check if we should auto-execute
        if not self.params.auto_execute:
            return {"status": "not_executed", "message": "Auto-execution disabled"}
           
        
        # This would call the actual tool executor
        try:
            # Import here to avoid circular imports
            from ..utensil import handle_tool_call
            return handle_tool_call(tool_call)
        except Exception as e:
            logger.error(f"Error handling tool call: {e}")
            return {"error": str(e)}