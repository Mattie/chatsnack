"""Goal contracts for Decisions, durable vision, and partial refusals."""

import base64
import asyncio
import json

import httpx2
import openai
import pytest

from chatsnack import ChatFile, Question, RefusalAnswer, Sampler, SamplerParams, resolve_fillings_a
from chatsnack.assets import AssetCorruptError, AssetMissingError, capture_asset
from chatsnack.sampler.adapters import normalize_decisions
from chatsnack.sampler.models import decode


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')


@pytest.fixture
def decisions_transport(monkeypatch, tmp_path):
    """Exercise the real SDK's HTTP boundary without credentials or network access."""
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only')
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    calls, clients = [], []
    sync, asynchronous = openai.OpenAI, openai.AsyncOpenAI

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == '/v1/decisions'
        answers = []
        for q in reversed(body['questions']):
            answer = dict(name=q['name'], type=q['type'])
            if q['name'].startswith('refused'):
                answer['type'] = 'refusal'
            elif q['type'] == 'predicate':
                answer['probability'] = .9
            elif q['type'] == 'choice':
                answer.update(choice=q['choices'][0]['value'], confidence=.73,
                    probabilities=[dict(value=c['value'], probability=1. if i == 0 else 0.)
                                   for i, c in enumerate(q['choices'])])
            else:
                answer.update(score=.25, confidence=.4,
                    probabilities=[dict(value=i, label=level['label'], probability=.75 if i == 0 else .25)
                                   for i, level in enumerate(q['levels'])])
            answers.append(answer)
        return httpx2.Response(200, json=dict(model='gpt-6-luna', answers=answers,
                                             usage=dict(input_tokens=10, output_tokens=0)))

    def factory(**options):
        client = sync(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), **options)
        clients.append(client)
        return client

    def async_factory(**options):
        client = asynchronous(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), **options)
        clients.append(client)
        return client

    monkeypatch.setattr(openai, 'OpenAI', factory)
    monkeypatch.setattr(openai, 'AsyncOpenAI', async_factory)
    yield calls, clients
    for client in clients:
        if isinstance(client, sync):
            client.close()


def test_goal_vision_saved_asset_replay_and_refusals(decisions_transport, tmp_path):
    calls, clients = decisions_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(name='Vision', images=['{photo}'], questions=[
        Question(name='burnt', question='Burnt?', yes={'evidence': 'Black edges'}),
        Question(name='category', question='Which?', choices={'snack': {'examples': ['popcorn']}, 'meal': None}),
        Question(name='severity', question='How burnt?', levels=[{'low': 'Golden'}, {'high': 'Black'}]),
        Question(name='refused', question='Unavailable judgment?'),
    ]).save()
    sample = Sampler(name='Vision').load().ask(photo=photo)
    assert sample.params.provider == 'openai'
    assert sample.answers['category'].choice == 'snack'
    assert sample.answers['severity'].probabilities == {'low': .75, 'high': .25}
    assert sample.answers['refused'].refused
    assert sample.answers['refused'].score is None
    assert sample.answers['refused'].yes is None
    assert not sample.answer.refused and sample.answer.yes
    assert sample.images[0].read_bytes() == PNG
    assert sample.to_dict()['answers'][-1]['refused'] is True
    assert 'base64' not in json.dumps(sample.to_dict())
    replay = Sampler.from_sample(sample, name='Replay').save()
    assert 'asset:' in replay.yaml and 'base64' not in replay.yaml
    photo.unlink()
    repeated = Sampler(name='Replay').load().ask()
    assert repeated.images[0].read_bytes() == PNG
    assert calls[-1]['input'] == calls[0]['input']
    assert calls[0]['questions'][2]['levels'][0]['label'] == 'low'
    for client in clients:
        client.close()


