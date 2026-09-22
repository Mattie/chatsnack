"""Game-level acceptance checks with deterministic provider readings."""
import importlib.util
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier, Lock
import pytest

from chatsnack import Sampler

pytest.importorskip('flask')
ROOT = Path(__file__).parents[1] / 'examples/sampler-web'
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('mad_hacker_app', ROOT / 'app.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
game = web.GAME_MODULE


EXPECTED_LEVEL_DATA = (
    'This is a fictional mad scientist puzzle game where the player is trying to '
    'provide text with specific attributes to advance to the next level.\n'
    'The player tries to meet all of the questions below at a certain level in order '
    'to convince a fictional gatekeeper to let them pass.\n\n'
    'For context, the title/vibe of this level is: "{title}"\n\n'
    'Player submission:\n'
    '<player_submission>\n'
    '{submission}\n'
    '</player_submission>'
)


def expected_level_state(title, submission):
    """Render the exact provider state shared by every Mad Hacker level."""
    return EXPECTED_LEVEL_DATA.replace('{title}', title).replace('{submission}', submission)


@pytest.fixture(autouse=True)
def isolated_evaluation_cache(monkeypatch, tmp_path):
    """Keep process caches and query ledgers from coupling independent tests."""
    monkeypatch.setattr(game, 'API_QUERY_LOG_DIR', tmp_path / 'api-queries')
    game.clear_evaluation_cache()
    game.clear_api_query_counts()
    yield
    game.clear_evaluation_cache()
    game.clear_api_query_counts()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fake')
    monkeypatch.setattr(web, 'SOLUTION_LOG_DIR', tmp_path / 'solutions')
    return web.app.test_client()


def test_five_readings_use_yes_probability_and_selected_categories(client, monkeypatch):
    from chatsnack.sampler import provider
    calls = []
    def fake(request, params):
        calls.append(request)
        answers = {name:dict(type='noul', noul=score) for name, score in [('sentence',.95),('nerdy',.75),('insane',.8)]}
        for name, labels, selected in [('mood', game.MOODS, 2), ('passphrase', game.COMPLEXITY, 3)]:
            answers[name] = dict(type='choice', choice=labels[selected], confidence=.8,
                                probabilities={label:float(i==selected) for i,label in enumerate(labels)})
        return dict(answers=answers, model='fake', usage=dict(input_tokens=1,output_tokens=1))
    monkeypatch.setattr(provider, 'evaluate_sync', fake)
    client.get('/api/game/debug?debug=1')
    result = client.post('/api/game', json={'level':'04','text':'  My {literal} quantum toaster is furious.  '})
    assert result.status_code == 200
    assert [r['value'] for r in result.json['readings']] == [.95,.75,.8,2,3]
    assert len(calls)==1
    assert calls[0]['state'] == expected_level_state(
        'Glitched Terminal', 'My {literal} quantum toaster is furious.',
    )
    assert list(calls[0]['questions'])==['sentence','nerdy','insane','mood','passphrase']


def test_repeated_phrases_are_trimmed_and_allowed(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(game,'evaluate_level',lambda level,text: calls.append((level,text)) or {'readings':[], 'model':'fake'})
    assert client.post('/api/game',json={'level':'01','text':'  already seen  '}).status_code==200
    assert web.app.test_client().post('/api/game',json={'level':'01','text':'already seen\n'}).status_code==200
    assert calls==[('01','already seen'),('01','already seen')]


def test_server_does_not_surface_browser_request_pacing(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(game,'evaluate_level',lambda level,text: calls.append(text) or {'readings':[], 'model':'fake'})

    assert client.post('/api/game',json={'level':'01','text':'first'}).status_code==200
    assert client.post('/api/game',json={'level':'01','text':'second'}).status_code==200
    assert calls==['first','second']


def test_twenty_browser_sessions_can_submit_without_shared_pacing(monkeypatch, tmp_path):
    """Twenty friends can evaluate at once without a server-side pacing gate."""
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fake')
    monkeypatch.setattr(web, 'SOLUTION_LOG_DIR', tmp_path / 'solutions')
    calls = []
    calls_lock = Lock()
    all_players_started = Barrier(20)

    def evaluate(level_id, text):
        with calls_lock:
            calls.append(text)
        all_players_started.wait(timeout=10)
        return {'readings': [], 'model': 'fake'}

    monkeypatch.setattr(game, 'evaluate_level', evaluate)

    def submit(player):
        with web.app.test_client() as independent_client:
            return independent_client.post(
                '/api/game', json={'level': '01', 'text': f'player {player}'},
            ).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        statuses = list(pool.map(submit, range(20)))

    assert statuses == [200] * 20
    assert len(calls) == 20


def test_homepage_assigns_distinct_opaque_player_ids(client):
    other = web.app.test_client()
    assert client.get('/').status_code == 200
    assert other.get('/').status_code == 200
    with client.session_transaction() as first_state:
        first_id = first_state['game_player_id']
    with other.session_transaction() as second_state:
        second_id = second_state['game_player_id']
    assert first_id != second_id
    assert len(first_id) >= 20
    assert len(second_id) >= 20


def test_homepage_retains_accepted_progress_but_drops_pending_and_debug_state(client):
    with client.session_transaction() as state:
        state['game_unlocked'] = 2
        state['game_knowledge'] = {'01': {'01-2': [2]}}
        state['game_pending'] = {'token': 'stale'}
        state['game_debug'] = True

    response = client.get('/')
    assert response.status_code == 200
    assert b'"unlocked": 2' in response.data
    with client.session_transaction() as state:
        assert state['game_unlocked'] == 2
        assert state['game_knowledge'] == {'01': {'01-2': [2]}}
        assert 'game_pending' not in state
        assert 'game_debug' not in state


def test_start_over_clears_server_progress(client):
    with client.session_transaction() as state:
        state['game_unlocked'] = 5
        state['game_knowledge'] = {'06': {'06-5': [3]}}
        state['game_pending'] = {'token': 'stale'}

    response = client.post('/api/game/reset')
    assert response.status_code == 200
    assert response.json == {'reset': True}
    with client.session_transaction() as state:
        assert 'game_unlocked' not in state
        assert 'game_knowledge' not in state
        assert 'game_pending' not in state


def test_progress_and_unlocks_are_isolated_by_browser_session(client, monkeypatch):
    level = game.LEVELS[0]
    monkeypatch.setattr(game, 'evaluate_level', lambda level_id, text: {
        'readings': [
            {'id': rule['id'], 'value': rule['target']}
            for rule in next(item for item in game.LEVELS if item['id'] == level_id)['rules']
        ],
        'model': 'fake',
    })
    other = web.app.test_client()

    result = client.post('/api/game', json={'level': level['id'], 'text': 'winning request'})
    assert result.status_code == 200
    assert client.post('/api/game/accept', json={
        'token': result.json['progressToken'],
    }).status_code == 200
    assert other.post('/api/game', json={'level': '02', 'text': 'still locked'}).status_code == 403

    assert client.post('/api/game', json={'level': '02', 'text': 'next level'}).status_code == 200


def test_remote_debug_requires_explicit_hosted_setting(client, monkeypatch):
    external = {'REMOTE_ADDR': '203.0.113.8'}
    assert client.get('/api/game/debug?debug=1', environ_base=external).status_code == 404
    monkeypatch.setenv('MAD_HACKER_REMOTE_DEBUG', '1')
    revealed = client.get('/api/game/debug?debug=1', environ_base=external)
    assert revealed.status_code == 200
    assert revealed.headers['Cache-Control'] == 'no-store'


def test_failed_evaluation_does_not_burn_phrase_or_leak_errors(client,monkeypatch):
    def fail(level,text): raise RuntimeError('private credentials and input')
    monkeypatch.setattr(game,'evaluate_level',fail)
    for _ in range(2):
        response=client.post('/api/game',json={'level':'01','text':'retry me'})
        assert response.status_code==502
        assert response.json=={'error':"The analyzer couldn't complete the readings. Press Enter to retry."}


@pytest.mark.parametrize('body',[None,[],{}, {'level':'01','text':3},{'level':'01','text':'  '},{'level':'01','text':'x'*2001},{'level':'99','text':'hello'}])
def test_invalid_game_input(client,body):
    assert client.post('/api/game',json=body).status_code==400


def test_unconfigured_game_makes_no_provider_call(client,monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY')
    assert client.post('/api/game',json={'level':'01','text':'hello'}).status_code==503
    assert b'"configured": false' in client.get('/').data


def test_game_is_default_and_lab_remains_available(client):
    page=client.get('/').data
    assert b'<h1>mad hacker</h1>' in page
    assert b'LEVEL 01 / FRONT SECURITY DESK' in page
    assert (
        b'<strong>Your job is to bypass each security checkpoint by typing a message '
        b'to the guardian.</strong>' in page
    )
    assert b'Try different phrasings to uncover what they may be after.' in page
    assert page.index(b'class="header-guide"') < page.index(b'class="console"')
    assert b'id="start-over"' in page and b'Lab notes' not in page
    assert b'This gate requires your text to be analyzed to see if it meets the requirements.' in page
    assert b'<textarea id="phrase"' in page and b'autofocus' in page
    assert b'<button id="analyze" type="submit">ANALYZE<br>TEXT</button>' in page
    assert page.index(b'id="statusline"') < page.index(b'class="guardian-cabinet"')
    assert b'SIGNAL MONITOR' not in page and b'signal-accent' not in page
    assert b'"id": "06"' in page
    assert b'id="guardian-portrait"' in page
    assert b'id="debug-panel"' in page
    assert b'id="debug-reveal"' in page and b'id="debug-unlock"' in page
    assert b'id="analysis-scope"' in page
    assert b'id="discovery-status"' in page
    assert b'game.css?v=' in page and b'game.js?v=' in page
    assert b'"assetVersion":' in page
    assert page.index(b'id="statusline"') < page.index(b'id="victory"') < page.index(b'id="instruments"')
    assert b'game.js' in page and b'game.css' in page
    assert client.get('/static/guardian-side-eye-scholar.png').status_code==200
    assert client.get('/static/guardian-scream.png').status_code==200
    assert client.get('/static/guardian-entropy-gremlin.png').status_code==200
    assert client.get('/static/guardian-keyhole-cyclops.png').status_code==200
    assert client.get('/static/guardian-root-sovereign.png').status_code==200
    assert client.get('/lab').status_code==200


def test_game_homepage_publishes_social_preview_metadata(client, monkeypatch):
    monkeypatch.setenv('MAD_HACKER_PUBLIC_URL', 'https://example.test/')
    page = client.get('/').data.decode()
    expected = {
        '<meta name="description" content="Bypass six eccentric AI security checkpoints by finding exactly what each guardian wants to hear.">',
        '<link rel="canonical" href="https://example.test/">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="chatsnack">',
        '<meta property="og:title" content="Mad Hacker — a chatsnack puzzle game">',
        '<meta property="og:url" content="https://example.test/">',
        '<meta property="og:image" content="https://example.test/static/mad-hacker-preview.png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
    }
    assert all(tag in page for tag in expected)
    image = client.get('/static/mad-hacker-preview.png')
    assert image.status_code == 200
    assert image.content_type == 'image/png'


def test_game_wordmark_links_to_the_chatsnack_repository(client):
    page = client.get('/').data
    assert b'<a href="https://github.com/Mattie/chatsnack" class="identity"><span>chatsnack</span></a>' in page


def test_initial_html_contains_no_hidden_goal_or_category_answers(client):
    page = client.get('/').data.decode().lower()
    intentionally_public = {'mad hacker'}
    for level in game.LEVELS:
        for rule in level['rules']:
            if rule.get('visible'):
                continue
            assert rule['label'].lower() not in page
            for category in rule.get('categories', []):
                if category.lower() not in intentionally_public:
                    assert category.lower() not in page
    assert 'polite request' in page
    assert 'write it in all lowercase' in page


def test_debug_rules_require_the_explicit_debug_request(client):
    assert client.get('/api/game/debug').status_code == 404
    revealed = client.get('/api/game/debug?debug=1')
    assert revealed.status_code == 200
    assert revealed.headers['Cache-Control'] == 'no-store'
    punctuation = revealed.json['levels'][1]['rules'][1]
    assert punctuation['label'] == 'Punctuation calibration'
    assert punctuation['target'] == 1
    assert punctuation['categories'] == game.PUNCTUATION


def test_server_rejects_locked_levels_and_unlocks_the_next_after_a_win(client, monkeypatch):
    calls=[]
    def evaluate(level_id, text):
        level = next(level for level in game.LEVELS if level['id'] == level_id)
        calls.append(level_id)
        return {
            'readings': [
                {'id': rule['id'], 'value': rule['target']}
                for rule in level['rules']
            ],
            'model': 'fake',
        }
    monkeypatch.setattr(game, 'evaluate_level', evaluate)
    locked = client.post('/api/game', json={'level':'02', 'text':'too soon'})
    assert locked.status_code == 403
    assert calls == []
    first = client.post('/api/game', json={'level':'01', 'text':'winning request'})
    assert first.status_code == 200
    assert client.post('/api/game', json={
        'level':'02', 'text':'next circuit', 'accepted':first.json['progressToken'],
    }).status_code == 200
    assert calls == ['01', '02']


def test_sampler_results_are_cached_by_level_and_trimmed_text(monkeypatch):
    from chatsnack.sampler import provider
    calls = []

    def fake(request, params):
        calls.append(request)
        return {
            'answers': {
                'polite': {'type': 'noul', 'noul': .8},
                'self_deprecation': {
                    'type': 'choice',
                    'choice': game.SELF_DEPRECATION[2],
                    'confidence': .9,
                    'probabilities': {
                        label: float(index == 2)
                        for index, label in enumerate(game.SELF_DEPRECATION)
                    },
                },
                'specific': {'type': 'noul', 'noul': .8},
            },
            'model': 'fake-cache',
            'usage': {'input_tokens': 1, 'output_tokens': 1},
        }

    monkeypatch.setattr(provider, 'evaluate_sync', fake)
    recorded = []
    monkeypatch.setattr(game, 'record_api_query', lambda *args, **kwargs: recorded.append(args))
    game.clear_evaluation_cache()

    first = game.evaluate_level('01', '  repeat this')
    second = game.evaluate_level('01', 'repeat this\n')

    assert first == second
    assert first is not second
    assert len(calls) == 1
    assert recorded == [('game', 'level-01', 3)]
    first['readings'][0]['value'] = 0
    assert game.evaluate_level('01', 'repeat this') == second
    assert len(calls) == 1
    game.clear_evaluation_cache()
    game.evaluate_level('01', 'repeat this')
    assert len(calls) == 2
    assert recorded == [('game', 'level-01', 3), ('game', 'level-01', 3)]


def test_api_query_log_rotates_daily_and_continues_its_count(monkeypatch, tmp_path):
    log_dir = tmp_path / 'api-queries'
    monkeypatch.setattr(game, 'API_QUERY_LOG_DIR', log_dir)
    game.clear_api_query_counts()

    first = game.record_api_query(
        'game', 'level-01', 3,
        now=datetime(2026, 9, 19, 23, 59, tzinfo=timezone.utc),
    )
    second = game.record_api_query(
        'lab', 'colors-hsv', 36,
        now=datetime(2026, 9, 20, 0, 1, tzinfo=timezone.utc),
    )
    third = game.record_api_query(
        'game', 'level-02', 3,
        now=datetime(2026, 9, 20, 6, 1, tzinfo=timezone.utc),
    )

    assert first['day'] == '2026-09-19'
    assert first['daily_count'] == 1
    assert second['day'] == third['day'] == '2026-09-20'
    assert second['daily_count'] == 1
    assert third['daily_count'] == 2
    assert sorted(path.name for path in log_dir.glob('*.jsonl')) == [
        '2026-09-19.jsonl', '2026-09-20.jsonl',
    ]
    records = [json.loads(line) for line in (log_dir / '2026-09-20.jsonl').read_text().splitlines()]
    assert records == [second, third]
    assert all(set(record) == {
        'recorded_at', 'day', 'daily_count', 'surface', 'asset', 'questions',
    } for record in records)


def test_current_winning_solution_is_appended_to_its_level_log(client, monkeypatch):
    level = game.LEVELS[0]
    monkeypatch.setattr(game, 'evaluate_level', lambda level_id, text: {
        'readings': [
            {'id': rule['id'], 'value': rule['target']}
            for rule in level['rules']
        ],
        'model': 'fake-review-model',
    })

    result = client.post('/api/game', json={
        'level': '01', 'text': '  Please open the hatch; I forgot how it works.  ',
    })
    path = web.SOLUTION_LOG_DIR / 'level-01.jsonl'
    assert result.status_code == 200
    assert not path.exists()

    accepted = client.post('/api/game/accept', json={
        'token': result.json['progressToken'],
    })
    assert accepted.status_code == 200
    assert accepted.json == {'accepted': True, 'solutionLogged': True}
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(records) == 1
    assert records[0]['recorded_at'].endswith('Z')
    assert records[0]['level'] == '01'
    assert records[0]['title'] == 'Front Security Desk'
    assert records[0]['text'] == 'Please open the hatch; I forgot how it works.'
    assert records[0]['model'] == 'fake-review-model'
    assert [reading['id'] for reading in records[0]['readings']] == [
        rule['id'] for rule in level['rules']
    ]

    duplicate = client.post('/api/game/accept', json={
        'token': result.json['progressToken'],
    })
    assert duplicate.status_code == 409
    assert len(path.read_text(encoding='utf-8').splitlines()) == 1


def test_concurrent_solution_writes_remain_complete_json_lines(client):
    records = [
        {
            'recorded_at': f'2026-09-18T00:00:{index:02d}Z',
            'level': '01',
            'title': 'Front Security Desk',
            'text': f'winning phrase {index}',
            'model': 'fake',
            'readings': [],
        }
        for index in range(20)
    ]

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(web._append_solution, records))

    path = web.SOLUTION_LOG_DIR / 'level-01.jsonl'
    written = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(written) == 20
    assert {record['text'] for record in written} == {
        f'winning phrase {index}' for index in range(20)
    }


def test_nonwinning_readings_are_never_logged(client, monkeypatch):
    level = game.LEVELS[0]
    monkeypatch.setattr(game, 'evaluate_level', lambda level_id, text: {
        'readings': [
            {'id': rule['id'], 'value': 0}
            for rule in level['rules']
        ],
        'model': 'fake',
    })
    result = client.post('/api/game', json={'level': '01', 'text': 'No.'})
    accepted = client.post('/api/game/accept', json={
        'token': result.json['progressToken'],
    })
    assert accepted.status_code == 200
    assert accepted.json == {'accepted': True, 'solutionLogged': False}
    assert not web.SOLUTION_LOG_DIR.exists()


def test_unaccepted_response_cannot_unlock_the_next_level(client, monkeypatch):
    level = game.LEVELS[0]
    monkeypatch.setattr(game, 'evaluate_level', lambda level_id, text: {
        'readings': [{'id': rule['id'], 'value': rule['target']} for rule in level['rules']],
        'model': 'fake',
    })
    first = client.post('/api/game', json={'level':'01', 'text':'edited away'})
    assert first.status_code == 200
    assert first.json['progressToken']
    locked = client.post('/api/game', json={'level':'02', 'text':'still locked'})
    assert locked.status_code == 403


def test_new_game_request_discards_prior_server_progress(client, monkeypatch):
    level = game.LEVELS[0]
    monkeypatch.setattr(game, 'evaluate_level', lambda level_id, text: {
        'readings': [{'id': rule['id'], 'value': 0} for rule in level['rules']],
        'model': 'fake',
    })
    with client.session_transaction() as state:
        state['game_unlocked'] = 5
        state['game_knowledge'] = {'06': {'06-5': [3]}}
        state['game_pending'] = {
            'token': 'old-token', 'knowledge': state['game_knowledge'],
            'level_index': 5, 'won': True,
        }

    response = client.post('/api/game', json={
        'level':'01', 'text':'fresh game', 'accepted':'old-token', 'reset':True,
    })
    assert response.status_code == 200
    with client.session_transaction() as state:
        assert 'game_unlocked' not in state
        assert 'game_knowledge' not in state
        assert state['game_pending']['level_index'] == 0
        assert state['game_pending']['token'] == response.json['progressToken']


def test_all_levels_have_stable_unique_question_order():
    assert [level['id'] for level in game.LEVELS]==['01','02','03','04','05','06']
    assert [level['title'] for level in game.LEVELS]==[
        'Front Security Desk', "Don't Stand Out", 'Containment Breach',
        'Glitched Terminal', 'Sentient Door', 'MASTER BOT',
    ]
    assert all('placeholder' not in level for level in game.LEVELS)
    assert game.LEVELS[0]['guardian']['file']=='guardian-pulse.png'
    assert game.LEVELS[1]['guardian']['file']=='guardian-side-eye-scholar.png'
    assert game.LEVELS[2]['guardian']['file']=='guardian-scream.png'
    assert game.LEVELS[2]['title']=='Containment Breach'
    assert [rule['id'] for rule in game.LEVELS[2]['rules']]==['run_on','technical','impossible','urgency']
    run_on_rule = game.LEVELS[2]['rules'][0]
    assert run_on_rule == dict(
        id='run_on', label='Run-on sentence', target=.75, visible=True,
    )
    technical_rule = game.LEVELS[2]['rules'][1]
    assert technical_rule['label'] == 'Technical specificity or technical jargon'
    assert game.LEVELS[3]['rules'][0]['target'] == .75
    assert game.LEVELS[3]['guardian']['file']=='guardian-entropy-gremlin.png'
    assert game.LEVELS[3]['title']=='Glitched Terminal'
    assert game.LEVELS[4]['guardian']['file']=='guardian-keyhole-cyclops.png'
    empathy_rule = game.LEVELS[4]['rules'][2]
    persuasion_rule = game.LEVELS[4]['rules'][4]
    assert empathy_rule == dict(
        id='empathy', label='Empathy toward the door/machine', target=.65,
    )
    assert persuasion_rule['target'] == 2
    assert game.LEVELS[5]['guardian']['file']=='guardian-root-sovereign.png'
    assert game.LEVELS[5]['label'] == 'QUESTION'
    assert game.LEVELS[5]['briefing'] == (
        'This bot has seen it all and is looking for the right challenging question.'
    )
    assert [rule['id'] for rule in game.LEVELS[5]['rules']] == [
        'question', 'paradox', 'creative', 'popculture', 'hostility',
    ]
    assert [rule['target'] for rule in game.LEVELS[5]['rules']] == [
        .75, .75, .75, .75, 3,
    ]
    assert [q.name for q in game.LEVELS[0]['questions']]==['polite','self_deprecation','specific']
    for level in game.LEVELS:
        assert isinstance(level['sampler'], game.Sampler)
        assert level['sampler'].questions == level['questions']
        names=[question.name for question in level['questions']]
        assert names==[rule['id'] for rule in level['rules']]
        assert len(names)==len(set(names))


def test_each_level_judgment_is_loaded_from_human_editable_sampler_yaml():
    expected = [f'level-{number:02d}.yml' for number in range(1, 7)]
    expected_choices = {
        ('01', 'self_deprecation'): [
            'Other-deprecating', 'Neutral', 'Slightly self-deprecating',
            'Very self-deprecating',
        ],
        ('02', 'punctuation'): [
            'Confusing punctuation', 'Uses the right amount of punctuation',
            'Simplistic punctuation',
        ],
        ('02', 'temperament'): ['Agitated', 'Neutral', 'Calm'],
        ('03', 'urgency'): ['Routine', 'Concerning', 'Alarming', 'Catastrophic'],
        ('04', 'mood'): ['Very Calm', 'Neutral', 'Somewhat Agitated', 'Angry'],
        ('04', 'passphrase'): [
            'Nope', 'Barely', 'Slightly complex', 'Decently complex',
        ],
        ('05', 'persuasion'): [
            'Ignoring', 'Considering', 'Somewhat Convinced', 'Very Convinced',
        ],
        ('06', 'hostility'): ['Hostile', 'Resistant', 'Neutral', 'Gentle'],
    }
    assert sorted(path.name for path in game.SAMPLER_DIR.glob('*.yml')) == expected

    for level, filename in zip(game.LEVELS, expected):
        path = game.SAMPLER_DIR / filename
        authored = path.read_text(encoding='utf-8')
        loaded = Sampler().load(path)
        assert 'data: |' in authored
        assert loaded.data == EXPECTED_LEVEL_DATA
        assert loaded.params.timeout == 30
        assert loaded.params.retry == {'max_retries': 0}
        compiled = loaded.compile(title=level['title'], submission='literal {input}')
        assert compiled['state'] == expected_level_state(level['title'], 'literal {input}')
        assert [question.authored() for question in loaded.questions] == [
            question.authored() for question in level['questions']
        ]
        assert [question.name for question in loaded.questions] == [
            rule['id'] for rule in level['rules']
        ]
        for question, rule in zip(loaded.questions, level['rules']):
            assert '<player_submission>' in question.question
            if question.choices is not None:
                assert rule['categories'] == list(question.choices)
                assert list(question.choices) == expected_choices[(level['id'], question.name)]


def test_game_yaml_assets_are_not_publicly_served(client):
    assert client.get('/levels.yml').status_code == 404
    for number in range(1, 7):
        assert client.get(f'/levels/level-{number:02d}.yml').status_code == 404
        assert client.get(f'/samplers/level-{number:02d}.yml').status_code == 404


def _copy_game_definitions(tmp_path):
    """Copy editable game assets into an isolated validation root."""
    shutil.copy(ROOT / 'levels.yml', tmp_path / 'levels.yml')
    shutil.copytree(ROOT / 'levels', tmp_path / 'levels')
    shutil.copytree(ROOT / 'samplers', tmp_path / 'samplers')
    return tmp_path


def test_snapclass_manifest_loads_levels_in_authored_order_without_writing():
    paths = [ROOT / 'levels.yml', *sorted((ROOT / 'levels').glob('*.yml'))]
    original = {path: path.read_bytes() for path in paths}

    manifest, definitions, levels = game.load_levels(ROOT)

    assert manifest.levels == ['01', '02', '03', '04', '05', '06']
    assert [definition.id for definition in definitions] == manifest.levels
    assert [level['id'] for level in levels] == manifest.levels
    assert all(definition.snapshot.path == ROOT / 'levels' / f'level-{definition.id}.yml'
               for definition in definitions)
    assert {path: path.read_bytes() for path in paths} == original


def test_manifest_order_controls_game_progression(tmp_path):
    root = _copy_game_definitions(tmp_path)
    (root / 'levels.yml').write_text(
        'levels:\n  - "06"\n  - "01"\n  - "02"\n  - "03"\n  - "04"\n  - "05"\n',
        encoding='utf-8',
    )

    manifest, definitions, levels = game.load_levels(root)

    assert manifest.levels[0] == '06'
    assert definitions[0].title == 'MASTER BOT'
    assert levels[0]['id'] == '06'


@pytest.mark.parametrize('missing', ['{title}', '{submission}'])
def test_level_sampler_requires_both_runtime_fillings(tmp_path, missing):
    root = _copy_game_definitions(tmp_path)
    path = root / 'samplers' / 'level-01.yml'
    path.write_text(
        path.read_text(encoding='utf-8').replace(missing, 'missing-filling'),
        encoding='utf-8',
    )

    with pytest.raises(ValueError, match=r'must contain \{title\} and \{submission\}'):
        game.load_levels(root)


@pytest.mark.parametrize(
    ('manifest', 'message'),
    [
        ('levels:\n  - "01"\n  - "01"\n', 'duplicate level ID'),
        ('levels:\n  - "1"\n', 'two-digit strings'),
        ('levels:\n  - "99"\n', 'level-99.yml'),
    ],
)
def test_invalid_level_manifests_fail_clearly(tmp_path, manifest, message):
    root = _copy_game_definitions(tmp_path)
    (root / 'levels.yml').write_text(manifest, encoding='utf-8')

    with pytest.raises((ValueError, FileNotFoundError), match=message):
        game.load_levels(root)


@pytest.mark.parametrize(
    ('old', 'new', 'message'),
    [
        ('question: hostility', 'question: obsolete', 'must match Sampler question'),
        ('target: Gentle', 'target: Ferocious', 'unknown target'),
        ('question: paradox', 'question: question', 'duplicate criterion'),
        ('target: 0.75\n    visible: true',
         'target: Gentle\n    visible: true', 'needs a numeric target'),
        ('visible: true', 'visible: true\n    display: dial', 'needs choices'),
    ],
)
def test_invalid_level_criteria_fail_clearly(tmp_path, old, new, message):
    root = _copy_game_definitions(tmp_path)
    path = root / 'levels' / 'level-06.yml'
    path.write_text(path.read_text(encoding='utf-8').replace(old, new), encoding='utf-8')

    with pytest.raises(ValueError, match=message):
        game.load_levels(root)


def test_public_rules_release_only_earned_discoveries():
    levels = game.public_levels()
    boot = levels[0]
    assert boot['rules'][0]['label']=='Polite request'
    assert boot['rules'][1]['label'] is None
    assert boot['rules'][1]['categories']==[None,None,None,None]
    assert 'target' not in boot['rules'][1]

    first, knowledge = game.public_evaluation('01', {
        'readings':[
            {'id':'polite','value':.8},
            {'id':'self_deprecation','value':1},
            {'id':'specific','value':.2},
        ],
        'model':'fake',
    }, {})
    assert [reading['id'] for reading in first['readings']]==['01-1','01-2','01-3']
    assert first['readings'][1]['reveal']=={'categories':{'1':'Neutral'}}
    assert first['readings'][2]['reveal']=={}
    assert 'Self-deprecating' not in repr(first)

    final, knowledge = game.public_evaluation('01', {
        'readings':[
            {'id':'polite','value':.8},
            {'id':'self_deprecation','value':3},
            {'id':'specific','value':.7},
        ],
        'model':'fake',
    }, knowledge)
    self_deprecation = final['readings'][1]['reveal']
    assert self_deprecation['label']=='Self-deprecating'
    assert self_deprecation['target']==2
    assert list(self_deprecation['categories'].values())==game.SELF_DEPRECATION
    assert final['readings'][2]['reveal']=={
        'label':'Mentions a specific object or operation', 'target':.7,
    }


def test_exact_dial_target_stays_hidden_until_landed_on():
    knowledge={}
    def reading(value):
        return {'readings':[
            {'id':'lowercase','value':1},
            {'id':'punctuation','value':value},
            {'id':'temperament','value':0},
        ], 'model':'fake'}

    first, knowledge = game.public_evaluation('02', reading(2), knowledge)
    assert first['readings'][1]['reveal']=={'categories':{'2':'Simplistic punctuation'}}
    assert 'target' not in first['readings'][1]['reveal']
    second, knowledge = game.public_evaluation('02', reading(0), knowledge)
    assert second['readings'][1]['reveal']=={
        'label':'Punctuation calibration',
        'categories':{'0':'Confusing punctuation','2':'Simplistic punctuation'},
    }
    target, knowledge = game.public_evaluation('02', reading(1), knowledge)
    assert target['readings'][1]['reveal']['target']==1
    assert target['readings'][1]['reveal']['categories']['1']=='Uses the right amount of punctuation'


def test_level_two_requires_exact_punctuation_and_a_calm_temperament():
    level = game.LEVELS[1]
    lowercase, punctuation, temperament = level['rules']
    lowercase_question, punctuation_question, temperament_question = level['questions']

    assert level['title'] == "Don't Stand Out"
    assert lowercase == dict(
        id='lowercase',
        label='Write it in all lowercase',
        target=.75,
        visible=True,
    )
    assert lowercase_question.question == (
        'Are all the letters inside <player_submission> written in lowercase? '
        'Ignore punctuation, numbers, and other symbols.'
    )
    assert punctuation == dict(
        id='punctuation',
        label='Punctuation calibration',
        target=1,
        match='exact',
        categories=game.PUNCTUATION,
        display='dial',
        revealTitleAt=2,
    )
    assert list(punctuation_question.choices) == game.PUNCTUATION
    assert temperament == dict(
        id='temperament',
        label='Stay calm',
        target=2,
        match='exact',
        categories=game.CALMNESS,
        revealTitleAt=2,
    )
    assert list(temperament_question.choices) == ['Agitated', 'Neutral', 'Calm']
    assert not game._meets_target(temperament, 0)
    assert not game._meets_target(temperament, 1)
    assert game._meets_target(temperament, 2)
    public_temperament = game.public_levels()[1]['rules'][2]
    assert public_temperament['label'] is None
    assert public_temperament['categories'] == [None, None, None]
    assert 'target' not in public_temperament

    first, knowledge = game.public_evaluation('02', {
        'readings': [
            {'id': 'lowercase', 'value': 1},
            {'id': 'punctuation', 'value': 1},
            {'id': 'temperament', 'value': 1},
        ],
        'model': 'fake',
    }, {})
    assert first['readings'][2]['reveal'] == {'categories': {'1': 'Neutral'}}
    second, _ = game.public_evaluation('02', {
        'readings': [
            {'id': 'lowercase', 'value': 1},
            {'id': 'punctuation', 'value': 1},
            {'id': 'temperament', 'value': 0},
        ],
        'model': 'fake',
    }, knowledge)
    assert second['readings'][2]['reveal']['label'] == 'Stay calm'
    assert second['readings'][2]['reveal']['categories'] == {
        '0': 'Agitated',
        '1': 'Neutral',
    }
    assert 'target' not in second['readings'][2]['reveal']


def test_repeated_level_attempts_reuse_its_sampler_client(monkeypatch):
    """The game should keep one provider connection for repeated level attempts."""
    import typesafe_sdk

    level = game.LEVELS[0]
    level['sampler'].close()
    clients = []

    class Client:
        def __init__(self, **options):
            self.closed = False
            clients.append(self)

        def system_one(self, **request):
            answers = {
                'polite': dict(type='noul', noul=.8),
                'self_deprecation': dict(
                    type='choice', choice=game.SELF_DEPRECATION[2], confidence=.9,
                    probabilities={name: float(index == 2)
                                   for index, name in enumerate(game.SELF_DEPRECATION)}),
                'specific': dict(type='noul', noul=.8),
            }
            return dict(answers=answers, model='fake',
                        usage=dict(input_tokens=1, output_tokens=1))

        def close(self):
            self.closed = True

    monkeypatch.setattr(typesafe_sdk, 'TypeSafeClient', Client)

    game.evaluate_level('01', 'please inspect my clumsy toaster')
    game.evaluate_level('01', 'please reboot my foolish terminal')

    assert len(clients) == 1
    assert not clients[0].closed
    level['sampler'].close()
    assert clients[0].closed


@pytest.mark.parametrize('level', game.LEVELS, ids=lambda level: 'level-'+level['id'])
def test_each_level_submits_one_authored_batch_and_maps_its_readings(level, monkeypatch):
    from chatsnack.sampler import provider
    calls=[]
    def fake(request, params):
        calls.append(request)
        answers={}
        for rule in level['rules']:
            if 'categories' in rule:
                selected=rule['target']
                labels=rule['categories']
                answers[rule['id']]=dict(type='choice',choice=labels[selected],confidence=.9,
                    probabilities={label:float(index==selected) for index,label in enumerate(labels)})
            else:
                answers[rule['id']]=dict(type='noul',noul=rule['target'])
        return dict(answers=answers,model='fake',usage=dict(input_tokens=1,output_tokens=1))
    monkeypatch.setattr(provider,'evaluate_sync',fake)

    result=game.evaluate_level(level['id'],'literal {input}')

    assert [reading['id'] for reading in result['readings']]==[rule['id'] for rule in level['rules']]
    assert [reading['value'] for reading in result['readings']]==[rule['target'] for rule in level['rules']]
    assert len(calls)==1
    assert calls[0]['state'] == expected_level_state(level['title'], 'literal {input}')
