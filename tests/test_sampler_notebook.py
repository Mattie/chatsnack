"""Execute the actual introductory cells offline, with only provider work replaced."""

import json
from pathlib import Path

from chatsnack import Chat
from chatsnack.sampler import provider
from tests.features.test_sampler import evaluations
from tests.features.test_sampler_decisions import PNG


def test_introductory_notebook_cells(tmp_path, monkeypatch, evaluations):
    notebook = Path(__file__).resolve().parents[1] / 'notebooks/TastySamplersWithChatsnack.ipynb'
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'snack.png').write_bytes(PNG)
    prompts = []
    descriptions = [
        'A buttery bowl of popcorn for an easy everyday snack.',
        'A bargain bowl of truffle popcorn for your everyday snack break.',
        'A warm cinnamon-sugar pretzel for a small everyday treat.',
    ]
    original_evaluate = provider.evaluate_sync

    def menu_evaluate(request, params):
        """Supply varied ratings and a rejection to exercise the notebook's data flow."""
        response = original_evaluate(request, params)
        if 'price' in request['questions']:
            choice = 'expensive' if request['state']['name'] == 'Truffle popcorn' else 'inexpensive'
            response['answers']['price'].update(choice=choice)
        elif 'fits' in request['questions']:
            response['answers']['fits']['noul'] = (
                .1 if request['state']['product']['name'] == 'Truffle popcorn' else .9)
        elif 'burnt' in request['questions'] and params.provider == 'openai':
            response['answers']['burnt'] = {'type': 'refusal'}
        return response

    monkeypatch.setattr(provider, 'evaluate_sync', menu_evaluate)

    def chat_reply(self, **fillings):
        """Inspect the real writer prompt and return a deterministic draft for judging."""
        prompts.append(self._run_sync(self._build_final_prompt(fillings), 'notebook'))
        return descriptions[len(prompts) - 1]

    monkeypatch.setattr(Chat, 'ask', chat_reply)
    scope = {}
    for cell in json.loads(notebook.read_text(encoding='utf-8'))['cells']:
        if cell['cell_type'] == 'code':
            exec(compile(''.join(cell['source']), str(notebook), 'exec'), scope)
    assert scope['repeated'].data == scope['sample'].data
    assert len(scope['repeated'].answers) == 3
    assert (tmp_path / 'samplers/SnackCheck.yml').read_text() == (
        'data: "{snack}"\nquestions:\n  - "{question.crunchy}"\n')
    assert len(evaluations) == 16
    assert scope['visual'].answer.refused
    assert scope['visual_repeated'].images[0].read_bytes() == PNG
    assert scope['followup'].images[0].read_bytes() == PNG
    assert scope['text_review'].images == []
    assert scope['jev'].params.model == 'jev-latest'
    assert 'experimental' not in scope['jev_visual'].params.authored()
    assert scope['jev_visual'].images[0].read_bytes() == PNG
    assert 'asset:' in (tmp_path / 'samplers/SnackPhotoReplay.yml').read_text()
    assert len(prompts) == len(scope['menu']) == 3
    assert [row['rating'] for row in scope['menu']] == ['inexpensive', 'expensive', 'inexpensive']
    assert [row['verdict'].yes for row in scope['menu']] == [True, False, True]
    for index, row in enumerate(scope['menu']):
        assert evaluations[3 + index * 2][0]['state'] == row['product']
        assert f"Original price rating: {row['rating']}." in prompts[index]
        assert row['product']['name'] in prompts[index]
        assert evaluations[4 + index * 2][0]['state'] == dict(
            product=row['product'], rating=row['rating'], description=descriptions[index])
        assert row['description'] == descriptions[index]
