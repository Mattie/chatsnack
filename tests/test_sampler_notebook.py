"""Execute the actual introductory cells offline, with only provider work replaced."""

import json
from pathlib import Path

from chatsnack import Chat
from tests.features.test_sampler import evaluations


def test_introductory_notebook_cells(tmp_path, monkeypatch, evaluations):
    notebook = Path(__file__).resolve().parents[1] / 'notebooks/TastySamplersWithChatsnack.ipynb'
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    monkeypatch.chdir(tmp_path)

    def chat_reply(self, **fillings):
        """Exercise real prompt composition without requesting OpenAI generation."""
        return self._run_sync(self._build_final_prompt(fillings), 'notebook')

    monkeypatch.setattr(Chat, 'ask', chat_reply)
    scope = {}
    for cell in json.loads(notebook.read_text(encoding='utf-8'))['cells']:
        if cell['cell_type'] == 'code':
            exec(compile(''.join(cell['source']), str(notebook), 'exec'), scope)
    assert scope['repeated'].data == scope['sample'].data
    assert len(scope['repeated'].answers) == 3
    assert (tmp_path / 'samplers/SnackCheck.yml').read_text() == (
        'data: "{snack}"\nquestions:\n  - "{question.crunchy}"\n')
    assert len(evaluations) == 5
