from __future__ import annotations

import ast
import builtins
import json
import linecache
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"
INPUT_TAG = "input"
SKIP_TEST_TAG = "skip_test"
ALLOWED_EXECUTION_TAGS = {INPUT_TAG, SKIP_TEST_TAG}
LEGACY_EXECUTION_TAGS = {"test", "live", "manual"}
LIVE_ENV_VALUES = {"1", "true", "yes"}
LIVE_CELL_SKIP_REASON = (
    "Notebook live cells require OPENAI_API_KEY and CHATSNACK_RUN_LIVE_TESTS=1."
)
_SHELL_LINE_RE = re.compile(r"^(?P<indent>\s*)!(?P<command>.*)$")


def live_notebook_cells_enabled() -> bool:
    run_live = os.environ.get("CHATSNACK_RUN_LIVE_TESTS", "").lower() in LIVE_ENV_VALUES
    return bool(os.environ.get("OPENAI_API_KEY")) and run_live


@dataclass(frozen=True)
class NotebookCell:
    notebook_path: Path
    notebook_name: str
    notebook_cell_index: int
    code_cell_ordinal: int
    tags: tuple[str, ...]
    source: str
    original_source: str
    defined_names: frozenset[str] = field(default_factory=frozenset)
    dependency_map: dict[str, int] = field(default_factory=dict)
    parse_error: str | None = None

    @property
    def pytest_id(self) -> str:
        return f"{self.notebook_name}::cell_{self.notebook_cell_index}"

    @property
    def synthetic_filename(self) -> str:
        return f"{self.notebook_path}::cell_{self.notebook_cell_index}"

    @property
    def execution_tags(self) -> tuple[str, ...]:
        known = ALLOWED_EXECUTION_TAGS | LEGACY_EXECUTION_TAGS
        return tuple(tag for tag in self.tags if tag in known)

    @property
    def legacy_execution_tags(self) -> tuple[str, ...]:
        return tuple(tag for tag in self.tags if tag in LEGACY_EXECUTION_TAGS)

    @property
    def skip_for_input(self) -> bool:
        return INPUT_TAG in self.tags

    @property
    def skip_for_test(self) -> bool:
        return SKIP_TEST_TAG in self.tags


@dataclass(frozen=True)
class NotebookDocument:
    path: Path
    cells: tuple[NotebookCell, ...]

    @property
    def name(self) -> str:
        return self.path.name

    def cell_for_index(self, notebook_cell_index: int) -> NotebookCell:
        for cell in self.cells:
            if cell.notebook_cell_index == notebook_cell_index:
                return cell
        raise KeyError(f"{self.path.name} has no code cell {notebook_cell_index}")

    def prior_defining_cell(self, name: str, before_index: int) -> NotebookCell | None:
        for cell in reversed(self.cells):
            if cell.notebook_cell_index >= before_index:
                continue
            if name in cell.defined_names:
                return cell
        return None


@dataclass(frozen=True)
class CellExecutionRecord:
    status: str
    reason: str | None = None


