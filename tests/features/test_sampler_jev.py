"""Jev image Goals through the real SDK, with only HTTP replaced."""

import base64
import json
from email import policy
from email.parser import BytesParser

import httpx2
import pytest
import typesafe_sdk

from chatsnack import Question, Sampler, resolve_fillings_a
from tests.test_sampler_decisions_live import red_png


PNG = red_png(280)  # Meet Jev's minimum pixel area as well as its width/height limits.


@pytest.fixture
def jev_transport(monkeypatch, tmp_path, request):
    """Capture actual JSON/multipart uploads and decode actual SDK responses."""
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only')
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    calls, clients = [], []
    sync, asynchronous = typesafe_sdk.TypeSafeClient, typesafe_sdk.AsyncTypeSafeClient
    reject_standard_context = getattr(request, 'param', False)

    def handler(request):
        """Inspect multipart with the standard MIME parser instead of mocking assets."""
        files = {}
        if request.headers['content-type'].startswith('multipart/'):
            message = BytesParser(policy=policy.default).parsebytes(
                ('Content-Type: ' + request.headers['content-type'] + '\r\n\r\n').encode()
                + request.content)
            parts = {part.get_param('name', header='content-disposition'): part.get_payload(decode=True)
                     for part in message.iter_parts()}
            body = json.loads(parts.pop('request'))
            files = parts
        else:
            body = json.loads(request.content)
        calls.append((body, files, dict(request.headers)))
        assert request.url.path == '/v1/systemone'
        if reject_standard_context and 'typesafe-danger-zone-long-context' not in request.headers:
            return httpx2.Response(400, json={'error': 'max_tokens_exceeded'})
        return httpx2.Response(200, json=dict(model='jev-1.14.0',
            usage=dict(input_tokens=120, output_tokens=1),
            answers={key: dict(type='noul', noul=.9) for key in body['questions']}))

    def factory(**options):
        """Disable SDK compression only to keep the captured request readable."""
        http = httpx2.Client(transport=httpx2.MockTransport(handler))
        client = sync(http_client=http, compression=False, **options)
        clients.append(http)
        return client

    def async_factory(**options):
        """Exercise async multipart sending and SDK-owned client cleanup."""
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        clients.append(http)
        return asynchronous(http_client=http, compression=False, **options)

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient', factory)
    monkeypatch.setattr(typesafe_sdk, 'AsyncTypeSafeClient', async_factory)
    yield calls, clients
    for client in clients:
        if isinstance(client, httpx2.Client):
            client.close()


def _uploaded_images(call):
    """Recover the bytes the HTTP request actually sent in state image order."""
    body, files, _ = call
    return [files[body['assets'][key]['part']] if 'part' in body['assets'][key]
            else base64.b64decode(body['assets'][key]['data_base64'])
            for key in body['state']['images']]


def test_goal_saved_jev_images_replay_without_original_file(jev_transport, tmp_path):
    calls, _ = jev_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    Sampler(name='JevPhoto', model='jev-1.14.0',
            data={'snack': '{snack}'}, images=['{photo}'],
            questions=[Question(name='burnt', question='Does the snack look burnt?')]).save()
    sampler = Sampler(name='JevPhoto').load()
    try:
        sample = sampler.ask(snack='popcorn', photo=photo)
        assert sample.answers['burnt'].yes
        assert 'experimental' not in sample.params.authored()
        assert sample.data == {'snack': 'popcorn'}
        assert sample.images[0].read_bytes() == PNG
        assert calls[0][0]['state']['data'] == sample.data
        assert calls[0][2]['typesafe-danger-zone-images'] == 'true'
        assert _uploaded_images(calls[0]) == [PNG]
        replay = Sampler.from_sample(sample, name='JevReplay').save()
        assert 'asset:' in replay.yaml and 'base64' not in replay.yaml
        assert 'base64' not in json.dumps(sample.to_dict())
        photo.unlink()
        repeated_sampler = Sampler(name='JevReplay').load()
        try:
            repeated = repeated_sampler.ask()
            assert repeated.answer.yes
            assert 'experimental' not in repeated.params.authored()
            assert repeated.images[0].read_bytes() == PNG
            assert _uploaded_images(calls[-1]) == [PNG]
        finally:
            repeated_sampler.close()
    finally:
        sampler.close()


