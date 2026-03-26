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

    def test_images_reject_file_object_bucket_mismatch(self):
        fh = io.BytesIO(b"bad")
        with pytest.raises(ValueError, match="Unsupported images attachment entry type"):
            Chat._prepare_query_vars("x", images=[fh])

    def test_dict_with_multiple_sources_is_rejected(self):
        with pytest.raises(ValueError, match="ambiguous sources"):
            Chat._prepare_query_vars("x", files=[{"path": "a", "url": "b"}])
