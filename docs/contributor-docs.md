# Contributor Docs

This site keeps the public path small. The repo still contains deeper material for implementation work.

## Docs authoring workflow

Install docs dependencies into a virtual environment:

```bash
python -m pip install -e .
python -m pip install -r docs/requirements.txt
```

Preview locally:

```bash
mkdocs serve
```

Build the site the same way CI does:

```bash
mkdocs build --strict
```

## Authoring rules

- teach the `Chat(...)` path first
- prefer short, copyable examples over provider-shaped setup
- keep notebook-derived content as edited Markdown pages in `docs/`
- keep API reference focused on stable public imports
- add or improve docstrings when a public page would otherwise render thinly

## Repo references

- [Datafiles reference notes](https://github.com/Mattie/chatsnack/blob/master/docs/reference/datafiles.md)
- [Phase 1 runtime adapter RFC](https://github.com/Mattie/chatsnack/blob/master/docs/rfcs/phase-1-runtime-adapter-rfc.md)
- [Phase 3 Responses YAML RFC](https://github.com/Mattie/chatsnack/blob/master/docs/rfcs/phase-3-responses-yaml-rfc.md)
- [Hosted tools and utensils checklist](https://github.com/Mattie/chatsnack/blob/master/docs/projects/phase-4a-hosted-tools-utensils-checklist.md)

## Deployment

The docs workflow in [`.github/workflows/docs.yml`](https://github.com/Mattie/chatsnack/blob/master/.github/workflows/docs.yml) builds on pull requests and deploys to GitHub Pages on pushes to `master`.
