# Cataclysm Note: Replaces the default datafiles YAML formatter with our own version, this
# is solely for a cleaner yaml file format for source code with the "key: |" format

# Yaml format class is taken from https://github.com/jacebrowning/datafiles  formats.py
# The MIT License (MIT)
# Copyright © 2018, Jace Browning
# Permission is hereby granted, free of charge, to any person obtaining a copy of this 
# software and associated documentation files (the "Software"), to deal in the Software 
# without restriction, including without limitation the rights to use, copy, modify, 
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to 
# permit persons to whom the Software is furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all copies or 
# substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY 
# OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF 
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL 
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION 
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
from io import StringIO
import log
from typing import IO, Dict, List, Union
import dataclasses
from datafiles import formats, types
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml import YAML as _YAML

from .chat.turns import (
    CANONICAL_FIELD_ORDER,
    CANONICAL_SYSTEM_ROLE,
    DEVELOPER_ALIAS,
    ALLOWED_FIELDS_BY_ROLE,
    NormalizedTurn,
)
from .compact_tools import parse_tools_authoring, serialize_tools_authoring, split_tools_for_params


# ── Phase 3 helpers ────────────────────────────────────────────────────

def _get_fidelity(params_dict):
    """Determine the fidelity mode from params.responses."""
    responses = params_dict.get("responses") if isinstance(params_dict, dict) else None
    if not isinstance(responses, dict):
        return "authoring"
    if responses.get("export_diagnostics"):
        return "diagnostic"
    if responses.get("export_state"):
        return "continuation"
    return "authoring"


def _normalize_message_on_load(msg):
    """Accept developer as an alias for system, move unknown expanded-turn fields to provider_extras."""
    if not isinstance(msg, dict) or len(msg) == 0:
        return msg

    role = next(iter(msg))
    content = msg[role]

    # developer → system alias
    if role == DEVELOPER_ALIAS:
        role = CANONICAL_SYSTEM_ROLE
        msg = {role: content}

    if not isinstance(content, dict):
        return msg

    # For tool and include, no normalization needed.
    if role in ("tool", "include"):
        return msg

    # Move unknown fields into provider_extras on expanded turns.
    allowed = ALLOWED_FIELDS_BY_ROLE.get(role, set())
    known = set()
    extras = {}
    for key in list(content.keys()):
        if key in allowed:
            known.add(key)
        elif key == "provider_extras":
            known.add(key)
        else:
            extras[key] = content[key]

    if extras:
        # Remove unknown fields from the content and merge into provider_extras.
        for key in extras:
            del content[key]
        existing = content.get("provider_extras")
        if isinstance(existing, dict):
            existing.update(extras)
        else:
            content["provider_extras"] = extras

    return {role: content}


def _canonical_expanded_block(content_dict, role):
    """Re-order an expanded block's fields into canonical order."""
    ordered = {}
    for field_name in CANONICAL_FIELD_ORDER:
        if field_name in content_dict:
            ordered[field_name] = content_dict[field_name]
    # Add any remaining fields not in canonical order (defensive; shouldn't
    # happen after normalization, but log a warning if it does).
    for key in content_dict:
        if key not in ordered:
            log.warning(f"Unexpected field '{key}' outside canonical order on {role} turn")
            ordered[key] = content_dict[key]
    return ordered


def _should_collapse_to_scalar(content_dict, fidelity):
    """Return True if an expanded block can collapse back to scalar form."""
    for key in content_dict:
        if key == "text":
            continue
        if key == "provider_extras":
            if fidelity in ("continuation", "diagnostic"):
                return False
            continue
        if key == "encrypted_content":
            if fidelity != "authoring":
                return False
            continue
        return False
    return True


def _apply_fidelity_gate(content_dict, fidelity):
    """Remove fields that the selected fidelity mode does not emit."""
    gated = {}
    for key, value in content_dict.items():
        if value is None:
            continue
        # provider_extras only in continuation/diagnostic
        if key == "provider_extras" and fidelity not in ("continuation", "diagnostic"):
            continue
        # encrypted_content may be dropped in authoring
        if key == "encrypted_content" and fidelity == "authoring":
            continue
        gated[key] = value
    return gated


def _normalize_message_on_save(msg, fidelity):
    """Normalize a message dict for canonical save ordering.
    
    - system role is always the canonical key (developer never emitted)
    - expanded blocks get canonical field ordering
    - scalar collapse when only text remains after fidelity gating
    - empty canonical fields are omitted
    """
    if not isinstance(msg, dict) or len(msg) == 0:
        return msg

    role = next(iter(msg))
    content = msg[role]

    # Always save as canonical system role (never developer).
    if role == DEVELOPER_ALIAS:
        role = CANONICAL_SYSTEM_ROLE

    # System turns are text-only after normalization.
    if role == CANONICAL_SYSTEM_ROLE:
        if isinstance(content, dict):
            text_val = content.get("text")
            if text_val is None:
                log.warning("Expanded system message missing 'text' field; emitting empty string")
            return {role: text_val or ""}
        return {role: content}

    # Tool and include pass through unchanged.
    if role in ("tool", "include"):
        return {role: content}

    # Scalar content stays scalar.
    if not isinstance(content, dict):
        return {role: content}

    # Apply fidelity gating.
    gated = _apply_fidelity_gate(content, fidelity)

    # Fidelity gating for params.responses.state and provider_dump happens at the params level.

    # Collapse to scalar if only text remains.
    if _should_collapse_to_scalar(gated, fidelity):
        return {role: gated.get("text")}

    # Canonical field ordering.
    ordered = _canonical_expanded_block(gated, role)
    return {role: ordered}


