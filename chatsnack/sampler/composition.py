"""Typed filling values and expansion-local reuse of named Sampler evaluations."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from ..asynchelpers import aformatter
from ..fillings import (FillingError, active_filling_stash, filling_machine,
                       _missing_filling, _reserve_sampler_filling_call)
from ..defaults import CHATSNACK_ROOT


@dataclass
class _Expansion:
    tasks: dict = field(default_factory=dict)
    waits: dict = field(default_factory=dict)


_active = ContextVar('sampler_expansion', default=None)
_current = ContextVar('sampler_current_evaluation', default=None)
_question_chain = ContextVar('sampler_question_chain', default=())


@asynccontextmanager
async def expansion_scope():
    """Own cached evaluations only for the lifetime of the outermost expansion."""
    if _active.get() is not None:
        yield
        return
    state = _Expansion()
    token = _active.set(state)
    try:
        yield
    finally:
        for task in state.tasks.values():
            if not task.done():
                task.cancel()
        if state.tasks:
            await asyncio.gather(*state.tasks.values(), return_exceptions=True)
        _active.reset(token)


def _text(value):
    """Render structured interpolations as JSON while leaving whole values typed."""
    from .models import Question
    if isinstance(value, Question):
        value = value.question
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


async def resolve_value(value, fillings):
    """Expand authored values once; values injected into sockets remain opaque."""
    if isinstance(value, dict):
        return {key: await resolve_value(item, fillings) for key, item in value.items()}
    if isinstance(value, list):
        return [await resolve_value(item, fillings) for item in value]
    if not isinstance(value, str):
        return copy.deepcopy(value)
    parsed = list(aformatter.parse(value))
    variables = filling_machine(fillings)
    if len(parsed) == 1 and parsed[0][0] == '' and parsed[0][1] is not None and not parsed[0][2] and not parsed[0][3]:
        return await aformatter.async_expand_field(parsed[0][1], (), variables)
    result = []
    for literal, name, spec, conversion in parsed:
        result.append(literal)
        if name is not None:
            result.append(_text(await aformatter.async_expand_field(name, (), variables)))
    return ''.join(result)


def _root():
    """Resolve the caller's asset root rather than a provider-specific directory."""
    return active_filling_stash.get() or CHATSNACK_ROOT.refresh()


async def question_filling(name, additional=None):
    """Load a live Question and resolve its authored fields without mutating it."""
    from .models import Question
    root = _root()
    root_path = Path(getattr(root, 'path', root)).resolve()
    key = (str(root_path), name)
    if key in _question_chain.get():
        raise FillingError(f'question filling cycle: question.{name}')
    question = Question.snapshots(root).get_or_none(name)
    if question is None:
        raise _missing_filling(f'question.{name}')
    token = _question_chain.set(_question_chain.get() + (key,))
    try:
        content = question.authored()
        return Question(**{k: await resolve_value(v, additional or {}) if k != 'name' else v
                           for k, v in content.items()})
    finally:
        _question_chain.reset(token)


def sampler_reference(suffix):
    """Parse a named answer leaf while allowing dots in the saved asset name."""
    from snapclass.paths import safe_path_placeholder
    parts = suffix.rsplit('.', 2)
    if len(parts) != 3 or not parts[1] or parts[2] not in {'choice', 'score', 'confidence'}:
        raise ValueError('Use sampler.Name.answer.choice, score, or confidence')
    safe_path_placeholder('name', parts[0])
    if any(char in parts[1] for char in '{}[]'):
        raise ValueError('Invalid sampler answer name')
    return parts


def _fingerprint(value):
    """Distinguish value bindings without logging content or requiring JSON objects."""
    from .models import Question, Sample
    if isinstance(value, (Question, Sample)):
        value = value.authored() if isinstance(value, Question) else value.to_dict()
    if isinstance(value, dict):
        return tuple((k, _fingerprint(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_fingerprint(v) for v in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return (type(value), value)
    return (type(value), id(value))


def _reaches(waits, start, target, seen=None):
    """Prevent two concurrently prepared result fillings from awaiting each other."""
    if start == target:
        return True
    seen = set() if seen is None else seen
    if start in seen:
        return False
    seen.add(start)
    return any(_reaches(waits, child, target, seen) for child in waits.get(start, ()))


async def sampler_filling(suffix, additional=None):
    """Share one saved evaluation among named result fields in this expansion."""
    from . import Sampler
    name, answer_name, attribute = sampler_reference(suffix)
    root = _root()
    root_path = Path(getattr(root, 'path', root)).resolve()
    key = (str(root_path), name, _fingerprint(additional or {}))
    async with expansion_scope():
        state, parent = _active.get(), _current.get()
        if parent is not None:
            if _reaches(state.waits, key, parent):
                raise FillingError(f'sampler filling cycle: sampler.{name}')
            state.waits.setdefault(parent, set()).add(key)
        try:
            if key not in state.tasks:
                sampler = Sampler.snapshots(root).get_or_none(name)
                if sampler is None:
                    raise _missing_filling(f'sampler.{suffix}')

                async def evaluate():
                    token = _current.set(key)
                    try:
                        # Filling bindings remain template data even when named
                        # model/timeout/etc.; the saved asset owns its settings.
                        from . import _UNSET, provider
                        request, questions, params = await sampler._prepare(
                            _UNSET, _UNSET, _UNSET, additional or {})
                        _reserve_sampler_filling_call(f'sampler.{name}')
                        from .models import decode
                        response = await provider.evaluate(request, params)
                        return decode(request['state'], questions, list(request['questions']), response)
                    finally:
                        _current.reset(token)

                state.tasks[key] = asyncio.create_task(evaluate())
            sample = await asyncio.shield(state.tasks[key])
            try:
                return getattr(sample.answers[answer_name], attribute)
            except KeyError:
                raise FillingError(f'Unknown named answer in sampler.{suffix}') from None
        finally:
            if parent is not None:
                state.waits[parent].discard(key)


# Reserve at provider dispatch so missing assets and shared answer reads cost no calls.
sampler_filling._chatsnack_reserves_sampler_after_lookup = True
