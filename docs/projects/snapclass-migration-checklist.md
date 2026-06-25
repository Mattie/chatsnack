# Snapclass Migration Checklist

- [x] Add `snapclass` dependency and remove live `datafiles` imports.
- [x] Move `CHATSNACK_BASE_DIR` handling behind a `Stash`.
- [x] Convert `Text`, `Chat`, and nested persistence value classes to `snapclass`.
- [x] Preserve `.save()`, `.load()`, `.yaml`, `.objects`, and `.datafile` compatibility.
- [x] Port TXT and chatsnack YAML formatting to model-local snapclass formatters.
- [x] Verify focused persistence, compact tools, and Phase 3 YAML coverage.
- [x] Verify broad local and live-model coverage for the migration boundary.
- [ ] Verify the full test suite.
- [x] Regenerate `poetry.lock` against the PyPI `snapclass` dependency.
- [x] Remove the inactive datafiles path-mount hack from live code.

Notes:

- Deterministic migration/YAML coverage passed against PyPI `snapclass==0.1.2`: `tests/test_file_snack_fillings.py`, `tests/test_chatsnack_yaml_peeves.py`, `tests/test_compact_tools_yaml.py`, `tests/test_phase3_yaml.py`, and `tests/test_snapclass_persistence_compat.py` with the three live OpenAI filling tests deselected.
- New snapclass compatibility tests passed against PyPI `snapclass==0.1.2`.
- Runtime and Responses-family regression tests passed, including the tool-followup request handling added during the port.
- Live model coverage passed after the Responses-family tool-followup fix: `172 passed, 1 skipped` across live-relevant Python tests and `43 passed, 2 skipped` across notebook examples.
- Full-suite verification remains open only because a single monolithic `pytest -q` run has not been repeated after the targeted local and live suites.
