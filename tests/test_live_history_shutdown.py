"""Offline process-level regressions for the opt-in live suite's cleanup."""

import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_live_conversation_history import _close_live_chats


def test_live_fixture_releases_anyio_workers_before_process_exit(tmp_path):
    """Passing assertions must also allow Python to exit without a stuck worker."""
    test_file = tmp_path / "test_worker.py"
    test_file.write_text(
        "import anyio\n"
        "import pytest\n"
        "from tests.test_live_conversation_history import _drain_live_callbacks\n"
        "\n"
        "@pytest.mark.asyncio\n"
        "async def test_worker():\n"
        "    assert await anyio.to_thread.run_sync(lambda: 7) == 7\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CHATSNACK_RUN_LIVE_TESTS"] = ""
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[1]), env.get("PYTHONPATH")]))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


@pytest.mark.asyncio
async def test_live_cleanup_fails_when_a_client_will_not_close():
    """A stalled close is a bounded failure, never a successful test hang."""
    class StalledChat:
        async def close_a(self):
            """Simulate an owned client whose close never finishes."""
            await asyncio.Event().wait()

    with pytest.raises(TimeoutError):
        await _close_live_chats([StalledChat()], timeout=0.02)
