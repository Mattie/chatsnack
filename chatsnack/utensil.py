import inspect
import functools
import json
from typing import Any, Callable, Dict, List, Optional, Union, get_type_hints
from .chat.mixin_params import ToolDefinition, FunctionDefinition
from loguru import logger

class UtensilGroup:
    """A group of related utensil functions."""
    
    def __init__(self, name: str, description: Optional[str] = None):
        """
        Initialize a group of related utensil functions.
        
        Args:
            name: The name of the group
            description: Optional description of the group
        """
        logger.debug(f"Creating utensil group '{name}'")
        self.name = name
        self.description = description
        self.utensils = []
        
    def add(self, func=None, *, name: Optional[str] = None, description: Optional[str] = None):
        """Decorator to add a function to this utensil group. Overwrites existing utensils with the same name."""
        logger.debug(f"Adding function to group '{self.name}'")
        def decorator(func):
            utensil_obj = _create_utensil(func, name, description)
            
            # Check if a function with the same name already exists in the group
            existing_names = [u.name for u in self.utensils]
            if utensil_obj.name in existing_names:
                # Find the index of the existing utensil and replace it
                index = existing_names.index(utensil_obj.name)
                self.utensils[index] = utensil_obj
            else:
                # No existing utensil with this name, so append it
                self.utensils.append(utensil_obj)
                
            return func
        
        if func is None:
            return decorator
        return decorator(func)
    
    def get_openai_tools(self) -> List[Dict[str, str]]:
        """Convert all utensils in this group to the OpenAI tools format."""
        logger.debug(f"Converting utensil group '{self.name}' to OpenAI tools format")
        return [u.get_openai_tool() for u in self.utensils]


