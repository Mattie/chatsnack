# chatsnack · mad hacker

A black-and-green passphrase puzzle built with Flask, plain JavaScript, and one
chatsnack Sampler batch per attempt. The APPARATUS console has hidden signals,
category scales that remember individually discovered labels, and six sequential levels.

From the repository root:

```powershell
poetry install -E flask
```

Set `TYPESAFE_API_KEY` in the server environment or `examples/sampler-web/.env`,
then launch:

```powershell
poetry run python examples/sampler-web/app.py
```

Open <http://127.0.0.1:5050>. Invent a fictional passphrase. Changed text is
queued automatically. The browser starts at most one analysis per second, allows
only one request in flight, and keeps only the newest phrase typed while it waits.
**Analyze** or Enter queues any changed text; keyboard submission plays a short
synthesized reactor chirp, and Shift+Enter adds a line. Each uncached analysis sends
the text to TypeSafe and incurs API usage. After a recoverable failure, **Retry** or
Enter resubmits the same phrase once the request gate opens; failures never retry automatically.
Do not enter real passwords. Without a key, analysis is disabled.

When every target agrees, the accepted request is frozen and both Continue controls
advance to the next circuit. The primary Analyze control changes into Continue so the
next action stays where the player was already working.

Hidden goal names, category labels, and target values are not embedded in the initial
HTML. The server releases each discovery with the reading that earned it. While tuning
levels locally, open <http://127.0.0.1:5050/?debug=1> to expose header controls that
explicitly request every authored goal and unlock direct navigation to every level.

## Phone layout

At widths up to 760px, POCKET keeps compact signal rows above the phrase composer.
Dials and category scales expand automatically when all signal summaries still fit.
When space shrinks, MET instruments compact first. Tap a categorical reading to
keep it expanded or closed until changing levels; manual choices may require scrolling. HELP contains instructions,
Start Over, and debug controls when enabled. Saved answers remain below gameplay.
The desktop apparatus uses the same controls and game state in its original layout.

For an optional browser smoke test against a running local server, with Playwright
available in your Node environment:

```powershell
node --test examples/sampler-web/pocket.browser.test.cjs
```

Set `PLAYWRIGHT_CHANNEL=msedge` to use installed Edge, or use Playwright's installed
Chromium. The test intercepts every analysis request with deterministic responses;
it makes no provider calls. Physical iOS/Android keyboard testing remains a separate
check from browser viewport emulation.

## Levels

Level 01 begins with three targets: a polite request, some self-deprecation,
and a specific object or operation. ACCESS GRANTED unlocks the next circuit:

| Level | Experiment |
| --- | --- |
| 01 | Front Security Desk |
| 02 | Don't Stand Out |
| 03 | Containment Breach |
| 04 | Glitched Terminal |
| 05 | Sentient Door |
| 06 | MASTER BOT |

Completed levels remain selectable. Their winning phrase, readings, and revealed
targets are saved in browser storage so players can review them after returning to
the site. The signed browser session retains the corresponding server progress.
**START OVER** clears both copies. Unfinished attempts still reset when the player
changes levels.

For local launches, the app creates an ignored `.local/session-secret` file so
signed sessions survive process restarts. Set `MAD_HACKER_SECRET_KEY` to use an
explicit deployment secret instead. Game sessions remain valid for 30 days so
browser-restored levels retain their matching server authorization.

`levels.yml` lists the level IDs in progression order. Each ID loads a matching
file such as `levels/level-03.yml`, which owns that level's title, guardian,
Sampler path, meter labels, targets, and reveal settings. Categorical targets use
their readable choice labels instead of numeric positions.

The evaluation language lives separately in `samplers/level-01.yml` through
`samplers/level-06.yml`. Those files contain the shared context, ordered Questions,
criteria descriptions, choice labels, timeout, and retry policy. Restart the app
after editing either file tree. At startup, `game.py` checks that every level
criterion names the corresponding Sampler Question and resolves choice targets
against the authored choice order.

