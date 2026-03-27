"""Normalize natural attachment inputs at query-call boundaries.

Phase 3A adds ergonomic ``files=`` / ``images=`` kwargs across query methods.
This helper keeps that normalization logic in one place so sync/async/listen
entrypoints all produce the same canonical expanded user-turn shape.
"""

import atexit
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_ALLOWED_SOURCE_KEYS = {"path", "file_id", "url"}
_ALLOWED_OPTIONAL_KEYS = {"filename"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".heic"}
_MATERIALIZED_TEMP_PATHS: set[str] = set()


def cleanup_unresolved_materialized_paths() -> None:
    """Best-effort cleanup of any materialized temp files that were never resolved.

    Temp files in ``_MATERIALIZED_TEMP_PATHS`` are normally removed by
    :class:`~chatsnack.runtime.attachment_resolver.AttachmentResolver` after
    each upload attempt.  This function handles paths that were never passed
    through the resolver — for example when a non-Responses runtime is used or
    when an exception occurs before resolution.  It is registered as an
    ``atexit`` handler so paths are cleaned up at interpreter shutdown even if
    callers never invoke it explicitly.
    """
    for path in list(_MATERIALIZED_TEMP_PATHS):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        finally:
            _MATERIALIZED_TEMP_PATHS.discard(path)


atexit.register(cleanup_unresolved_materialized_paths)


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
        file_entries: List[Dict[str, Any]] = []
        image_entries: List[Dict[str, Any]] = []
        for entry in norm_files:
            if _looks_like_image_entry(entry):
                image_entries.append(entry)
            else:
                file_entries.append(entry)
        if file_entries:
            normalized["files"] = file_entries
        if image_entries:
            normalized.setdefault("images", []).extend(image_entries)

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


def _looks_like_image_entry(entry: Dict[str, Any]) -> bool:
    """Classify a normalized attachment entry as image-like or generic file."""
    if not isinstance(entry, dict):
        return False
    candidate = entry.get("path") or entry.get("url") or entry.get("filename")
    if not isinstance(candidate, str):
        return False
    _, suffix = os.path.splitext(candidate.lower())
    return suffix in _IMAGE_SUFFIXES


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

    _MATERIALIZED_TEMP_PATHS.add(tmp.name)
    return {"path": tmp.name, "filename": name}


def is_materialized_tempfile(entry: Dict[str, Any]) -> bool:
    """Return True when an attachment entry points at a chatsnack temp file."""
    if not isinstance(entry, dict):
        return False
    path = entry.get("path")
    return isinstance(path, str) and path in _MATERIALIZED_TEMP_PATHS
