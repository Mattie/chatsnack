from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from tests.notebook_support import (
    NotebookCell,
    NotebookDocument,
    NotebookRunner,
    REPO_ROOT,
    _transform_notebook_source,
)


def _build_runner(
    test_root: Path,
    *,
    original_source: str,
    transformed_source: str | None = None,
) -> NotebookRunner:
    notebook_dir = test_root / "notebook-fixture"
    notebook_dir.mkdir()
    notebook_path = notebook_dir / "TracebackNotebook.ipynb"
    notebook_path.write_text("{}", encoding="utf-8")
    cell = NotebookCell(
        notebook_path=notebook_path,
        notebook_name=notebook_path.name,
        notebook_cell_index=1,
        code_cell_ordinal=1,
        tags=(),
        source=transformed_source or original_source,
        original_source=original_source,
    )
    document = NotebookDocument(path=notebook_path, cells=(cell,))
    return NotebookRunner(document, test_root / "workspace")


@contextmanager
def _repo_local_test_root():
    test_root = REPO_ROOT / ".tmp" / f"notebook-traceback-{uuid.uuid4().hex[:8]}"
    test_root.mkdir(parents=True, exist_ok=False)
    try:
        yield test_root
    finally:
        shutil.rmtree(test_root, ignore_errors=True)


def test_python_cell_failure_reports_notebook_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "traceback-test-key")
    monkeypatch.setenv("CHATSNACK_RUN_LIVE_TESTS", "1")
    source = "value = 1\nraise RuntimeError('boom')\n"
    with _repo_local_test_root() as test_root:
        runner = _build_runner(test_root, original_source=source)
        with pytest.raises(RuntimeError) as excinfo:
            runner.ensure_cell(1)

    output = str(excinfo.getrepr(style="long"))
    assert "TracebackNotebook.ipynb::cell_1" in output
    assert "raise RuntimeError('boom')" in output
    assert "Notebook cell context:" in output
    assert "workdir:" in output
    assert "???" not in output


def test_shell_cell_failure_reports_command_output_and_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "traceback-test-key")
    monkeypatch.setenv("CHATSNACK_RUN_LIVE_TESTS", "1")
    original_source = (
        f'!"{sys.executable}" -c "import sys; '
        "print('shell-stdout'); "
        "print('shell-stderr', file=sys.stderr); "
        'raise SystemExit(7)"\n'
    )
    with _repo_local_test_root() as test_root:
        runner = _build_runner(
            test_root,
            original_source=original_source,
            transformed_source=_transform_notebook_source(original_source),
        )
        with pytest.raises(subprocess.CalledProcessError) as excinfo:
            runner.ensure_cell(1)

    captured = capsys.readouterr()
    output = str(excinfo.getrepr(style="long"))
    assert "TracebackNotebook.ipynb::cell_1" in output
    assert 'raise SystemExit(7)"' in output
    assert "Notebook shell command failed:" in output
    assert "exit code: 7" in output
    assert "cwd:" in output
    assert "???" not in output
    assert "shell-stdout" in captured.out
    assert "shell-stderr" in captured.err
