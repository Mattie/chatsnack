import inspect
import functools
import json
from typing import Any, Callable, Dict, List, Optional, Union, get_type_hints
from .chat.mixin_params import ToolDefinition, FunctionDefinition
from loguru import logger


# ── Hosted utensil specs ───────────────────────────────────────────────

class HostedUtensil:
    """A hosted OpenAI tool spec passable in ``utensils=[...]``.

    Instances carry the provider tool definition and any implied
    ``params.responses.include`` entries so that ``Chat`` can wire both
    from a single ``utensils`` list without manual dict mutation.
    """

    def __init__(self, tool_type: str, config: Optional[Dict[str, Any]] = None,
                 include_entries: Optional[List[str]] = None):
        self.tool_type = tool_type
        self.config = config or {}
        self.include_entries = include_entries or []

    def to_tool_dict(self) -> Dict[str, Any]:
        """Return the provider-shaped tool dict for the runtime."""
        tool: Dict[str, Any] = {"type": self.tool_type}
        tool.update(self.config)
        return tool

    def get_include_entries(self) -> List[str]:
        """Return any ``params.responses.include`` entries this tool implies."""
        return list(self.include_entries)

    def __repr__(self) -> str:
        cfg = f", {self.config}" if self.config else ""
        return f"HostedUtensil({self.tool_type!r}{cfg})"


def _make_web_search(*, domains: Optional[List[str]] = None,
                     sources: bool = False,
                     user_location: Optional[Dict[str, Any]] = None,
                     external_web_access: Optional[bool] = None,
                     **extra: Any) -> HostedUtensil:
    """Build a ``web_search`` hosted utensil spec."""
    cfg: Dict[str, Any] = {}
    filters: Dict[str, Any] = {}
    if domains:
        filters["allowed_domains"] = list(domains)
    if filters:
        cfg["filters"] = filters
    if user_location is not None:
        cfg["user_location"] = user_location
    if external_web_access is not None:
        cfg["external_web_access"] = external_web_access
    cfg.update(extra)
    includes: List[str] = []
    if sources:
        includes.append("web_search_call.action.sources")
    return HostedUtensil("web_search", cfg, includes)


def _make_file_search(*, vector_store_ids: Optional[List[str]] = None,
                      max_num_results: Optional[int] = None,
                      results: bool = False,
                      **extra: Any) -> HostedUtensil:
    """Build a ``file_search`` hosted utensil spec."""
    cfg: Dict[str, Any] = {}
    if vector_store_ids:
        cfg["vector_store_ids"] = list(vector_store_ids)
    if max_num_results is not None:
        cfg["max_num_results"] = max_num_results
    cfg.update(extra)
    includes: List[str] = []
    if results:
        includes.append("file_search_call.results")
    return HostedUtensil("file_search", cfg, includes)


def _make_mcp(*, server_label: Optional[str] = None,
              connector_id: Optional[str] = None,
              allowed_tools: Optional[List[str]] = None,
              require_approval: Optional[str] = None,
              **extra: Any) -> HostedUtensil:
    """Build an ``mcp`` hosted utensil spec."""
    cfg: Dict[str, Any] = {}
    if server_label is not None:
        cfg["server_label"] = server_label
    if connector_id is not None:
        cfg["connector_id"] = connector_id
    if allowed_tools is not None:
        cfg["allowed_tools"] = list(allowed_tools)
    if require_approval is not None:
        cfg["require_approval"] = require_approval
    cfg.update(extra)
    return HostedUtensil("mcp", cfg)


# ── Utensil group ─────────────────────────────────────────────────────