The runtime supplies each Sampler's `title` and `submission` fillings. The shared
context places player text inside `<player_submission>` tags, and each Question
names that tagged text explicitly so the rubric stays focused on the player's words.

Accepted winning phrases are also appended to disk for later review. Each level
has its own JSON Lines file under `examples/sampler-web/.local/solutions/`, such
as `level-03.jsonl`. A row contains the UTC time, level, phrase, model, and
criterion readings. The ignored `.local` directory keeps these player submissions
out of Git.

### Level 02

The SIDE-EYE SCHOLAR wants an all-lowercase phrase with punctuation that supports
its meaning and rhythm. The first instrument targets 75% lowercase confidence.
The second is an analog choice dial with one green target band. Before its first
reading, every label is hidden and the needle searches unpredictably. Each result
reveals only the category where the needle landed. The instrument's name appears
after two different categories have been discovered.

### Level 03

Containment Breach asks for a run-on sentence with technical specificity or
technical jargon, an impossible hazard, and catastrophic urgency. The previous
Incident credibility instrument is no longer part of this circuit.

### Level 04

One submission must satisfy all five targets:

| Reading | Target | Reveal |
| --- | --- | --- |
| Complete sentence | At least 75% | Visible from the start |
| Nerdy | At least 70% | At 30% |
| Somewhat insane | At least 70% | At 30% |
| Temperament | Somewhat Agitated or Angry | Each attained label; full gauge at Angry |
| Computer passphrase | Decently complex | Each attained label; full gauge at Decently complex |

Numeric meters show the Sampler answer's probability of yes, not its confidence.
Categories use the provider's selected choice. Winning always requires every
target in the current level to pass in one current reading.

### Level 06

MASTER BOT asks for one coherent question containing a paradox, creativity, and
a pop-culture reference. Each numeric reading targets 75%, and the final
classification must land on Gentle.

The server creates one reusable Sampler per level. Repeated attempts keep the
matching TypeSafe connection warm, and process shutdown closes those Samplers.
Successful readings are cached in memory by level and trimmed phrase until the
server process restarts. Retyping a cached phrase restores its readings without
another provider evaluation.

Only commands that satisfy every target in their level are added to the page-local access
log. Repeated sentences are allowed. Request pacing happens inside each browser;
the server does not show cooldown errors. Reloading restores completed progress
and the access log, while the process cache remains available to all players until restart.

## Language lab

The seven-tab Sampler example remains at <http://127.0.0.1:5050/lab>.
Writing evaluates 34 named signals. Colors turns 36 yes/no RGB judgments into a
12-stop strip, while Colors HSV compares one hue choice plus saturation and
brightness judgments for each bar. Code, Menu, Reviews, and Decisions provide
smaller batches. The page evaluates automatically after an 800 ms typing pause.
Its local font attribution and licenses are in `static/fonts/`.

`lab.yml` controls tab order. Each file under `lab/` defines one tab's input,
sample text, and optional result-label overrides, while `lab/samplers/` contains
the native chatsnack Sampler YAML evaluated by that tab. Newly added questions
appear automatically and use their full question text when no shorter label is
authored. Restart the example after editing these files.

## Checks

```powershell
poetry run pytest tests/test_sampler_web.py tests/test_mad_hacker.py
node --test examples/sampler-web/*.test.mjs
```

Question rubrics live in `samplers/level-*.yml`; game presentation, win targets,
and reveal settings live in `levels/level-*.yml`. The server returns opaque instrument IDs,
readings, pass/fail verdicts, and only newly earned labels. The browser coordinates
reveal state in `static/game-state.mjs`. Reusable PULSE and BLOOM image-generation prompts are in
`GUARDIAN_ART.md`. The server binds to localhost on port 5050 with debug off.
Permanent hosting, accounts, allowlists, and leaderboards remain outside this example.
Earlier designs remain in Git history.
