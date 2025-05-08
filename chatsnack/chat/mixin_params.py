import re
import json
from typing import Optional, List, Dict, Any, Union, Literal
from dataclasses import dataclass, field
from datafiles import datafile

@datafile
class ParameterProperty:
    """Represents a property in the parameters schema"""
    type: str
    description: Optional[str] = None
    enum: Optional[List[str]] = None

@datafile
class ParameterSchema:
    """Represents a parameter schema in JSON Schema format"""
    type: str
    description: Optional[str] = None
    enum: Optional[List[str]] = None
    # Add other common JSON Schema fields as needed
    format: Optional[str] = None
    default: Optional[Union[str, int, float, bool]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    minLength: Optional[int] = None
    maxLength: Optional[int] = None
    pattern: Optional[str] = None
    
    # JSON strings to store complex nested structures
    properties_json: Optional[str] = None  # Store properties as JSON string
    items_json: Optional[str] = None  # Store array items schema as JSON string
    additional_properties_json: Optional[str] = None  # Store additionalProperties as JSON string
    required_json: Optional[str] = None  # Store required fields list as JSON string
    
    def to_dict(self) -> Dict:
        """Convert to the dictionary format expected by the API"""
        result = {"type": self.type}
        
        # Add optional fields if present
        if self.description:
            result["description"] = self.description
            
        if self.enum:
            result["enum"] = self.enum
            
        # Add other fields conditionally
        for attr in ["format", "default", "minimum", "maximum", "minLength", "maxLength", "pattern"]:
            value = getattr(self, attr, None)
            if value is not None:
                result[attr] = value
        
        # Handle nested properties from JSON string
        if self.properties_json:
            try:
                result["properties"] = json.loads(self.properties_json)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Handle items from JSON string
        if self.items_json:
            try:
                result["items"] = json.loads(self.items_json)
            except (json.JSONDecodeError, TypeError):
                pass
                
        # Handle additionalProperties from JSON string
        if self.additional_properties_json:
            try:
                result["additionalProperties"] = json.loads(self.additional_properties_json)
            except (json.JSONDecodeError, TypeError):
                pass
                
        # Handle required fields from JSON string
        if self.required_json:
            try:
                result["required"] = json.loads(self.required_json)
            except (json.JSONDecodeError, TypeError):
                pass
                
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ParameterSchema':
        """Create a ParameterSchema from an API-format dictionary"""
        schema = cls(
            type=data.get("type", "string"),
            description=data.get("description"),
            enum=data.get("enum"),
            format=data.get("format"),
            default=data.get("default"),
            minimum=data.get("minimum"),
            maximum=data.get("maximum"),
            minLength=data.get("minLength"),
            maxLength=data.get("maxLength"),
            pattern=data.get("pattern")
        )
        
        # Handle properties (object fields)
        if "properties" in data and data["properties"]:
            schema.properties_json = json.dumps(data["properties"])
            
        # Handle items (array items schema)
        if "items" in data and data["items"]:
            schema.items_json = json.dumps(data["items"])
            
        # Handle additionalProperties (for object schemas)
        if "additionalProperties" in data:
            schema.additional_properties_json = json.dumps(data["additionalProperties"])
            
        # Handle required fields
        if "required" in data and data["required"]:
            schema.required_json = json.dumps(data["required"])
            
        return schema

@datafile
class FunctionDefinition:
    """Represents a function definition within a tool"""
    name: str
    description: Optional[str] = None
    parameters: Dict[str, ParameterSchema] = field(default_factory=dict)
    required: List[str] = field(default_factory=list)
    strict: Optional[bool] = None
    
    # For storing complex parameter schema
    parameters_json: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to the dictionary format expected by the API"""
        result = {
            "name": self.name
        }
        
        if self.description:
            result["description"] = self.description
        
        # Handle parameters - use JSON if available, otherwise build from individual parameters
        if self.parameters_json:
            try:
                result["parameters"] = json.loads(self.parameters_json)
            except (json.JSONDecodeError, TypeError):
                # Fall back to building from individual parameters
                self._build_parameters_from_dict(result)
        else:
            self._build_parameters_from_dict(result)
            
        if self.strict is not None:
            result["strict"] = self.strict
            
        return result
    
    def _build_parameters_from_dict(self, result):
        """Helper to build parameters structure from individual parameters"""
        if self.parameters:
            # Create JSON Schema style parameters object
            param_properties = {}
            for param_name, param_schema in self.parameters.items():
                # Handle both ParameterSchema objects and dictionaries
                if hasattr(param_schema, 'to_dict'):
                    param_properties[param_name] = param_schema.to_dict()
                else:
                    # Assume it's a dictionary that's already in the right format
                    param_properties[param_name] = param_schema
            
            params_obj = {
                "type": "object",
                "properties": param_properties
            }
            
            # Add required array if present
            if self.required:
                params_obj["required"] = self.required
                
            result["parameters"] = params_obj
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FunctionDefinition':
        """Create from an API-format dictionary, preserving complex parameter schemas"""
        function_def = cls(
            name=data.get("name", ""),
            description=data.get("description")
        )
        
        # Extract parameters
        params = data.get("parameters", {})
        if params:
            # Store the complete parameters schema as JSON
            function_def.parameters_json = json.dumps(params)
            
            # Also extract individual parameters for backward compatibility
            properties = params.get("properties", {})
            function_def.parameters = {
                param_name: ParameterSchema.from_dict(param_props)
                for param_name, param_props in properties.items()
            }
            
            # Extract required fields
            function_def.required = params.get("required", [])
        
        # Extract strict flag
        if "strict" in data:
            function_def.strict = data["strict"]
        
        return function_def

@datafile
class ToolDefinition:
    """Represents a tool that can be called by the model"""
    type: str = "function"  # Currently only "function" is supported
    function: FunctionDefinition = field(default_factory=FunctionDefinition)
    
    def to_dict(self) -> Dict:
        """Convert to the dictionary format expected by the API"""
        return {
            "type": self.type,
            "function": self.function.to_dict()
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ToolDefinition':
        """Create a ToolDefinition from an API-format dictionary"""
        tool_type = data.get("type", "function")
        
        # Create the function definition
        function_data = data.get("function", {})
        function_def = FunctionDefinition(
            name=function_data.get("name", ""),
            description=function_data.get("description")
        )
        
        # Extract parameters
        params = function_data.get("parameters", {})
        properties = params.get("properties", {})
        
        # Store the original parameters dictionary structure
        function_def.parameters = {
            param_name: ParameterSchema.from_dict(param_props)
            for param_name, param_props in properties.items()
        }
        
        # Extract required fields
        function_def.required = params.get("required", [])
        
        # Extract strict flag
        if "strict" in function_data:
            function_def.strict = function_data["strict"]
        
        return cls(type=tool_type, function=function_def)

@datafile
class ChatParams:
    """
    Engine/query parameters for the chat prompt. See OpenAI documentation for most of these. ⭐
    """
    model: str = "gpt-4-turbo"  #: The engine to use for generating responses, typically 'gpt-3.5-turbo', 'gpt-4', or 'gpt-4o'.
    engine: Optional[str] = None   #: Deprecated, use model instead
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = None
    stop: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    seed: Optional[int] = None
    n: Optional[int] = None
    
    # Tool-related parameters with proper dataclass typing
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[str] = None
    auto_execute: Optional[bool] = None  
    auto_feed: Optional[bool] = True  # Whether to automatically feed tool results back to the model

    # Azure-specific parameters
    deployment: Optional[str] = None
    api_type: Optional[str] = None
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    api_key_env: Optional[str] = None

    response_pattern: Optional[str] = None  # internal usage, not passed to the API


    """
    Here is a comparison of the parameters supported by different models: (Bless your heart, OpenAI)
    | Parameter                  | o3-mini | o1  | o1-preview | o1-mini | gpt-4o/mini | gpt-4-turbo | gpt-4o-audio | chatgpt-4o |
    |---------------------------|---------|-----|------------|---------|-------------|-------------|--------------|------------|
    | messages/system *         | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | messages/developer *      | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | messages/user-images      | No      | Yes | No         | No      | Yes         | Yes         | No           | Yes        |
    | `tools` (as functions)    | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | No         |
    | `functions` (legacy)      | Yes     | Yes | No         | No      | Yes         | Yes         | Yes          | No         |
    | `response_format`-object  | Yes     | Yes | No         | No      | Yes         | Yes         | No           | Yes        |
    | `response_format`-schema  | Yes     | Yes | No         | No      | Yes         | No          | No           | No         |
    | `reasoning_effort`        | Yes     | Yes | No         | No      | No          | No          | No           | No         |
    | `max_tokens`              | No      | No  | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | `max_completion_tokens`*  | Yes     | Yes | Yes        | Yes     | Yes         | Yes         | Yes          | Yes        |
    | `temperature` & `top_p`   | No      | No  | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | `logprobs`                | No      | No  | No         | No      | Yes         | Yes         | No           | Yes        |
    | `xxx_penalty`             | No      | No  | No         | No      | Yes         | Yes         | Yes          | Yes        |
    | `logit_bias` (broken!)    | No      | No  | No         | No      | Yes         | Yes         | ?            | Yes        |
    | `prediction`              | No      | No  | No         | No      | Yes         | No          | No           | No         |
    | `streaming:True`          | Yes     | No  | Yes        | Yes     | Yes         | Yes         | Yes          | Yes        |
    | Cache discount            | Yes     | Yes | Yes        | Yes     | Yes         | No          | No           | No         |
    |---------------------------|---------|-----|------------|---------|-------------|-------------|--------------|------------|
    """
    def _supports_developer_messages(self) -> bool:
        """Returns True if current model supports developer messages."""
        return not ("o1-preview" in self.model or "o1-mini" in self.model)

    def _supports_system_messages(self) -> bool:
        """Returns True if current model supports system messages."""
        return not ("o1" in self.model or "o1-preview" in self.model or "o1-mini" in self.model)

    def _supports_temperature(self) -> bool:
        """Returns True if current model supports temperature."""
        return "gpt-4o" in self.model or "gpt-4-turbo" in self.model

    def _get_non_none_params(self) -> dict:
        """
        Returns a dictionary of non-None parameters to send to the ChatCompletion API.
        Converts old usage (engine, max_tokens) to new fields (model, max_completion_tokens)
        automatically for reasoning models, so clients don't have to change code.
        """
        # Gather all fields of the dataclass
        fields = [field.name for field in self.__dataclass_fields__.values()]
        out = {field: getattr(self, field) for field in fields if getattr(self, field) is not None}

        # Ensure `model` is set, falling back to `engine` if needed
        if "model" not in out or not out["model"].strip():
            if "engine" in out:  
                out["model"] = out["engine"]
            else:
                out["model"] = "chatgpt-4o-latest"

        # engine is deprecated; remove it from the final dict
        if "engine" in out:
            del out["engine"]

        # max_tokens is deprecated
        if "max_tokens" in out:
            out["max_completion_tokens"] = out["max_tokens"]
            del out["max_tokens"]

        # If model supports temperatures, remove it to avoid breakage
        if not self._supports_temperature():
            if "temperature" in out:
                out["temperature"] = None
                del out["temperature"]
        else:
            # For older GPT-3.5 or GPT-4, we keep max_tokens as-is 
            pass

        # Remove tools and tool_choice as they are handled by the utensil_params
        if "tools" in out:
            del out["tools"]
        if "tool_choice" in out:
            del out["tool_choice"]
        if "auto_execute" in out:
            del out["auto_execute"]
        if "auto_feed" in out:
            del out["auto_feed"]

        # response_pattern is for internal usage only; remove it
        if "response_pattern" in out:
            del out["response_pattern"]

        # Convert tool definitions to API format
        if "tools" in out and out["tools"]:
            out["tools"] = [tool.to_dict() for tool in out["tools"]]

        return out

    # Helper method to add a tool from a dictionary
    def add_tool_from_dict(self, tool_dict: Dict) -> None:
        """Add a tool definition from an API-format dictionary"""
        tool = ToolDefinition.from_dict(tool_dict)
        if not self.tools:
            self.tools = []
        self.tools.append(tool)

    # Add this method
    def set_tools(self, tools_list: List[Dict]) -> None:
        """Set the tools list from API-format dictionaries"""
        self.tools = [ToolDefinition.from_dict(tool_dict) for tool_dict in tools_list]

    # Add this method near the set_tools method
    def get_tools(self) -> List[Dict]:
        """Get the tools list in API-format dictionaries"""
        if not self.tools:
            return []
        return [tool.to_dict() for tool in self.tools]

class ChatParamsMixin:
    params: Optional[ChatParams] = None

    @property
    def engine(self) -> Optional[str]:
        if self.params is None:
            self.params = ChatParams()
        return self.params.engine

    @engine.setter
    def engine(self, value: str):
        if self.params is None:
            self.params = ChatParams()
        self.params.engine = value
        # also sync model to that same value
        if self.model != value:
            self.model = value

    @property
    def model(self) -> str:
        if self.params is None:
            self.params = ChatParams()
        return self.params.model

    @model.setter
    def model(self, value: str):
        if self.params is None:
            self.params = ChatParams()
        self.params.model = value

    @property
    def temperature(self) -> Optional[float]:
        if self.params is None:
            self.params = ChatParams()
        return self.params.temperature

    @temperature.setter
    def temperature(self, value: float):
        if self.params is None:
            self.params = ChatParams()
        self.params.temperature = value

    @property
    def pattern(self) -> Optional[str]:
        if not self.params:
            return None
        return self.params.response_pattern

    @pattern.setter
    def pattern(self, value: str):
        if not self.params:
            self.params = ChatParams()
        self.params.response_pattern = value

    @property
    def stream(self) -> bool:
        if not self.params:
            return False  # default to False
        return bool(self.params.stream)

    @stream.setter
    def stream(self, value: bool):
        if not self.params:
            self.params = ChatParams()
        self.params.stream = value

    @property
    def auto_execute(self) -> Optional[bool]:
        if self.params is None:
            return None
        return self.params.auto_execute

    @auto_execute.setter
    def auto_execute(self, value: bool):
        if self.params is None and value is not None:
            self.params = ChatParams()
        if self.params is not None:
            self.params.auto_execute = value

    @property
    def tool_choice(self) -> Optional[str]:
        if self.params is None:
            return None
        return self.params.tool_choice

    @tool_choice.setter
    def tool_choice(self, value: str):
        if self.params is None and value is not None:
            self.params = ChatParams()
        if self.params is not None:
            self.params.tool_choice = value

    @property
    def auto_feed(self) -> Optional[bool]:
        if self.params is None:
            return None
        return self.params.auto_feed

    @auto_feed.setter
    def auto_feed(self, value: bool):
        if self.params is None and value is not None:
            self.params = ChatParams()
        if self.params is not None:
            self.params.auto_feed = value

    def set_tools(self, tools_list):
        """Set the tools list from API-format dictionaries"""
        if tools_list:
            if self.params is None:
                self.params = ChatParams()
            self.params.set_tools(tools_list)

    def set_response_filter(
        self,
        prefix: Optional[str] = None,
        suffix: Optional[str] = None,
        pattern: Optional[str] = None
    ):
        """
        Filters the response by a given prefix/suffix or regex pattern.
        If suffix is None, it is set to the same as prefix.
        """
        if pattern and (prefix or suffix):
            raise ValueError("Cannot set both pattern and prefix/suffix")
        if pattern:
            self.pattern = pattern
        else:
            self.pattern = self._generate_pattern_from_separator(prefix, suffix)

    @staticmethod
    def _generate_pattern_from_separator(prefix: str, suffix: Optional[str] = None) -> str:
        prefix_escaped = re.escape(prefix)
        if suffix:
            suffix_escaped = re.escape(suffix)
        else:
            suffix_escaped = prefix_escaped
        # Generate a pattern capturing everything between prefix and suffix
        pattern = rf"{prefix_escaped}(.*?)(?:{suffix_escaped}|$)"
        return pattern

    def filter_by_pattern(self, text: str) -> Optional[str]:
        """
        Applies self.pattern if set, returning the first capture group match.
        """
        if not self.pattern:
            return text
        return self._search_pattern(self.pattern, text)

    @staticmethod
    def _search_pattern(pattern: str, text: str) -> Optional[str]:
        matches = re.finditer(pattern, text, re.DOTALL)
        try:
            first_match = next(matches)
        except StopIteration:
            return None
        # Return the first capturing group if present
        if len(first_match.groups()) > 0:
            return first_match.group(1)
        else:
            return first_match.group()