class UtensilGroup:
    """A group of related utensil functions that forms a searchable namespace.

    Instances are both decorators (``@group``) and directly passable in
    ``utensils=[...]``.
    """
    
    def __init__(self, name: str, description: Optional[str] = None):
        logger.debug(f"Creating utensil group '{name}'")
        self.name = name
        self.description = description
        self.utensils = []

    def __call__(self, func=None, *, name: Optional[str] = None,
                 description: Optional[str] = None):
        """Use as ``@group`` or ``@group(name=..., description=...)``."""
        def decorator(fn):
            utensil_obj = _create_utensil(fn, name, description)
            existing_names = [u.name for u in self.utensils]
            if utensil_obj.name in existing_names:
                idx = existing_names.index(utensil_obj.name)
                self.utensils[idx] = utensil_obj
            else:
                self.utensils.append(utensil_obj)
            return fn

        if func is None:
            return decorator
        return decorator(func)

    # Keep legacy .add() working as an alias
    def add(self, func=None, *, name: Optional[str] = None,
            description: Optional[str] = None):
        """Decorator to add a function to this utensil group. Overwrites existing utensils with the same name."""
        return self.__call__(func, name=name, description=description)
    
    def get_openai_tools(self) -> List[Dict[str, str]]:
        """Convert all utensils in this group to the OpenAI tools format."""
        logger.debug(f"Converting utensil group '{self.name}' to OpenAI tools format")
        return [u.get_openai_tool() for u in self.utensils]

    def to_namespace_tool_dict(self) -> Dict[str, Any]:
        """Compile this group into a provider-shaped namespace tool dict."""
        children = []
        for u in self.utensils:
            tool_dict = u.get_openai_tool()
            children.append(tool_dict)
        ns: Dict[str, Any] = {
            "type": "namespace",
            "name": self.name,
            "tools": children,
        }
        if self.description:
            ns["description"] = self.description
        return ns

    def __repr__(self) -> str:
        return f"UtensilGroup({self.name!r}, {len(self.utensils)} utensils)"


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


class _UtensilNamespace:
    """Callable namespace that serves as decorator, group factory, and
    hosted-tool builder — all from a single ``utensil`` symbol.

    ``@utensil`` still works as the plain decorator.
    ``utensil.group(...)`` creates grouped namespaces.
    ``utensil.tool_search`` / ``utensil.web_search(...)`` etc. create hosted specs.
    """

    # ── decorator behaviour (preserves @utensil) ──────────────────────

    def __call__(self, func=None, *, name: Optional[str] = None,
                 description: Optional[str] = None,
                 parameter_descriptions: Optional[Dict[str, str]] = None):
        """Use as ``@utensil`` or ``@utensil(name=..., description=...)``."""
        def decorator(fn):
            utensil_obj = _create_utensil(fn, name, description, parameter_descriptions)
            _REGISTRY.append(utensil_obj)
            return fn

        if func is None:
            return decorator
        return decorator(func)

    # ── group factory ─────────────────────────────────────────────────

    @staticmethod
    def group(name: str, description: Optional[str] = None) -> UtensilGroup:
        """Create a grouped namespace for related utensil functions."""
        return UtensilGroup(name, description)

    # ── zero-config hosted properties ─────────────────────────────────

    @property
    def tool_search(self) -> HostedUtensil:
        return HostedUtensil("tool_search")

    @property
    def code_interpreter(self) -> HostedUtensil:
        return HostedUtensil("code_interpreter")

    @property
    def image_generation(self) -> HostedUtensil:
        return HostedUtensil("image_generation")

    # ── configured hosted builders ────────────────────────────────────

    @staticmethod
    def web_search(**kwargs: Any) -> HostedUtensil:
        """Create a configured ``web_search`` hosted utensil."""
        return _make_web_search(**kwargs)

    @staticmethod
    def file_search(**kwargs: Any) -> HostedUtensil:
        """Create a configured ``file_search`` hosted utensil."""
        return _make_file_search(**kwargs)

    @staticmethod
    def mcp(**kwargs: Any) -> HostedUtensil:
        """Create a configured ``mcp`` hosted utensil."""
        return _make_mcp(**kwargs)


# Module-level singleton that replaces the old ``utensil`` function.
utensil = _UtensilNamespace()


def get_all_utensils() -> List[UtensilFunction]:
    """Get all registered utensil functions."""
    logger.trace(f"Retrieving all registered utensils")
    return _REGISTRY

