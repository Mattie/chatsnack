"""Contract tests through the required SDK's HTTP encode/decode boundary."""

import asyncio
import builtins
import json
import os

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
    original = sdk.AsyncTypeSafeClient

    def configure(handler):
        def factory(**kwargs):
            http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            clients.append(http_client)
            return original(http_client=http_client, **kwargs)
        monkeypatch.setattr(sdk, 'AsyncTypeSafeClient', factory)
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
    sample = Sampler(data={'record': []}, model='jev-pinned', timeout=4,
                     api_key_env='SAMPLER_TEST_KEY', base_url='https://example.test/v1',
                     retry={'max_retries': 0}).ask(questions=[
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
    assert clients[0].is_closed


def test_sdk_error_remains_recognizable_and_closes(sdk_transport):
    sdk, httpx, configure = sdk_transport
    clients = configure(lambda request: httpx.Response(401, json={'error': 'unauthorized'}))
    with pytest.raises(sdk.TypeSafeAPIError):
        Sampler(data='hello', retry={'max_retries': 0}).ask('Good?')
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
    assert Sampler(data='hello', retry={'max_retries': 1, 'backoff_initial': 0}).ask('Good?').answer.yes
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_sdk_client_closes_on_cancellation(sdk_transport):
    sdk, httpx, configure = sdk_transport
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.Event().wait()

    clients = configure(handler)
    task = asyncio.create_task(Sampler(data='hello').ask_a('Good?'))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients[0].is_closed


def test_authoring_does_not_import_provider_sdk(monkeypatch, tmp_path):
    original = builtins.__import__

    def without_sdk(name, *args, **kwargs):
        if name == 'typesafe_sdk':
            raise AssertionError('Authoring must not import the provider SDK')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', without_sdk)
    sampler = Sampler(name='Offline', data='hi', questions=['Good?'])
    sampler.save(tmp_path / 'Offline.yml')
    assert sampler.compile()['state'] == 'hi'


@pytest.mark.skipif(os.getenv('CHATSNACK_RUN_TYPESAFE_LIVE') != '1', reason='opt-in paid TypeSafe contract')
def test_live_mixed_questions():
    sample = Sampler(data={'food': 'buttered popcorn'}).ask(questions=[
        Question(name='crunchy', question='Is this crunchy?'),
        Question(name='category', question='Which category?', choices=['snack', 'drink']),
        Question(name='sweetness', question='How sweet?', levels=['Not sweet', 'Very sweet']),
    ])
    assert len(sample.answers) == 3
    assert sample.answer is sample.answers['crunchy']
    assert all(answer.choice in answer.probabilities for answer in sample.answers)
    assert sample.model and sample.usage.input_tokens >= 0
