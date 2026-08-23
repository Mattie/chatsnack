"""Goal and focused contracts for the local Apply Patch workspace example.

Goal set:
- G1: a real workspace update runs through the native Responses loop.
- G2: create and delete operations make the requested filesystem changes.
- G3: paths outside the selected workspace fail without filesystem changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from chatsnack import ApplyPatchCall, Chat, utensil
from chatsnack.runtime import ResponsesAdapter
from chatsnack.runtime.types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    NormalizedToolCall,
)
from examples.apply_patch_workspace import LocalWorkspace, _apply_v4a_diff


def _patch_completion(operation: dict[str, str]) -> NormalizedCompletionResult:
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(
            tool_calls=[
                NormalizedToolCall(
                    id="call_patch_example",
                    item_id="apc_example",
                    type="apply_patch",
                    status="completed",
                    payload={"operation": operation},
                )
            ]
        ),
        finish_reason="completed",
        metadata={"response_id": "resp_patch_example"},
    )


def _final_completion() -> NormalizedCompletionResult:
    return NormalizedCompletionResult(
        message=NormalizedAssistantMessage(content="The snack file is fresh."),
        finish_reason="completed",
        metadata={"response_id": "resp_patch_done"},
    )


def _call(operation: dict[str, object]) -> ApplyPatchCall:
    return ApplyPatchCall(
        item_id="apc_example",
        call_id="call_patch_example",
        status="completed",
        operation=operation,
    )


def test_steer_workspace_root_must_be_an_existing_directory(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        LocalWorkspace(tmp_path / "missing")

    file_root = tmp_path / "file.txt"
    file_root.write_text("snack\n", encoding="utf-8")
    with pytest.raises(ValueError, match="existing directory"):
        LocalWorkspace(file_root)


def test_steer_malformed_operation_returns_a_safe_failure(tmp_path: Path):
    call = ApplyPatchCall(
        item_id="apc_example",
        call_id="call_patch_example",
        status="completed",
        operation=None,  # type: ignore[arg-type]
    )

    assert LocalWorkspace(tmp_path).apply_patch(call) == {
        "status": "failed",
        "output": "Apply Patch returned an invalid operation.",
    }


@pytest.mark.asyncio
async def test_goal_local_workspace_applies_v4a_update_through_chat(
    monkeypatch,
    tmp_path: Path,
):
    target = tmp_path / "snack.txt"
    target.write_text("kettle corn\nstale\n", encoding="utf-8")
    workspace = LocalWorkspace(tmp_path)
    chat = Chat(
        "Keep the snack file fresh.",
        utensils=[utensil.apply_patch(execute=workspace.apply_patch)],
    )
    completions: Iterator[NormalizedCompletionResult] = iter(
        [
            _patch_completion(
                {
                    "type": "update_file",
                    "path": "snack.txt",
                    "diff": "@@ kettle corn\n-stale\n+fresh",
                }
            ),
            _final_completion(),
        ]
    )

    async def create_completion_a(adapter, messages, **kwargs):
        return next(completions)

    monkeypatch.setattr(ResponsesAdapter, "create_completion_a", create_completion_a)
    chat.runtime = ResponsesAdapter(chat.ai)

    continued = await chat.chat_a("Replace stale with fresh.")
    try:
        assert target.read_text(encoding="utf-8") == "kettle corn\nfresh\n"
        assert continued.last == "The snack file is fresh."
    finally:
        continued.close_session()
        chat.close_session()


def test_goal_local_workspace_creates_and_deletes_real_files(tmp_path: Path):
    workspace = LocalWorkspace(tmp_path)

    created = workspace.apply_patch(
        _call(
            {
                "type": "create_file",
                "path": "menus/movie-night.txt",
                "diff": "+popcorn\n+pretzels\n+",
            }
        )
    )

    target = tmp_path / "menus" / "movie-night.txt"
    assert created["status"] == "completed"
    assert target.read_text(encoding="utf-8") == "popcorn\npretzels\n"

    deleted = workspace.apply_patch(
        _call({"type": "delete_file", "path": "menus/movie-night.txt"})
    )

    assert deleted["status"] == "completed"
    assert not target.exists()


def test_goal_local_workspace_rejects_escape_without_touching_sibling(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me\n", encoding="utf-8")
    workspace = LocalWorkspace(workspace_root)

    result = workspace.apply_patch(
        _call(
            {
                "type": "update_file",
                "path": "../outside.txt",
                "diff": "@@\n-keep me\n+changed",
            }
        )
    )

    assert result["status"] == "failed"
    assert "leave the workspace" in result["output"]
    assert outside.read_text(encoding="utf-8") == "keep me\n"


@pytest.mark.parametrize(
    "path",
    [
        r"..\outside.txt",
        "snack.txt:alternate-stream",
        "NUL.txt",
        "CONIN$",
        "COM¹.txt",
        "snack.txt.",
    ],
)
def test_steer_windows_path_aliases_fail_portably(tmp_path: Path, path: str):
    result = LocalWorkspace(tmp_path).apply_patch(
        _call({"type": "create_file", "path": path, "diff": "+changed"})
    )

    assert result["status"] == "failed"
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        ({"type": "move_file", "path": "snack.txt"}, "unsupported operation"),
        ({"type": "create_file", "path": "/snack.txt", "diff": "+new"}, "relative"),
        ({"type": "create_file", "diff": "+new"}, "invalid file path"),
        ({"type": "create_file", "path": "snack.txt"}, "needs a text diff"),
        ({"type": "update_file", "path": "missing.txt", "diff": "@@\n+x"}, "does not exist"),
        ({"type": "delete_file", "path": "missing.txt"}, "does not exist"),
    ],
)
def test_steer_invalid_operations_return_model_safe_failures(
    tmp_path: Path,
    operation: dict[str, object],
    message: str,
):
    result = LocalWorkspace(tmp_path).apply_patch(_call(operation))

    assert result["status"] == "failed"
    assert message in result["output"]
    assert str(tmp_path) not in result["output"]


def test_steer_create_refuses_to_overwrite_existing_file(tmp_path: Path):
    target = tmp_path / "snack.txt"
    target.write_text("original\n", encoding="utf-8")

    result = LocalWorkspace(tmp_path).apply_patch(
        _call({"type": "create_file", "path": "snack.txt", "diff": "+replacement"})
    )

    assert result["status"] == "failed"
    assert target.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("operation_type", ["update_file", "delete_file"])
def test_steer_update_and_delete_refuse_directories(
    tmp_path: Path,
    operation_type: str,
):
    directory = tmp_path / "snacks"
    directory.mkdir()
    operation: dict[str, object] = {"type": operation_type, "path": "snacks"}
    if operation_type == "update_file":
        operation["diff"] = "@@\n+popcorn"

    result = LocalWorkspace(tmp_path).apply_patch(_call(operation))

    assert result["status"] == "failed"
    assert "not a file" in result["output"]
    assert directory.is_dir()


def test_steer_update_rejects_non_utf8_without_changing_bytes(tmp_path: Path):
    target = tmp_path / "binary.txt"
    original = b"snack:\xff\n"
    target.write_bytes(original)

    result = LocalWorkspace(tmp_path).apply_patch(
        _call(
            {
                "type": "update_file",
                "path": "binary.txt",
                "diff": "@@\n-snack\n+popcorn",
            }
        )
    )

    assert result["status"] == "failed"
    assert "UTF-8" in result["output"]
    assert target.read_bytes() == original


def test_steer_patch_conflict_leaves_file_and_directory_clean(tmp_path: Path):
    target = tmp_path / "snack.txt"
    target.write_text("popcorn\n", encoding="utf-8")

    result = LocalWorkspace(tmp_path).apply_patch(
        _call(
            {
                "type": "update_file",
                "path": "snack.txt",
                "diff": "@@\n-pretzels\n+chips",
            }
        )
    )

    assert result["status"] == "failed"
    assert "context did not match" in result["output"]
    assert target.read_text(encoding="utf-8") == "popcorn\n"
    assert list(tmp_path.iterdir()) == [target]


def test_steer_symlink_target_is_rejected(tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("original\n", encoding="utf-8")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    link = workspace_root / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    result = LocalWorkspace(workspace_root).apply_patch(
        _call(
            {
                "type": "update_file",
                "path": "linked.txt",
                "diff": "@@\n-original\n+changed",
            }
        )
    )

    assert result["status"] == "failed"
    assert "symlink" in result["output"]
    assert outside.read_text(encoding="utf-8") == "original\n"


def test_unit_v4a_applies_multiple_stacked_anchor_hunks():
    original = (
        "class Popcorn:\n"
        "    def price(self):\n"
        "        return 4\n"
        "\n"
        "    def size(self):\n"
        "        return 'small'\n"
    )
    diff = (
        "@@ class Popcorn:\n"
        "@@     def price(self):\n"
        "-        return 4\n"
        "+        return 5\n"
        "@@ class Popcorn:\n"
        "@@     def size(self):\n"
        "-        return 'small'\n"
        "+        return 'large'"
    )

    assert _apply_v4a_diff(original, diff) == (
        "class Popcorn:\n"
        "    def price(self):\n"
        "        return 5\n"
        "\n"
        "    def size(self):\n"
        "        return 'large'\n"
    )


def test_unit_v4a_uses_whitespace_tolerant_context_after_exact_match_fails():
    original = "snacks:\n    - popcorn   \n    - pretzels\n"
    diff = "@@ snacks:\n-  - popcorn\n+  - caramel corn\n     - pretzels"

    assert _apply_v4a_diff(original, diff) == (
        "snacks:\n  - caramel corn\n    - pretzels\n"
    )


def test_unit_v4a_end_of_file_marker_appends_at_the_end():
    original = "popcorn\npretzels\n"
    diff = "@@\n pretzels\n+caramel corn\n*** End of File"

    assert _apply_v4a_diff(original, diff) == "popcorn\npretzels\ncaramel corn\n"


def test_unit_v4a_preserves_crlf_for_updates_and_creates():
    updated = _apply_v4a_diff(
        "popcorn\r\nplain\r\n",
        "@@ popcorn\n-plain\n+caramel",
    )
    created = _apply_v4a_diff("", "+popcorn\r\n+caramel\r\n+", mode="create")

    assert updated == "popcorn\r\ncaramel\r\n"
    assert created == "popcorn\r\ncaramel\r\n"


def test_unit_v4a_single_unmatched_anchor_can_fall_back_to_context():
    assert _apply_v4a_diff("old\nsnack\n", "@@ missing\n-snack\n+popcorn") == (
        "old\npopcorn\n"
    )


@pytest.mark.parametrize("diff", ["", "@@\n snack"])
def test_unit_v4a_keeps_reference_compatible_noop_updates(diff: str):
    original = "snack\n"

    assert _apply_v4a_diff(original, diff) == original


def test_unit_v4a_stacked_anchors_narrow_to_the_named_block():
    original = (
        "class First\n"
        "    def target():\n"
        "        return 0\n"
        "\n"
        "class Second\n"
        "    def helper():\n"
        "        pass\n"
        "\n"
        "    def target():\n"
        "        pass\n"
    )
    diff = (
        "@@ class Second\n"
        "@@     def target():\n"
        "-        pass\n"
        "+        return 1"
    )

    assert _apply_v4a_diff(original, diff) == original.rsplit("pass", 1)[0] + "return 1\n"


@pytest.mark.parametrize(
    "diff",
    [
        "@@ missing\n@@ also missing\n-snack\n+popcorn",
        "@@broken\n-snack\n+popcorn",
        "@@\nsnack",
        "@@\n*** Unknown Marker",
    ],
)
def test_unit_v4a_rejects_malformed_or_unmatched_hunks(diff: str):
    with pytest.raises(ValueError):
        _apply_v4a_diff("snack\n", diff)
