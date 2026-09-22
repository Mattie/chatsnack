"""A local, live Flask playground backed by authored chatsnack Samplers."""

from __future__ import annotations

import json
import os
import secrets
from hashlib import sha256
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, render_template, request, session
from dotenv import load_dotenv

HERE = Path(__file__).parent


def _game_asset_version():
    """Fingerprint the game bundle so browsers replace stale deployed modules."""
    digest = sha256()
    for name in ("game.css", "game.js", "game-state.mjs", "game-pocket.css", "game-pocket.mjs"):
        digest.update((HERE / "static" / name).read_bytes())
    return digest.hexdigest()[:12]


GAME_ASSET_VERSION = _game_asset_version()
GAME_SPEC = spec_from_file_location("sampler_web_game", HERE / "game.py")
GAME_MODULE = module_from_spec(GAME_SPEC)
assert GAME_SPEC.loader is not None
GAME_SPEC.loader.exec_module(GAME_MODULE)
LAB_SPEC = spec_from_file_location("sampler_web_lab", HERE / "lab.py")
LAB_MODULE = module_from_spec(LAB_SPEC)
assert LAB_SPEC.loader is not None
LAB_SPEC.loader.exec_module(LAB_MODULE)
# Keep local credentials beside the example; explicit environment values win.
load_dotenv(HERE / ".env")
app = Flask(__name__, template_folder=str(HERE / "templates"), static_folder=str(HERE / "static"))
app.secret_key = os.getenv("MAD_HACKER_SECRET_KEY") or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("MAD_HACKER_HOSTED") == "1",
)
_solution_log_lock = Lock()
SOLUTION_LOG_DIR = HERE / ".local" / "solutions"


def _game_player_id():
    """Give each browser an opaque identity for independent game sessions."""
    player_id = session.get("game_player_id")
    if not isinstance(player_id, str):
        player_id = secrets.token_urlsafe(18)
        session["game_player_id"] = player_id
    return player_id


def _append_solution(record):
    """Append one accepted winning phrase to its level's local review log."""
    path = SOLUTION_LOG_DIR / f"level-{record['level']}.jsonl"
    line = json.dumps(record, ensure_ascii=False, separators=(',', ':'))
    with _solution_log_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8', newline='\n') as stream:
            stream.write(line + '\n')


def _accept_game_progress(token):
    """Commit only the pending result identified by the browser's current token."""
    pending = session.get('game_pending')
    if not pending or token != pending['token']:
        return False, False
    session.pop('game_pending', None)
    session['game_knowledge'] = pending['knowledge']
    logged = False
    if pending['won']:
        session['game_unlocked'] = min(
            len(GAME_MODULE.LEVELS) - 1,
            max(session.get('game_unlocked', 0), pending['level_index'] + 1),
        )
        try:
            _append_solution(pending['solution'])
            logged = True
        except OSError as exc:
            app.logger.warning("Mad Hacker solution log failed (%s)", type(exc).__name__)
    return True, logged


DEMOS = LAB_MODULE.DEMOS
GAME_DESCRIPTION = (
    "Bypass six eccentric AI security checkpoints by finding exactly what each "
    "guardian wants to hear."
)


app.config["MAX_CONTENT_LENGTH"] = 256_000


@app.get("/lab")
def index():
    """Expose authored examples and key availability, never credentials."""
    return render_template(
        "index.html",
        demos=LAB_MODULE.public_tabs(),
        configured=bool(os.getenv("TYPESAFE_API_KEY")),
    )


@app.get("/")
def game():
    """Open the passphrase experiment while retaining this browser's progress."""
    _game_player_id()
    session.pop('game_debug', None)
    session.pop('game_pending', None)
    saved_unlocked = session.get('game_unlocked', 0)
    unlocked = min(max(saved_unlocked, 0), len(GAME_MODULE.LEVELS) - 1) \
        if isinstance(saved_unlocked, int) else 0
    public_url = (os.getenv("MAD_HACKER_PUBLIC_URL") or request.url_root).rstrip("/") + "/"
    return render_template(
        "game.html",
        configured=bool(os.getenv("TYPESAFE_API_KEY")),
        levels=GAME_MODULE.public_levels(),
        unlocked=unlocked,
        asset_version=GAME_ASSET_VERSION,
        social_url=public_url,
        social_image=f"{public_url}static/mad-hacker-preview.png",
        social_description=GAME_DESCRIPTION,
    )


@app.post("/api/game/reset")
def reset_game():
    """Clear the server-owned half of one browser's saved game."""
    session.pop('game_knowledge', None)
    session.pop('game_unlocked', None)
    session.pop('game_pending', None)
    return jsonify(reset=True)


