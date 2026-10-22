"""Paid, explicit opt-ins for implemented Decisions vision and long-context contracts."""

import json
import os
import struct
import zlib

import pytest

from chatsnack import Question, Sampler


def red_png(size=64):
    """Make a simple vision fixture without requiring an imaging dependency."""
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', size, size, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0' * size) * size)) + chunk(b'IEND', b''))


def context_questions():
    """Read independently placed evidence with all three judgment kinds."""
    return [
        Question(name='end_approved', question='Is the approved field of target record FINAL true? Use only that named record.'),
        Question(name='middle_warehouse', question='Which warehouse is assigned to target record CENTER? Use only that named record.',
                 choices=['red', 'blue', 'green']),
        Question(name='start_severity', question='What is the severity of target record ORIGIN? Use only that named record.',
                 levels=['ordinary', 'major', 'critical']),
    ]


def judgments(sample):
    """Report correctness without treating confidence as a shared calibration scale."""
    return [sample.answers['end_approved'].yes is True,
            sample.answers['middle_warehouse'].choice == 'blue',
            sample.answers['start_severity'].choice == 'critical']


@pytest.mark.skipif(os.getenv('CHATSNACK_RUN_DECISIONS_LIVE') != '1', reason='opt-in paid Decisions contract')
def test_live_mixed_questions_and_image_replay(tmp_path, monkeypatch):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    sampler = Sampler(data='Target record ORIGIN has severity critical.\n'
                           'Target record CENTER has warehouse blue.\nTarget record FINAL has approved true.',
                      timeout=45, retry={'max_retries': 0})
    try:
        sample = sampler.ask(questions=context_questions())
        assert all(judgments(sample))
        print(json.dumps(dict(stage='mixed', provider=sample.provider, model=sample.model,
                              input_tokens=sample.usage.input_tokens, accuracy=judgments(sample))))
    finally:
        sampler.close()
    photo = tmp_path / 'red.png'
    photo.write_bytes(red_png())
    sampler = Sampler(images=[photo], questions=[Question(name='color', question='What is the dominant color?',
                                                       choices=['red', 'blue', 'green'])],
                      timeout=45, retry={'max_retries': 0})
    try:
        sample = sampler.ask()
        assert sample.answer.choice == 'red'
        replay = Sampler.from_sample(sample)
        replay.save(tmp_path / 'Replay.yml')
        photo.unlink()
        repeated = Sampler().load(tmp_path / 'Replay.yml')
        try:
            result = repeated.ask()
            assert result.answer.choice == 'red'
            assert result.images[0].read_bytes() == red_png()
        finally:
            repeated.close()
        print(json.dumps(dict(stage='vision', provider=sample.provider, input_tokens=sample.usage.input_tokens)))
    finally:
        sampler.close()


def make_document(records, varied):
    """Place targets among neutral records or varied prose and conflicting distractors."""
    middle = records // 2
    parts = ['Target record ORIGIN has severity critical.\n']
    for index in range(records):
        if index == middle:
            parts.append('Target record CENTER has warehouse blue.\n')
        if varied:
            row = ('Routine inspection of the loading bay found no change to procedure.\n',
                   'Weather bulletin: scattered clouds, mild wind, normal delivery schedule.\n',
                   f'Other record DISTRACTOR-{index} has warehouse red, severity ordinary, approved false.\n',
                   f'Archive note {index}: maintenance team reviewed packaging and inventory forms.\n')[index % 4]
        else:
            row = 'This is an ordinary inventory entry with no special marker.\n'
        parts.append(row)
    parts.append('Target record FINAL has approved true.\n')
    return ''.join(parts)


@pytest.mark.skipif(os.getenv('CHATSNACK_RUN_DECISIONS_CONTEXT_LIVE') != '1', reason='opt-in paid context probes')
@pytest.mark.parametrize('varied', [False, True], ids=['repeated', 'varied'])
@pytest.mark.parametrize('target_tokens', [8000, 30000, 100000])
def test_live_context_evidence(target_tokens, varied):
    from openai import OpenAI
    from typesafe_sdk import TypeSafeAPIError
    with OpenAI(timeout=45, max_retries=0) as counter:
        def count(records):
            return counter.responses.input_tokens.count(model='gpt-6-luna', input=make_document(records, varied)).input_tokens
        initial, larger = count(1), count(1001)
        records = max(1, round((target_tokens - initial) / ((larger - initial) / 1000)) + 1)
        document = make_document(records, varied)
        counted = counter.responses.input_tokens.count(model='gpt-6-luna', input=document).input_tokens
    for provider in ('openai', 'typesafe'):
        sampler = Sampler(data=document, provider=provider, timeout=45, retry={'max_retries': 0})
        try:
            try:
                sample = sampler.ask(questions=context_questions())
            except TypeSafeAPIError as exc:
                # Only Jev's documented context limit is an expected comparison outcome.
                if provider != 'typesafe' or 'max_tokens_exceeded' not in str(exc):
                    raise
                print(json.dumps(dict(provider=provider, varied=varied, target_tokens=target_tokens,
                                      counted_text_tokens=counted, error='max_tokens_exceeded')))
                continue
            accurate = judgments(sample)
            print(json.dumps(dict(provider=provider, varied=varied, target_tokens=target_tokens,
                counted_text_tokens=counted, input_tokens=sample.usage.input_tokens,
                output_tokens=sample.usage.output_tokens, accuracy=accurate)))
            assert all(accurate)
        finally:
            sampler.close()
