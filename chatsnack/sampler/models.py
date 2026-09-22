"""Authored questions and provider-independent evaluation results."""

import copy
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any, Generic, TypeVar

from snapclass import snapclass

from ..defaults import CHATSNACK_ROOT
from .persistence import Asset, AssetYAML, ValueSerializer


def json_value(value):
    """Copy JSON content without coercing keys, opaque objects, or nonfinite numbers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('JSON object keys must be strings')
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    raise ValueError('Expected finite JSON-compatible content')


@snapclass('questions/{self.name}.yml', stash=CHATSNACK_ROOT, manual=True,
           formatter=AssetYAML, minimal_diffs=False, unknown='reject',
           fields={key: ValueSerializer for key in ('question', 'yes', 'no', 'choices', 'levels')})
class Question(Asset):
    """A reusable judgment; choices or levels select its kind implicitly."""

    name: str | None = None
    question: Any = None
    yes: Any = None
    no: Any = None
    choices: Any = None
    levels: Any = None

    def __str__(self):
        """Interpolate the question's content, keeping whole-value references typed."""
        return self.question if isinstance(self.question, str) else json.dumps(json_value(self.question))

    def authored(self, *, include_name=True):
        """Return the authored definition, retaining structured criteria and order."""
        return {field.name: json_value(getattr(self, field.name)) for field in fields(self)
                if getattr(self, field.name) is not None and (include_name or field.name != 'name')}

    @property
    def kind(self):
        """Infer the provider primitive without adding a discriminator to YAML."""
        return 'choice' if self.choices is not None else 'score' if self.levels is not None else 'noul'

    def compile(self):
        """Validate and translate one resolved question into Jev vocabulary."""
        instructions = json_value(self.question)
        if not isinstance(instructions, (str, dict, list)) or not instructions or (
            isinstance(instructions, str) and not instructions.strip()
        ):
            raise ValueError('A question needs nonempty instructions')
        if self.name is not None and (not isinstance(self.name, str) or not self.name.strip()):
            raise ValueError('Question names must be nonempty strings')
        if self.choices is not None and self.levels is not None:
            raise ValueError('A question cannot have both choices and levels')
        if self.kind != 'noul' and (self.yes is not None or self.no is not None):
            raise ValueError('yes/no criteria cannot accompany choices or levels')
        result = dict(type=self.kind, instructions=instructions)
        if self.kind == 'noul':
            criteria = {key: json_value(value) for key, value in
                        (('true', self.yes), ('false', self.no)) if value is not None}
            if criteria:
                result['criteria'] = criteria
        elif self.kind == 'choice':
            if isinstance(self.choices, list):
                names = self.choices
                _unique_names(names, 'Choice options')
                criteria = dict.fromkeys(names)
            elif isinstance(self.choices, Mapping):
                _unique_names(list(self.choices), 'Choice options')
                criteria = json_value(self.choices)
            else:
                raise ValueError('choices must be a list or mapping')
            result['criteria'] = criteria
        else:
            names, descriptions = self.score_levels()
            result['criteria'] = descriptions
        return result

    def score_levels(self):
        """Keep stable authored names alongside Jev's ordered level descriptions."""
        if not isinstance(self.levels, list) or len(self.levels) < 2:
            raise ValueError('Score questions require at least two levels')
        names, descriptions = [], []
        for level in self.levels:
            if isinstance(level, str):
                name, description = level, level
            elif isinstance(level, Mapping) and len(level) == 1:
                name, description = next(iter(level.items()))
            else:
                raise ValueError('Each level must be a name or single-entry mapping')
            names.append(name)
            descriptions.append(json_value(description))
        _unique_names(names, 'Score levels')
        return names, descriptions


def _unique_names(names, label):
    """Reject ambiguous identifiers before a mapping can discard duplicates."""
    if not names or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError(f'{label} require nonempty string names')
    if len(set(names)) != len(names):
        raise ValueError(f'{label} contain duplicate names')


@dataclass
class SamplerParams:
    """Serializable execution choices; None delegates to SDK/environment defaults."""

    model: str | None = None
    timeout: float | None = None
    retry: dict | None = None
    base_url: str | None = None
    api_key_env: str | None = None

    def authored(self):
        """Keep absent SDK defaults and credentials out of saved definitions."""
        return {field.name: json_value(getattr(self, field.name)) for field in fields(self)
                if getattr(self, field.name) is not None}

    def validate(self):
        """Fail invalid serializable options before dependent model work starts."""
        for name in ('model', 'base_url', 'api_key_env'):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f'{name} must be a nonempty string')
        if self.timeout is not None:
            _number(self.timeout, 'timeout', positive=True)
        if self.retry is not None:
            if not isinstance(self.retry, Mapping):
                raise ValueError('retry must be a mapping')
            allowed = {'max_retries', 'backoff_initial', 'backoff_max', 'backoff_jitter',
                       'http_statuses', 'respect_retry_after', 'api_connection_error',
                       'api_timeout_error', 'timeout'}
            if self.retry.keys() - allowed:
                raise ValueError('Unsupported retry policy member')
            for key, value in self.retry.items():
                if key in ('respect_retry_after', 'api_connection_error', 'api_timeout_error'):
                    if not isinstance(value, bool):
                        raise ValueError(f'retry.{key} must be Boolean')
                elif key == 'http_statuses':
                    if not isinstance(value, list) or any(type(v) is not int or not 100 <= v <= 599 for v in value):
                        raise ValueError('retry.http_statuses must contain HTTP status integers')
                elif key == 'max_retries':
                    if type(value) is not int or value < 0:
                        raise ValueError('retry.max_retries must be a nonnegative integer')
                elif key == 'timeout' and value is None:
                    continue
                else:
                    _number(value, f'retry.{key}')
                    if value < 0 or (key == 'backoff_jitter' and value > 1):
                        raise ValueError(f'Invalid retry.{key}')


