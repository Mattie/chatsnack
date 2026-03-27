import io
from types import SimpleNamespace

import pytest

from chatsnack import Chat
from chatsnack.chat.mixin_query import ChatStreamListener


class TestPhase3ANaturalAttachmentsGoal:
    def test_ask_accepts_files_and_images_and_sends_expanded_user_turn(self, monkeypatch):
        chat = Chat(runtime_selector="responses")

        async def fake_create_completion_a(self, messages, **kwargs):
            user = messages[-1]
            assert user["role"] == "user"
            assert user["content"] == "check attachments"
            assert user["files"] == [{"path": "docs/table.csv"}]
            assert user["images"] == [{"path": "img/chart.png"}]
            return SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))

        monkeypatch.setattr(type(chat.runtime), "create_completion_a", fake_create_completion_a)

        out = chat.ask("check attachments", files=["docs/table.csv"], images=["img/chart.png"])
        assert out == "ok"

    def test_chat_persists_expanded_user_turn_with_images(self, monkeypatch):
        chat = Chat(runtime_selector="responses")

        async def fake_create_completion_a(self, messages, **kwargs):
            return SimpleNamespace(
                message=SimpleNamespace(content="processed", tool_calls=[]),
                metadata={"response_id": "resp_1", "provider_extras": {"status": "completed"}},
            )

        monkeypatch.setattr(type(chat.runtime), "create_completion_a", fake_create_completion_a)

        out = chat.chat("review image", images=["img/plot.png"])
        assert out.messages[0] == {"user": {"text": "review image", "images": [{"path": "img/plot.png"}]}}
        assert out.messages[-1] == {"assistant": "processed"}

    def test_chat_persists_rich_assistant_fields_from_normalized_response(self, monkeypatch):
        chat = Chat(runtime_selector="responses")

        async def fake_create_completion_a(self, messages, **kwargs):
            return SimpleNamespace(
                message=SimpleNamespace(
                    content="processed",
                    tool_calls=[],
                    reasoning="why",
                    sources=[{"type": "url_citation", "url": "https://example.com"}],
                    images=[{"file_id": "file_img"}],
                    files=[{"file_id": "file_doc"}],
                    encrypted_content="enc",
                ),
                metadata={"response_id": "resp_1", "provider_extras": {"status": "completed"}},
            )

        monkeypatch.setattr(type(chat.runtime), "create_completion_a", fake_create_completion_a)

        out = chat.chat("review image", images=["img/plot.png"])
        assert out.messages[-1] == {
            "assistant": {
                "text": "processed",
                "reasoning": "why",
                "sources": [{"type": "url_citation", "url": "https://example.com"}],
                "images": [{"file_id": "file_img"}],
                "files": [{"file_id": "file_doc"}],
                "encrypted_content": "enc",
            }
        }

    def test_listen_accepts_attachments_on_streaming_path(self, monkeypatch):
        chat = Chat(stream=True)

        class _FakeListener(ChatStreamListener):
            def __init__(self):
                self.events = False
                self.event_schema = "legacy"
                self.started = False

            def start(self):
                self.started = True
                return self

        listener = _FakeListener()

        async def fake_submit(self, **kwargs):
            user = kwargs["__user"]
            assert user["text"] == "stream this"
            assert user["files"] == [{"path": "data.txt"}]
            return "[]", listener

        monkeypatch.setattr(Chat, "_submit_for_response_and_prompt", fake_submit)

        result = chat.listen("stream this", files=["data.txt"], events=True)
        assert result is listener
        assert result.events is True
        assert result.started is True

    @pytest.mark.asyncio
    async def test_async_parity_for_ask_chat_listen(self, monkeypatch):
        chat = Chat(runtime_selector="responses")

        async def fake_create_completion_a(self, messages, **kwargs):
            return SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=[]),
                metadata={"response_id": "resp_2", "provider_extras": {"status": "completed"}},
            )

        monkeypatch.setattr(type(chat.runtime), "create_completion_a", fake_create_completion_a)

        assert await chat.ask_a("a", files=["one.txt"]) == "ok"
        chat_out = await chat.chat_a("b", images=["one.png"])
        assert chat_out.messages[0] == {"user": {"text": "b", "images": [{"path": "one.png"}]}}

        streaming_chat = Chat(stream=True)

        class _FakeListener(ChatStreamListener):
            def __init__(self):
                self.started = False
                self.events = False
                self.event_schema = "legacy"

            async def start_a(self):
                self.started = True
                return self

        listener = _FakeListener()

        async def fake_submit_stream(self, **kwargs):
            assert kwargs["__user"]["files"] == [{"path": "async.txt"}]
            return "[]", listener

        monkeypatch.setattr(Chat, "_submit_for_response_and_prompt", fake_submit_stream)
        heard = await streaming_chat.listen_a("go", files=["async.txt"], events=True)
        assert heard is listener
        assert heard.events is True
        assert heard.started is True


