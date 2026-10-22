"""Small durable judgments over data, composed through ordinary fillings."""

import asyncio
import copy
from dataclasses import field

from snapclass import snapclass

from ..defaults import CHATSNACK_ROOT
from ..fillings import active_filling_stash
from . import provider as _provider
from .client import _SamplerClient, connection_signature
from .models import (Answer, ChoiceAnswer, NamedSequence, Question, RefusalAnswer, Sample, SamplerParams,
                     SampleUsage, ScoreAnswer, YesNoAnswer, decode, json_value,
                     _FILLING_FORMAT_METACHARACTERS)
from .persistence import Asset, AssetYAML, DataSerializer, ImagesSerializer, ParamsSerializer, QuestionsSerializer, ValueSerializer
from .images import authored_images, read_images
from .adapters import validate_images, wire_request


_UNSET = object()


def _bindings(explicit, ordinary):
    """Merge the reserved-key escape hatch without silently overwriting bindings."""
    if explicit is None:
        return ordinary
    if not isinstance(explicit, dict) or any(not isinstance(key, str) for key in explicit):
        raise ValueError('fillings must be a mapping with string keys')
    if explicit.keys() & ordinary.keys():
        raise ValueError('Duplicate filling bindings')
    return {**explicit, **ordinary}


def _sync(coro):
    """Run in notebooks and drain task-completion cleanup before returning."""
    try:
        return asyncio.run(coro)
    finally:
        # nest_asyncio stops as soon as the task finishes. AnyIO's worker-stop
        # callbacks need another loop turn, including when provider work fails.
        asyncio.run(asyncio.sleep(0))


@snapclass('samplers/{self.name}.yml', stash=CHATSNACK_ROOT, manual=True, init=False,
           formatter=AssetYAML, minimal_diffs=False, unknown='reject',
           fields={'data': DataSerializer, 'images': ImagesSerializer, 'questions': QuestionsSerializer,
                   'params': ParamsSerializer, 'expand': ValueSerializer})
