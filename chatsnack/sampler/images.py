"""Local image evidence: read once, inspect inline, snapshot only on evaluation."""

import base64
from dataclasses import dataclass
from pathlib import Path

from ..assets import ChatFile, _image_extension, capture_asset
from ..runtime.attachment_inputs import normalize_attachment_inputs


def authored_images(value):
    """Keep live sockets and paths readable; serialize ChatFiles as asset references."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, ChatFile):
        return value._attachment_reference()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [authored_images(item) for item in value]
    from .models import json_value
    return json_value(value)


@dataclass(frozen=True)
class ImageEvidence:
    """The exact bytes inspected by the provider, independent of a changing path."""

    data: bytes
    filename: str
    mime: str

    def inline(self):
        """Encode at the wire boundary, never in saved authoring or Sample data."""
        return 'data:' + self.mime + ';base64,' + base64.b64encode(self.data).decode('ascii')

    def snapshot(self):
        """Capture these same bytes using the existing content-addressed asset store."""
        return ChatFile.from_reference(capture_asset(self.data, filename=self.filename, kind='image'), kind='image')


def read_images(value):
    """Normalize local inputs and reject unsupported sources before provider dispatch."""
    entries = normalize_attachment_inputs(images=value).get('images', [])
    images = []
    for entry in entries:
        if 'url' in entry or 'file_id' in entry:
            raise ValueError('Sampler images require local paths or captured ChatFiles; URLs and file IDs are unsupported')
        if 'path' in entry and str(entry['path']).lower().startswith(('http:', 'https:', 'data:')):
            raise ValueError('Sampler images require local paths, not URLs')
        source = ChatFile.from_reference(entry, kind='image')
        data = source.read_bytes()
        extension = _image_extension(data)
        if extension is None:
            raise ValueError('Sampler images must be PNG, JPEG, or WebP')
        mime = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp'}[extension]
        images.append(ImageEvidence(data, source.filename or 'image.' + extension, mime))
    return tuple(images)
