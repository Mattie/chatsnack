"""A copyable local workspace for Chatsnack's native Apply Patch utensil.

``LocalWorkspace`` applies UTF-8 text patches beneath one directory. It gives
the Utensils guide a working executor while leaving approval, evidence, and
recovery policy with the application.

Usage::

    from chatsnack import Chat, utensil
    from examples.apply_patch_workspace import LocalWorkspace

    workspace = LocalWorkspace("my-project")
    editor = Chat(
        "Edit only files inside the project.",
        utensils=[utensil.apply_patch(execute=workspace.apply_patch)],
    )
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

from chatsnack import ApplyPatchCall


_END_FILE = "*** End of File"
_DIFF_TERMINATORS = (
    "*** End Patch",
    "*** Update File:",
    "*** Delete File:",
    "*** Add File:",
)
class _PatchFailure(ValueError):
    """A model-safe failure that can be returned without leaking local details."""


@dataclass(frozen=True)
class _Edit:
    start: int
    remove: tuple[str, ...]
    insert: tuple[str, ...]


@dataclass(frozen=True)
class _RelativeEdit:
    start: int
    remove: tuple[str, ...]
    insert: tuple[str, ...]


@dataclass(frozen=True)
class _Section:
    context: tuple[str, ...]
    edits: tuple[_RelativeEdit, ...]
    next_index: int
    end_of_file: bool


def _diff_lines(diff: str) -> list[str]:
    """Split a V4A diff without turning its final newline into a patch line."""
    lines = diff.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _newline_for(original: str, diff: str, mode: Literal["update", "create"]) -> str:
    """Preserve the file's newline convention, or use the create diff's style."""
    source = original if mode == "update" and "\n" in original else diff
    return "\r\n" if "\r\n" in source else "\n"


def _finish_relative_edit(
    edits: list[_RelativeEdit],
    start: int | None,
    removed: list[str],
    inserted: list[str],
) -> None:
    if start is None:
        return
    edits.append(_RelativeEdit(start, tuple(removed), tuple(inserted)))


def _read_section(lines: Sequence[str], start: int) -> _Section:
    """Read one hunk body and retain the source context used to locate it."""
    context: list[str] = []
    edits: list[_RelativeEdit] = []
    removed: list[str] = []
    inserted: list[str] = []
    edit_start: int | None = None
    index = start

    while index < len(lines):
        raw = lines[index]
        if raw.startswith("@@") or raw == _END_FILE:
            break
        if any(raw.startswith(marker) for marker in _DIFF_TERMINATORS):
            break
        if raw.startswith("***"):
            raise _PatchFailure("The patch contains an unsupported V4A marker.")

        index += 1
        line = raw if raw else " "
        prefix, content = line[0], line[1:]
        if prefix == " ":
            _finish_relative_edit(edits, edit_start, removed, inserted)
            removed = []
            inserted = []
            edit_start = None
            context.append(content)
        elif prefix == "-":
            if edit_start is None:
                edit_start = len(context)
            removed.append(content)
            context.append(content)
        elif prefix == "+":
            if edit_start is None:
                edit_start = len(context)
            inserted.append(content)
        else:
            raise _PatchFailure("Every V4A hunk line must start with space, +, or -.")

    _finish_relative_edit(edits, edit_start, removed, inserted)
    if index == start:
        raise _PatchFailure("A V4A hunk has no patch lines.")

    end_of_file = index < len(lines) and lines[index] == _END_FILE
    return _Section(tuple(context), tuple(edits), index + end_of_file, end_of_file)


def _mapped_slice_matches(
    source: Sequence[str],
    expected: Sequence[str],
    start: int,
    transform,
) -> bool:
    if start + len(expected) > len(source):
        return False
    return all(
        transform(source[start + offset]) == transform(value)
        for offset, value in enumerate(expected)
    )


def _find_context(
    source: Sequence[str],
    expected: Sequence[str],
    start: int,
) -> int | None:
    """Find context with the exact, trailing-space, then stripped V4A fallbacks."""
    if not expected:
        return start

    stop = len(source) - len(expected) + 1
    for transform in (lambda value: value, str.rstrip, str.strip):
        for index in range(start, max(start, stop)):
            if _mapped_slice_matches(source, expected, index, transform):
                return index
    return None


def _line_matches(candidate: str, anchor: str, *, stripped: bool) -> bool:
    if stripped:
        return candidate.strip() == anchor.strip()
    return candidate == anchor


def _advance_to_anchor(
    source: Sequence[str],
    anchor: str,
    cursor: int,
    *,
    allow_prior: bool,
    required: bool,
) -> int:
    """Narrow a hunk to its named block while permitting a reused parent anchor."""
    for stripped in (False, True):
        if allow_prior and any(
            _line_matches(line, anchor, stripped=stripped) for line in source[:cursor]
        ):
            return cursor
        for index in range(cursor, len(source)):
            if _line_matches(source[index], anchor, stripped=stripped):
                return index + 1

    if required:
        raise _PatchFailure(f"The V4A anchor did not match: {anchor}")
    return cursor


def _parse_update(source: list[str], lines: list[str]) -> list[_Edit]:
    """Turn V4A hunks into ordered edits against normalized source lines."""
    edits: list[_Edit] = []
    cursor = 0
    index = 0

    while index < len(lines):
        if any(lines[index].startswith(marker) for marker in _DIFF_TERMINATORS):
            break

        anchors: list[str] = []
        header_count = 0
        while index < len(lines) and (
            lines[index] == "@@" or lines[index].startswith("@@ ")
        ):
            header = lines[index]
            if header == "@@":
                anchor = ""
            else:
                anchor = header[3:]
            header_count += 1
            if anchor.strip():
                anchors.append(anchor)
            index += 1

        if header_count == 0 and cursor != 0:
            raise _PatchFailure("Each V4A update hunk after the first needs an @@ header.")

        for anchor_index, anchor in enumerate(anchors):
            cursor = _advance_to_anchor(
                source,
                anchor,
                cursor,
                allow_prior=anchor_index == 0,
                required=header_count > 1,
            )

        section = _read_section(lines, index)
        context_start: int | None
        if section.end_of_file:
            eof_start = max(0, len(source) - len(section.context))
            context_start = _find_context(source, section.context, eof_start)
            if context_start is None:
                context_start = _find_context(source, section.context, cursor)
        else:
            context_start = _find_context(source, section.context, cursor)

        if context_start is None:
            raise _PatchFailure("The V4A patch context did not match the file.")

        edits.extend(
            _Edit(
                start=context_start + edit.start,
                remove=edit.remove,
                insert=edit.insert,
            )
            for edit in section.edits
        )
        cursor = context_start + len(section.context)
        index = section.next_index

    return edits


def _apply_edits(source: list[str], edits: Sequence[_Edit]) -> list[str]:
    """Apply ordered, non-overlapping edits after the complete diff has parsed."""
    output: list[str] = []
    cursor = 0
    for edit in edits:
        if edit.start < cursor:
            raise _PatchFailure("The V4A patch contains overlapping hunks.")
        if edit.start + len(edit.remove) > len(source):
            raise _PatchFailure("The V4A patch removes lines beyond the file.")
        output.extend(source[cursor : edit.start])
        output.extend(edit.insert)
        cursor = edit.start + len(edit.remove)
    output.extend(source[cursor:])
    return output


def _apply_v4a_diff(
    original: str,
    diff: str,
    *,
    mode: Literal["update", "create"] = "update",
) -> str:
    """Apply the operation-level V4A format emitted by the native tool."""
    newline = _newline_for(original, diff, mode)
    lines = _diff_lines(diff)

    if mode == "create":
        content: list[str] = []
        for line in lines:
            if any(line.startswith(marker) for marker in _DIFF_TERMINATORS):
                break
            if not line.startswith("+"):
                raise _PatchFailure("Every create_file diff line must start with +.")
            content.append(line[1:])
        return newline.join(content)

    normalized = original.replace("\r\n", "\n")
    source = normalized.split("\n")
    edits = _parse_update(source, lines)
    return newline.join(_apply_edits(source, edits))


class LocalWorkspace:
    """Apply native patch calls to UTF-8 text files below one existing root.

    Passing this executor to a Chat grants write access throughout ``root``.
    The example rejects path escapes and symlinks. Applications that need
    approval, audit evidence, or crash recovery should add those policies
    around ``apply_patch``.
    """

    def __init__(self, root: str | os.PathLike[str]):
        candidate = Path(root).resolve(strict=True)
        if not candidate.is_dir():
            raise ValueError("LocalWorkspace root must be an existing directory.")
        self.root = candidate

    def apply_patch(self, call: ApplyPatchCall) -> dict[str, str]:
        """Apply one completed native operation and return its model-facing result."""
        operation = call.operation
        if not isinstance(operation, Mapping):
            return self._failed("Apply Patch returned an invalid operation.")

        operation_type = operation.get("type")
        raw_path = operation.get("path")
        display = raw_path if isinstance(raw_path, str) and raw_path else "the requested file"

        try:
            if operation_type not in {"create_file", "update_file", "delete_file"}:
                raise _PatchFailure("Apply Patch returned an unsupported operation type.")
            target, display = self._target(raw_path)

            if operation_type == "create_file":
                self._create(target, display, self._required_diff(operation))
                return self._completed(f"Created {display}.")
            if operation_type == "update_file":
                self._update(target, display, self._required_diff(operation))
                return self._completed(f"Updated {display}.")

            self._delete(target, display)
            return self._completed(f"Deleted {display}.")
        except _PatchFailure as exc:
            return self._failed(str(exc))
        except UnicodeError:
            return self._failed(f"Could not read {display} as UTF-8 text.")
        except OSError as exc:
            action = str(operation_type).removesuffix("_file").replace("_", " ")
            return self._failed(
                f"Could not {action or 'change'} {display}: {type(exc).__name__}."
            )

    @staticmethod
    def _completed(output: str) -> dict[str, str]:
        return {"status": "completed", "output": output}

    @staticmethod
    def _failed(output: str) -> dict[str, str]:
        return {"status": "failed", "output": output}

    @staticmethod
    def _required_diff(operation: Mapping[str, object]) -> str:
        diff = operation.get("diff")
        if not isinstance(diff, str):
            raise _PatchFailure("This Apply Patch operation needs a text diff.")
        return diff

    def _target(self, raw_path: object) -> tuple[Path, str]:
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            raise _PatchFailure("Apply Patch returned an invalid file path.")

        posix = PurePosixPath(raw_path)
        windows = PureWindowsPath(raw_path)
        if posix.is_absolute() or windows.is_absolute() or windows.drive:
            raise _PatchFailure("Apply Patch paths must be relative to the workspace.")
        if ".." in posix.parts or ".." in windows.parts:
            raise _PatchFailure("Apply Patch paths cannot leave the workspace.")
        for part in windows.parts:
            if part in {"", "."}:
                continue
            if (
                part != part.rstrip(" .")
                or ":" in part
                or PureWindowsPath(part).is_reserved()
                or any(character in '<>"|?*' or ord(character) < 32 for character in part)
            ):
                raise _PatchFailure("Apply Patch returned an unsafe file path.")

        relative = Path(raw_path)
        current = self.root
        for part in relative.parts:
            if part in {"", "."}:
                continue
            current = current / part
            if current.is_symlink():
                raise _PatchFailure("The local workspace example does not follow symlinks.")

        target = (self.root / relative).resolve(strict=False)
        try:
            display_path = target.relative_to(self.root)
        except ValueError:
            raise _PatchFailure("Apply Patch paths cannot leave the workspace.") from None
        if display_path == Path("."):
            raise _PatchFailure("Apply Patch needs a file path below the workspace root.")
        return target, display_path.as_posix()

    @staticmethod
    def _read_text(target: Path) -> str:
        with target.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()

    @staticmethod
    def _write_new(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with target.open("x", encoding="utf-8", newline="") as handle:
                created = True
                handle.write(content)
        except BaseException:
            if created:
                target.unlink(missing_ok=True)
            raise

    @staticmethod
    def _replace_text(target: Path, content: str) -> None:
        source_mode = stat.S_IMODE(target.stat().st_mode)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
            os.chmod(temporary, source_mode)
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _create(self, target: Path, display: str, diff: str) -> None:
        if target.exists():
            raise _PatchFailure(f"Cannot create {display}: the path already exists.")
        content = _apply_v4a_diff("", diff, mode="create")
        self._write_new(target, content)

    def _update(self, target: Path, display: str, diff: str) -> None:
        if not target.exists():
            raise _PatchFailure(f"Cannot update {display}: the file does not exist.")
        if not target.is_file():
            raise _PatchFailure(f"Cannot update {display}: the path is not a file.")
        original = self._read_text(target)
        updated = _apply_v4a_diff(original, diff)
        self._replace_text(target, updated)

    @staticmethod
    def _delete(target: Path, display: str) -> None:
        if not target.exists():
            raise _PatchFailure(f"Cannot delete {display}: the file does not exist.")
        if not target.is_file():
            raise _PatchFailure(f"Cannot delete {display}: the path is not a file.")
        target.unlink()


__all__ = ["LocalWorkspace"]
