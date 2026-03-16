# Agent Guidance

## Project context first

Before making changes, review `README.md` and `PHILOSOPHY.md` for background and project intent.

When in doubt about intended usage and end-user interaction philosophy, review the example notebooks. They provide the best guidance on how the library is meant to be used.

## Method intent documentation

For new methods (internal or external), maintain docstrings (or at least comments) that summarize intent beyond what the code alone expresses.

Use existing docstrings and comments as guidance. Clear variable/function names are important, but we also need the what/why behind a method so we can evaluate whether behavior conforms to intent (and whether that intent is what we actually want).

## Datafiles persistence reference

When working with the `datafiles` module for Python, use the following *Datafiles* documentation for reference:

- `docs/reference/datafiles.md`