class UtensilFunction:
    """Represents a function that can be called by the AI as a tool."""
    
    def __init__(
        self, 
        func: Callable,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parameter_descriptions: Optional[Dict[str, str]] = None
    ):
        """
        Initialize a utensil function.
        
        Args:
            func: The actual function to call
            name: Optional override for the function name
            description: Optional override for the function description
            parameter_descriptions: Optional descriptions for parameters
        """
        logger.debug(f"Creating utensil function '{name or func.__name__}'")
        self.func = func
        self.name = name or func.__name__
        self._extract_function_info(description_override=description, param_descriptions=parameter_descriptions)
        
    def _extract_function_info(self, description_override=None, param_descriptions=None):
        """
        Extract function information from docstrings, type hints, and parameters.
        Uses Pydantic to generate a JSON schema that includes the function description
        and per-parameter info.
        """
        import inspect
        from pydantic import create_model, Field

        # Get type hints and docstring from the function
        type_hints = get_type_hints(self.func)
        docstring = inspect.getdoc(self.func) or ""
        
        # Set the function description using an override or the first line of the docstring
        if description_override:
            self.description = description_override
        else:
            self.description = docstring.split('\n')[0].strip() if docstring else ""
        
        # Extract parameter descriptions from the docstring
        param_docs = {}
        if docstring:
            lines = docstring.split('\n')
            in_args = False
            current_param = None
            for line in lines:
                line = line.strip()
                if line.lower().startswith('args:') or line.lower().startswith('parameters:'):
                    in_args = True
                    continue
                elif line.startswith('Returns:') or not line:
                    in_args = False
                    continue
                if in_args:
                    if line and not line.startswith(' '):
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            current_param = parts[0].strip()
                            param_docs[current_param] = parts[1].strip()
                        else:
                            current_param = None
                    elif current_param and line.startswith(' '):
                        param_docs[current_param] += ' ' + line.strip()
        
        # Update using externally provided parameter descriptions if any
        if param_descriptions:
            param_docs.update(param_descriptions)
        
        # Build a Pydantic model dynamically from the function signature
        signature = inspect.signature(self.func)
        fields = {}
        for param_name, param in signature.parameters.items():
            if param_name == 'self':
                continue
            param_type = type_hints.get(param_name, str)
            param_description = param_docs.get(param_name, "")
            # Use Ellipsis if no default is provided to mark a required field.
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (param_type, Field(default, description=param_description))
        
        # Create the dynamic Pydantic model
        DynamicModel = create_model(f"{self.func.__name__}Model", **fields)
        model_schema = DynamicModel.model_json_schema()
        
        # Optionally add the function's overall description to the schema
        if self.description:
            model_schema["description"] = self.description
        
        # Store the final JSON schema for tool parameters
        self.parameters = model_schema
        
    def _get_json_schema_type(self, type_hint):
        """Convert Python type hint to JSON schema type."""
        import typing
        from typing import get_origin, get_args, List, Dict, Union, Optional
        
        # Handle None type
        if type_hint is type(None):
            return {"type": "null"}
        
        # Handle primitive types
        if type_hint is str:
            return {"type": "string"}
        elif type_hint is int:
            return {"type": "integer"}
        elif type_hint is float:
            return {"type": "number"}
        elif type_hint is bool:
            return {"type": "boolean"}
        
        # Handle list and dict without type arguments
        elif type_hint is list or type_hint is List:
            return {"type": "array", "items": {"type": "string"}}
        elif type_hint is dict or type_hint is Dict:
            return {"type": "object"}
        
        # Handle generic types
        origin = get_origin(type_hint)
        args = get_args(type_hint)
        
        if origin is Union:
            # Handle Optional (Union with NoneType)
            if type(None) in args:
                # It's an Optional[X] type
                non_none_types = [arg for arg in args if arg is not type(None)]
                if len(non_none_types) == 1:
                    return self._get_json_schema_type(non_none_types[0])
            
            # Regular Union type
            schemas = [self._get_json_schema_type(arg) for arg in args]
            return {"oneOf": schemas}
        
        # Handle typed lists (List[X])
        if origin is list or origin is typing.List:
            if args:
                return {
                    "type": "array",
                    "items": self._get_json_schema_type(args[0])
                }
            return {"type": "array", "items": {"type": "string"}}
        
        # Handle typed dicts (Dict[K, V])
        if origin is dict or origin is typing.Dict:
            if len(args) == 2:
                return {
                    "type": "object",
                    "additionalProperties": self._get_json_schema_type(args[1])
                }
            return {"type": "object"}
        
        # Default for any other type
        return {"type": "string"}
    
    def get_openai_tool(self) -> Dict[str, str]:
        """Convert this utensil to the OpenAI tools format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
        
    def __call__(self, *args, **kwargs):
        """Execute the function with the given arguments."""
        logger.debug(f"Calling utensil function '{self.name}' with args: {args}, kwargs: {kwargs}")
        return self.func(*args, **kwargs)

    def to_tool_definition(self) -> ToolDefinition:
        """Convert this utensil to a ToolDefinition object for serialization."""
        logger.debug(f"Converting utensil function '{self.name}' to ToolDefinition")
        # Create the function definition
        function_def = FunctionDefinition(
            name=self.name,
            description=self.description
        )
        
        # Extract parameters from the existing parameters dict
        if self.parameters:
            # Store properties directly
            function_def.parameters = self.parameters.get("properties", {})
            
            # Copy required fields
            function_def.required = self.parameters.get("required", [])
        
        # Create and return the tool definition
        return ToolDefinition(type="function", function=function_def)


# Global registry for all utensil functions
_REGISTRY = []


def _create_utensil(
    func: Callable, 
    name: Optional[str] = None, 
    description: Optional[str] = None,
    parameter_descriptions: Optional[Dict[str, str]] = None
) -> UtensilFunction:
    """Create a utensil function from a regular function."""
    logger.debug(f"Creating utensil for function '{name or func.__name__}'")
    utensil_obj = UtensilFunction(func, name, description, parameter_descriptions)
    # Store the utensil in the function itself for easy access
    func.__utensil__ = utensil_obj
    return utensil_obj


def utensil(
    func=None, *, 
    name: Optional[str] = None, 
    description: Optional[str] = None,
    parameter_descriptions: Optional[Dict[str, str]] = None
):
    """
    Decorator to mark a function as a utensil that can be called by the AI.
    
    Args:
        func: The function to decorate
        name: Optional override for the function name
        description: Optional override for the function description
        parameter_descriptions: Optional descriptions for parameters
    
    Returns:
        The decorated function
    """
    logger.debug(f"Registering utensil function '{name or func.__name__}'")
    def decorator(func):
        utensil_obj = _create_utensil(func, name, description, parameter_descriptions)
        _REGISTRY.append(utensil_obj)
        return func
        
    if func is None:
        return decorator
    return decorator(func)


# Add group method to the utensil function
utensil.group = UtensilGroup


def get_all_utensils() -> List[UtensilFunction]:
    """Get all registered utensil functions."""
    logger.trace(f"Retrieving all registered utensils")
    return _REGISTRY

def extract_utensil_functions(utensils=None) -> List[UtensilFunction]:
    """
    Extract all UtensilFunction objects from various input types.
    
    Args:
        utensils: List of utensil functions, groups, or callables.
                 If None, returns all from global registry.
    
    Returns:
        List of UtensilFunction objects
    """
    logger.debug(f"Extracting utensil functions from input")
    if utensils is None:
        return _REGISTRY.copy()
    
    result = []
    for u in utensils:
        if isinstance(u, UtensilFunction):
            result.append(u)
        elif isinstance(u, UtensilGroup):
            result.extend(u.utensils)
        elif hasattr(u, '__utensil__'):
            result.append(u.__utensil__)
        elif callable(u):
            # Create a utensil on the fly (but don't add to global registry)
            utensil_obj = _create_utensil(u)
            result.append(utensil_obj)
    
    return result

# Update the existing functions to use this core function
def get_openai_tools(utensils=None) -> List[Dict[str, str]]:
    """Convert utensil functions to the OpenAI tools format."""
    utensil_functions = extract_utensil_functions(utensils)
    return [func.get_openai_tool() for func in utensil_functions]

def get_tool_definitions(utensils=None) -> List[ToolDefinition]:
    """Convert utensil functions to ToolDefinition objects."""
    utensil_functions = extract_utensil_functions(utensils)
    return [func.to_tool_definition() for func in utensil_functions]

# Modify handle_tool_call to accept a local registry
def handle_tool_call(tool_call: Dict[str, Any], local_registry=None) -> Dict[str, Any]:
    """Handle a tool call from the AI."""
    function_name = tool_call.get("function", {}).get("name")
    arguments_json = tool_call.get("function", {}).get("arguments", "{}")
    call_id = tool_call.get("id")

    # log the name, arguments_json, and call_id
    from loguru import logger
    logger.debug(f"Function name: {function_name}")
    logger.debug(f"Arguments JSON: {arguments_json}")
    logger.debug(f"Call ID: {call_id}")    

    # Get the utensils to search through
    utensils_to_search = extract_utensil_functions(local_registry) if local_registry else _REGISTRY
    logger.debug(f"Searching through {len(utensils_to_search)} utensils for '{function_name}'")

    # Find the function in the registry
    for utensil_obj in utensils_to_search:
        logger.debug(f"Checking utensil: {utensil_obj.name}")
        if utensil_obj.name == function_name:
            try:
                arguments = json.loads(arguments_json)
                logger.debug(f"Executing function '{function_name}' with arguments: \n---\n{arguments}\n---")
                # we wanna be sure the arguments are named
                result = utensil_obj.func(**arguments)
                
                if not isinstance(result, dict):
                    result = {"result": str(result)}
                
                if call_id:
                    result["tool_call_id"] = call_id
                    
                return result
            except json.JSONDecodeError:
                return {"error": f"Invalid JSON arguments: {arguments_json}", "tool_call_id": call_id}
            except Exception as e:
                return {"error": f"Error executing function: {str(e)}", "tool_call_id": call_id}
    
    return {"error": f"Function '{function_name}' not found", "tool_call_id": call_id}