@pytest.mark.asyncio
async def test_goal_followup_images_and_explicit_clear(decisions_transport, tmp_path):
    calls, clients = decisions_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sample = await Sampler(images=[photo]).ask_a('Burnt?')
    followup = Sampler(data=sample, questions=['Still burnt?'])
    followup.save(tmp_path / 'Follow.yml')
    carried = await Sampler().load(tmp_path / 'Follow.yml').ask_a()
    assert carried.images[0].read_bytes() == PNG
    cleared = Sampler(data=sample, images=[], questions=['Review the answer?'])
    cleared.save(tmp_path / 'Cleared.yml')
    result = await Sampler().load(tmp_path / 'Cleared.yml').ask_a()
    assert result.images == []
    assert isinstance(calls[-1]['input'], str)
    assert all(client.is_closed() for client in clients)


def test_goal_inspection_and_reserved_fillings(decisions_transport, tmp_path):
    calls, _ = decisions_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(data='{provider}', images=[photo])
    wire = sampler.compile('Burnt?', fillings={'provider': 'A bakery'})
    assert wire['model'] == 'gpt-6-luna'
    assert wire['input'][0]['content'][0]['text'] == 'A bakery'
    assert not calls
    assert not (tmp_path / 'assets').exists()
    with pytest.raises(ValueError, match='Duplicate filling'):
        sampler.compile('Burnt?', fillings={'snack': 'a'}, snack='b')


@pytest.mark.asyncio
async def test_refusal_fillings_share_evaluation_and_keep_null(decisions_transport):
    calls, _ = decisions_transport
    Sampler(name='Declined', data='popcorn', questions=[Question(name='refused', question='Good?')]).save()
    values = await resolve_fillings_a(
        ['sampler.Declined.refused.choice', 'sampler.Declined.refused.refused'], allow_sampler=True)
    assert values['sampler']['Declined.refused.choice'] is None
    assert values['sampler']['Declined.refused.refused'] is True
    assert len(calls) == 1
    wire = await Sampler(data={'result': '{sampler.Declined.refused.choice}',
                              'note': 'Answer: {sampler.Declined.refused.choice}'}).compile_a('Good?')
    assert json.loads(wire['input']) == {'result': None, 'note': 'Answer: None'}
    assert len(calls) == 2


def test_all_refused_answers_keep_slots(decisions_transport):
    sample = Sampler(data='popcorn').ask(questions=[
        Question(name='refused', question='Good?'),
        Question(name='refused-choice', question='Which?', choices=['a', 'b']),
        Question(name='refused-score', question='How?', levels=['low', 'high']),
    ])
    assert isinstance(sample.answer, RefusalAnswer)
    assert len(sample.answers) == 3 and sample.answer is sample.answers['refused']
    assert all(getattr(answer, attr) is None for answer in sample.answers for attr in
               ('choice', 'score', 'probabilities', 'confidence', 'yes', 'no'))


def test_openai_settings_and_credentials_are_nonsecret(decisions_transport, monkeypatch):
    calls, clients = decisions_transport
    monkeypatch.setenv('SAMPLER_OPENAI_KEY', 'test-alternate-key')
    sampler = Sampler(data='popcorn', timeout=4, retry={'max_retries': 0},
                      base_url='https://example.test/v1', api_key_env='SAMPLER_OPENAI_KEY')
    sample = sampler.ask('Good?')
    assert clients[0].timeout == 4 and clients[0].max_retries == 0
    assert clients[0].api_key == 'test-alternate-key'
    assert str(clients[0].base_url) == 'https://example.test/v1/'
    assert sample.params.api_key_env == 'SAMPLER_OPENAI_KEY'
    assert 'test-alternate-key' not in json.dumps(sample.to_dict())
    replay = Sampler.from_sample(sample)
    assert replay.params == sample.params
    with pytest.raises(ValueError, match='Missing credential'):
        Sampler(data='popcorn', api_key_env='CHATSNACK_TEST_ABSENT_KEY').ask('Good?')
    assert len(calls) == 1


