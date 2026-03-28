import ast
import re
from typing import Any, Dict, List, Optional, Tuple

RESERVED_CHILD_KEYS = {"description", "args", "required", "defer_loading"}
BUILTIN_TYPES = {"web_search", "file_search", "tool_search", "code_interpreter", "image_generation", "mcp"}


class CompactToolSyntaxError(ValueError):
    """Raised when compact tool YAML cannot be parsed safely."""


def reconstruct_tool_order(
    fn_list: List[Dict[str, Any]],
    native_list: List[Dict[str, Any]],
    order: Optional[List[Tuple[str, int]]],
) -> List[Dict[str, Any]]:
    """Reconstruct a merged tool list from separate function/native lists using stored order.

    If *order* is ``None`` or empty, falls back to function-first/native-second.
    """
    if not order:
        return list(fn_list) + list(native_list)
    result: List[Dict[str, Any]] = []
    for kind, idx in order:
        if kind == "fn" and idx < len(fn_list):
            result.append(fn_list[idx])
        elif kind == "native" and idx < len(native_list):
            result.append(native_list[idx])
    # Append any tools added after the original authoring.
    seen_fn = {idx for kind, idx in order if kind == "fn"}
    seen_native = {idx for kind, idx in order if kind == "native"}
    for i, t in enumerate(fn_list):
        if i not in seen_fn:
            result.append(t)
    for i, t in enumerate(native_list):
        if i not in seen_native:
            result.append(t)
    return result


def _infer_schema_from_expr(expr: str) -> Tuple[Dict[str, Any], bool]:
    """Compile a tiny Python-like type expression into JSON-schema-ish fields.

    Returns ``(schema, nullable)`` where nullable means the caller authored
    ``T | None``/``Optional[T]`` and may want to preserve explicit nullability.
    """
    expr = expr.strip()
    nullable = False

    if expr.startswith("Optional[") and expr.endswith("]"):
        inner = expr[len("Optional[") : -1].strip()
        schema, _ = _infer_schema_from_expr(inner)
        nullable = True
        return schema, nullable

    if "|" in expr:
        parts = [p.strip() for p in expr.split("|")]
        non_none = [p for p in parts if p != "None"]
        if len(non_none) == 1 and len(non_none) != len(parts):
            schema, _ = _infer_schema_from_expr(non_none[0])
            return schema, True

    if expr.startswith("Literal[") and expr.endswith("]"):
        inner = expr[len("Literal[") : -1]
        try:
            values = ast.literal_eval(f"[{inner}]")
        except Exception as exc:
            raise CompactToolSyntaxError(f"Invalid Literal expression: {expr}") from exc
        if not isinstance(values, list) or not values:
            raise CompactToolSyntaxError(f"Literal must contain at least one value: {expr}")
        value_types = {type(v) for v in values}
        if len(value_types) != 1:
            raise CompactToolSyntaxError(f"Literal values must have one primitive type: {expr}")
        py_type = value_types.pop()
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
        json_type = type_map.get(py_type, "string")
        return {"type": json_type, "enum": values}, False

    m = re.fullmatch(r"list\[(.+)\]", expr)
    if m:
        item_schema, _ = _infer_schema_from_expr(m.group(1).strip())
        return {"type": "array", "items": item_schema}, False

    m = re.fullmatch(r"dict\[(.+),(.+)\]", expr)
    if m:
        value_schema, _ = _infer_schema_from_expr(m.group(2).strip())
        return {"type": "object", "additionalProperties": value_schema}, False

    base = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
    }.get(expr)
    if base:
        return {"type": base}, False

    raise CompactToolSyntaxError(f"Unsupported compact arg type: {expr}")


def _compile_arg_spec(spec: Any) -> Tuple[Dict[str, Any], bool]:
    if isinstance(spec, dict):
        schema = dict(spec)
        required = bool(schema.pop("required", False))
        return schema, required

    if not isinstance(spec, str):
        raise CompactToolSyntaxError(f"Arg spec must be string or mapping, got {type(spec).__name__}")

    raw = spec.strip()
    default_set = False
    default_value = None
    type_expr = raw
    if "=" in raw:
        type_expr, default_expr = raw.split("=", 1)
        type_expr = type_expr.strip()
        default_expr = default_expr.strip()
        default_set = True
        try:
            default_value = ast.literal_eval(default_expr)
        except Exception:
            # keep as text fallback for resilience
            default_value = default_expr

    schema, nullable = _infer_schema_from_expr(type_expr)
    required = not default_set
    if default_set:
        schema["default"] = default_value
    if nullable:
        schema["nullable"] = True
    return schema, required


