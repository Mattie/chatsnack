import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from chatsnack import Chat, ChatFile
from chatsnack.assets import (
    AssetCorruptError,
    AssetMissingError,
    GeneratedAssetError,
    capture_asset,
)
from chatsnack.runtime.attachment_resolver import AttachmentResolver
from chatsnack.runtime.types import (
    NormalizedAssistantMessage,
    NormalizedCompletionResult,
    PendingOutput,
)


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
)


class _OneResponseRuntime:
    def __init__(self, message):
        self.message = message

    async def create_completion_a(self, messages, **kwargs):
        return NormalizedCompletionResult(message=self.message)


@pytest.fixture
def asset_root(tmp_path, monkeypatch):
    root = tmp_path / "chatsnack-data"
    monkeypatch.setenv("CHATSNACK_BASE_DIR", str(root))
    return root


class TestGeneratedAssetsGoals:
    """Goal proofs for the 0.7.0 generated-file story."""

    def test_g1_generated_image_survives_an_offline_yaml_round_trip(self, asset_root, tmp_path):
        runtime = _OneResponseRuntime(
            NormalizedAssistantMessage(
                content="Here is your tiny snack.",
                pending_outputs=[PendingOutput(kind="image", data=PNG_BYTES)],
            )
        )

        drawing = Chat(runtime=runtime).chat("Draw one tiny popcorn kernel.")
        image = drawing.images[0]

        assert drawing.last == "Here is your tiny snack."
        assert drawing.response == "Here is your tiny snack."
        assert str(drawing) == "Here is your tiny snack."
        drawing.pattern = r"tiny (snack)"
        assert drawing.response == "snack"
        drawing.pattern = None
        assert isinstance(image, ChatFile)
        assert image.read_bytes() == PNG_BYTES
        assert image.captured
        digest = hashlib.sha256(PNG_BYTES).hexdigest()
        assert image.asset == f"sha256:{digest}"
        assert f"- asset: 'sha256:{digest}'" in {
            line.strip() for line in drawing.yaml.splitlines()
        }
        assert "generated_images" not in drawing.yaml

        chat_path = tmp_path / "drawing.yml"
        drawing.save(str(chat_path))
        loaded = Chat()
        loaded.load(str(chat_path))

        assert loaded.images[0].read_bytes() == PNG_BYTES
        assert loaded.files == loaded.images

    def test_g2_code_interpreter_file_is_local_before_chat_returns(self, asset_root, monkeypatch):
        async def download(container_id, file_id):
            assert (container_id, file_id) == ("container_snacks", "file_inventory")
            return b"snack,score\npopcorn,9\n"

        runtime = _OneResponseRuntime(
            NormalizedAssistantMessage(
                content="The inventory is ready.",
                files=[
                    {
                        "file_id": "file_inventory",
                        "container_id": "container_snacks",
                        "filename": "snack_inventory.csv",
                    }
                ],
                pending_outputs=[
                    PendingOutput(
                        kind="file",
                        file_id="file_inventory",
                        container_id="container_snacks",
                        filename="snack_inventory.csv",
                    )
                ],
            )
        )
        runtime.ai_client = SimpleNamespace(download_container_file_async=download)
        chat = Chat(runtime=runtime)

        async def wrong_client(*args):
            raise AssertionError("generated files must use the active runtime client")

        monkeypatch.setattr(chat.ai, "download_container_file_async", wrong_client)

        report = chat.chat("Make the inventory CSV.")
        generated = report.files[0]

        assert generated.filename == "snack_inventory.csv"
        assert generated.read_bytes() == b"snack,score\npopcorn,9\n"
        assert "asset:" in report.yaml
        assert "sha256:" in report.yaml

    def test_g3_a_generated_file_can_be_reused_as_a_chat_attachment(self, asset_root, monkeypatch):
        first = Chat(
            runtime=_OneResponseRuntime(
                NormalizedAssistantMessage(
                    content="Made it.",
                    pending_outputs=[
                        PendingOutput(
                            kind="file",
                            data=b"snack,score\npretzels,8\n",
                            filename="scores.csv",
                        )
                    ],
                )
            )
        ).chat("Make a score sheet.")
        generated = first.files[0]

        uploaded = []

        class _ReplayRuntime:
            def __init__(self, ai_client):
                self.resolver = AttachmentResolver(ai_client)

            async def create_completion_a(self, messages, **kwargs):
                resolved = await self.resolver.resolve_messages_async(messages)
                uploaded.extend(resolved[-1]["files"])
                return NormalizedCompletionResult(
                    message=NormalizedAssistantMessage(content="Pretzels scored eight.")
                )

        replay = Chat()

        async def upload(path, purpose):
            assert Path(path).read_bytes() == generated.read_bytes()
            assert purpose == "assistants"
            return "file_replayed"

        monkeypatch.setattr(replay.ai, "upload_file_async", upload)
        replay.runtime = _ReplayRuntime(replay.ai)

        continued = replay.chat("Read this score sheet.", files=[generated])

        assert uploaded == [{"file_id": "file_replayed"}]
        assert continued.messages[0]["user"]["files"] == [
            {"asset": generated.asset, "filename": "scores.csv"}
        ]


