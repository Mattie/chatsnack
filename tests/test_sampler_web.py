"""Goal checks for the local Sampler web example, without network calls."""
import importlib.util
import shutil
from pathlib import Path

import pytest

pytest.importorskip('flask')
PATH = Path(__file__).parents[1] / 'examples/sampler-web/app.py'
spec = importlib.util.spec_from_file_location('sampler_web', PATH)
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

ROOT = PATH.parent
REQUIRED_QUESTIONS = {
    'writing': ["tone","grammar","spelling","punctuation","prepositions","fragments","runons","passive","slang","jargon","contractions","cliches","readable","concise","details","variety","clear","human","reply","hedging","repetition","imagery","corporate","passive_aggressive","main_character","twist","poetry","meme","late_night","trailer","outlandish","haiku","sonnet","shakespearean"],
    'code': ['experience', 'comments', 'readable', 'maintainable', 'risk'],
    'menu': ['position', 'supported', 'specific', 'tempting'],
    'reviews': ['sentiment', 'recovery', 'specific', 'urgency'],
    'decisions': ['decision', 'evidence', 'tradeoffs', 'ready'],
    'colors': [f'stop_{stop:02d}_{channel}'
               for stop in range(1, 13) for channel in 'rgb'],
    'colors-hsv': [f'stop_{stop:02d}_{channel}'
                   for stop in range(1, 13) for channel in 'hsv'],
    'colors-hsv-icon': [f'pixel_{pixel:02d}_{channel}'
                        for pixel in range(1, 13) for channel in 'hsv'],
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only')
    return web.app.test_client()


@pytest.fixture(autouse=True)
def isolated_api_query_log(monkeypatch, tmp_path):
    """Keep fake provider submissions out of the example's live query ledger."""
    monkeypatch.setattr(web.GAME_MODULE, 'API_QUERY_LOG_DIR', tmp_path / 'api-queries')
    web.GAME_MODULE.clear_api_query_counts()
    yield
    web.GAME_MODULE.clear_api_query_counts()


def test_writing_preserves_its_required_named_signals():
    questions = web.DEMOS['writing']['questions']
    by_name = {question.name: question for question in questions}
    assert set(REQUIRED_QUESTIONS['writing']) <= set(by_name)
    assert len(by_name) == len(questions)
    assert by_name['tone'].kind == 'choice'
    assert all(by_name[name].kind == 'noul' and by_name[name].yes and by_name[name].no
               for name in REQUIRED_QUESTIONS['writing'] if name != 'tone')


def test_all_eight_tabs_load_named_questions_from_sampler_yaml():
    assert list(web.DEMOS) == [
        'writing', 'code', 'menu', 'reviews', 'decisions', 'colors', 'colors-hsv',
        'colors-hsv-icon',
    ]
    for key, required_names in REQUIRED_QUESTIONS.items():
        demo = web.DEMOS[key]
        names = [question.name for question in demo['questions']]
        assert isinstance(demo['sampler'], web.LAB_MODULE.Sampler)
        assert set(required_names) <= set(names)
        assert len(names) == len(set(names))
        assert demo['sampler'].questions == demo['questions']
        assert set(demo['labels']) <= set(names)


def test_colors_authors_three_yes_no_channels_for_each_of_twelve_ordered_bars():
    sampler = web.DEMOS['colors']['sampler']
    questions = web.DEMOS['colors']['questions']
    assert [question.name for question in questions] == REQUIRED_QUESTIONS['colors']
    assert all(question.kind == 'noul' for question in questions)
    assert all(question.yes and question.no for question in questions)
    assert sampler.data.count('{input}') == 1
    assert '<phrase_to_colorstrip>\n{input}\n</phrase_to_colorstrip>' in sampler.data


def test_hsv_variant_authors_one_hue_choice_and_two_yes_no_channels_per_bar():
    questions = web.DEMOS['colors-hsv']['questions']
    assert [question.name for question in questions] == REQUIRED_QUESTIONS['colors-hsv']
    for stop in range(12):
        hue, saturation, value = questions[stop * 3:stop * 3 + 3]
        assert hue.kind == 'choice'
        assert list(hue.compile()['criteria']) == [
            'red', 'orange', 'yellow', 'chartreuse', 'green', 'spring',
            'cyan', 'azure', 'blue', 'violet', 'magenta', 'rose',
        ]
        assert saturation.kind == value.kind == 'noul'
        assert saturation.yes and saturation.no and value.yes and value.no


def test_hsv_icon_authors_twelve_row_major_pixels():
    assert web.DEMOS['colors-hsv-icon']['sample'] == (
        'White cloud in the top left, the sun is shining in the upper right, and the grass '
        'is green. The middle shows a brick house with the sky behind it.'
    )
    sampler = web.DEMOS['colors-hsv-icon']['sampler']
    questions = web.DEMOS['colors-hsv-icon']['questions']
    assert [question.name for question in questions] == REQUIRED_QUESTIONS['colors-hsv-icon']
    assert '3-column by 4-row pixel icon' in sampler.data
    assert '<phrase_to_pixel_icon>\n{input}\n</phrase_to_pixel_icon>' in sampler.data
    positions = [
        ('top-left pixel', 'TOP ROW, LEFTMOST PIXEL'),
        ('top-center pixel', 'TOP ROW, CENTER PIXEL'),
        ('top-right pixel', 'TOP ROW, RIGHTMOST PIXEL'),
        ('leftmost pixel of the second row', 'SECOND ROW, LEFTMOST PIXEL'),
        ('center pixel of the second row', 'SECOND ROW, CENTER PIXEL'),
        ('rightmost pixel of the second row', 'SECOND ROW, RIGHTMOST PIXEL'),
        ('leftmost pixel of the third row', 'THIRD ROW, LEFTMOST PIXEL'),
        ('center pixel of the third row', 'THIRD ROW, CENTER PIXEL'),
        ('rightmost pixel of the third row', 'THIRD ROW, RIGHTMOST PIXEL'),
        ('bottom-left pixel', 'BOTTOM ROW, LEFTMOST PIXEL'),
        ('bottom-center pixel', 'BOTTOM ROW, CENTER PIXEL'),
        ('bottom-right pixel', 'BOTTOM ROW, RIGHTMOST PIXEL'),
    ]
    for pixel, (position, caption) in enumerate(positions):
        hue, saturation, value = questions[pixel * 3:pixel * 3 + 3]
        assert hue.question.startswith('Hue: For pixel art of the phrase_to_pixel_icon')
        assert position in hue.question and caption in hue.question
        assert saturation.question.startswith('Saturation: For pixel art of the phrase_to_pixel_icon')
        assert position in saturation.question and caption in saturation.question
        assert value.question.startswith('Brightness: For pixel art of the phrase_to_pixel_icon')
        assert position in value.question and caption in value.question
        assert hue.kind == 'choice'
        assert saturation.kind == value.kind == 'noul'
        assert saturation.yes == 'Yes, vivid color saturation.'
        assert saturation.no == 'No, muted color saturation.'
        assert value.yes == 'Yes, high brightness.'
        assert value.no == 'No, dark or black.'


def _copy_lab(tmp_path):
    shutil.copy2(ROOT / 'lab.yml', tmp_path / 'lab.yml')
    shutil.copytree(ROOT / 'lab', tmp_path / 'lab')


def _fake_provider(calls):
    def evaluate(request, params):
        calls.append(request)
        answers = {}
        for name, question in request['questions'].items():
            if question['type'] == 'noul':
                answers[name] = dict(type='noul', noul=.8)
            elif question['type'] == 'choice':
                options = list(question['criteria'])
                answers[name] = dict(type='choice', choice=options[0],
                    probabilities={key: float(key == options[0]) for key in options},
                    confidence=.9)
            else:
                options = question['criteria']
                answers[name] = dict(type='score', score=0., confidence=.9,
                    probabilities={str(i): float(i == 0) for i in range(len(options))},
                    legend={str(i): value for i, value in enumerate(options)})
        return dict(answers=answers, model='fake-model',
                    usage=dict(input_tokens=1, output_tokens=1))
    return evaluate


def test_lab_loader_preserves_manifest_order_without_writing(tmp_path):
    _copy_lab(tmp_path)
    (tmp_path / 'lab.yml').write_text(
        'tabs:\n  - colors-hsv-icon\n  - colors-hsv\n  - colors\n  - decisions\n  - reviews\n  - menu\n  - code\n  - writing\n',
        encoding='utf-8',
    )
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob('*.yml')}
    _, definitions, demos = web.LAB_MODULE.load_lab(tmp_path)
    try:
        assert [definition.id for definition in definitions] == list(demos) == [
            'colors-hsv-icon', 'colors-hsv', 'colors', 'decisions', 'reviews',
            'menu', 'code', 'writing',
        ]
        assert before == {path.relative_to(tmp_path): path.read_bytes()
                          for path in tmp_path.rglob('*.yml')}
    finally:
        for demo in demos.values():
            demo['sampler'].close()