@app.get("/api/game/debug")
def game_debug_rules():
    """Reveal goals only when explicitly requested in an allowed environment."""
    debug_allowed = (
        request.remote_addr in {'127.0.0.1', '::1'} or
        os.getenv('MAD_HACKER_REMOTE_DEBUG') == '1'
    )
    if request.args.get('debug') != '1' or not debug_allowed:
        return jsonify(error="Debug reveal is unavailable."), 404
    session['game_debug'] = True
    response = jsonify(levels=GAME_MODULE.public_levels(reveal=True))
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post("/api/game")
def game_readings():
    """Validate one level submission and return its content-free readings."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("text"), str) or not isinstance(body.get('level'), str):
        return jsonify(error="Send a level and phrase as text."), 400
    if body['level'] not in {level['id'] for level in GAME_MODULE.LEVELS}:
        return jsonify(error="Choose an available level."), 400
    if body.get('reset') is True and body['level'] == '01':
        session.pop('game_knowledge', None)
        session.pop('game_unlocked', None)
        session.pop('game_pending', None)
    # Commit only progress from a response the browser accepted as current.
    if isinstance(body.get('accepted'), str):
        _accept_game_progress(body['accepted'])
    level_index = next(index for index, level in enumerate(GAME_MODULE.LEVELS)
                       if level['id'] == body['level'])
    if not session.get('game_debug') and level_index > session.get('game_unlocked', 0):
        return jsonify(error="That circuit is still locked."), 403
    text = body["text"].strip()
    if not text.strip() or len(text) > 2000:
        return jsonify(error="Use between 1 and 2,000 characters."), 400
    if not os.getenv("TYPESAFE_API_KEY"):
        return jsonify(error="Set TYPESAFE_API_KEY on the server, then reload."), 503
    try:
        evaluation = GAME_MODULE.evaluate_level(body['level'], text)
        knowledge = dict(session.get('game_knowledge', {}))
        result, retained = GAME_MODULE.public_evaluation(
            body['level'], evaluation, knowledge.get(body['level'], {}))
        knowledge[body['level']] = retained
        progress_token = secrets.token_urlsafe(16)
        won = (len(result['readings']) == len(GAME_MODULE.LEVELS[level_index]['rules']) and
               all(reading['met'] for reading in result['readings']))
        level = GAME_MODULE.LEVELS[level_index]
        session['game_pending'] = {
            'token': progress_token,
            'knowledge': knowledge,
            'level_index': level_index,
            'won': won,
            'solution': {
                'recorded_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'level': level['id'],
                'title': level['title'],
                'text': text,
                'model': evaluation.get('model', ''),
                'readings': evaluation['readings'],
            } if won else None,
        }
        result['progressToken'] = progress_token
        return jsonify(result)
    except Exception as exc:
        # Record only the exception class: provider messages may contain input or credentials.
        app.logger.warning("Mad Hacker evaluation failed (%s)", type(exc).__name__)
        return jsonify(error="The analyzer couldn't complete the readings. Press Enter to retry."), 502


@app.post("/api/game/accept")
def accept_game_progress():
    """Commit and log the winning response the browser retained as current."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get('token'), str):
        return jsonify(error="Send a progress token."), 400
    accepted, logged = _accept_game_progress(body['token'])
    if not accepted:
        return jsonify(error="That reading is no longer current."), 409
    return jsonify(accepted=True, solutionLogged=logged)


@app.errorhandler(413)
def oversized_request(error):
    """Keep oversized request failures in the same content-free JSON format."""
    return jsonify(error="Use no more than 20,000 characters."), 413


@app.post("/api/evaluate")
def evaluate():
    """Evaluate one literal input with an authored question batch."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Send a JSON object with demo and text."), 400
    key, text = body.get("demo"), body.get("text")
    if not isinstance(key, str) or key not in DEMOS:
        return jsonify(error="Choose a valid tab."), 400
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Add some text to evaluate."), 400
    if len(text) > 20_000:
        return jsonify(error="Use no more than 20,000 characters."), 400
    if not os.getenv("TYPESAFE_API_KEY"):
        return jsonify(error="Set TYPESAFE_API_KEY on the server, then reload."), 503
    try:
        demo = DEMOS[key]
        GAME_MODULE.record_api_query('lab', key, len(demo["questions"]))
        sample = demo["sampler"].ask(input=text)
        results = [dict(name=q.name, label=demo["labels"].get(q.name, q.question),
                        question=q.question,
                        choice=a.choice, score=a.score, confidence=a.confidence,
                        probabilities=a.probabilities)
                   for q, a in zip(sample.questions, sample.answers)]
        return jsonify(results=results, model=sample.model)
    except Exception:
        # Provider exception messages may contain submitted content or credentials.
        return jsonify(error="Evaluation failed. Try again."), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
