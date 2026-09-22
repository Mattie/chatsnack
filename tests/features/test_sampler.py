"""Goal contracts: notebook-sized authored Samplers and consistent Samples."""

import asyncio

import pytest

from chatsnack import Question, Sample, Sampler
from chatsnack import Chat, Text, resolve_fillings_a, FillingError, FillingAuthorityError, FillingLimitError


@pytest.fixture
def evaluations(monkeypatch):
    """Record the SDK boundary while returning deterministic mixed answers."""
    calls = []

    async def evaluate(request, params):
        calls.append((request, params))
        answers = {}
        for key, question in reversed(list(request['questions'].items())):
            kind = question['type']
            if kind == 'noul':
                answers[key] = {'type': kind, 'noul': 0.8}
            elif kind == 'choice':
                options = list(question['criteria'])
                answers[key] = dict(type=kind, choice=options[0], confidence=0.7,
                                    probabilities={k: 1 / len(options) for k in options})
            else:
                count = len(question['criteria'])
                answers[key] = dict(type=kind, score=0.75, confidence=0.3,
                                    probabilities={str(i): 1 / count for i in range(count)})
        return dict(model='jev-test', answers=answers,
                    usage=dict(input_tokens=12, output_tokens=3))

    monkeypatch.setattr('chatsnack.sampler.provider.evaluate', evaluate)
    return calls


def test_goal_every_ask_returns_sample(evaluations):
    sampler = Sampler(data='popcorn', questions=['Crunchy?'])
    for sample in (sampler.ask('Crunchy?'), sampler.ask(questions=['Crunchy?']), sampler.ask()):
        assert isinstance(sample, Sample)
        assert sample.answer is sample.answers[0]
        assert sample.question is sample.questions[0]
        assert sample.answer.yes
        assert sample.model == 'jev-test'
        assert sample.usage.input_tokens == 12


@pytest.mark.asyncio
async def test_goal_batch_order_names_and_async(evaluations):
    questions = [Question(name='approved', question='Good?'),
                 Question(name='category', question='Which?', choices=['snack', 'meal']),
                 Question(name='health', question='Healthy?', levels=['low', 'high'])]
    sample = await Sampler(data={'food': 'popcorn'}).ask_a(questions=questions)
    assert sample.question.name == 'approved'
    assert sample.answers['category'].choice == 'snack'
    assert sample.answers['health'].choice == 'low'
    assert sample.answers['health'].score == 0.75
    assert sample.answers['approved'].confidence == pytest.approx(0.6)
    reordered = await Sampler(data='popcorn').ask_a(questions=list(reversed(questions)))
    assert reordered.question.name == 'health'
    assert reordered.answers['category'].choice == sample.answers['category'].choice
    assert reordered.answers['approved'].yes == sample.answers['approved'].yes
    questions[0].question = 'Changed'
    assert sample.question.question == 'Good?'