class Sampler(Asset):
    """An authored evaluation definition; ask always returns a resolved Sample."""

    name: str | None = None
    data: object = None
    images: object = None
    questions: list = field(default_factory=list)
    params: SamplerParams = field(default_factory=SamplerParams)
    expand: bool = True

    def __init__(self, *, name=None, data=None, images=None, questions=None, params=None, expand=True,
                 provider=_UNSET, model=_UNSET, timeout=_UNSET, retry=_UNSET, base_url=_UNSET,
                 api_key_env=_UNSET):
        """Keep construction in memory, with convenient authored execution options."""
        self.name, self.data = name, data
        self.images = images
        if questions is not None and not isinstance(questions, (list, tuple)):
            raise ValueError('questions must be a list or tuple')
        self.questions = [] if questions is None else list(questions)
        self.params = copy.deepcopy(SamplerParams(**params) if isinstance(params, dict) else params or SamplerParams())
        for key, value in dict(provider=provider, model=model, timeout=timeout, retry=retry,
                               base_url=base_url, api_key_env=api_key_env).items():
            if value is not _UNSET:
                setattr(self.params, key, copy.deepcopy(value))
        if not isinstance(expand, bool):
            raise ValueError('expand must be Boolean')
        self.expand = expand
        self._provider_clients = _SamplerClient(copy.deepcopy(self.params))
        self.__post_init__()

    @property
    def model(self):
        """Convenient view of the authored model setting."""
        return self.params.model

    @model.setter
    def model(self, value):
        self.params.model = value

    @property
    def provider(self):
        """View explicit routing; an unset value selects by model or the default."""
        return self.params.provider

    @provider.setter
    def provider(self, value):
        self.params.provider = value

    def authored(self, *, include_name=True):
        """Return readable authored values without resolving their live fillings."""
        result = {}
        if include_name and self.name is not None:
            result['name'] = self.name
        params = ParamsSerializer.to_preserialization_data(self.params)
        if params:
            result['params'] = params
        if self.data is not None:
            result['data'] = DataSerializer.to_preserialization_data(self.data, target_object=self)
        images = self.images if self.images is not None else self.data.images if isinstance(self.data, Sample) else None
        if images is not None:
            result['images'] = authored_images(images)
        if self.questions:
            result['questions'] = QuestionsSerializer.to_preserialization_data(self.questions)
        if not self.expand:
            result['expand'] = False
        return result

    def save(self, path=None):
        """Persist only names that the saved-result filling grammar can address."""
        if self.name is not None and (
            not isinstance(self.name, str) or not self.name.strip()
            or any(char in self.name for char in _FILLING_FORMAT_METACHARACTERS)
        ):
            raise ValueError(
                'Sampler names must be nonempty strings without filling metacharacters {}!:'
            )
        # A prior Sample becomes literal data on disk. Save its carried images
        # alongside it while keeping the in-memory inheritance rule live.
        images = self.images
        if images is None and isinstance(self.data, Sample):
            self.images = self.data.images
            try:
                return super().save(path)
            finally:
                self.images = images
        return super().save(path)

    @classmethod
    def from_sample(cls, sample, *, name=None):
        """Reconstruct the evaluated inputs literally, independent of live assets."""
        if not isinstance(sample, Sample):
            raise TypeError('from_sample requires a Sample')
        return cls(name=name, data=copy.deepcopy(sample.data), params=sample.params,
                   images=sample.images,
                   questions=[Question(**q.authored()) for q in sample.questions], expand=False)

    def ask(self, question=_UNSET, **kwargs):
        """Evaluate inline or saved questions and return a Sample in every case."""
        return _sync(self._ask_sync(question, **kwargs))

    async def _ask_sync(self, question=_UNSET, *, questions=_UNSET, data=_UNSET,
                        images=_UNSET, provider=_UNSET, model=_UNSET, timeout=_UNSET, retry=_UNSET, base_url=_UNSET,
                        api_key_env=_UNSET, fillings=None, **ordinary):
        """Resolve asynchronously, then submit through this Sampler's sync SDK client."""
        from .composition import expansion_scope
        async with expansion_scope():
            request, resolved, params = await self._prepare(
                question, questions, data, _bindings(fillings, ordinary), images=images, provider=provider, model=model, timeout=timeout,
                retry=retry, base_url=base_url, api_key_env=api_key_env)
            authored = SamplerParams(**ParamsSerializer.to_preserialization_data(self.params)).resolved()
            if connection_signature(params) == connection_signature(authored):
                clients = self._bind_authored_client(authored)
                with _provider.use_sync_client(lambda: clients.client):
                    response = _provider.evaluate_sync(request, params)
            else:
                response = _provider.evaluate_sync(request, params)
            return self._finish(request, resolved, params, response)

    async def ask_a(self, question=_UNSET, *, questions=_UNSET, data=_UNSET,
                    images=_UNSET, provider=_UNSET, model=_UNSET, timeout=_UNSET, retry=_UNSET, base_url=_UNSET,
                    api_key_env=_UNSET, fillings=None, **ordinary):
        """Async evaluation; override values belong only to this invocation."""
        from .composition import expansion_scope
        async with expansion_scope():
            request, resolved, params = await self._prepare(
                question, questions, data, _bindings(fillings, ordinary), images=images, provider=provider, model=model, timeout=timeout,
                retry=retry, base_url=base_url, api_key_env=api_key_env)
            response = await _provider.evaluate(request, params)
            return self._finish(request, resolved, params, response)

    @staticmethod
    def _finish(request, questions, params, response):
        """Decode first, then capture the inspected bytes for durable result replay."""
        sample = decode(request['state'], questions, list(request['questions']), response, params=params)
        sample._images = tuple(image.snapshot() for image in request.get('_images', ()))
        return sample

    def _bind_authored_client(self, authored):
        """Bind the lazy sync client after effective parameters have been validated."""
        if not hasattr(self, '_provider_clients'):
            self._provider_clients = _SamplerClient(copy.deepcopy(authored))
        self._provider_clients.bind(authored)
        return self._provider_clients

    def close(self):
        """Close the retained sync provider client opened by this Sampler."""
        if hasattr(self, '_provider_clients'):
            self._provider_clients.close()

    async def close_a(self):
        """Close the retained sync provider client from async code."""
        if hasattr(self, '_provider_clients'):
            await self._provider_clients.close_a()

    def compile(self, question=_UNSET, **kwargs):
        """Inspect a request; executable dependency fillings may still run."""
        return _sync(self.compile_a(question, **kwargs))

    async def compile_a(self, question=_UNSET, *, questions=_UNSET, data=_UNSET,
                        images=_UNSET, provider=_UNSET, model=_UNSET, timeout=_UNSET, retry=_UNSET, base_url=_UNSET,
                        api_key_env=_UNSET, fillings=None, **ordinary):
        """Resolve and validate without evaluating this Sampler itself."""
        from .composition import expansion_scope
        async with expansion_scope():
            request, _, params = await self._prepare(question, questions, data, _bindings(fillings, ordinary),
                images=images, provider=provider, model=model, timeout=timeout, retry=retry,
                base_url=base_url, api_key_env=api_key_env)
            return wire_request(request, params)

    async def _prepare(self, question, questions, data, fillings, *, images=_UNSET, **overrides):
        """Copy authoring, resolve values once, and compile a stable ordered batch."""
        from .composition import resolve_value
        if question is not _UNSET and questions is not _UNSET:
            raise ValueError('Supply a positional question or questions=, not both')
        authored = ([question] if question is not _UNSET else
                    self.questions if questions is _UNSET else questions)
        if not isinstance(authored, (list, tuple)) or not authored:
            raise ValueError('At least one question is required')
        params = SamplerParams(**ParamsSerializer.to_preserialization_data(self.params))
        for key, value in overrides.items():
            if value is not _UNSET:
                setattr(params, key, copy.deepcopy(value))
        params.validate()
        params = params.resolved()
        supplied = self.data if data is _UNSET else data
        image_source = (images if images is not _UNSET else self.images if self.images is not None
                        else supplied.images if isinstance(supplied, Sample) else None)
        if not isinstance(self.expand, bool):
            raise ValueError('expand must be Boolean')
        token = active_filling_stash.set(self.lookup_root)
        try:
            if isinstance(supplied, Sample):
                state = supplied.to_dict()
            elif data is _UNSET and self.expand:
                state = await resolve_value(supplied, fillings)
            else:
                state = json_value(supplied)
            state = json_value(state)
            if state is not None and not isinstance(state, (str, dict, list)):
                raise ValueError('Sampler data must be text, an object, or an array')
            if self.expand and image_source is not None:
                image_source = await resolve_value(authored_images(image_source), fillings)
            image_evidence = await asyncio.to_thread(read_images, image_source) if image_source is not None else ()
            validate_images(image_evidence, params)
            if supplied is None and not image_evidence:
                raise ValueError('Sampler data is missing')
            resolved = []
            for item in authored:
                already_resolved = isinstance(item, str) and self.expand
                if isinstance(item, str) and self.expand:
                    item = await resolve_value(item, fillings)
                if isinstance(item, str):
                    item = Question(question=item)
                    # This string has already been expanded. Never reparse an
                    # injected document or generated result as a fresh template.
                    resolve_question = False
                else:
                    resolve_question = self.expand and not already_resolved
                if isinstance(item, dict):
                    item = Question(**item)
                if not isinstance(item, Question):
                    raise ValueError('Each question must be a string, Question, or definition')
                content = item.authored()
                if resolve_question:
                    content = {k: await resolve_value(v, fillings) if k != 'name' else v
                               for k, v in content.items()}
                resolved.append(Question(**content))
            for question in resolved:
                question._validate_name()
            names = [q.name for q in resolved if q.name is not None]
            if len(set(names)) != len(names):
                raise ValueError('Duplicate question names')
            compiled, used = {}, set(names)
            for index, item in enumerate(resolved):
                key = item.name
                if key is None:
                    key = f'_question_{index}'
                    while key in used:
                        key = '_' + key
                used.add(key)
                compiled[key] = item.compile()
            request = dict(state=state, questions=compiled, model=params.model,
                           _labels={key: item.score_levels()[0] for key, item in zip(compiled, resolved) if item.kind == 'score'},
                           _images=image_evidence)
            return request, resolved, params
        finally:
            active_filling_stash.reset(token)


__all__ = ['Sampler', 'Question', 'Sample', 'SamplerParams', 'Answer', 'YesNoAnswer',
           'ChoiceAnswer', 'ScoreAnswer', 'RefusalAnswer', 'SampleUsage']