def _expand_child_tool(entry: Dict[str, Any]) -> Dict[str, Any]:
    if len(entry) == 1:
        name = next(iter(entry))
        value = entry[name]
        if isinstance(value, dict):
            data = dict(value)
        else:
            data = {"description": value}
    else:
        name = next(iter(entry))
        data = dict(entry)
        data.pop(name, None)
        data["description"] = entry[name]

    description = data.get("description")
    defer_loading = data.get("defer_loading")
    explicit_args = data.get("args")
    required_explicit = data.get("required")

    inline_args = {k: v for k, v in data.items() if k not in RESERVED_CHILD_KEYS}
    arg_specs = explicit_args if isinstance(explicit_args, dict) else inline_args

    properties: Dict[str, Any] = {}
    required: List[str] = []
    for arg_name, arg_spec in arg_specs.items():
        schema, is_required = _compile_arg_spec(arg_spec)
        properties[arg_name] = schema
        if is_required:
            required.append(arg_name)

    if isinstance(required_explicit, list):
        required = list(required_explicit)

    function_block: Dict[str, Any] = {
        "name": name,
        "parameters": {
            "type": "object",
            "properties": properties,
        },
    }
    if description:
        function_block["description"] = description
    if required:
        function_block["parameters"]["required"] = required

    tool = {"type": "function", "function": function_block}
    if defer_loading is not None:
        tool["defer_loading"] = bool(defer_loading)
    return tool


def parse_tools_authoring(entries: Optional[List[Any]]) -> List[Dict[str, Any]]:
    if not isinstance(entries, list):
        return []

    parsed: List[Dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str):
            parsed.append({"type": entry})
            continue

        if not isinstance(entry, dict):
            raise CompactToolSyntaxError(f"Tool entry must be scalar or mapping, got {type(entry).__name__}")

        if "type" in entry:
            parsed.append(dict(entry))
            continue

        if "tools" in entry:
            keys = [k for k in entry.keys() if k != "tools"]
            if len(keys) != 1:
                raise CompactToolSyntaxError("Namespace tool must have exactly one namespace key plus tools")
            namespace = keys[0]
            namespace_description = entry.get(namespace)
            child_entries = entry.get("tools") or []
            children = []
            for child in child_entries:
                if isinstance(child, dict):
                    children.append(_expand_child_tool(child))
                else:
                    raise CompactToolSyntaxError("Namespace child tools must be mappings")
            ns_tool = {
                "type": "namespace",
                "name": namespace,
                "tools": children,
            }
            if namespace_description:
                ns_tool["description"] = namespace_description
            parsed.append(ns_tool)
            continue

        if len(entry) == 1:
            t = next(iter(entry))
            cfg = entry[t]
            if t in BUILTIN_TYPES:
                tool = {"type": t}
                if isinstance(cfg, dict):
                    tool.update(cfg)
                    # Compile compact ``args`` shorthand into provider-ready
                    # JSON-schema parameters (e.g. client tool_search).
                    raw_args = tool.get("args")
                    if isinstance(raw_args, dict):
                        properties: Dict[str, Any] = {}
                        required_args: List[str] = []
                        for arg_name, arg_spec in raw_args.items():
                            schema, is_req = _compile_arg_spec(arg_spec)
                            properties[arg_name] = schema
                            if is_req:
                                required_args.append(arg_name)
                        compiled: Dict[str, Any] = {
                            "type": "object",
                            "properties": properties,
                        }
                        if required_args:
                            compiled["required"] = required_args
                        tool["args"] = compiled
                parsed.append(tool)
                continue

        # fallback passthrough for unknown authored mapping
        parsed.append(dict(entry))

    has_tool_search = any(t.get("type") == "tool_search" for t in parsed if isinstance(t, dict))
    if has_tool_search:
        for tool in parsed:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") == "namespace":
                for child in tool.get("tools") or []:
                    if isinstance(child, dict) and "defer_loading" not in child:
                        child["defer_loading"] = True
            if tool.get("type") == "mcp" and "defer_loading" not in tool:
                tool["defer_loading"] = True

    return parsed


def _schema_to_compact_expr(schema: Dict[str, Any]) -> str:
    t = schema.get("type")
    if "enum" in schema and isinstance(schema.get("enum"), list):
        vals = ", ".join(repr(v) for v in schema["enum"])
        base = f"Literal[{vals}]"
    elif t == "string":
        base = "str"
    elif t == "integer":
        base = "int"
    elif t == "number":
        base = "float"
    elif t == "boolean":
        base = "bool"
    elif t == "array" and isinstance(schema.get("items"), dict):
        base = f"list[{_schema_to_compact_expr(schema['items'])}]"
    elif t == "object" and isinstance(schema.get("additionalProperties"), dict):
        base = f"dict[str, {_schema_to_compact_expr(schema['additionalProperties'])}]"
    else:
        base = "str"

    if schema.get("nullable"):
        base = f"{base} | None"
    if "default" in schema:
        base = f"{base} = {repr(schema['default'])}"
    return base


