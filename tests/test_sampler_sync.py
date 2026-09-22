"""A synchronous Sampler must let its process exit after SDK worker-thread work."""

import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('fail', [False, True])
def test_sync_sampler_releases_worker_threads(nested, fail, tmp_path):
    script = textwrap.dedent(f'''
        import asyncio
        from chatsnack import Sampler
        from chatsnack.sampler import provider

        def evaluate(request, params):
            if {fail!r}:
                raise ValueError('provider failed')
            return dict(model='fake', usage=dict(input_tokens=1, output_tokens=1),
                        answers={{'_question_0': dict(type='noul', noul=.8)}})

        provider.evaluate_sync = evaluate
        def ask():
            try:
                sample = Sampler(data='popcorn').ask('Crunchy?')
            except ValueError as exc:
                assert {fail!r} and str(exc) == 'provider failed'
            else:
                assert not {fail!r} and sample.answer.yes

        async def notebook():
            ask()

        if {nested!r}:
            asyncio.run(notebook())
        else:
            ask()
        print('completed', flush=True)
    ''')
    completed = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
                               capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == 'completed'