@dataclass(frozen=True)
class Answer:
    """One decoded judgment with its provider probabilities and primary score."""

    choice: str
    score: float
    probabilities: dict[str, float]
    confidence: float


class YesNoAnswer(Answer):
    """Binary judgment with readable Boolean views of the selected outcome."""

    @property
    def yes(self):
        """Whether the selected outcome is yes, including an exact tie."""
        return self.choice == 'yes'

    @property
    def no(self):
        """Whether the selected outcome is no."""
        return self.choice == 'no'


class ChoiceAnswer(Answer):
    """Selection among authored alternatives; preserve Jev's selected key."""


class ScoreAnswer(Answer):
    """Ordered-rubric judgment with Jev's probability-weighted numeric score."""


T = TypeVar('T')


class NamedSequence(Sequence, Generic[T]):
    """Read-only ordered collection with optional explicit-name lookup."""

    def __init__(self, values, names):
        self._values = tuple(values)
        self._named = {name: value for name, value in zip(names, self._values) if name is not None}

    def __getitem__(self, key):
        return self._named[key] if isinstance(key, str) else self._values[key]

    def __len__(self):
        return len(self._values)


@dataclass(frozen=True)
class SampleUsage:
    """Token counts reported for this evaluation."""

    input_tokens: int
    output_tokens: int


class Sample:
    """Resolved evaluation inputs and results, always in authored question order."""

    data: Any
    questions: NamedSequence[Question]
    answers: NamedSequence[Answer]
    model: str
    usage: SampleUsage

    def __init__(self, data, questions, answers, model, usage):
        """Keep results outside persistence tracking when used as new Sampler data."""
        if not questions or len(questions) != len(answers):
            raise ValueError('A Sample requires matching nonempty questions and answers')
        self.data, self.questions, self.answers = data, questions, answers
        self.model, self.usage = model, usage

    @property
    def question(self):
        """The first resolved question, also available as questions[0]."""
        return self.questions[0]

    @property
    def answer(self):
        """The first answer, also available as answers[0], even in a batch."""
        return self.answers[0]

    def to_dict(self):
        """Project a prior Sample as ordinary structured evaluation data."""
        return dict(data=json_value(self.data),
                    questions=[q.authored() for q in self.questions],
                    answers=[{field.name: json_value(getattr(a, field.name)) for field in fields(a)}
                             for a in self.answers], model=self.model,
                    usage=dict(input_tokens=self.usage.input_tokens, output_tokens=self.usage.output_tokens))


def _number(value, label, *, positive=False, probability=False):
    """Require finite provider numbers without accepting Boolean probabilities."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    if positive and value <= 0 or probability and not 0 <= value <= 1:
        raise ValueError(f'{label} is out of range')
    return value


def decode(data, questions, ids, response):
    """Decode an entire response or fail; never manufacture partial answers."""
    if not isinstance(response, Mapping) or not isinstance(response.get('answers'), Mapping):
        raise ValueError('Malformed Sampler response')
    if set(response['answers']) != set(ids):
        raise ValueError('Sampler response has missing or unexpected answers')
    model, usage = response.get('model'), response.get('usage')
    if not isinstance(model, str) or not model.strip() or not isinstance(usage, Mapping):
        raise ValueError('Sampler response needs model and usage')
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in ('input_tokens', 'output_tokens')):
        raise ValueError('Sampler response has invalid usage')
    answers = []
    for question, key in zip(questions, ids):
        raw = response['answers'][key]
        if not isinstance(raw, Mapping) or raw.get('type') != question.kind:
            raise ValueError('Sampler answer kind does not match its question')
        if question.kind == 'noul':
            score = _number(raw.get('noul'), 'noul', probability=True)
            answers.append(YesNoAnswer('yes' if score >= .5 else 'no', score,
                                       {'yes': score, 'no': 1 - score}, abs(2 * score - 1)))
            continue
        keys = (list(question.compile()['criteria']) if question.kind == 'choice'
                else [str(i) for i in range(len(question.levels))])
        probabilities = raw.get('probabilities')
        if not isinstance(probabilities, Mapping) or set(probabilities) != set(keys):
            raise ValueError('Sampler answer probabilities do not match authored options')
        probabilities = {key: _number(probabilities[key], 'probability', probability=True) for key in keys}
        # Each independently hundredth-rounded option can contribute up to
        # half a hundredth of error to the reported total.
        rounding_tolerance = .005 * len(probabilities) + 1e-9
        if not math.isclose(sum(probabilities.values()), 1, abs_tol=rounding_tolerance):
            raise ValueError('Sampler probabilities must sum to one')
        confidence = _number(raw.get('confidence'), 'confidence', probability=True)
        if question.kind == 'choice':
            choice = raw.get('choice')
            if not isinstance(choice, str) or choice not in probabilities:
                raise ValueError('Returned choice is absent from probabilities')
            answers.append(ChoiceAnswer(choice, probabilities[choice], probabilities, confidence))
        else:
            names, _ = question.score_levels()
            probabilities = dict(zip(names, probabilities.values()))
            score = _number(raw.get('score'), 'score')
            answers.append(ScoreAnswer(max(probabilities, key=probabilities.get), score, probabilities, confidence))
    names = [q.name for q in questions]
    return Sample(copy.deepcopy(data), NamedSequence(questions, names), NamedSequence(answers, names),
                  model, SampleUsage(usage['input_tokens'], usage['output_tokens']))