def extract_utensil_functions(utensils=None) -> List[UtensilFunction]:
    """
    Extract all UtensilFunction objects from various input types.
    
    Note: HostedUtensil and UtensilGroup instances are skipped here because
    they are not local Python functions.  Use ``get_openai_tools()`` for the
    full provider-ready tool list.
    
    Args:
        utensils: List of utensil functions, groups, or callables.
                 If None, returns all from global registry.
    
    Returns:
        List of UtensilFunction objects
    """
    logger.debug(f"Extracting utensil functions from input: {utensils}")
    if utensils is None:
        return _REGISTRY.copy()
    
    result = []
    for u in utensils:
        if isinstance(u, UtensilFunction):
            result.append(u)
        elif isinstance(u, UtensilGroup):
            result.extend(u.utensils)
        elif isinstance(u, HostedUtensil):
            # Hosted specs have no local callable — skip for function extraction
            continue
        elif hasattr(u, '__utensil__'):
            result.append(u.__utensil__)
        elif callable(u):
            # Create a utensil on the fly (but don't add to global registry)
            utensil_obj = _create_utensil(u)
            result.append(utensil_obj)
        else:
            logger.warning(f"Unknown type {type(u)} in utensils, skipping")
    logger.debug(f"Extracted {len(result)} utensil functions")
    
    return result

# Update the existing functions to use this core function
def get_openai_tools(utensils=None) -> List[Dict[str, str]]:
    """Convert utensil items to the OpenAI tools format.

    Handles local functions, groups (as namespace tool dicts), and
    hosted utensil specs.
    """
    if utensils is None:
        return [func.get_openai_tool() for func in _REGISTRY]

    result: List[Dict[str, Any]] = []
    for u in utensils:
        if isinstance(u, HostedUtensil):
            result.append(u.to_tool_dict())
        elif isinstance(u, UtensilGroup):
            result.append(u.to_namespace_tool_dict())
        elif isinstance(u, UtensilFunction):
            result.append(u.get_openai_tool())
        elif hasattr(u, '__utensil__'):
            result.append(u.__utensil__.get_openai_tool())
        elif callable(u):
            utensil_obj = _create_utensil(u)
            result.append(utensil_obj.get_openai_tool())
        else:
            logger.warning(f"Unknown type {type(u)} in utensils, skipping")

    # Phase 4A: apply implicit defer_loading policy matching the compact YAML
    # surface — when tool_search is present, namespace child tools and mcp
    # tools default to defer_loading: true.
    has_tool_search = any(
        isinstance(t, dict) and t.get("type") == "tool_search"
        for t in result
    )
    if has_tool_search:
        for tool in result:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "namespace":
                for child in tool.get("tools") or []:
                    if isinstance(child, dict) and "defer_loading" not in child:
                        child["defer_loading"] = True
            if tool.get("type") == "mcp" and "defer_loading" not in tool:
                tool["defer_loading"] = True

    return result


def collect_include_entries(utensils) -> List[str]:
    """Gather implied ``params.responses.include`` entries from hosted utensils."""
    if not utensils:
        return []
    entries: List[str] = []
    for u in utensils:
        if isinstance(u, HostedUtensil):
            entries.extend(u.get_include_entries())
    return entries

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

    # output the local_registry if it exists
    if local_registry:
        logger.debug(f"Local registry: {local_registry}")
    else:
        logger.debug("No local registry provided, using global registry")
    
    # output the _REGISTRY if it exists
    logger.debug(f"Global registry: {_REGISTRY}")

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
                
                # log the result
                logger.debug(f"Function '{function_name}' result: \n---\n{result}\n---")
                return result
            except json.JSONDecodeError:
                return {"error": f"Invalid JSON arguments: {arguments_json}", "tool_call_id": call_id}
            except Exception as e:
                return {"error": f"Error executing function: {str(e)}", "tool_call_id": call_id}
    
    return {"error": f"Function '{function_name}' not found", "tool_call_id": call_id}