class TestGeneratedAssetsSteer:
    """Rules that keep the Goal behavior safe and provider-neutral."""

    def test_capture_uses_a_full_digest_safe_name_and_atomic_destination(self, asset_root):
        payload = b"snack,score\nchips,7\n"
        reference = capture_asset(payload, filename="../../unsafe\\scores?.csv")
        digest = hashlib.sha256(payload).hexdigest()

        assert reference == {
            "asset": f"sha256:{digest}",
            "filename": "scores_.csv",
        }
        expected = asset_root / "assets" / "sha256" / digest / "scores_.csv"
        assert expected.read_bytes() == payload
        assert not list(expected.parent.glob("*.tmp"))

    def test_corrupt_and_missing_assets_fail_loudly(self, asset_root):
        reference = capture_asset(b"important", filename="notes.txt")
        item = ChatFile.from_reference(reference)
        path = item.path
        path.write_bytes(b"changed")

        with pytest.raises(AssetCorruptError):
            item.read_bytes()

        path.unlink()
        with pytest.raises(AssetMissingError):
            item.read_bytes()

    def test_unsupported_generated_image_is_not_saved(self, asset_root):
        runtime = _OneResponseRuntime(
            NormalizedAssistantMessage(
                pending_outputs=[PendingOutput(kind="image", data=b"not an image")]
            )
        )

        with pytest.warns(RuntimeWarning, match="unsupported file signature"):
            result = Chat(runtime=runtime).chat("Draw something.")

        assert result.images == []
        assert not (asset_root / "assets").exists()

    def test_failed_container_capture_keeps_the_remote_reference(self, asset_root, monkeypatch):
        runtime = _OneResponseRuntime(
            NormalizedAssistantMessage(
                files=[
                    {
                        "file_id": "file_remote",
                        "container_id": "container_remote",
                        "filename": "remote.csv",
                    }
                ],
                pending_outputs=[
                    PendingOutput(
                        kind="file",
                        file_id="file_remote",
                        container_id="container_remote",
                        filename="remote.csv",
                    )
                ],
            )
        )
        chat = Chat(runtime=runtime)

        async def unavailable(*args):
            raise ConnectionError("container expired")

        monkeypatch.setattr(chat.ai, "download_container_file_async", unavailable)

        with pytest.warns(RuntimeWarning, match="container expired"):
            result = chat.chat("Make a file.")

        assert result.files[0].file_id == "file_remote"
        assert result.files[0].container_id == "container_remote"
        assert not result.files[0].captured

    def test_old_path_url_and_file_id_yaml_still_loads(self, tmp_path):
        path = tmp_path / "old-outputs.yml"
        path.write_text(
            """messages:
  - assistant:
      images:
        - path: old-chart.png
      files:
        - file_id: file_old
          filename: old.csv
        - url: https://example.com/report.pdf
""",
            encoding="utf-8",
        )

        loaded = Chat()
        loaded.load(str(path))

        assert loaded.images[0].filename == "old-chart.png"
        assert loaded.files[1].file_id == "file_old"
        assert loaded.files[2].url == "https://example.com/report.pdf"

    def test_remote_only_chatfile_cannot_pretend_to_have_bytes(self):
        item = ChatFile.from_reference({"file_id": "file_remote", "filename": "remote.csv"})

        assert not item.captured
        with pytest.raises(GeneratedAssetError, match="no local bytes"):
            item.read_bytes()

    def test_chatfile_can_be_copied_and_used_as_a_path(self, asset_root, tmp_path):
        reference = capture_asset(b"apple,popcorn\n", filename="pairings.csv")
        item = ChatFile.from_reference(reference)

        copied = item.save_as(tmp_path / "exports" / "pairings.csv")

        assert Path(item).read_bytes() == b"apple,popcorn\n"
        assert copied.read_bytes() == b"apple,popcorn\n"

    def test_ask_keeps_its_text_only_contract(self, asset_root):
        runtime = _OneResponseRuntime(
            NormalizedAssistantMessage(
                content="Made it.",
                pending_outputs=[
                    PendingOutput(kind="file", data=b"temporary", filename="one.txt")
                ],
            )
        )

        assert Chat(runtime=runtime).ask("Make a file.") == "Made it."
        assert not (asset_root / "assets").exists()
