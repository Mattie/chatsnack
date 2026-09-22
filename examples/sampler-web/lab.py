"""Load the language lab's authored tabs and chatsnack Samplers."""

import atexit
import re
from pathlib import Path

from chatsnack import Sampler
from snapclass import Fresh, Stash, snapclass


LAB_ROOT = Path(__file__).parent


@snapclass('lab/{self.id}.yml', manual=True, unknown='reject')
class LabTabDefinition:
    """Persisted input experience and optional result-label overrides."""

    id: str
    label: str
    title: str
    description: str
    placeholder: str
    sample: str
    sampler: str
    labels: dict[str, str] = Fresh.Dict


@snapclass('lab.yml', manual=True, unknown='reject')
class LabManifest:
    """Ordered membership of the language lab."""

    tabs: list[str] = Fresh.List


def _asset_path(root, relative, owner):
    """Resolve one trusted authored asset beneath the example directory."""
    path = Path(relative)
    resolved = (root / path).resolve()
    if path.is_absolute() or not resolved.is_relative_to(root.resolve()):
        raise ValueError(f'{owner} references an invalid asset path: {relative}')
    if not resolved.is_file():
        raise FileNotFoundError(f'{owner} references missing asset: {relative}')
    return resolved


def _load_tab(root, definition):
    """Load one native Sampler and validate any optional UI label overrides."""
    owner = f'lab/{definition.id}.yml'
    path = _asset_path(root, definition.sampler, owner)
    sampler = Sampler().load(path)
    sampler.params.validate()
    input_references = (
        re.findall(r'{([^{}]+)}', sampler.data)
        if isinstance(sampler.data, str) else []
    )
    if input_references != ['input']:
        raise ValueError(f'{path.name} data must contain exactly one {{input}} reference')
    questions = list(sampler.questions)
    if not questions:
        raise ValueError(f'{path.name} must define at least one question')
    names = [question.name for question in questions]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError(f'{path.name} questions must have explicit names')
    if len(names) != len(set(names)):
        raise ValueError(f'{path.name} has duplicate question names')
    unknown_labels = [name for name in definition.labels if name not in names]
    if unknown_labels:
        raise ValueError(f'{owner} labels unknown questions: {unknown_labels!r}')
    if any(not isinstance(label, str) or not label.strip()
           for label in definition.labels.values()):
        raise ValueError(f'{owner} result labels must be nonempty strings')
    for question in questions:
        question.compile()
    return {
        'id': definition.id,
        'label': definition.label,
        'title': definition.title,
        'description': definition.description,
        'placeholder': definition.placeholder,
        'sample': definition.sample,
        'labels': dict(definition.labels),
        'questions': questions,
        'sampler': sampler,
    }


def load_lab(root=LAB_ROOT):
    """Load tab definitions in manifest order without implicitly writing files."""
    root = Path(root).resolve()
    stash = Stash(root)
    manifest = LabManifest.snapshots(stash).get()
    ids = list(manifest.tabs)
    if not ids:
        raise ValueError('lab.yml must list at least one tab')
    if any(not isinstance(tab_id, str) or re.fullmatch(r'[a-z][a-z0-9_-]*', tab_id) is None
           for tab_id in ids):
        raise ValueError('lab.yml IDs must be lowercase names')
    if len(ids) != len(set(ids)):
        raise ValueError('lab.yml contains a duplicate tab ID')
    definitions = []
    demos = {}
    for tab_id in ids:
        try:
            definition = LabTabDefinition.snapshots(stash).get(tab_id)
        except FileNotFoundError as error:
            raise FileNotFoundError(f'lab/{tab_id}.yml is missing') from error
        definitions.append(definition)
        demos[tab_id] = _load_tab(root, definition)
    return manifest, definitions, demos


def public_tabs():
    """Return only the input metadata needed to render the browser UI."""
    fields = ('id', 'label', 'title', 'description', 'placeholder', 'sample')
    return [{field: demo[field] for field in fields} for demo in DEMOS.values()]


def close_samplers():
    """Release the lab evaluators' provider connections during shutdown."""
    for demo in DEMOS.values():
        demo['sampler'].close()


LAB_MANIFEST, LAB_TAB_DEFINITIONS, DEMOS = load_lab()
atexit.register(close_samplers)
