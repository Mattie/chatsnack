"""Contract tests through the required SDK's HTTP encode/decode boundary."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import httpx2
import typesafe_sdk

from chatsnack import Question, Sampler


@pytest.fixture
def sdk_transport(monkeypatch):
    """Use the real client against an in-memory HTTP transport."""
    sdk = typesafe_sdk
    httpx = httpx2
    clients = []
    original_sync = sdk.TypeSafeClient
    original_async = sdk.AsyncTypeSafeClient

    def configure(handler):
        def sync_factory(**kwargs):
            http_client = httpx.Client(transport=httpx.MockTransport(handler))
            clients.append(http_client)
            return original_sync(http_client=http_client, **kwargs)

        def async_factory(**kwargs):
            http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            clients.append(http_client)
            return original_async(http_client=http_client, **kwargs)

        monkeypatch.setattr(sdk, 'TypeSafeClient', sync_factory)
        monkeypatch.setattr(sdk, 'AsyncTypeSafeClient', async_factory)
        return clients

    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-key')
    return sdk, httpx, configure


def test_sdk_mixed_question_contract_and_settings(sdk_transport, monkeypatch):
    sdk, httpx, configure = sdk_transport
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=dict(model='jev-pinned', usage=dict(input_tokens=4, output_tokens=2),
            answers={'yes': dict(type='noul', noul=.8),
                     'topic': dict(type='choice', choice='a', probabilities={'a': 1., 'b': 0.}, confidence=1.),
                     'rating': dict(type='score', score=.25, probabilities={'0': .75, '1': .25},
                                    legend={'0': 'Low', '1': 'High'}, confidence=.4)}))

    clients = configure(handler)
    monkeypatch.setenv('SAMPLER_TEST_KEY', 'alternate-test-key')
    sampler = Sampler(provider='typesafe', data={'record': []}, model='jev-pinned', timeout=4,
                      api_key_env='SAMPLER_TEST_KEY', base_url='https://example.test/v1',
                      retry={'max_retries': 0})
    sample = sampler.ask(questions=[
                         Question(name='yes', question={'instruction': 'Good?'}, yes={'rubric': []}),
                         Question(name='topic', question='Topic?', choices=['a', 'b']),
                         Question(name='rating', question='Rate?', levels=[{'low': 'Low'}, {'high': 'High'}])])
    assert sample.answers['rating'].probabilities == {'low': .75, 'high': .25}
    assert sample.answers['rating'].score == .25
    assert seen[0].url.host == 'example.test'
    assert seen[0].headers['authorization'] == 'Bearer alternate-test-key'
    body = json.loads(seen[0].content)
    assert body['state'] == {'record': []}
    assert body['questions']['yes']['criteria']['true'] == {'rubric': []}
    assert body['questions']['topic']['criteria'] == {'a': None, 'b': None}
    assert body['model'] == 'jev-pinned'
    assert not clients[0].is_closed
    sampler.close()
    assert clients[0].is_closed


def test_sdk_error_remains_recognizable_and_closes(sdk_transport):
    sdk, httpx, configure = sdk_transport
    clients = configure(lambda request: httpx.Response(401, json={'error': 'unauthorized'}))
    sampler = Sampler(provider='typesafe', data='hello', retry={'max_retries': 0})
    with pytest.raises(sdk.TypeSafeAPIError):
        sampler.ask('Good?')
    assert not clients[0].is_closed
    sampler.close()
    assert clients[0].is_closed


def test_sdk_owns_retry_policy(sdk_transport):
    sdk, httpx, configure = sdk_transport
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429, json={'error': 'slow down'})
        return httpx.Response(200, json=dict(model='jev', usage=dict(input_tokens=1, output_tokens=1),
                                            answers={'_question_0': dict(type='noul', noul=.7)}))

    configure(handler)
    assert Sampler(provider='typesafe', data='hello', retry={'max_retries': 1, 'backoff_initial': 0}).ask('Good?').answer.yes
    assert len(seen) == 2


def test_goal_context_limit_retries_once_without_changing_short_calls(sdk_transport, tmp_path, monkeypatch):
    """Use server feedback to extend context, and start every new call normally."""
    _, httpx, configure = sdk_transport
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    Question(name='ContextCheck', question='Original question?').save()
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append((body, dict(request.headers)))
        if body['state'] == 'long document' and 'typesafe-danger-zone-long-context' not in request.headers:
            # Changing a live dependency must affect the next evaluation, not the retry.
            Question(name='ContextCheck', question='Updated question?').save()
            return httpx.Response(400, json={'detail': {'error_type': 'max_tokens_exceeded'}})
        return httpx.Response(200, json=dict(model='jev-1.14.0', usage=dict(input_tokens=4, output_tokens=1),
            answers={key: dict(type='noul', noul=.8) for key in body['questions']}))

    clients = configure(handler)
    sampler = Sampler(model='jev-1.14.0', data='long document', questions=['{question.ContextCheck}'],
                      retry={'max_retries': 0})
    try:
        sample = sampler.ask()
        assert sample.answer.yes
        assert len(calls) == 2 and calls[0][0] == calls[1][0]
        assert calls[1][0]['questions']['ContextCheck']['instructions'] == 'Original question?'
        assert 'typesafe-danger-zone-long-context' not in calls[0][1]
        assert calls[1][1]['typesafe-danger-zone-long-context'] == 'true'
        sampler.ask(data='short document')
        assert len(calls) == 3 and len(clients) == 1
        assert calls[-1][0]['questions']['ContextCheck']['instructions'] == 'Updated question?'
        assert 'typesafe-danger-zone-long-context' not in calls[-1][1]
        replay = Sampler.from_sample(sample).save(tmp_path / 'Long.yml')
        assert 'experimental' not in replay.yaml
        restored = Sampler().load(tmp_path / 'Long.yml')
        try:
            assert restored.ask().answer.yes
            assert len(calls) == 5
            assert 'typesafe-danger-zone-long-context' not in calls[-2][1]
            assert calls[-1][1]['typesafe-danger-zone-long-context'] == 'true'
        finally:
            restored.close()
    finally:
        sampler.close()


@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
@pytest.mark.parametrize('status,body,attempts', [
    (400, {'detail': {'error_type': 'max_tokens_exceeded'}}, 2),
    (400, {'error': 'max_tokens_exceeded'}, 2),
    (400, {'detail': 'max_tokens_exceeded'}, 2),
    (400, {'error': {'code': 'max_tokens_exceeded'}}, 2),
    (400, {'code': 'max_tokens_exceeded'}, 2),
    (400, {'error': 'invalid_image'}, 1),
    (400, {'detail': {'error_type': 'invalid_image'}}, 1),
    (400, {'message': 'Example text mentions max_tokens_exceeded'}, 1),
    (400, {'state': {'code': 'max_tokens_exceeded'}}, 1),
    (401, {'error': 'max_tokens_exceeded'}, 1),
    (413, {'error': 'max_tokens_exceeded'}, 1),
    (429, {'error': 'rate_limit_exceeded'}, 1),
    (500, {'error': 'max_tokens_exceeded'}, 1),
])
@pytest.mark.asyncio
async def test_goal_context_correction_is_bounded_and_errors_stay_recognizable(
        sdk_transport, asynchronous, status, body, attempts):
    """Only an explicit context error gets a second request, even if it fails again."""
    sdk, httpx, configure = sdk_transport
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers={'x-typesafe-request-id': f'attempt-{len(calls)}'})

    clients = configure(handler)
    sampler = Sampler(model='jev-1.14.0', data='document', retry={'max_retries': 0})
    try:
        with pytest.raises(sdk.TypeSafeAPIError) as failure:
            if asynchronous:
                await sampler.ask_a('Good?')
            else:
                sampler.ask('Good?')
        assert len(calls) == attempts and len(clients) == 1
        assert failure.value.status == status and failure.value.body == body
        assert failure.value.request_id == f'attempt-{attempts}'
        assert 'typesafe-danger-zone-long-context' not in calls[0].headers
        if attempts == 2:
            assert calls[-1].headers['typesafe-danger-zone-long-context'] == 'true'
        if asynchronous:
            assert clients[0].is_closed
    finally:
        sampler.close()


@pytest.mark.asyncio
async def test_cancellation_during_context_correction_closes_client(sdk_transport):
    _, httpx, configure = sdk_transport
    started, calls = asyncio.Event(), []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(400, json={'error': 'max_tokens_exceeded'})
        started.set()
        await asyncio.Event().wait()

    clients = configure(handler)
    task = asyncio.create_task(Sampler(model='jev-1.14.0', data='document',
                                      retry={'max_retries': 0}).ask_a('Good?'))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 2 and clients[0].is_closed


@pytest.mark.asyncio
async def test_sdk_client_closes_on_cancellation(sdk_transport):
    sdk, httpx, configure = sdk_transport
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.Event().wait()

    clients = configure(handler)
    sampler = Sampler(provider='typesafe', data='hello')
    task = asyncio.create_task(sampler.ask_a('Good?'))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients[0].is_closed
    await sampler.close_a()
    assert clients[0].is_closed


def test_authoring_does_not_import_provider_sdk(tmp_path):
    script = r'''
import builtins
from pathlib import Path
import sys

original = builtins.__import__

def without_sdk(name, *args, **kwargs):
    if name == 'typesafe_sdk' or name.startswith('typesafe_sdk.'):
        raise AssertionError('Authoring must not import the provider SDK')
    return original(name, *args, **kwargs)

builtins.__import__ = without_sdk
from chatsnack import Sampler
from tests.test_sampler_decisions_live import red_png

sampler = Sampler(provider='typesafe', name='Offline', data='hi', questions=['Good?'])
sampler.save(Path(sys.argv[1]) / 'Offline.yml')
assert sampler.compile()['state'] == 'hi'
photo = Path(sys.argv[1]) / 'photo.png'
photo.write_bytes(red_png(280))
wire = sampler.compile(images=[photo])
assert len(wire['assets']) == 1
assert 'typesafe_sdk' not in sys.modules
'''
    result = subprocess.run(
        [sys.executable, '-c', script, str(tmp_path)],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr


def _fake_response(score=.8):
    """Return the smallest provider result that exercises normal decoding."""
    return dict(model='fake', usage=dict(input_tokens=1, output_tokens=1),
                answers={'_question_0': dict(type='noul', noul=score)})


def test_repeated_sync_asks_reuse_one_client_until_sampler_closes(monkeypatch):
    """One authored Sampler should retain its sync transport across evaluations."""
    clients = []

    class Client:
        def __init__(self, **options):
            self.options = options
            self.closed = False
            self.calls = 0
            clients.append(self)

        def system_one(self, **request):
            self.calls += 1
            return _fake_response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient', Client)
    sampler = Sampler(provider='typesafe', data='popcorn', timeout=4)

    assert sampler.ask('Crunchy?').answer.yes
    assert sampler.ask('Crunchy?').answer.yes
    assert len(clients) == 1
    assert clients[0].calls == 2
    assert not clients[0].closed

    sampler.close()
    assert clients[0].closed


@pytest.mark.asyncio
async def test_repeated_async_asks_close_their_loop_scoped_clients(monkeypatch):
    """Every async evaluation closes its client on the active event loop."""
    clients = []

    class Client:
        def __init__(self, **options):
            self.options = options
            self.closed = False
            self.calls = 0
            clients.append(self)

        async def system_one(self, **request):
            self.calls += 1
            return _fake_response()

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(typesafe_sdk, 'AsyncTypeSafeClient', Client)
    sampler = Sampler(provider='typesafe', data='popcorn', timeout=4)

    assert (await sampler.ask_a('Crunchy?')).answer.yes
    assert (await sampler.ask_a('Crunchy?')).answer.yes
    assert len(clients) == 2
    assert [client.calls for client in clients] == [1, 1]
    assert all(client.closed for client in clients)

    await sampler.close_a()


def test_call_override_uses_scoped_client_without_rebinding_sampler(monkeypatch):
    """A one-call connection override must leave the authored client reusable."""
    clients = []

    class Client:
        def __init__(self, **options):
            self.options = options
            self.closed = False
            clients.append(self)

        def system_one(self, **request):
            return _fake_response()

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient', Client)
    sampler = Sampler(provider='typesafe', data='popcorn', timeout=4)

    sampler.ask('Crunchy?')
    sampler.ask('Crunchy?', model='jev-pinned')
    sampler.ask('Crunchy?', timeout=8)
    sampler.ask('Crunchy?')

    assert [client.options['timeout'] for client in clients] == [4, 8]
    assert not clients[0].closed
    assert clients[1].closed
    sampler.close()


def test_sync_override_replaces_invalid_authored_connection_setting(monkeypatch):
    """Only effective call parameters are validated for a scoped sync request."""
    clients = []

    class Client:
        def __init__(self, **options):
            self.options = options
            self.closed = False
            clients.append(self)

        def system_one(self, **request):
            return _fake_response()

        def close(self):
            self.closed = True

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient', Client)
    sampler = Sampler(provider='typesafe', data='popcorn', timeout=-1)

    assert sampler.ask('Crunchy?', timeout=1).answer.yes
    assert [client.options['timeout'] for client in clients] == [1]
    assert clients[0].closed


@pytest.mark.asyncio
async def test_async_override_replaces_invalid_authored_connection_setting(monkeypatch):
    """Only effective call parameters are validated for a scoped async request."""
    clients = []

    class Client:
        def __init__(self, **options):
            self.options = options
            self.closed = False
            clients.append(self)

        async def system_one(self, **request):
            return _fake_response()

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr(typesafe_sdk, 'AsyncTypeSafeClient', Client)
    sampler = Sampler(provider='typesafe', data='popcorn', timeout=-1)

    assert (await sampler.ask_a('Crunchy?', timeout=1)).answer.yes
    assert [client.options['timeout'] for client in clients] == [1]
    assert clients[0].closed


@pytest.mark.skipif(os.getenv('CHATSNACK_RUN_TYPESAFE_LIVE') != '1', reason='opt-in paid TypeSafe contract')
def test_live_mixed_questions():
    sample = Sampler(provider='typesafe', data={'food': 'buttered popcorn'}).ask(questions=[
        Question(name='crunchy', question='Is this crunchy?'),
        Question(name='category', question='Which category?', choices=['snack', 'drink']),
        Question(name='sweetness', question='How sweet?', levels=['Not sweet', 'Very sweet']),
    ])
    assert len(sample.answers) == 3
    assert sample.answer is sample.answers['crunchy']
    assert all(answer.choice in answer.probabilities for answer in sample.answers)
    assert sample.model and sample.usage.input_tokens >= 0


@pytest.mark.skipif(os.getenv('CHATSNACK_RUN_TYPESAFE_LIVE') != '1', reason='opt-in paid TypeSafe vision contract')
def test_live_jev_images_and_replay(tmp_path, monkeypatch):
    """Check experimental headers, semantic vision, and replay against Jev itself."""
    from tests.test_sampler_decisions_live import red_png
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    photo = tmp_path / 'red.png'
    photo.write_bytes(red_png(280))
    sampler = Sampler(model='jev-1.14.0', images=[photo],
                      questions=[Question(name='color', question='What is the dominant color?',
                                          choices=['red', 'blue', 'green'])],
                      timeout=45, retry={'max_retries': 0})
    try:
        sample = sampler.ask()
        assert sample.answer.choice == 'red'
        Sampler.from_sample(sample).save(tmp_path / 'JevReplay.yml')
        photo.unlink()
        replay = Sampler().load(tmp_path / 'JevReplay.yml')
        try:
            repeated = replay.ask()
            assert repeated.answer.choice == 'red'
            assert repeated.images[0].read_bytes() == red_png(280)
            assert 'experimental' not in repeated.params.authored()
        finally:
            replay.close()
    finally:
        sampler.close()