class TestPhase3ANaturalAttachmentsSteerUnit:
    def test_shared_normalizer_maps_paths_and_canonical_dicts(self):
        payload = Chat._prepare_query_vars(
            "hello",
            files=["alpha.txt", {"file_id": "file_1"}],
            images=[{"url": "https://example.com/i.png"}],
        )
        assert payload["__user"] == {
            "text": "hello",
            "files": [{"path": "alpha.txt"}, {"file_id": "file_1"}],
            "images": [{"url": "https://example.com/i.png"}],
        }

    def test_files_bucket_routes_image_extensions_into_images(self):
        payload = Chat._prepare_query_vars("hello", files=["photo.png", "notes.csv"])
        assert payload["__user"]["images"] == [{"path": "photo.png"}]
        assert payload["__user"]["files"] == [{"path": "notes.csv"}]

    def test_no_attachment_path_is_unchanged(self):
        payload = Chat._prepare_query_vars("hello", flavor="mint")
        assert payload == {"__user": "hello", "flavor": "mint"}

    def test_files_support_file_objects(self):
        fh = io.BytesIO(b"id,name\n1,Alice\n")
        fh.name = "records.csv"

        payload = Chat._prepare_query_vars("read", files=[fh])
        files = payload["__user"]["files"]
        assert len(files) == 1
        assert files[0]["filename"] == "records.csv"
        assert files[0]["path"].endswith(".csv")

    def test_files_support_file_object_cleanup_after_upload(self, monkeypatch):
        fh = io.BytesIO(b"id,name\n1,Alice\n")
        fh.name = "records.csv"
        chat = Chat(runtime_selector="responses")
        uploaded_paths = []

        def fake_upload(path, purpose):
            uploaded_paths.append(path)
            assert purpose == "assistants"
            return "file_1"

        monkeypatch.setattr(chat.ai, "upload_file", fake_upload)
        payload = Chat._prepare_query_vars("read", files=[fh])
        files = payload["__user"]["files"]
        chat.runtime.attachment_resolver.resolve_attachment(files[0], "file")
        assert uploaded_paths, "expected one upload call"
        import os
        assert not os.path.exists(uploaded_paths[0])

    def test_images_reject_file_object_bucket_mismatch(self):
        fh = io.BytesIO(b"bad")
        with pytest.raises(ValueError, match="Unsupported images attachment entry type"):
            Chat._prepare_query_vars("x", images=[fh])

    def test_dict_with_multiple_sources_is_rejected(self):
        with pytest.raises(ValueError, match="ambiguous sources"):
            Chat._prepare_query_vars("x", files=[{"path": "a", "url": "b"}])

    # ------------------------------------------------------------------
    # Merge behaviour: existing __user must not be overwritten
    # ------------------------------------------------------------------

    def test_existing_user_string_merged_when_no_explicit_usermsg(self):
        """__call__ puts text in __user then delegates; files must not drop it."""
        payload = Chat._prepare_query_vars(
            None,  # usermsg=None — mimics __call__ → chat() delegation
            files=["report.csv"],
            __user="Summarize this file.",
        )
        assert payload["__user"] == {
            "text": "Summarize this file.",
            "files": [{"path": "report.csv"}],
        }

    def test_existing_user_dict_merged_with_new_attachments(self):
        """A pre-existing expanded __user dict is extended with new attachments."""
        payload = Chat._prepare_query_vars(
            None,
            images=["chart.png"],
            __user={"text": "Describe this.", "files": [{"file_id": "file_1"}]},
        )
        assert payload["__user"] == {
            "text": "Describe this.",
            "files": [{"file_id": "file_1"}],
            "images": [{"path": "chart.png"}],
        }

    def test_explicit_usermsg_wins_over_existing_user_string(self):
        """Explicit usermsg overwrites the text from a pre-existing __user string."""
        payload = Chat._prepare_query_vars(
            "Explicit text",
            files=["data.csv"],
            __user="Old text",
        )
        assert payload["__user"]["text"] == "Explicit text"
        assert payload["__user"]["files"] == [{"path": "data.csv"}]

    def test_call_operator_with_files_preserves_text(self, monkeypatch):
        """chat("hello", files=[...]) via __call__ must deliver text + attachment."""
        chat = Chat(runtime_selector="responses")
        captured = {}

        async def fake_create_completion_a(self, messages, **kwargs):
            captured["messages"] = messages
            return SimpleNamespace(
                message=SimpleNamespace(content="got it", tool_calls=[]),
                metadata={"response_id": "r1", "provider_extras": {"status": "completed"}},
            )

        monkeypatch.setattr(type(chat.runtime), "create_completion_a", fake_create_completion_a)

        # __call__ is a shortcut for .chat(); it sets __user then delegates
        result = chat("hello via __call__", files=["data.csv"])
        user_msg = captured["messages"][-1]
        assert user_msg["role"] == "user"
        assert user_msg["content"] == "hello via __call__"
        assert user_msg["files"] == [{"path": "data.csv"}]
