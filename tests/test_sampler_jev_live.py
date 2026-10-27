"""Paid Jev checks that require real context rejection and successful recovery."""

import asyncio
import hashlib
import json
import os

import pytest

from chatsnack import Question, Sampler
from tests.test_sampler_decisions_live import context_questions, judgments, make_document, red_png


@pytest.mark.skipif(os.getenv('CHATSNACK_RUN_TYPESAFE_LIVE') != '1', reason='opt-in paid TypeSafe context contract')
@pytest.mark.parametrize('asynchronous', [False, True], ids=['sync', 'async'])
def test_live_context_retry_preserves_images_and_short_requests(asynchronous, tmp_path, monkeypatch):
    """Observe real SDK calls while checking context recovery and all judgment kinds."""
    import typesafe_sdk as sdk

    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    calls = []

    def record(wire):
        """Retain safe request metadata without logging input or credentials."""
        evidence = {key: wire[key] for key in ('model', 'state', 'questions')}
        call = dict(evidence=hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
                    headers=dict(wire.get('extra_headers', {})), status=200)
        calls.append(call)
        return call

    sync_submit = sdk.TypeSafeClient.system_one
    async_submit = sdk.AsyncTypeSafeClient.system_one

    def submit(client, **wire):
        """Observe the synchronous call, retaining the real network and response."""
        call = record(wire)
        try:
            return sync_submit(client, **wire)
        except sdk.TypeSafeAPIError as error:
            call['status'] = error.status
            raise

    async def submit_a(client, **wire):
        """Observe the asynchronous call without replacing its transport."""
        call = record(wire)
        try:
            return await async_submit(client, **wire)
        except sdk.TypeSafeAPIError as error:
            call['status'] = error.status
            raise

    monkeypatch.setattr(sdk.TypeSafeClient, 'system_one', submit)
    monkeypatch.setattr(sdk.AsyncTypeSafeClient, 'system_one', submit_a)
    photo = tmp_path / 'red.png'
    photo.write_bytes(red_png(280))
    # Fixed oversized evidence exercises server feedback; runtime code never estimates tokens.
    sampler = Sampler(model='jev-1.14.0', data=make_document(5000, varied=False),
                      images=[photo], questions=context_questions(), timeout=60, retry={'max_retries': 0})

    def ask(**overrides):
        """Drain AnyIO worker-stop callbacks after the standalone async evaluation."""
        if not asynchronous:
            return sampler.ask(**overrides)
        try:
            return asyncio.run(sampler.ask_a(**overrides))
        finally:
            asyncio.run(asyncio.sleep(0))

    try:
        sample = ask()
        assert all(judgments(sample))
        assert len(calls) == 2
        assert [call['status'] for call in calls] == [400, 200]
        assert calls[0]['evidence'] == calls[1]['evidence']
        assert 'TypeSafe-Danger-Zone-Long-Context' not in calls[0]['headers']
        assert calls[1]['headers']['TypeSafe-Danger-Zone-Long-Context'] == 'true'
        assert calls[0]['headers'] == {key: value for key, value in calls[1]['headers'].items()
                                      if key != 'TypeSafe-Danger-Zone-Long-Context'}
        assert calls[0]['headers']['TypeSafe-Danger-Zone-Images'] == 'true'

        short = dict(data='The sky is blue.', images=[],
                     questions=[Question(name='blue', question='Is the sky blue?')])
        result = ask(**short)
        assert result.answer.yes
        assert len(calls) == 3
        assert calls[-1]['headers'] == {}
        assert calls[-1]['status'] == 200
        print(json.dumps(dict(stage='context-retry', asynchronous=asynchronous, model=sample.model,
                              input_tokens=sample.usage.input_tokens, accuracy=judgments(sample),
                              statuses=[call['status'] for call in calls], short_headers=calls[-1]['headers'])))
    finally:
        sampler.close()