class _TopLevelNameAnalyzer(ast.NodeVisitor):
    def __init__(self) -> None:
        self.defined_names: set[str] = set()
        self.loaded_names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defined_names.add(node.name)
        self._visit_function_signature(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.defined_names.add(node.name)
        self._visit_function_signature(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined_names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arguments(node.args)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.defined_names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.defined_names.add(alias.asname or alias.name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.defined_names.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self.loaded_names.add(node.id)

    def _visit_function_signature(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arguments(node.args)
        if node.returns is not None:
            self.visit(node.returns)

    def _visit_arguments(self, args: ast.arguments) -> None:
        for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if args.vararg and args.vararg.annotation is not None:
            self.visit(args.vararg.annotation)
        if args.kwarg and args.kwarg.annotation is not None:
            self.visit(args.kwarg.annotation)
        for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            self.visit(default)


def _analyze_cell_source(source: str) -> tuple[frozenset[str], set[str], str | None]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return frozenset(), set(), exc.msg

    analyzer = _TopLevelNameAnalyzer()
    analyzer.visit(tree)
    return frozenset(analyzer.defined_names), set(analyzer.loaded_names), None


@lru_cache(maxsize=1)
def load_notebook_documents() -> tuple[NotebookDocument, ...]:
    documents: list[NotebookDocument] = []
    for path in sorted(NOTEBOOKS_DIR.glob("*.ipynb")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cells: list[NotebookCell] = []
        prior_name_sources: dict[str, int] = {}
        code_cell_ordinal = 0
        for notebook_cell_index, raw_cell in enumerate(data.get("cells", []), start=1):
            if raw_cell.get("cell_type") != "code":
                continue
            code_cell_ordinal += 1
            metadata = raw_cell.get("metadata", {})
            tags = tuple(metadata.get("tags", []))
            original_source = "".join(raw_cell.get("source", []))
            source = _transform_notebook_source(original_source)
            defined_names, loaded_names, parse_error = _analyze_cell_source(source)
            dependency_map = {
                name: prior_name_sources[name]
                for name in loaded_names
                if name in prior_name_sources
            }
            cell = NotebookCell(
                notebook_path=path,
                notebook_name=path.name,
                notebook_cell_index=notebook_cell_index,
                code_cell_ordinal=code_cell_ordinal,
                tags=tags,
                source=source,
                original_source=original_source,
                defined_names=defined_names,
                dependency_map=dependency_map,
                parse_error=parse_error,
            )
            cells.append(cell)
            for name in defined_names:
                prior_name_sources[name] = notebook_cell_index
        documents.append(NotebookDocument(path=path, cells=tuple(cells)))
    return tuple(documents)


def iter_notebook_cells() -> tuple[NotebookCell, ...]:
    cells: list[NotebookCell] = []
    for document in load_notebook_documents():
        cells.extend(document.cells)
    return tuple(cells)


def notebook_test_params() -> list[pytest.ParameterSet]:
    params: list[pytest.ParameterSet] = []
    for cell in iter_notebook_cells():
        marks = []
        if not cell.skip_for_input and not cell.skip_for_test:
            marks.append(pytest.mark.notebooks_live)
        params.append(pytest.param(cell, id=cell.pytest_id, marks=marks))
    return params


class NotebookRunner:
    def __init__(self, notebook: NotebookDocument, workspace_root: Path) -> None:
        self.notebook = notebook
        workspace_root.mkdir(parents=True, exist_ok=True)
        self.workdir = _make_unique_directory(workspace_root, _slugify(notebook.path.stem))
        self.globals = {
            "__builtins__": builtins.__dict__,
            "__name__": "__notebook__",
            "__package__": None,
            "__file__": str(notebook.path),
            "__notebook_shell__": self._run_shell_cell,
        }
        self.execution_ledger: dict[int, CellExecutionRecord] = {}
        self._ensure_repo_root_on_path()
        self._seed_notebook_assets()

    def ensure_cell(self, notebook_cell_index: int) -> None:
        __tracebackhide__ = True
        target_cell = self.notebook.cell_for_index(notebook_cell_index)
        target_record = self.execution_ledger.get(notebook_cell_index)
        if target_record is not None:
            self._finalize_target(target_cell, target_record)
            return

        for cell in self.notebook.cells:
            if cell.notebook_cell_index > notebook_cell_index:
                break
            if cell.notebook_cell_index in self.execution_ledger:
                continue

            blocking_reason = self._blocking_reason(cell)
            if blocking_reason is not None:
                self.execution_ledger[cell.notebook_cell_index] = CellExecutionRecord(
                    status="skipped",
                    reason=blocking_reason,
                )
                continue

            try:
                self._execute_cell(cell)
            except pytest.skip.Exception as exc:
                self.execution_ledger[cell.notebook_cell_index] = CellExecutionRecord(
                    status="skipped",
                    reason=str(exc),
                )
                continue
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                self.execution_ledger[cell.notebook_cell_index] = CellExecutionRecord(
                    status="failed",
                    reason=reason,
                )
                if cell.notebook_cell_index == notebook_cell_index:
                    raise

        target_record = self.execution_ledger[notebook_cell_index]
        self._finalize_target(target_cell, target_record)

    def _ensure_repo_root_on_path(self) -> None:
        repo_root = str(REPO_ROOT)
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)

    def _seed_notebook_assets(self) -> None:
        notebook_dir = self.notebook.path.parent
        for sibling in notebook_dir.iterdir():
            if sibling == self.notebook.path:
                continue
            destination = self.workdir / sibling.name
            if sibling.is_dir():
                shutil.copytree(sibling, destination, dirs_exist_ok=True)
            elif sibling.is_file() and sibling.suffix != ".ipynb":
                shutil.copy2(sibling, destination)

    def _run_shell_cell(self, command: str) -> None:
        __tracebackhide__ = True
        env = os.environ.copy()
        temp_dir = self.workdir / ".tmp-shell"
        temp_dir.mkdir(parents=True, exist_ok=True)
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        env["PIP_BUILD_TRACKER"] = str(temp_dir / "pip-build-tracker")
        env["PIP_CACHE_DIR"] = str(temp_dir / "pip-cache")

        parsed = shlex.split(command, posix=False)
        if len(parsed) >= 3 and parsed[0].lower() == "pip" and parsed[1].lower() == "install":
            requested = [part for part in parsed[2:] if not part.startswith("-")]
            if requested == ["chatsnack"]:
                self._run_subprocess(
                    [sys.executable, "-c", "import chatsnack"],
                    cwd=self.workdir,
                    env=env,
                )
                return

            target_dir = self.workdir / ".notebook-site-packages"
            target_dir.mkdir(parents=True, exist_ok=True)
            env["PYTHONPATH"] = str(target_dir) + os.pathsep + env.get("PYTHONPATH", "")
            self._run_subprocess(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-cache-dir",
                    "--target",
                    str(target_dir),
                    *parsed[2:],
                ],
                cwd=self.workdir,
                env=env,
            )
            target_dir_str = str(target_dir)
            if target_dir_str not in sys.path:
                sys.path.insert(0, target_dir_str)
            return

        self._run_subprocess(command, cwd=self.workdir, env=env, shell=True)

    def _execute_cell(self, cell: NotebookCell) -> None:
        __tracebackhide__ = True
        _register_cell_source_in_linecache(cell)
        code = compile(cell.source, cell.synthetic_filename, "exec")
        self.globals["__file__"] = cell.synthetic_filename
        with _temporary_cwd(self.workdir):
            try:
                exec(code, self.globals, self.globals)
            except NameError as exc:
                missing_name = _missing_name_from_error(exc)
                if missing_name:
                    blocking_reason = self._missing_name_blocking_reason(
                        missing_name,
                        cell,
                    )
                    if blocking_reason is not None:
                        raise pytest.skip.Exception(blocking_reason)
                _add_notebook_cell_exception_note(exc, cell, self.workdir)
                raise
            except BaseException as exc:
                if isinstance(exc, pytest.skip.Exception):
                    raise
                _add_notebook_cell_exception_note(exc, cell, self.workdir)
                raise
        self.execution_ledger[cell.notebook_cell_index] = CellExecutionRecord(status="completed")

    def _run_subprocess(
        self,
        command: str | list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        shell: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        __tracebackhide__ = True
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            shell=shell,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return result

        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)

        exc = subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
        _add_shell_command_exception_note(exc, command=result.args, cwd=cwd)
        raise exc

    def _blocking_reason(self, cell: NotebookCell) -> str | None:
        failed_prerequisite = self._first_prior_status(cell, "failed")
        if failed_prerequisite is not None:
            return (
                f"Blocked by failing prerequisite cell "
                f"{failed_prerequisite.notebook_cell_index}: "
                f"{self.execution_ledger[failed_prerequisite.notebook_cell_index].reason}"
            )

        if cell.skip_for_test:
            return "Notebook cell is tagged skip_test."

        if cell.skip_for_input:
            return "Notebook cell is tagged input."

        if not live_notebook_cells_enabled():
            return LIVE_CELL_SKIP_REASON

        for name, dependency_cell_index in cell.dependency_map.items():
            dependency_record = self.execution_ledger.get(dependency_cell_index)
            if dependency_record is None or dependency_record.status == "completed":
                continue
            dependency_cell = self.notebook.cell_for_index(dependency_cell_index)
            return (
                f"Blocked by prerequisite cell {dependency_cell.notebook_cell_index} "
                f"for '{name}': {dependency_record.reason}"
            )
        return None

    def _finalize_target(self, cell: NotebookCell, record: CellExecutionRecord) -> None:
        if record.status == "completed":
            return
        if record.status == "skipped":
            raise pytest.skip.Exception(record.reason or "Notebook cell skipped.")
        raise RuntimeError(
            f"{cell.pytest_id} previously failed during replay: {record.reason}"
        )

    def _first_prior_status(
        self,
        cell: NotebookCell,
        status: str,
    ) -> NotebookCell | None:
        for prior_cell in self.notebook.cells:
            if prior_cell.notebook_cell_index >= cell.notebook_cell_index:
                break
            prior = self.execution_ledger.get(
                prior_cell.notebook_cell_index,
                CellExecutionRecord("pending"),
            )
            if prior.status == status:
                return prior_cell
        return None

    def _missing_name_blocking_reason(self, missing_name: str, cell: NotebookCell) -> str | None:
        dependency_cell = self.notebook.prior_defining_cell(
            missing_name,
            before_index=cell.notebook_cell_index,
        )
        if dependency_cell is None:
            return None
        dependency_record = self.execution_ledger.get(dependency_cell.notebook_cell_index)
        if dependency_record is None or dependency_record.status == "completed":
            return None
        return (
            f"Blocked by prerequisite cell {dependency_cell.notebook_cell_index} "
            f"for '{missing_name}': {dependency_record.reason}"
        )


def _transform_notebook_source(source: str) -> str:
    transformed_lines: list[str] = []
    for line in source.splitlines(keepends=True):
        match = _SHELL_LINE_RE.match(line)
        if match is None:
            transformed_lines.append(line)
            continue
        indent = match.group("indent")
        command = match.group("command").rstrip("\r\n")
        newline = "\n" if line.endswith("\n") else ""
        transformed_lines.append(f"{indent}__notebook_shell__({command!r}){newline}")
    return "".join(transformed_lines)


@contextmanager
def _temporary_cwd(path: Path):
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _missing_name_from_error(exc: NameError) -> str | None:
    match = re.search(r"name '([^']+)' is not defined", str(exc))
    if match:
        return match.group(1)
    return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return f"notebook-{slug or 'run'}-"


def _make_unique_directory(parent: Path, prefix: str) -> Path:
    for _ in range(20):
        candidate = parent / f"{prefix}{uuid.uuid4().hex[:8]}"
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"Could not create a unique directory under {parent}")


def _register_cell_source_in_linecache(cell: NotebookCell) -> None:
    linecache.cache[cell.synthetic_filename] = (
        len(cell.original_source),
        None,
        cell.original_source.splitlines(keepends=True),
        cell.synthetic_filename,
    )


def _add_notebook_cell_exception_note(
    exc: BaseException,
    cell: NotebookCell,
    workdir: Path,
) -> None:
    note = (
        "Notebook cell context:\n"
        f"notebook: {cell.notebook_name}\n"
        f"cell: {cell.notebook_cell_index}\n"
        f"workdir: {workdir}\n"
        "cell source:\n"
        f"{cell.original_source.rstrip()}"
    )
    _add_exception_note_once(exc, note)


def _add_shell_command_exception_note(
    exc: BaseException,
    *,
    command: str | list[str],
    cwd: Path,
) -> None:
    note = (
        "Notebook shell command failed:\n"
        f"command: {_format_command_for_note(command)}\n"
        f"exit code: {getattr(exc, 'returncode', 'unknown')}\n"
        f"cwd: {cwd}"
    )
    _add_exception_note_once(exc, note)


def _add_exception_note_once(exc: BaseException, note: str) -> None:
    notes = getattr(exc, "__notes__", ())
    if note in notes:
        return
    exc.add_note(note)


def _format_command_for_note(command: str | list[str]) -> str:
    if isinstance(command, str):
        return command
    return subprocess.list2cmdline([str(part) for part in command])