def test_openai_transport_failure_keeps_sdk_error(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only')
    original, clients = openai.OpenAI, []

    def factory(**options):
        client = original(http_client=httpx2.Client(transport=httpx2.MockTransport(
            lambda request: httpx2.Response(401, json={'error': {'message': 'unauthorized'}}))), **options)
        clients.append(client)
        return client

    monkeypatch.setattr(openai, 'OpenAI', factory)
    sampler = Sampler(data='popcorn', retry={'max_retries': 0})
    try:
        with pytest.raises(openai.AuthenticationError):
            sampler.ask('Good?')
        assert len(clients) == 1 and not clients[0].is_closed()
    finally:
        sampler.close()
    assert clients[0].is_closed()


def test_replay_freezes_environment_endpoint(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only')
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://first.test/v1')
    monkeypatch.setenv('TYPESAFE_BASE_URL', 'https://jev.test/v1')
    endpoints = []
    original = openai.OpenAI

    def handler(request):
        endpoints.append(str(request.url))
        body = json.loads(request.content)
        return httpx2.Response(200, json=dict(model='gpt-6-luna', usage=dict(input_tokens=1, output_tokens=0),
            answers=[dict(type='predicate', name=q['name'], probability=.8) for q in body['questions']]))

    def factory(**options):
        return original(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), **options)

    monkeypatch.setattr(openai, 'OpenAI', factory)
    sampler = Sampler(data='popcorn')
    try:
        sample = sampler.ask('Good?')
    finally:
        sampler.close()
    assert sample.params.base_url == 'https://first.test/v1'
    monkeypatch.setenv('OPENAI_BASE_URL', 'https://second.test/v1')
    replay = Sampler.from_sample(sample)
    try:
        replay.ask()
    finally:
        replay.close()
    assert endpoints == ['https://first.test/v1/decisions'] * 2
    assert SamplerParams(provider='typesafe').resolved().base_url == 'https://jev.test/v1'
    assert SamplerParams(base_url='https://explicit.test/v1').resolved().base_url == 'https://explicit.test/v1'


def test_provider_defaults_and_explicit_models(monkeypatch):
    monkeypatch.setenv('TYPESAFE_DEFAULT_MODEL', 'jev-custom')
    assert Sampler(data='snack').compile('Good?')['model'] == 'gpt-6-luna'
    assert Sampler(data='snack', provider='typesafe').compile('Good?')['model'] == 'jev-custom'
    assert Sampler(data='snack', model='jev-pinned').compile('Good?')['state'] == 'snack'
    explicit = Sampler(data='snack', provider='openai', model='jev-pinned').compile('Good?')
    assert explicit['model'] == 'jev-pinned' and explicit['input'] == 'snack'
    assert Sampler(data='snack', provider='typesafe', model='custom').compile('Good?')['model'] == 'custom'
    assert Sampler(data='snack').compile('Good?', provider='typesafe')['state'] == 'snack'


def test_structured_wire_and_anonymous_identifiers():
    wire = Sampler(data={'z': 1, 'a': [2]}).compile(questions=[
        Question(question={'z': 'Good?', 'a': []}, yes={'z': 1}, no=['bad']),
        Question(name='_question_0', question='Which?', choices={'b': None, 'a': {'z': 1, 'a': 2}}),
        Question(question='How?', levels=[{'high': None}, {'low': {'z': 3}}]),
    ])
    assert wire['input'] == '{"z":1,"a":[2]}'
    assert [q['name'] for q in wire['questions']] == ['__question_0', '_question_0', '_question_2']
    assert json.loads(wire['questions'][0]['instructions']) == {
        'question': {'z': 'Good?', 'a': []}, 'yes': {'z': 1}, 'no': ['bad']}
    assert wire['questions'][1]['choices'] == [{'value': 'b'}, {'value': 'a', 'description': '{"z":1,"a":2}'}]
    assert wire['questions'][2]['levels'] == [{'label': 'high'}, {'label': 'low', 'description': '{"z":3}'}]
    assert Question(question='Good?').compile() == {'type': 'noul', 'instructions': 'Good?'}


@pytest.mark.parametrize('answer', [
    {'type': 'choice', 'name': 'q', 'choice': 'a', 'confidence': .5,
     'probabilities': [{'value': 'a', 'probability': .5}, {'value': 'a', 'probability': .5}]},
    {'type': 'predicate', 'name': 'q', 'probability': .5},
    {'type': 'choice', 'name': 'q', 'choice': 'a', 'confidence': .5,
     'probabilities': [{'value': 'a', 'probability': 2}, {'value': 'b', 'probability': -1}]},
    {'type': 'choice', 'name': 'q', 'choice': 'c', 'confidence': .5,
     'probabilities': [{'value': 'a', 'probability': .5}, {'value': 'b', 'probability': .5}]},
    {'type': 'choice', 'name': 'q', 'choice': 'a', 'confidence': True,
     'probabilities': [{'value': 'a', 'probability': .5}, {'value': 'b', 'probability': .5}]},
    {'type': 'choice', 'name': 'q', 'choice': 'a', 'confidence': .5,
     'probabilities': [{'value': 'a', 'probability': .3}]},
])
def test_invalid_choice_responses_fail_without_answers(answer):
    question = Question(name='q', question='Which?', choices=['a', 'b'])
    request = dict(questions={'q': question.compile()})
    with pytest.raises(ValueError):
        response = normalize_decisions(dict(model='gpt-6-luna', answers=[answer],
            usage=dict(input_tokens=1, output_tokens=0)), request)
        decode('data', [question], ['q'], response, params=SamplerParams(provider='openai'))


@pytest.mark.parametrize('answers', [[], [{'name': 'other', 'type': 'refusal'}],
    [{'name': 'q', 'type': 'refusal'}, {'name': 'q', 'type': 'refusal'}],
    [{'name': None, 'type': 'refusal'}]])
def test_response_identities_are_strict(answers):
    question = Question(name='q', question='Good?')
    with pytest.raises(ValueError):
        response = normalize_decisions(dict(model='gpt-6-luna', answers=answers,
            usage=dict(input_tokens=1, output_tokens=0)), dict(questions={'q': question.compile()}))
        decode('data', [question], ['q'], response, params=SamplerParams(provider='openai'))


@pytest.mark.parametrize('value,label', [(True, 'low'), (0, 'wrong'), (2, 'high'), ('0', 'low')])
def test_score_indices_and_labels_must_match(value, label):
    request = dict(questions={'q': {'type': 'score'}}, _labels={'q': ['low', 'high']})
    with pytest.raises(ValueError, match='labels'):
        normalize_decisions({'answers': [dict(name='q', type='score', score=.4, confidence=.5,
            probabilities=[dict(value=value, label=label, probability=1)])]}, request)


@pytest.mark.parametrize('source', ['https://example.test/photo.png', {'url': 'https://example.test/a'},
                                   {'file_id': 'file-123'}, ChatFile(url='https://example.test/a')])
def test_unsupported_images_never_dispatch(decisions_transport, source):
    with pytest.raises(ValueError, match='local'):
        Sampler(images=[source]).ask('Good?')
    assert not decisions_transport[0]


def test_image_preflight_integrity_order_and_limits(decisions_transport, tmp_path):
    calls, _ = decisions_transport
    path = tmp_path / 'photo.png'
    path.write_bytes(PNG)
    reference = capture_asset(PNG, filename='generated.png', kind='image')
    generated = ChatFile.from_reference(reference, kind='image')
    assert len(Sampler(images=[path, generated]).compile('Good?')['input'][0]['content']) == 2
    assert Sampler().compile('Good?', images=['{photo}'], photo=generated)['input'][0]['content'][0]['type'] == 'input_image'
    with pytest.raises(ValueError, match='128'):
        Sampler(images=[path] * 129).ask('Good?')
    with pytest.raises(AssetMissingError):
        Sampler(images=[tmp_path / 'missing.png']).ask('Good?')
    path.write_bytes(b'GIF89a')
    with pytest.raises(ValueError, match='PNG, JPEG, or WebP'):
        Sampler(images=[path]).ask('Good?')
    generated.path.write_bytes(b'corrupt')
    with pytest.raises(AssetCorruptError):
        Sampler(images=[generated]).ask('Good?')
    assert not calls


def test_image_precedence_and_detached_execution_settings(decisions_transport, tmp_path):
    path = tmp_path / 'snack.png'
    path.write_bytes(PNG)
    sampler = Sampler(images=[path], timeout=4, retry={'max_retries': 0})
    original = sampler.ask('Good?')
    original.params.retry['max_retries'] = 100
    assert original.params.retry == {'max_retries': 0}
    path.unlink()
    assert Sampler(data=original).ask('Good?').images[0].read_bytes() == PNG
    assert Sampler(data=original, images=[]).ask('Good?').images == []
    assert Sampler(data=original, images=[path]).ask('Good?', images=[]).images == []
    with pytest.raises(ValueError, match='missing'):
        Sampler(images=[]).ask('Good?')
    sampler.close()


def test_snapshot_uses_inspected_bytes_when_source_changes(decisions_transport, tmp_path, monkeypatch):
    from chatsnack.sampler import provider
    path = tmp_path / 'snack.png'
    path.write_bytes(PNG)
    evaluate = provider.evaluate_sync

    def change_after_inspection(request, params):
        response = evaluate(request, params)
        path.write_bytes(b'changed after dispatch')
        return response

    monkeypatch.setattr(provider, 'evaluate_sync', change_after_inspection)
    sampler = Sampler(images=[path])
    try:
        sample = sampler.ask('Good?')
        encoded = decisions_transport[0][0]['input'][0]['content'][0]['image_url'].split(',', 1)[1]
        assert sample.images[0].read_bytes() == base64.b64decode(encoded) == PNG
    finally:
        sampler.close()


def test_openai_retry_settings_fail_before_dependencies(decisions_transport):
    with pytest.raises(ValueError, match='retry.max_retries'):
        Sampler(data='{chat.Dependency}', retry={'backoff_initial': 0}).ask('Good?')
    assert not decisions_transport[0]


def test_sync_provider_override_is_scoped(decisions_transport, monkeypatch):
    import typesafe_sdk
    calls, clients = decisions_transport
    jev_clients = []

    class Jev:
        def __init__(self, **options):
            self.closed = False
            jev_clients.append(self)

        def system_one(self, **wire):
            return dict(model='jev-pinned', usage=dict(input_tokens=1, output_tokens=0),
                        answers={key: dict(type='noul', noul=.8) for key in wire['questions']})

        def close(self):
            self.closed = True

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient', Jev)
    sampler = Sampler(data='popcorn')
    sampler.ask('Good?')
    assert sampler.ask('Good?', model='jev-pinned').provider == 'typesafe'
    sampler.ask('Good?')
    assert len(clients) == 1 and len(calls) == 2
    assert jev_clients[0].closed and not clients[0].is_closed()
    sampler.provider = 'typesafe'
    with pytest.raises(RuntimeError, match='Close'):
        sampler.ask('Good?')
    sampler.close()
    sampler.ask('Good?')
    assert len(jev_clients) == 2
    sampler.close()


def test_openai_context_errors_do_not_use_jev_correction(monkeypatch):
    """The provider-specific context retry must never resubmit OpenAI requests."""
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only')
    original = openai.OpenAI
    calls = []

    def handler(request):
        calls.append(request)
        return httpx2.Response(400, json={'error': {'code': 'max_tokens_exceeded', 'message': 'Too long'}})

    def factory(**options):
        return original(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), **options)

    monkeypatch.setattr(openai, 'OpenAI', factory)
    sampler = Sampler(data='document', retry={'max_retries': 0})
    try:
        with pytest.raises(openai.BadRequestError):
            sampler.ask('Good?')
        assert len(calls) == 1
        assert not any(key.startswith('typesafe-') for key in calls[0].headers)
    finally:
        sampler.close()


@pytest.mark.asyncio
async def test_openai_cancellation_closes_client(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only')
    started, clients = asyncio.Event(), []
    original = openai.AsyncOpenAI

    async def handler(request):
        started.set()
        await asyncio.Event().wait()

    def factory(**options):
        client = original(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), **options)
        clients.append(client)
        return client

    monkeypatch.setattr(openai, 'AsyncOpenAI', factory)
    task = asyncio.create_task(Sampler(data='popcorn').ask_a('Good?'))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients[0].is_closed()