def _normalize_params_on_save(params_dict, fidelity):
    """Gate params.responses fields based on fidelity."""
    if not isinstance(params_dict, dict):
        return params_dict
    
    result = dict(params_dict)
    responses = result.get("responses")
    if not isinstance(responses, dict):
        return result

    responses = dict(responses)
    
    # state: only persist when export_state is true
    if fidelity not in ("continuation", "diagnostic"):
        responses.pop("state", None)
    
    # provider_dump: only persist when export_diagnostics is true
    if fidelity != "diagnostic":
        responses.pop("provider_dump", None)

    result["responses"] = responses
    return result


def _normalize_data_on_load(data):
    """Normalize the full data dict on load (developer alias, provider_extras routing)."""
    if not isinstance(data, dict):
        return data

    messages = data.get("messages")
    if isinstance(messages, list):
        data["messages"] = [_normalize_message_on_load(m) for m in messages]

    params = data.get("params")
    if isinstance(params, dict) and isinstance(params.get("tools"), list):
        # Phase 4: compile compact authoring syntax under params.tools into
        # provider-shaped dicts, then split back to the current internal
        # storage fields so dataclass typing/deserialization stays stable.
        provider_tools = parse_tools_authoring(params.get("tools"))
        function_tools, native_tools = split_tools_for_params(provider_tools)
        params["tools"] = function_tools or None
        if native_tools:
            params["native_tools"] = native_tools
        elif "native_tools" in params:
            params.pop("native_tools", None)

    return data


def _normalize_data_on_save(data):
    """Normalize the full data dict on save (canonical roles, field ordering, fidelity gating)."""
    if not isinstance(data, dict):
        return data

    params = data.get("params")
    fidelity = _get_fidelity(params)

    messages = data.get("messages")
    if isinstance(messages, list):
        data["messages"] = [_normalize_message_on_save(m, fidelity) for m in messages]

    if isinstance(params, dict):
        # Phase 4: params.tools is the single authored surface. Merge any
        # legacy native_tools field for save and emit compact canonical syntax.
        authored_tools = []
        if isinstance(params.get("tools"), list):
            authored_tools.extend(params.get("tools") or [])
        if isinstance(params.get("native_tools"), list):
            authored_tools.extend(params.get("native_tools") or [])
        if authored_tools:
            params = dict(params)
            params["tools"] = serialize_tools_authoring(authored_tools)
            params.pop("native_tools", None)
            data["params"] = params
        data["params"] = _normalize_params_on_save(params, fidelity)

    return data


class YAML(formats.Formatter):
    """Formatter for (round-trip) YAML Ain't Markup Language."""

    @classmethod
    def extensions(cls):
        return {"", ".yml", ".yaml"}

    @classmethod
    def deserialize(cls, file_object):
        from ruamel.yaml import YAML as _YAML

        yaml = _YAML()
        yaml.preserve_quotes = True  # type: ignore
        try:
            data = yaml.load(file_object)
        except NotImplementedError as e:
            log.error(str(e))
            return {}

        # Phase 3: normalize developer→system, unknown fields→provider_extras on load.
        data = _normalize_data_on_load(data)
        return data

    @classmethod
    def serialize(cls, data):
        # HACK: to remove None values from the data and make the yaml file cleaner
        def filter_none_values(data: Union[Dict, List]):
            if isinstance(data, dict):
                # this code worked for None values, but not really for optional default values like I want :()
                return {k: filter_none_values(v) for k, v in data.items() if v is not None}
            elif isinstance(data, list):
                return [filter_none_values(v) for v in data]
            else:
                return data
        data = filter_none_values(data)

        # Phase 3: canonical roles, field ordering, fidelity gating on save.
        data = _normalize_data_on_save(data)

        yaml = _YAML()

        # Define custom string representation function
        def represent_plain_str(dumper, data):
            if "\n" in data or "\r" in data or "#" in data or ":" in data or "'" in data or '"' in data:
                return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='|')
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='')

        # Configure the library to use plain style for dictionary keys
        yaml.representer.add_representer(str, represent_plain_str)


        yaml.default_style = "|"  # support the cleaner multiline format for source code blocks
        yaml.register_class(types.List)
        yaml.register_class(types.Dict)

        yaml.indent(mapping=2, sequence=4, offset=2)

        stream = StringIO()
        yaml.dump(data, stream)
        text = stream.getvalue()

        if text.startswith("  "):
            return text[2:].replace("\n  ", "\n")

        if text == "{}\n":
            return ""

        return text.replace("- \n", "-\n")

def register_yaml_datafiles():
    # replace with our own version of 
    formats.register(".yml", YAML)
