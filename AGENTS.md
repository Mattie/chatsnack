# Agent Guidance

## Project context first

Before making changes, review `README.md` and `PHILOSOPHY.md` for background and project intent.

When in doubt about intended usage and end-user interaction philosophy, review the example notebooks. They provide the best guidance on how the library is meant to be used.

## Notebooks

This project is heavily driven by notebook syntax and usage for convenient developer exploration.

When adding a new feature or making a major change, create a new example notebook or add a cell or two to an existing notebook to demonstrate the change in a nice introductory or exploratory way.

Keep notebook additions aligned with chatsnack's convenient, terse, and readable style. Demonstrate the feature clearly without overexplaining it.

## Testing approach

When working on a bug fix or feature, review `3HTDD.md` and prefer its Three-Horizon TDD approach for planning and tests.

Use TDD, but worry less about forcing every step into a low-level red-green loop. Aim a little higher with top-level Goal tests that prove acceptance criteria and serve as user-facing examples, use Steer tests to bridge toward implementation, and drop to Unit tests only when a tighter loop is helpful.

## Project checklists

When working on a major feature or change, use the relevant checklist in `docs/projects/` to track progress and ensure alignment with the RFC. Check things off, leave short notes, and say what somebody can actually do now. The goal is to keep the implementation work easy to follow (for the team and the follow-on developers) without making anyone dig through the full RFC every time.

## Method intent documentation

For new methods (internal or external), maintain docstrings (or at least comments) that summarize intent beyond what the code alone expresses.

Use existing docstrings and comments as guidance. Clear variable/function names are important, but we also need the what/why behind a method so we can evaluate whether behavior conforms to intent (and whether that intent is what we actually want).

## Datafiles persistence reference

When working with the `datafiles` module for Python, use the following *Datafiles* documentation for reference:

- `docs/reference/datafiles.md`