def test_goal_save_load_and_literal_replay(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    question = Question(name='crunchy', question='Is {food} crunchy?')
    question.save()
    sampler = Sampler(name='SnackCheck', data='{snack}', questions=['{question.crunchy}'])
    assert not (tmp_path / 'samplers' / 'SnackCheck.yml').exists()
    sampler.save()
    assert sampler.yaml == 'data: "{snack}"\nquestions:\n  - "{question.crunchy}"\n'
    loaded = Sampler(name='SnackCheck')
    loaded.load()
    sample = loaded.ask(snack={'text': '{literal}'}, food='{raw}')
    assert sample.data == {'text': '{literal}'}
    assert sample.question.question == 'Is {raw} crunchy?'
    replay = Sampler.from_sample(sample, name='Replay')
    replay.save()
    replay = Sampler.snapshots.get('Replay')
    repeated = replay.ask()
    assert repeated.data == sample.data
    assert repeated.question.question == sample.question.question
    assert replay.model == sample.model
    assert evaluations[-1][0]['state'] == sample.data


def test_goal_reject_empty_batch_before_evaluation(evaluations):
    with pytest.raises(ValueError, match='question'):
        Sampler(data='popcorn').ask()
    assert not evaluations


def test_batch_requires_a_collection_and_unique_names(evaluations):
    with pytest.raises(ValueError, match='list or tuple'):
        Sampler(data='hi', questions='Good?')
    sampler = Sampler(data='hi')
    with pytest.raises(ValueError, match='not both'):
        sampler.ask('Good?', questions=['Good?'])
    with pytest.raises(ValueError, match='Duplicate'):
        sampler.ask(questions=[Question(name='same', question='One?'),
                               Question(name='same', question='Two?')])
    assert not evaluations


@pytest.mark.parametrize('name', [
    ['unhashable'], 'ambiguous.answer', 'indexed[answer]', 'braced{answer}',
    'converted!answer', 'formatted:answer',
])
def test_question_names_fail_preflight_before_mapping_or_filling(name, evaluations):
    with pytest.raises(ValueError, match='Question names must be nonempty strings without filling metacharacters'):
        Sampler(data='hi').ask(Question(name=name, question='Good?'))
    assert not evaluations


def saved_sampler(name='SnackCheck', **kwargs):
    """Small saved fixture with a named answer suitable for composition."""
    return Sampler(name=name, data=kwargs.pop('data', '{snack}'),
                   questions=[Question(name='crunchy', question='Crunchy?')], **kwargs).save()


@pytest.mark.asyncio
async def test_goal_result_fillings_share_one_evaluation_across_chat_messages(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    saved_sampler()
    Text(name='Decision', content='{sampler.SnackCheck.crunchy.choice}').save()
    chat = Chat().system('{text.Decision}').user(
        '{sampler.SnackCheck.crunchy.score} {sampler.SnackCheck.crunchy.confidence}')
    # Inspect the actual Chat preparation boundary without an unrelated chat API call.
    prompt = await chat._build_final_prompt({'snack': 'popcorn'})
    assert 'yes' in prompt and '0.8' in prompt
    assert len(evaluations) == 1
    await chat._build_final_prompt({'snack': 'apple'})
    assert len(evaluations) == 2
    assert evaluations[-1][0]['state'] == 'apple'


@pytest.mark.asyncio
async def test_named_result_fillings_accept_non_formatter_punctuation(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    Sampler(name='SnackCheck', data='popcorn', questions=[
        Question(name='well-approved', question='Good?'),
    ]).save()
    values = await resolve_fillings_a(
        ['sampler.SnackCheck.well-approved.choice'], allow_sampler=True,
    )
    assert values['sampler']['SnackCheck.well-approved.choice'] == 'yes'
    assert len(evaluations) == 1


@pytest.mark.asyncio
async def test_goal_public_resolver_authority_and_typed_results(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    saved_sampler()
    Question(name='Saved', question='Is {snack} crunchy?').save()
    refs = ['sampler.SnackCheck.crunchy.choice', 'sampler.SnackCheck.crunchy.score', 'question.Saved']
    with pytest.raises(FillingAuthorityError):
        await resolve_fillings_a(refs, variables={'snack': 'popcorn'})
    assert not evaluations
    values = await resolve_fillings_a(refs, variables={'snack': 'popcorn'}, allow_sampler=True)
    assert values['sampler']['SnackCheck.crunchy.score'] == 0.8
    assert isinstance(values['question']['Saved'], Question)
    assert values['question']['Saved'].question == 'Is popcorn crunchy?'
    assert len(evaluations) == 1
    literal = await resolve_fillings_a(refs[:1], variables={'sampler': {'SnackCheck.crunchy.choice': '{raw}'}})
    assert literal['sampler']['SnackCheck.crunchy.choice'] == '{raw}'
    assert len(evaluations) == 1


@pytest.mark.asyncio
async def test_transitive_authority_is_independent(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    saved_sampler(data='{chat.Prep}')
    Chat(name='Prep').system('hello').save()
    with pytest.raises(FillingAuthorityError, match='chat'):
        await resolve_fillings_a(['sampler.SnackCheck.crunchy.choice'], allow_sampler=True)
    Text(name='Indirect', content='{sampler.SnackCheck.crunchy.choice}').save()
    with pytest.raises(FillingAuthorityError, match='sampler'):
        await resolve_fillings_a(['text.Indirect'], allow_chat=True)
    assert not evaluations


@pytest.mark.asyncio
async def test_concurrent_cycle_fails_without_deadlock(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    saved_sampler('A', data='{sampler.B.crunchy.choice}')
    saved_sampler('B', data='{sampler.A.crunchy.choice}')
    chat = Chat('{sampler.A.crunchy.choice} {sampler.B.crunchy.choice}')
    with pytest.raises(FillingError, match='cycle'):
        await asyncio.wait_for(chat._build_final_prompt(), 2)
    assert not evaluations


@pytest.mark.asyncio
async def test_question_cycle_fails_without_recursion(tmp_path, monkeypatch):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    Question(name='A', question='{question.B}').save()
    Question(name='B', question='{question.A}').save()
    with pytest.raises(FillingError, match='cycle'):
        await Sampler(data='hi').compile_a('{question.A}')


@pytest.mark.asyncio
async def test_cancellation_cleans_up_shared_evaluation(tmp_path, monkeypatch):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    saved_sampler(data='hi')
    started, stopped = asyncio.Event(), asyncio.Event()

    async def wait(request, params):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr('chatsnack.sampler.provider.evaluate', wait)
    task = asyncio.create_task(Chat('{sampler.SnackCheck.crunchy.choice}')._build_final_prompt())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_resolver_counts_actual_evaluations_and_missing_assets(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    for index in range(17):
        saved_sampler(f'S{index}', data='hello')
    refs = [f'sampler.S{i}.crunchy.choice' for i in range(17)]
    with pytest.raises(FillingLimitError, match='sampler'):
        await resolve_fillings_a(refs, allow_sampler=True)
    assert len(evaluations) == 16
    missing = await resolve_fillings_a(['sampler.Absent.crunchy.choice'], allow_sampler=True)
    assert missing['sampler'] == {}


@pytest.mark.asyncio
async def test_custom_sampler_callback_obeys_resolver_budget(monkeypatch):
    from chatsnack.fillings import snack_catalog
    calls = []

    async def custom(suffix, additional=None):
        calls.append(suffix)
        return 'yes'

    monkeypatch.setitem(snack_catalog.vendors, 'sampler', custom)
    with pytest.raises(FillingLimitError, match='sampler'):
        await resolve_fillings_a([f'sampler.S{i}.approved.choice' for i in range(17)], allow_sampler=True)
    assert len(calls) == 16


@pytest.mark.asyncio
async def test_reuse_separates_bindings_and_stashes_in_one_expansion(tmp_path, monkeypatch, evaluations):
    from chatsnack.fillings import active_filling_stash, filling_machine
    from chatsnack.sampler.composition import expansion_scope
    roots = [tmp_path / 'one', tmp_path / 'two']
    for root in roots:
        saved = Sampler(name='Shared', data={'food': '{food}'},
                        questions=[Question(name='approved', question='Good?')])
        saved.save(root / 'samplers/Shared.yml')
    async with expansion_scope():
        for root, food in [(roots[0], 'apple'), (roots[0], 'apple'),
                           (roots[0], 'pear'), (roots[1], 'apple')]:
            token = active_filling_stash.set(root)
            try:
                assert await filling_machine({'food': food})['sampler']['Shared.approved.score']() == .8
            finally:
                active_filling_stash.reset(token)
    assert [request['state'] for request, _ in evaluations] == [
        {'food': 'apple'}, {'food': 'pear'}, {'food': 'apple'}]


@pytest.mark.asyncio
async def test_resolver_provider_errors_omit_evaluated_content(tmp_path, monkeypatch):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    saved_sampler(data='private content')

    async def fail(request, params):
        raise RuntimeError('private content')

    monkeypatch.setattr('chatsnack.sampler.provider.evaluate', fail)
    with pytest.raises(FillingError, match='could not resolve') as error:
        await resolve_fillings_a(['sampler.SnackCheck.crunchy.choice'], allow_sampler=True)
    assert 'private content' not in str(error.value)


def test_overrides_and_anonymous_ids_are_independent(evaluations):
    sampler = Sampler(data={'original': []}, model='authored', questions=['Good?'])
    sample = sampler.ask(data={'literal': '{x}'}, model='override', timeout=3,
                         questions=[Question(name='_question_1', question='One?'), 'Two?'])
    assert len(sample.answers) == 2
    assert sample.data == {'literal': '{x}'}
    assert sampler.data == {'original': []} and sampler.model == 'authored'
    assert evaluations[0][1].timeout == 3
    assert len(evaluations[0][0]['questions']) == 2


def test_saved_forms_stay_authored_and_live_reference_updates(tmp_path, monkeypatch, evaluations):
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path))
    question = Question(name='shared', question='Original?')
    question.save()
    sampler = Sampler(name='Forms', data={}, questions=['Inline?', question, '{question.shared}'])
    sampler.save()
    loaded = Sampler.snapshots.get('Forms')
    assert loaded.questions[0] == 'Inline?'
    assert isinstance(loaded.questions[1], Question)
    assert loaded.questions[2] == '{question.shared}'
    # Evaluate each saved form independently: repeated explicit names are correctly rejected in a batch.
    question.question = 'Updated?'
    question.save()
    assert loaded.ask(loaded.questions[1]).question.question == 'Original?'
    assert loaded.ask(loaded.questions[2]).question.question == 'Updated?'


def test_custom_stash_and_anonymous_save(tmp_path, monkeypatch, evaluations):
    from snapclass import Stash
    root = tmp_path / 'custom'
    monkeypatch.setenv('CHATSNACK_BASE_DIR', str(tmp_path / 'elsewhere'))
    Question(name='local', question='Local?').save(root / 'questions/local.yml')
    Sampler(name='Review', data='hi', questions=['{question.local}']).save(root / 'samplers/Review.yml')
    assert Sampler.snapshots(Stash(root)).get('Review').ask().question.question == 'Local?'
    anonymous = Sampler(data='hi', questions=['Good?'])
    with pytest.raises(ValueError, match='name'):
        anonymous.save()
    anonymous.save(root / 'samplers/Anonymous.yml')
    assert Sampler.snapshots(root).get('Anonymous').ask().answer.yes
    anonymous.questions = ['{question.local}']
    anonymous.save(root / 'samplers/Anonymous.yml')
    assert anonymous.ask().question.question == 'Local?'
    assert Sampler().load(root / 'samplers/Anonymous.yml').ask().question.question == 'Local?'


@pytest.mark.parametrize('question', [
    Question(question=''), Question(question=' ', choices=['a']),
    Question(question='Q', choices=[]), Question(question='Q', choices=['a', 'a']),
    Question(question='Q', levels=['a']), Question(question='Q', levels=['a', {'a': 'other'}]),
    Question(question='Q', levels=['a', 'b'], choices=['a']),
    Question(question='Q', choices=['a'], yes='yes'),
])
def test_invalid_question_rejected_before_evaluation(question, evaluations):
    with pytest.raises(ValueError):
        Sampler(data='hi').ask(question)
    assert not evaluations


@pytest.mark.parametrize('response', [
    {}, {'model': 'jev', 'answers': {}, 'usage': {'input_tokens': 1, 'output_tokens': 1}},
    {'model': 'jev', 'answers': {'_question_0': {'type': 'noul', 'noul': float('nan')}},
     'usage': {'input_tokens': 1, 'output_tokens': 1}},
])
def test_malformed_response_is_not_a_plausible_answer(response, monkeypatch):
    async def bad(request, params):
        return response
    monkeypatch.setattr('chatsnack.sampler.provider.evaluate', bad)
    with pytest.raises(ValueError):
        Sampler(data='hi').ask('Good?')


def test_ties_and_provider_choice_are_preserved(monkeypatch):
    async def tied(request, params):
        return dict(model='jev', usage=dict(input_tokens=0, output_tokens=0), answers={
            'binary': dict(type='noul', noul=0.5),
            'choice': dict(type='choice', choice='b', probabilities={'a': .9, 'b': .1}, confidence=.44),
            'score': dict(type='score', score=.7, probabilities={'1': .5, '0': .5}, confidence=.22)})
    monkeypatch.setattr('chatsnack.sampler.provider.evaluate', tied)
    sample = Sampler(data='hi').ask(questions=[Question(name='binary', question='Q'),
        Question(name='choice', question='Q', choices=['a', 'b']),
        Question(name='score', question='Q', levels=[{'first': {}}, {'second': []}])])
    assert sample.answer.yes and sample.answer.confidence == 0
    assert sample.answers['choice'].choice == 'b'
    assert sample.answers['choice'].score == .1
    assert sample.answers['score'].choice == 'first'
    assert sample.answers['score'].score == .7


def test_structured_content_and_sample_as_new_data(evaluations):
    first = Sampler(data={'empty': []}).ask(Question(question={'instruction': 'Good?'}, yes={'rubric': []}))
    second = Sampler(data=first).ask('Was the previous answer yes?')
    assert second.data['answers'][0]['choice'] == 'yes'
    assert second.data['data'] == {'empty': []}


@pytest.mark.parametrize('expand', [True, False])
def test_prior_sample_data_stays_literal_after_followup_save(tmp_path, evaluations, expand):
    first = Sampler(data='unused').ask('Good?', data={'literal': '{sampler.Missing.q.choice}',
                                                    'braces': ['{', '}', '{{nested}}']})
    followup = Sampler(name='Follow', data=first, expand=expand,
                      questions=['Review {subject}?'])
    path = tmp_path / 'Follow.yml'
    followup.save(path)
    loaded = Sampler().load(path)
    repeated = loaded.ask(subject='the result')
    assert repeated.data == first.to_dict()
    assert repeated.question.question == ('Review the result?' if expand else 'Review {subject}?')
    loaded.save(path)
    assert Sampler().load(path).ask(subject='again').data == first.to_dict()
    assert followup.data is first
