# Notebook Test Coverage

Notebook code cells run under `pytest` directly from the `.ipynb` files in `notebooks/`.

## Cell Handling

Every code cell is collected as a pytest case.

- Cells tagged `skip_test` are collected and skipped in every notebook test run.
- The interactive loop keeps `input` metadata and also carries `skip_test`, so it stays descriptive in the notebook and skipped in pytest.
- Every remaining code cell is treated as a live notebook test.
- Non-`skip_test` cells execute in order inside a shared per-notebook namespace when `OPENAI_API_KEY` is set and `CHATSNACK_RUN_LIVE_TESTS=1`.

## Commands

Run the notebook-derived suite:

```bash
pytest tests/test_notebook_metadata.py tests/test_notebooks.py -q
```

Run the live notebook cells:

```bash
CHATSNACK_RUN_LIVE_TESTS=1 pytest tests/test_notebooks.py -q -m notebooks_live
```

Run one notebook cell directly:

```bash
pytest tests/test_notebooks.py -q -k "GettingStartedWithChatsnack and cell_53"
```
