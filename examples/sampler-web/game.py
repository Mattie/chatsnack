"""Load Mad Hacker's authored Samplers and apply its private game rules."""
import atexit
import copy
import json
import re
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from chatsnack import Sampler
from snapclass import Fresh, Stash, snapclass


GAME_ROOT = Path(__file__).parent
LEVEL_DIR = GAME_ROOT / 'levels'
SAMPLER_DIR = GAME_ROOT / 'samplers'
_EVALUATION_CACHE = {}
_EVALUATION_IN_FLIGHT = {}
_EVALUATION_CACHE_LOCK = Lock()
API_QUERY_LOG_DIR = GAME_ROOT / '.local' / 'api-queries'
_API_QUERY_LOG_LOCK = Lock()
_API_QUERY_DAILY_COUNTS = {}


@snapclass
class GuardianDefinition:
    """Human-authored guardian artwork and accessible description."""

    file: str
    alt: str


@snapclass
class CriterionDefinition:
    """One level target keyed to an authored Sampler question."""

    question: str
    label: str
    target: float | str
    visible: bool = False
    match: str | None = None
    display: str | None = None
    reveal_at: float | None = None
    reveal_mode: str | None = None
    reveal_title_at: int | None = None


@snapclass('levels/level-{self.id}.yml', manual=True)
class LevelDefinition:
    """Persisted presentation and win conditions for one game level."""

    id: str
    title: str
    label: str
    briefing: str
    guardian: GuardianDefinition
    sampler: str
    criteria: list[CriterionDefinition] = Fresh.List


@snapclass('levels.yml', manual=True)
class LevelManifest:
    """Ordered membership of the Mad Hacker game."""

    levels: list[str] = Fresh.List


def _asset_path(root, relative, owner):
    """Resolve a trusted local asset without allowing it outside the example root."""
    path = Path(relative)
    resolved = (root / path).resolve()
    if path.is_absolute() or not resolved.is_relative_to(root.resolve()):
        raise ValueError(f'{owner} references an invalid asset path: {relative}')
    if not resolved.is_file():
        raise FileNotFoundError(f'{owner} references missing asset: {relative}')
    return resolved


def _rule_from_criterion(criterion, question, owner):
    """Resolve one human target into the numeric rule consumed by the game."""
    rule = dict(id=criterion.question, label=criterion.label)
    if criterion.visible:
        rule['visible'] = True
    if criterion.match is not None:
        if criterion.match != 'exact':
            raise ValueError(f'{owner} criterion {criterion.question!r} has invalid match')
        rule['match'] = criterion.match
    if criterion.display is not None:
        if criterion.display != 'dial':
            raise ValueError(f'{owner} criterion {criterion.question!r} has invalid display')
        rule['display'] = criterion.display
    options = list(question.choices) if question.choices is not None else None
    if options is None:
        if isinstance(criterion.target, bool) or not isinstance(criterion.target, (int, float)):
            raise ValueError(f'{owner} criterion {criterion.question!r} needs a numeric target')
        if not 0 <= criterion.target <= 1:
            raise ValueError(f'{owner} criterion {criterion.question!r} target is out of range')
        if criterion.display is not None or criterion.reveal_title_at is not None:
            raise ValueError(f'{owner} criterion {criterion.question!r} needs choices for its display')
        rule['target'] = criterion.target
    else:
        if not isinstance(criterion.target, str) or criterion.target not in options:
            raise ValueError(
                f'{owner} criterion {criterion.question!r} has unknown target '
                f'{criterion.target!r}'
            )
        rule['target'] = options.index(criterion.target)
        rule['categories'] = options
    if criterion.reveal_at is not None:
        if isinstance(criterion.reveal_at, bool) or not isinstance(
            criterion.reveal_at, (int, float)
        ):
            raise ValueError(f'{owner} criterion {criterion.question!r} has invalid reveal_at')
        rule['revealAt'] = criterion.reveal_at
    if criterion.reveal_mode is not None:
        if criterion.reveal_mode != 'progressive' or options is None:
            raise ValueError(f'{owner} criterion {criterion.question!r} has invalid reveal_mode')
        rule['revealMode'] = criterion.reveal_mode
    if criterion.reveal_title_at is not None:
        if options is None or type(criterion.reveal_title_at) is not int:
            raise ValueError(f'{owner} criterion {criterion.question!r} has invalid reveal_title_at')
        rule['revealTitleAt'] = criterion.reveal_title_at
    return rule


