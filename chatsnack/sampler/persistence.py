"""Small snapclass serializers for readable authored sampler assets."""

import copy
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, LiteralScalarString
from snapclass import serializers
from snapclass.formatters import FileFormatter

from ..defaults import CHATSNACK_ROOT


class ValueSerializer(serializers.Serializer):
    """Preserve authored JSON shapes without snapclass type coercion."""

    @classmethod
    def to_python_value(cls, value, **kwargs):
        return copy.deepcopy(value)

    @classmethod
    def to_preserialization_data(cls, value, **kwargs):
        from .models import Sample, json_value
        return value.to_dict() if isinstance(value, Sample) else json_value(value)


class QuestionsSerializer(ValueSerializer):
    """Keep embedded Questions embedded and live reference strings untouched."""

    @classmethod
    def to_python_value(cls, value, **kwargs):
        from .models import Question
        if not isinstance(value, list):
            raise ValueError('questions must be a list')
        return [Question(**q) if isinstance(q, dict) else copy.deepcopy(q) for q in value]

    @classmethod
    def to_preserialization_data(cls, value, **kwargs):
        from .models import Question, json_value
        return [q.authored() if isinstance(q, Question) else json_value(q) for q in value]


class DataSerializer(ValueSerializer):
    """Keep a prior Sample literal after reload while follow-up questions stay live."""

    @classmethod
    def to_preserialization_data(cls, value, *, target_object=None, **kwargs):
        from .models import Sample
        data = super().to_preserialization_data(value)
        if isinstance(value, Sample) and getattr(target_object, 'expand', True):
            return _escape_template(data)
        return data


def _escape_template(value):
    """Quote literal braces once when saving resolved content as authored data."""
    if isinstance(value, str):
        return value.replace('{', '{{').replace('}', '}}')
    if isinstance(value, dict):
        return {key: _escape_template(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_escape_template(item) for item in value]
    return value


class ParamsSerializer(ValueSerializer):
    """Store only authored execution settings, never SDK client objects."""

    @classmethod
    def to_python_value(cls, value, **kwargs):
        from .models import SamplerParams
        return SamplerParams(**(value or {}))

    @classmethod
    def to_preserialization_data(cls, value, **kwargs):
        from .models import SamplerParams
        return (SamplerParams(**value) if isinstance(value, dict) else value).authored()


def _styled(value):
    """Keep prose legible and live whole-value fillings visibly quoted."""
    if isinstance(value, str):
        if '\n' in value:
            return LiteralScalarString(value)
        return DoubleQuotedScalarString(value) if value.startswith('{') else str(value)
    if isinstance(value, dict):
        return {str(k): _styled(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_styled(v) for v in value]
    return value


class AssetYAML(FileFormatter):
    """Readable YAML without Chat-specific message or parameter normalization."""

    extensions = {'.yml', '.yaml'}

    @classmethod
    def loads(cls, text):
        data = YAML(typ='safe').load(text)
        if not isinstance(data, dict):
            raise ValueError('An asset must contain a YAML mapping')
        return data

    @classmethod
    def dumps(cls, data):
        stream, yaml = StringIO(), YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)
        yaml.dump(_styled(data), stream)
        return stream.getvalue()


class Asset:
    """Explicit persistence with a common asset root for sibling filling lookup."""

    def __post_init__(self):
        """Refresh relative/env-backed roots before a new snapshot attaches."""
        self.__snapclass_config__.stash = CHATSNACK_ROOT.refresh()

    @property
    def yaml(self):
        """Inspect authored YAML without requiring a name or writing a file."""
        return AssetYAML.dumps(self.authored(include_name=False))

    def save(self, path=None):
        """Write only when requested; unnamed values need an explicit path."""
        if path is None and not self.name:
            raise ValueError('Saving an anonymous asset requires a name or explicit path')
        self.snapshot._stash = self.snapshot.stash.refresh()
        self.snapshot.save(path)
        return self

    def load(self, path=None):
        """Load explicitly, preserving native snapclass collection behavior."""
        if path is None and not self.name:
            raise ValueError('Loading an anonymous asset requires a name or explicit path')
        self.snapshot._stash = self.snapshot.stash.refresh()
        self.snapshot.load(path)
        return self

    @property
    def lookup_root(self):
        """Find sibling collections from an explicit path or the bound root stash."""
        snapshot = self.snapshot
        # Explicit paths can override the stash; normal collection paths include
        # the dedicated questions/ or samplers/ directory in their pattern.
        snapshot._stash = snapshot.stash.refresh()
        if self.name or snapshot._path_override is not None:
            path = snapshot.path
            parent = Path(path).parent
            if parent.name in ('questions', 'samplers'):
                return parent.parent
            return parent
        return snapshot.stash.refresh().path
