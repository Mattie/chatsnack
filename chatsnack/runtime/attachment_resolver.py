"""Attachment resolver for local ``path:`` entries in expanded turns.

Resolves local file and image paths to provider-ready ``file_id`` references
by uploading through the OpenAI Files API.  Uploads are cached in memory by
``(absolute_path, size, mtime_ns, kind)`` so repeated prompts within the same
session or notebook run do not re-upload the same asset.

The resolver is shared between the HTTP Responses adapter and the WebSocket
Responses adapter so both transports get the same upload behaviour.
"""

import os
import warnings
from typing import Any, Dict, Optional, Tuple

from loguru import logger

# Cache key: (absolute_path, file_size, mtime_ns, kind)
_CacheKey = Tuple[str, int, int, str]


class AttachmentResolver:
    """Resolves local ``path:`` attachment entries to ``file_id`` references.

    Parameters
    ----------
    ai_client : AiClient
        The chatsnack ``AiClient`` wrapper (exposes ``upload_file`` /
        ``upload_file_async``).
    """

    def __init__(self, ai_client=None):
        self.ai_client = ai_client
        # In-memory upload cache keyed by (abs_path, size, mtime_ns, kind).
        self._upload_cache: Dict[_CacheKey, str] = {}

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(path: str, kind: str) -> Optional[_CacheKey]:
        """Build a cache key from a local path.

        Returns ``None`` if the file does not exist (caller should skip/warn).
        """
        try:
            abs_path = os.path.abspath(path)
            stat = os.stat(abs_path)
            return (abs_path, stat.st_size, stat.st_mtime_ns, kind)
        except OSError:
            return None

    def _get_cached(self, key: _CacheKey) -> Optional[str]:
        return self._upload_cache.get(key)

    def _set_cached(self, key: _CacheKey, file_id: str) -> None:
        self._upload_cache[key] = file_id

    # ------------------------------------------------------------------
    # Upload helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _upload_purpose(kind: str) -> str:
        """Return the OpenAI Files API purpose for an attachment kind."""
        return "vision" if kind == "image" else "assistants"

    def _upload_sync(self, path: str, kind: str) -> str:
        """Upload *path* via the Files API (sync) and return the file_id."""
        return self.ai_client.upload_file(
            os.path.abspath(path),
            purpose=self._upload_purpose(kind),
        )

    async def _upload_async(self, path: str, kind: str) -> str:
        """Upload *path* via the Files API (async) and return the file_id."""
        return await self.ai_client.upload_file_async(
            os.path.abspath(path),
            purpose=self._upload_purpose(kind),
        )

    # ------------------------------------------------------------------
    # Public API – resolve a single attachment dict
    # ------------------------------------------------------------------

    def resolve_attachment(self, entry: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
        """Resolve a single attachment dict (sync).

        *kind* is ``"image"`` or ``"file"`` – used for the cache key and for
        choosing between ``input_image`` and ``input_file`` content parts.

        Returns a **new** dict with ``file_id`` set (leaving the original
        ``path`` entry untouched), or ``None`` if resolution fails.
        """
        if not isinstance(entry, dict):
            return entry

        # Already resolved – pass through.
        if entry.get("file_id") or entry.get("url"):
            return entry

        path = entry.get("path")
        if not path:
            return entry

        if self.ai_client is None:
            warnings.warn(
                f"Skipping local-path {kind} '{path}': no ai_client available for upload.",
                stacklevel=3,
            )
            return None

        cache_key = self._cache_key(path, kind)
        if cache_key is None:
            warnings.warn(
                f"Skipping local-path {kind} '{path}': file not found.",
                stacklevel=3,
            )
            return None

        cached = self._get_cached(cache_key)
        if cached:
            logger.debug("Cache hit for {kind} upload: {name} → {fid}", kind=kind, name=os.path.basename(path), fid=cached)
            return {"file_id": cached}

        try:
            file_id = self._upload_sync(path, kind)
        except Exception as exc:
            warnings.warn(
                f"Skipping local-path {kind} '{path}': upload failed ({exc}).",
                stacklevel=3,
            )
            return None

        self._set_cached(cache_key, file_id)
        logger.debug("Uploaded {kind}: {name} → {fid}", kind=kind, name=os.path.basename(path), fid=file_id)
        return {"file_id": file_id}

    async def resolve_attachment_async(self, entry: Dict[str, Any], kind: str) -> Optional[Dict[str, Any]]:
        """Async variant of :meth:`resolve_attachment`."""
        if not isinstance(entry, dict):
            return entry

        if entry.get("file_id") or entry.get("url"):
            return entry

        path = entry.get("path")
        if not path:
            return entry

        if self.ai_client is None:
            warnings.warn(
                f"Skipping local-path {kind} '{path}': no ai_client available for upload.",
                stacklevel=3,
            )
            return None

        cache_key = self._cache_key(path, kind)
        if cache_key is None:
            warnings.warn(
                f"Skipping local-path {kind} '{path}': file not found.",
                stacklevel=3,
            )
            return None

        cached = self._get_cached(cache_key)
        if cached:
            logger.debug("Cache hit for {kind} upload: {name} → {fid}", kind=kind, name=os.path.basename(path), fid=cached)
            return {"file_id": cached}

        try:
            file_id = await self._upload_async(path, kind)
        except Exception as exc:
            warnings.warn(
                f"Skipping local-path {kind} '{path}': upload failed ({exc}).",
                stacklevel=3,
            )
            return None

        self._set_cached(cache_key, file_id)
        logger.debug("Uploaded {kind}: {name} → {fid}", kind=kind, name=os.path.basename(path), fid=file_id)
        return {"file_id": file_id}

    # ------------------------------------------------------------------
    # Batch resolve all attachments in a message list
    # ------------------------------------------------------------------

    def resolve_messages(self, messages):
        """Resolve all local path entries in a list of API message dicts (sync).

        Mutates nothing on the original message dicts.  Returns a new list
        with resolved entries.
        """
        resolved = []
        for msg in messages:
            new_msg = dict(msg)
            changed = False

            for key, kind in (("images", "image"), ("files", "file")):
                entries = msg.get(key)
                if not entries:
                    continue
                new_entries = []
                for entry in entries:
                    result = self.resolve_attachment(entry, kind)
                    if result is not None:
                        new_entries.append(result)
                if new_entries != entries:
                    changed = True
                new_msg[key] = new_entries

            resolved.append(new_msg if changed else msg)
        return resolved

    async def resolve_messages_async(self, messages):
        """Async variant of :meth:`resolve_messages`."""
        resolved = []
        for msg in messages:
            new_msg = dict(msg)
            changed = False

            for key, kind in (("images", "image"), ("files", "file")):
                entries = msg.get(key)
                if not entries:
                    continue
                new_entries = []
                for entry in entries:
                    result = await self.resolve_attachment_async(entry, kind)
                    if result is not None:
                        new_entries.append(result)
                if new_entries != entries:
                    changed = True
                new_msg[key] = new_entries

            resolved.append(new_msg if changed else msg)
        return resolved