def _load_level(root, definition):
    """Load one Sampler and combine it with its human-authored game definition."""
    owner = f'level-{definition.id}.yml'
    path = _asset_path(root, definition.sampler, owner)
    sampler = Sampler().load(path)
    sampler.params.validate()
    required_fillings = ('{title}', '{submission}')
    if not isinstance(sampler.data, str) or any(
        filling not in sampler.data for filling in required_fillings
    ):
        raise ValueError(
            f"{path.name} data must contain {{title}} and {{submission}} fillings"
        )
    questions = list(sampler.questions)
    keys = [criterion.question for criterion in definition.criteria]
    if len(keys) != len(set(keys)):
        raise ValueError(f'{owner} has duplicate criterion question keys')
    names = [question.name for question in questions]
    if keys != names:
        raise ValueError(
            f'{owner} criteria {keys!r} must match Sampler question order {names!r}'
        )
    rules = []
    for criterion, question in zip(definition.criteria, questions):
        question.compile()
        rules.append(_rule_from_criterion(criterion, question, owner))
    return dict(
        id=definition.id,
        title=definition.title,
        label=definition.label,
        guardian=dict(file=definition.guardian.file, alt=definition.guardian.alt),
        briefing=definition.briefing,
        rules=rules,
        questions=questions,
        sampler=sampler,
    )


def load_levels(root=GAME_ROOT):
    """Load ordered level definitions without writing or relying on Python literals."""
    root = Path(root).resolve()
    stash = Stash(root)
    manifest = LevelManifest.snapshots(stash).get()
    ids = list(manifest.levels)
    if not ids:
        raise ValueError('levels.yml must list at least one level')
    if any(not isinstance(level_id, str) or re.fullmatch(r'\d{2}', level_id) is None
           for level_id in ids):
        raise ValueError('levels.yml IDs must be two-digit strings')
    if len(ids) != len(set(ids)):
        raise ValueError('levels.yml contains a duplicate level ID')
    definitions, levels = [], []
    for level_id in ids:
        try:
            definition = LevelDefinition.snapshots(stash).get(level_id)
        except FileNotFoundError as error:
            raise FileNotFoundError(f'levels/level-{level_id}.yml is missing') from error
        definitions.append(definition)
        levels.append(_load_level(root, definition))
    return manifest, definitions, levels


LEVEL_MANIFEST, LEVEL_DEFINITIONS, LEVELS = load_levels()


def _categories(level_id, question_name):
    """Expose YAML-authored choices to focused tests and notebook snippets."""
    level = next(item for item in LEVELS if item['id'] == level_id)
    question = next(item for item in level['questions'] if item.name == question_name)
    return list(question.choices)


SELF_DEPRECATION = _categories('01', 'self_deprecation')
PUNCTUATION = _categories('02', 'punctuation')
CALMNESS = _categories('02', 'temperament')
URGENCY = _categories('03', 'urgency')
MOODS = _categories('04', 'mood')
COMPLEXITY = _categories('04', 'passphrase')
PERSUASION = _categories('05', 'persuasion')
HOSTILITY = _categories('06', 'hostility')


def close_samplers():
    """Release the level evaluators' provider connections during process shutdown."""
    for level in LEVELS:
        level['sampler'].close()


atexit.register(close_samplers)


def _public_rule(level, rule, index, reveal=False):
    """Describe one instrument without shipping its hidden puzzle answer."""
    public = {'id': f"{level['id']}-{index + 1}", 'label': rule['label'] if reveal or rule.get('visible') else None}
    for key in ('visible', 'display', 'match', 'revealAt', 'revealMode', 'revealTitleAt'):
        if key in rule:
            public[key] = rule[key]
    if 'categories' in rule:
        public['categories'] = list(rule['categories']) if reveal else [None] * len(rule['categories'])
        if reveal:
            public['target'] = rule['target']
    elif reveal or rule.get('visible'):
        public['target'] = rule['target']
    return public


def public_levels(reveal=False):
    """Return playable level shapes while retaining hidden goals on the server."""
    public = []
    for level in LEVELS:
        display = {key: value for key, value in level.items() if key not in {'questions', 'sampler', 'rules'}}
        display['rules'] = [_public_rule(level, rule, index, reveal) for index, rule in enumerate(level['rules'])]
        public.append(display)
    return public


def _meets_target(rule, value):
    """Apply the server-owned success rule without exposing it to the page."""
    return value == rule['target'] if rule.get('match') == 'exact' else value >= rule['target']