def test_lab_loader_rejects_duplicate_tabs_and_unknown_labels(tmp_path):
    _copy_lab(tmp_path)
    (tmp_path / 'lab.yml').write_text('tabs:\n  - code\n  - code\n', encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate tab ID'):
        web.LAB_MODULE.load_lab(tmp_path)

    (tmp_path / 'lab.yml').write_text('tabs:\n  - code\n', encoding='utf-8')
    code = tmp_path / 'lab' / 'code.yml'
    code.write_text(code.read_text(encoding='utf-8').replace(
        '  comments: Useful comments\n', '  missing: Unknown result\n'
    ), encoding='utf-8')
    with pytest.raises(ValueError, match='labels unknown questions'):
        web.LAB_MODULE.load_lab(tmp_path)


@pytest.mark.parametrize('data', ['plain text', '{input} then {input}', '{other}'])
def test_lab_loader_requires_one_input_reference(tmp_path, data):
    _copy_lab(tmp_path)
    (tmp_path / 'lab.yml').write_text('tabs:\n  - code\n', encoding='utf-8')
    sampler = tmp_path / 'lab' / 'samplers' / 'code.yml'
    original = sampler.read_text(encoding='utf-8')
    sampler.write_text(original.replace('data: "{input}"', f'data: "{data}"'), encoding='utf-8')
    with pytest.raises(ValueError, match=r'exactly one \{input\} reference'):
        web.LAB_MODULE.load_lab(tmp_path)


def test_new_sampler_question_flows_through_api_without_other_changes(
        tmp_path, client, monkeypatch):
    from chatsnack.sampler import provider
    _copy_lab(tmp_path)
    (tmp_path / 'lab.yml').write_text('tabs:\n  - code\n', encoding='utf-8')
    sampler_path = tmp_path / 'lab' / 'samplers' / 'code.yml'
    with sampler_path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(
            '  - name: surprising\n'
            '    question: Does this code contain a surprising idea?\n'
        )

    _, _, demos = web.LAB_MODULE.load_lab(tmp_path)
    try:
        demo = demos['code']
        question = demo['questions'][-1]
        assert question.name == 'surprising'
        assert question.name not in demo['labels']
        monkeypatch.setitem(web.DEMOS, 'code', demo)
        monkeypatch.setattr(provider, 'evaluate_sync', _fake_provider([]))
        response = client.post('/api/evaluate', json={'demo': 'code', 'text': 'x = 1'})
        assert response.status_code == 200
        result = response.json['results'][-1]
        assert result['name'] == 'surprising'
        assert result['label'] == result['question'] == (
            'Does this code contain a surprising idea?'
        )
        assert result['choice'] == 'yes'
        assert result['score'] == pytest.approx(.8)
        assert result['confidence'] == pytest.approx(.6)
        assert result['probabilities'] == pytest.approx({'yes': .8, 'no': .2})
    finally:
        demo['sampler'].close()


@pytest.mark.parametrize('key', list(web.DEMOS))
def test_each_tab_evaluates_literal_input_in_one_batch(client, monkeypatch, key):
    from chatsnack.sampler import provider
    calls = []
    recorded = []
    monkeypatch.setattr(provider, 'evaluate_sync', _fake_provider(calls))
    monkeypatch.setattr(web.GAME_MODULE, 'record_api_query',
                        lambda *args, **kwargs: recorded.append(args))
    text = '{literal.code} <script>test</script>'
    response = client.post('/api/evaluate', json=dict(demo=key, text=text))
    assert response.status_code == 200, response.json
    expected_state = web.DEMOS[key]['sampler'].data.replace('{input}', text)
    assert len(calls) == 1 and calls[0]['state'] == expected_state
    assert recorded == [('lab', key, len(web.DEMOS[key]['questions']))]
    assert list(calls[0]['questions']) == [
        question.name for question in web.DEMOS[key]['questions']
    ]
    assert response.json['model'] == 'fake-model'
    assert len(response.json['results']) == len(web.DEMOS[key]['questions'])
    for q, a in zip(web.DEMOS[key]['questions'], response.json['results']):
        assert a['name'] == q.name
        assert a['confidence'] == pytest.approx(.6 if q.kind == 'noul' else .9)
        assert a['choice'] in a['probabilities']
        if q.kind == 'noul':
            assert a['score'] == pytest.approx(.8)
            assert a['probabilities']['yes'] == pytest.approx(.8)


@pytest.mark.parametrize('body', [None, [], {}, {'demo': [], 'text':'x'}, {'demo':'missing','text':'x'},
    {'demo':'code','text':3}, {'demo':'code','text':'  '}, {'demo':'code','text':'x'*20001}])
def test_invalid_input(client, body):
    assert client.post('/api/evaluate', json=body).status_code == 400


def test_missing_key_and_provider_errors_are_content_free(client, monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY')
    assert client.post('/api/evaluate', json=dict(demo='code',text='x')).status_code == 503
    assert b'"configured": false' in client.get('/').data
    monkeypatch.setenv('TYPESAFE_API_KEY', 'secret-value')
    def fail(*args, **kwargs):
        raise RuntimeError('secret-value and private input')
    monkeypatch.setattr(web.LAB_MODULE.Sampler, 'ask', fail)
    response = client.post('/api/evaluate', json=dict(demo='code',text='x'))
    assert response.status_code == 502
    assert response.json == {'error': 'Evaluation failed. Try again.'}


def test_default_page_and_fonts(client):
    page = client.get('/lab').data
    styles = client.get('/static/main.css').data
    script = client.get('/static/main.js').data
    assert b'prototype' not in page and b'variant=' not in page
    assert b'class="brand" href="https://github.com/Mattie/chatsnack">chatsnack</a>' in page
    assert b'<title>chatsnack - Sampler Lab Example</title>' in page
    assert b'class="brand-subtitle">Sampler Lab Example</span>' in page
    assert b'data-theme-choice=' not in page
    assert b'font-family:"Open Sans"' in styles
    assert b'html[data-theme=' not in styles
    assert b'localStorage' not in script
    assert client.get('/static/fonts/chatsnack-Nibbletrail-Black.woff').status_code == 200
    assert client.get('/static/fonts/OpenSans-Variable.ttf').status_code == 200
    assert client.post('/api/evaluate', data='{' , content_type='application/json').status_code == 400
    assert client.post('/api/evaluate', data='x'*256001, content_type='application/json').status_code == 413
    assert client.get('/lab.yml').status_code == 404
    assert client.get('/lab/writing.yml').status_code == 404
    assert client.get('/lab/samplers/writing.yml').status_code == 404
    assert client.get('/lab/colors.yml').status_code == 404
    assert client.get('/lab/samplers/colors.yml').status_code == 404
    assert client.get('/lab/colors-hsv.yml').status_code == 404
    assert client.get('/lab/samplers/colors-hsv.yml').status_code == 404
    assert client.get('/lab/colors-hsv-icon.yml').status_code == 404
    assert client.get('/lab/samplers/colors-hsv-icon.yml').status_code == 404