def _needs_structured_form(props: Dict[str, Any], required: List[str]) -> bool:
    """Return whether inline compact form cannot faithfully represent the tool.

    An arg that is optional (not in ``required``) but has no ``default`` in its
    schema cannot be represented in inline shorthand because the reload path
    infers required from the absence of a default.  In that case we must fall
    back to structured form with an explicit ``required`` block.

    Returns:
        ``True`` if structured form is needed to preserve optional args without
        defaults; ``False`` if inline compact form can faithfully round-trip.
    """
    for arg_name, arg_schema in props.items():
        if not isinstance(arg_schema, dict):
            continue
        if arg_name not in required and "default" not in arg_schema:
            return True
    return False


def _serialize_child_tool(child: Dict[str, Any], *, implicit_defer: bool) -> Dict[str, Any]:
    func = child.get("function") if isinstance(child, dict) else None
    if not isinstance(func, dict):
        return dict(child)

    name = func.get("name", "tool")
    params = func.get("parameters") if isinstance(func.get("parameters"), dict) else {}
    props = params.get("properties") if isinstance(params.get("properties"), dict) else {}
    required = params.get("required") if isinstance(params.get("required"), list) else []

    # Determine defer_loading output
    defer_loading = child.get("defer_loading")
    emit_defer: Optional[bool] = None
    if defer_loading is False:
        emit_defer = False
    elif defer_loading is True and not implicit_defer:
        emit_defer = True

    # Use structured form when inline shorthand would lose requiredness info
    if _needs_structured_form(props, required):
        structured: Dict[str, Any] = {
            name: {
                "description": func.get("description", ""),
                "args": {},
            }
        }
        for arg_name, arg_schema in props.items():
            if isinstance(arg_schema, dict):
                structured[name]["args"][arg_name] = _schema_to_compact_expr(arg_schema)
        if required:
            structured[name]["required"] = list(required)
        if emit_defer is not None:
            structured[name]["defer_loading"] = emit_defer
        return structured

    # Simple inline form – every optional arg has a default, so the reload
    # path can infer requiredness faithfully.
    inline: Dict[str, Any] = {}
    if func.get("description"):
        inline[name] = func["description"]
    else:
        inline[name] = ""

    for arg_name, arg_schema in props.items():
        if isinstance(arg_schema, dict):
            expr = _schema_to_compact_expr(arg_schema)
            if arg_name in required and "=" in expr:
                expr = expr.split("=", 1)[0].strip()
            inline[arg_name] = expr

    if emit_defer is not None:
        inline["defer_loading"] = emit_defer

    return inline


def _decompile_args_schema(schema: Dict[str, Any]) -> Dict[str, str]:
    """Reverse the compact args compilation.

    Turns a JSON-schema ``args`` object back into compact Python-like shorthand
    strings suitable for YAML authoring.

    Args:
        schema: A JSON-schema-style dict with ``properties`` and optional
            ``required`` keys, as produced by the args compilation step.

    Returns:
        A dict mapping argument names to compact type expressions (e.g.
        ``{"goal": "str", "limit": "int = 10"}``).
    """
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    out: Dict[str, str] = {}
    for arg_name, arg_schema in props.items():
        if isinstance(arg_schema, dict):
            expr = _schema_to_compact_expr(arg_schema)
            if arg_name in required and "=" in expr:
                expr = expr.split("=", 1)[0].strip()
            out[arg_name] = expr
    return out


def serialize_tools_authoring(provider_tools: Optional[List[Dict[str, Any]]]) -> List[Any]:
    if not isinstance(provider_tools, list):
        return []

    has_tool_search = any(isinstance(t, dict) and t.get("type") == "tool_search" for t in provider_tools)
    out: List[Any] = []
    for tool in provider_tools:
        if not isinstance(tool, dict):
            continue
        t = tool.get("type")
        if t == "namespace":
            ns_name = tool.get("name", "namespace")
            ns_entry: Dict[str, Any] = {ns_name: tool.get("description", ""), "tools": []}
            for child in tool.get("tools") or []:
                if isinstance(child, dict):
                    ns_entry["tools"].append(_serialize_child_tool(child, implicit_defer=has_tool_search))
            out.append(ns_entry)
            continue

        cfg = {k: v for k, v in tool.items() if k != "type"}
        if t in BUILTIN_TYPES:
            if not cfg:
                out.append(t)
            else:
                if t == "mcp" and has_tool_search and cfg.get("defer_loading") is True:
                    cfg = {k: v for k, v in cfg.items() if k != "defer_loading"}
                # Decompile compiled args back to compact shorthand
                if isinstance(cfg.get("args"), dict) and "properties" in cfg["args"]:
                    cfg = dict(cfg)
                    cfg["args"] = _decompile_args_schema(cfg["args"])
                out.append({t: cfg})
            continue

        out.append(dict(tool))

    return out


def split_tools_for_params(provider_tools: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    function_tools: List[Dict[str, Any]] = []
    native_tools: List[Dict[str, Any]] = []
    for tool in provider_tools:
        if isinstance(tool, dict) and tool.get("type") == "function":
            function_tools.append(tool)
        else:
            native_tools.append(tool)
    return function_tools, native_tools