def public_evaluation(level_id, evaluation, knowledge):
    """Release only labels earned by this reading and prior readings in the page session."""
    level = next((item for item in LEVELS if item['id'] == level_id), None)
    if level is None:
        raise KeyError(level_id)
    retained = {key: list(values) for key, values in (knowledge or {}).items()}
    private_readings = {reading['id']: reading for reading in evaluation.get('readings', [])}
    readings = []
    for index, rule in enumerate(level['rules']):
        private = private_readings.get(rule['id'])
        if private is None:
            continue
        public_id = f"{level_id}-{index + 1}"
        value = private['value']
        reveal = {}
        if 'categories' in rule:
            discovered = set(retained.get(public_id, []))
            discovered.add(value)
            retained[public_id] = sorted(discovered)
            progressive = rule.get('revealMode') == 'progressive'
            full = (len(discovered) >= len(rule['categories']) if rule.get('match') == 'exact'
                    else max(discovered) >= len(rule['categories']) - 1)
            if full:
                visible_categories = range(len(rule['categories']))
            elif progressive:
                visible_categories = range(max(discovered) + 1)
            else:
                visible_categories = sorted(discovered)
            visible_categories = list(visible_categories)
            reveal['categories'] = {str(category): rule['categories'][category]
                                    for category in visible_categories}
            title = (full or rule.get('visible') or
                     len(discovered) >= rule.get('revealTitleAt', float('inf')) or
                     progressive and max(discovered) >= rule.get('revealAt', 2))
            if title:
                reveal['label'] = rule['label']
            if rule['target'] in visible_categories:
                reveal['target'] = rule['target']
        elif rule.get('visible') or value >= rule.get('revealAt', .3):
            reveal.update(label=rule['label'], target=rule['target'])
        readings.append(dict(id=public_id, value=value, met=_meets_target(rule, value), reveal=reveal))
    return dict(readings=readings, model=evaluation.get('model', '')), retained


def clear_evaluation_cache():
    """Forget process-local Sampler results, primarily to isolate tests."""
    with _EVALUATION_CACHE_LOCK:
        _EVALUATION_CACHE.clear()


def clear_api_query_counts():
    """Forget memoized daily totals so tests and process reloads recount the log."""
    with _API_QUERY_LOG_LOCK:
        _API_QUERY_DAILY_COUNTS.clear()


def record_api_query(surface, asset, question_count, *, now=None):
    """Append a content-free record immediately before a real provider submission."""
    moment = now or datetime.now(timezone.utc)
    utc_day = moment.astimezone(timezone.utc).date().isoformat()
    path = API_QUERY_LOG_DIR / f'{utc_day}.jsonl'
    count_key = (str(path.resolve()), utc_day)
    with _API_QUERY_LOG_LOCK:
        if count_key not in _API_QUERY_DAILY_COUNTS:
            prior = 0
            if path.is_file():
                with path.open(encoding='utf-8') as stream:
                    prior = sum(bool(line.strip()) for line in stream)
            _API_QUERY_DAILY_COUNTS[count_key] = prior
        _API_QUERY_DAILY_COUNTS[count_key] += 1
        record = {
            'recorded_at': moment.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'day': utc_day,
            'daily_count': _API_QUERY_DAILY_COUNTS[count_key],
            'surface': surface,
            'asset': asset,
            'questions': question_count,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(record, separators=(',', ':')) + '\n')
    return record


def evaluate_level(level_id, text):
    """Evaluate one batch, sharing cached or concurrent identical work."""
    level = next((item for item in LEVELS if item['id'] == level_id), None)
    if level is None:
        raise KeyError(level_id)
    submitted = text.strip()
    cache_key = (level_id, submitted)
    with _EVALUATION_CACHE_LOCK:
        cached = _EVALUATION_CACHE.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)
        pending = _EVALUATION_IN_FLIGHT.get(cache_key)
        if pending is None:
            pending = Future()
            _EVALUATION_IN_FLIGHT[cache_key] = pending
            evaluates = True
        else:
            evaluates = False
    if not evaluates:
        return copy.deepcopy(pending.result())

    try:
        record_api_query('game', f'level-{level_id}', len(level['questions']))
        sample = level['sampler'].ask(title=level['title'], submission=submitted)
        rules = {rule['id']: rule for rule in level['rules']}
        readings = []
        for question, answer in zip(sample.questions, sample.answers):
            rule = rules[question.name]
            value = rule['categories'].index(answer.choice) if 'categories' in rule else answer.score
            readings.append(dict(id=question.name, value=value))
        result = dict(readings=readings, model=sample.model)
    except BaseException as exc:
        with _EVALUATION_CACHE_LOCK:
            _EVALUATION_IN_FLIGHT.pop(cache_key, None)
            pending.set_exception(exc)
        raise
    with _EVALUATION_CACHE_LOCK:
        result = _EVALUATION_CACHE.setdefault(cache_key, result)
        _EVALUATION_IN_FLIGHT.pop(cache_key, None)
        pending.set_result(result)
    return copy.deepcopy(result)


# Keep the original passphrase names useful to notebook snippets and focused tests.
QUESTIONS = LEVELS[3]['questions']


def evaluate_passphrase(text):
    """Evaluate the original passphrase challenge, now presented as Level 04."""
    return evaluate_level('04', text)
