"""Normalize natural attachment inputs at query-call boundaries.

Phase 3A adds ergonomic ``files=`` / ``images=`` kwargs across query methods.
This helper keeps that normalization logic in one place so sync/async/listen
entrypoints all produce the same canonical expanded user-turn shape.
"""

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_ALLOWED_SOURCE_KEYS = {"path", "file_id", "url"}
_ALLOWED_OPTIONAL_KEYS = {"filename"}


def normalize_attachment_inputs(
    files: Optional[Any] = None,
    images: Optional[Any] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Normalize convenience attachment kwargs into canonical dict entries.

    Returns a dict containing optional ``files`` and/or ``images`` keys,
    each mapped to a list of canonical entries suitable for expanded user turns.
    """
    normalized: Dict[str, List[Dict[str, Any]]] = {}

    norm_files = _normalize_bucket(files, bucket="files")
    if norm_files:
        normalized["files"] = norm_files

    norm_images = _normalize_bucket(images, bucket="images")
    if norm_images:
        normalized["images"] = norm_images

    return normalized


def _normalize_bucket(values: Optional[Any], bucket: str) -> List[Dict[str, Any]]:
    if values is None:
        return []

    items = values if isinstance(values, (list, tuple)) else [values]
    normalized: List[Dict[str, Any]] = []

    for entry in items:
        normalized.append(_normalize_entry(entry, bucket=bucket))

    return normalized


def _normalize_entry(entry: Any, bucket: str) -> Dict[str, Any]:
    if isinstance(entry, (str, Path, os.PathLike)):
        return {"path": str(entry)}

    if isinstance(entry, dict):
        return _normalize_dict_entry(entry, bucket=bucket)

    if bucket == "files" and _looks_like_file_obj(entry):
        return _materialize_file_obj(entry, filename=None)

    raise ValueError(
        f"Unsupported {bucket} attachment entry type: {type(entry).__name__}. "
        f"Use a path string, canonical dict, or (for files) a file object."
    )


def _normalize_dict_entry(entry: Dict[str, Any], bucket: str) -> Dict[str, Any]:
    keys = set(entry.keys())

    if "file" in entry:
        if bucket != "files":
            raise ValueError("images= does not support {'file': ...} entries; use a path/url/file_id instead.")
        allowed = {"file", "filename"}
        unexpected = keys - allowed
        if unexpected:
            raise ValueError(
                f"Unsupported keys for files attachment with file object: {sorted(unexpected)}"
            )
        file_obj = entry["file"]
        if not _looks_like_file_obj(file_obj):
            raise ValueError("files attachment dict {'file': ...} requires a readable file object.")
        return _materialize_file_obj(file_obj, filename=entry.get("filename"))

    source_keys = [k for k in ("path", "file_id", "url") if k in entry]
    if len(source_keys) == 0:
        raise ValueError(
            f"Attachment dict for {bucket} must include exactly one of path/file_id/url."
        )
    if len(source_keys) > 1:
        raise ValueError(
            f"Attachment dict for {bucket} has ambiguous sources {source_keys}; provide only one of path/file_id/url."
        )

    unexpected = keys - _ALLOWED_SOURCE_KEYS - _ALLOWED_OPTIONAL_KEYS
    if unexpected:
        raise ValueError(
            f"Attachment dict for {bucket} has unsupported keys: {sorted(unexpected)}"
        )

    out: Dict[str, Any] = {source_keys[0]: entry[source_keys[0]]}
    if "filename" in entry:
        out["filename"] = entry["filename"]
    return out


def _looks_like_file_obj(value: Any) -> bool:
    return hasattr(value, "read") and callable(value.read)


def _materialize_file_obj(file_obj: Any, filename: Optional[str]) -> Dict[str, Any]:
    original_pos = None
    if hasattr(file_obj, "tell") and callable(file_obj.tell):
        try:
            original_pos = file_obj.tell()
        except Exception:
            original_pos = None

    data = file_obj.read()
    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("file object attachments must produce bytes or text when read().")

    if original_pos is not None and hasattr(file_obj, "seek") and callable(file_obj.seek):
        try:
            file_obj.seek(original_pos)
        except Exception:
            pass

    name = filename or os.path.basename(getattr(file_obj, "name", "") or "") or f"attachment-{uuid.uuid4().hex}"
    suffix = os.path.splitext(name)[1]
    tmp = tempfile.NamedTemporaryFile(prefix="chatsnack-upload-", suffix=suffix, delete=False)
    with tmp:
        tmp.write(bytes(data))

    return {"path": tmp.name, "filename": name}