@pytest.mark.asyncio
async def test_goal_async_image_only_followups_and_named_fillings(jev_transport, tmp_path):
    calls, clients = jev_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(name='AsyncPhoto', model='jev-1.14.0',
                      images=['{photo}'], questions=[Question(name='burnt', question='Burnt?')]).save()
    sample = await sampler.ask_a(photo=photo)
    assert sample.data is None and _uploaded_images(calls[0]) == [PNG]
    values = await resolve_fillings_a(
        ['sampler.AsyncPhoto.burnt.choice', 'sampler.AsyncPhoto.burnt.confidence'],
        variables={'photo': photo}, allow_sampler=True)
    assert values['sampler']['AsyncPhoto.burnt.choice'] == 'yes'
    assert len(calls) == 2  # Both leaves share one saved evaluation.
    photo.unlink()
    carried = await Sampler(data=sample, model='jev-1.14.0').ask_a('Still burnt?')
    assert carried.images[0].read_bytes() == PNG
    assert _uploaded_images(calls[-1]) == [PNG]
    cleared = await Sampler(data=sample, model='jev-1.14.0').ask_a('Review the answers?', images=[])
    assert cleared.images == [] and 'assets' not in calls[-1][0]
    assert 'typesafe-danger-zone-images' not in calls[-1][2]
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize('jev_transport', [True], indirect=True)
async def test_goal_async_context_retry_preserves_images_and_filling_reuse(jev_transport, tmp_path):
    """A context correction repeats the resolved batch, not its dependency work."""
    calls, clients = jev_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(name='LongPhoto', model='jev-1.14.0', data='{document}',
                      images=['{photo}'], questions=[Question(name='burnt', question='Burnt?')],
                      retry={'max_retries': 0}).save()
    sample = await sampler.ask_a(document='a document', photo=photo)
    assert sample.answer.yes and len(calls) == 2
    assert calls[0][0] == calls[1][0]
    assert _uploaded_images(calls[0]) == _uploaded_images(calls[1]) == [PNG]
    assert 'typesafe-danger-zone-long-context' not in calls[0][2]
    assert calls[1][2]['typesafe-danger-zone-long-context'] == 'true'
    assert all(call[2]['typesafe-danger-zone-images'] == 'true' for call in calls)
    values = await resolve_fillings_a(
        ['sampler.LongPhoto.burnt.choice', 'sampler.LongPhoto.burnt.confidence'],
        variables={'document': 'a document', 'photo': photo}, allow_sampler=True)
    assert values['sampler']['LongPhoto.burnt.choice'] == 'yes'
    assert len(calls) == 4 and len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_inferred_image_header_tracks_call_overrides_on_one_client(jev_transport, tmp_path):
    calls, clients = jev_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(model='jev-1.14.0', data='popcorn', images=[photo])
    try:
        sampler.ask('Good?')
        cleared = sampler.ask('Good?', images=[])
        sampler.ask('Good?')
        sampler.ask('Good?')
        assert len(clients) == 1
        assert ['typesafe-danger-zone-images' in call[2] for call in calls] == [True, False, True, True]
        assert all('typesafe-danger-zone-long-context' not in call[2] for call in calls)
        assert cleared.images == [] and 'assets' not in calls[1][0]
        assert _uploaded_images(calls[2]) == [PNG]
    finally:
        sampler.close()


def test_inspection_is_json_and_uses_ordered_assets_without_snapshots(jev_transport, tmp_path):
    calls, _ = jev_transport
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(model='jev-1.14.0',
                      data={'images': 'caller data'}, images=[photo, photo])
    wire = sampler.compile('Good?')
    assert wire['state']['data'] == {'images': 'caller data'}
    assert len(set(wire['state']['images'])) == 2
    assert list(wire['assets']) == wire['state']['images']
    assert all(base64.b64decode(asset['data_base64']) == PNG for asset in wire['assets'].values())
    assert 'extra_headers' not in json.loads(json.dumps(wire))
    assert not calls and not (tmp_path / 'assets').exists()
    sampler.ask('Good?')
    assert calls[-1][2]['typesafe-danger-zone-images'] == 'true'
    assert 'typesafe-danger-zone-long-context' not in calls[-1][2]
    assert _uploaded_images(calls[-1]) == [PNG, PNG]
    sampler.close()


def test_unsupported_image_formats_fail_before_dispatch(jev_transport, tmp_path):
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    with pytest.raises(ValueError, match='PNG or JPEG'):
        photo.write_bytes(b'RIFF\x00\x00\x00\x00WEBP')
        Sampler(model='jev-1.14.0', images=[photo]).compile('Good?')
    with pytest.raises(ValueError, match='16 MiB'):
        photo.write_bytes(PNG + b'\0' * (16 * 1024 * 1024))
        Sampler(model='jev-1.14.0', images=[photo]).ask('Good?')
    assert not jev_transport[0]


def test_openai_image_limit_does_not_become_a_jev_limit(jev_transport, tmp_path):
    photo = tmp_path / 'snack.png'
    photo.write_bytes(PNG)
    sampler = Sampler(model='jev-1.14.0', images=[photo] * 129)
    assert len(sampler.compile('Good?')['assets']) == 129
    with pytest.raises(ValueError, match='128'):
        sampler.compile('Good?', provider='openai')


def test_experimental_keyword_can_still_be_a_filling():
    wire = Sampler(model='jev-1.14.0', data='{experimental}').compile(
        'Good?', experimental='an unusual snack')
    assert wire['state'] == 'an unusual snack'
