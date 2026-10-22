"""Translate resolved judgments without exposing provider vocabulary in authoring."""

import base64
import json
from collections.abc import Mapping
from uuid import uuid4

from .models import json_value


def validate_images(images, params):
    """Apply backend limits after shared local-byte loading, before dispatch."""
    if params.effective_provider == 'openai':
        if len(images) > 128:
            raise ValueError('Decisions accepts at most 128 images')
        return
    if not images:
        return
    # Verified 2026-10-22: https://docs.typesafe.ai/images#limits
    # Dimensions, decoded/expanded sizes, and context remain server-validated.
    if any(image.mime not in ('image/png', 'image/jpeg') for image in images):
        raise ValueError('TypeSafe images must be PNG or JPEG; convert WebP before sending')
    if any(len(image.data) > 16 * 1024 * 1024 for image in images):
        raise ValueError('TypeSafe images must be at most 16 MiB each')


def _typesafe_request(request):
    """Place ordered image evidence in state, keeping caller data nested intact."""
    wire = {key: request[key] for key in ('model', 'state', 'questions')}
    images = request.get('_images', ())
    if images:
        assets = {str(uuid4()): image for image in images}
        wire['state'] = dict(images=list(assets))
        if request['state'] is not None:
            wire['state']['data'] = request['state']
        wire['assets'] = assets
    return wire


def typesafe_execution(request):
    """Infer vision from resolved assets; keep all headers scoped to this call."""
    from typesafe_sdk import Image
    wire = _typesafe_request(request)
    if 'assets' in wire:
        wire['assets'] = {key: Image(image.data) for key, image in wire['assets'].items()}
    # Verified 2026-10-22: https://docs.typesafe.ai/images
    headers = {}
    if 'assets' in wire:
        headers['TypeSafe-Danger-Zone-Images'] = 'true'
    if headers:
        wire['extra_headers'] = headers
    return wire


def _text(value):
    """Retain prose; encode structured rubrics predictably without reordering keys."""
    return value if isinstance(value, str) else json.dumps(json_value(value), ensure_ascii=False, separators=(',', ':'))


def wire_request(request, params):
    """Build the selected provider's public request from the resolved internal batch."""
    if params.effective_provider == 'typesafe':
        wire = _typesafe_request(request)
        if 'assets' in wire:
            wire['assets'] = {key: dict(type='image', format='png' if image.mime == 'image/png' else 'jpg',
                                       data_base64=base64.b64encode(image.data).decode('ascii'))
                              for key, image in wire['assets'].items()}
        return wire
    questions = []
    for name, question in request['questions'].items():
        kind = question['type']
        item = dict(name=name, type='predicate' if kind == 'noul' else kind,
                    instructions=_text(question['instructions']))
        criteria = question.get('criteria', {})
        if kind == 'noul' and criteria:
            rubric = {'question': question['instructions']}
            rubric.update({label: criteria[key] for key, label in (('true', 'yes'), ('false', 'no')) if key in criteria})
            item['instructions'] = _text(rubric)
        elif kind == 'choice':
            item['choices'] = [dict(value=key, **({'description': _text(value)} if value is not None else {}))
                               for key, value in criteria.items()]
        elif kind == 'score':
            item['levels'] = [dict(label=label, **({'description': _text(value)} if value is not None else {}))
                              for label, value in zip(request['_labels'][name], criteria)]
        questions.append(item)
    state, images = request['state'], request.get('_images', ())
    if images:
        content = [] if state is None else [dict(type='input_text', text=_text(state))]
        content.extend(dict(type='input_image', image_url=image.inline(), detail='auto') for image in images)
        evidence = [dict(role='user', content=content)]
    else:
        evidence = _text(state)
    return dict(model=request['model'], input=evidence, questions=questions)


def normalize_decisions(response, request):
    """Validate array identities before mapping them; retain refusals as explicit slots."""
    if not isinstance(response, Mapping) or not isinstance(response.get('answers'), list):
        raise ValueError('Malformed Decisions response')
    answers = {}
    for answer in response['answers']:
        if not isinstance(answer, Mapping):
            raise ValueError('Malformed Decisions answer')
        name = answer.get('name')
        if not isinstance(name, str) or name not in request['questions'] or name in answers:
            raise ValueError('Decisions response has duplicate or unexpected answer names')
        expected = request['questions'][name]['type']
        kind = answer.get('type')
        if kind == 'refusal':
            answers[name] = dict(type='refusal')
            continue
        if kind != ('predicate' if expected == 'noul' else expected):
            raise ValueError('Decisions answer kind does not match its question')
        if kind == 'predicate':
            answers[name] = dict(type='noul', noul=answer.get('probability'))
            continue
        distribution = answer.get('probabilities')
        if not isinstance(distribution, list):
            raise ValueError('Malformed Decisions probabilities')
        probabilities = {}
        for entry in distribution:
            if not isinstance(entry, Mapping):
                raise ValueError('Malformed Decisions probability entry')
            value = entry.get('value')
            if kind == 'score':
                labels = request['_labels'][name]
                if type(value) is not int or not 0 <= value < len(labels) or entry.get('label') != labels[value]:
                    raise ValueError('Decisions score labels do not match authored levels')
                value = str(value)
            elif not isinstance(value, str):
                raise ValueError('Decisions choice values do not match authored string options')
            if value in probabilities:
                raise ValueError('Duplicate Decisions probability entry')
            probabilities[value] = entry.get('probability')
        answers[name] = dict(type=kind, probabilities=probabilities, confidence=answer.get('confidence'))
        answers[name]['choice' if kind == 'choice' else 'score'] = answer.get('choice' if kind == 'choice' else 'score')
    return dict(model=response.get('model'), usage=response.get('usage'), answers=answers)
