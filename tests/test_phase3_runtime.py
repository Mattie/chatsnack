"""Phase 3 runtime-boundary tests.

These tests verify that Phase 3 YAML config actually reaches the provider API,
that expanded turns produce mixed-content input, that runtime metadata bridges
into params.responses.state, and that provider-native tools pass through
without being wrapped in function-tool schema.

All tests are offline (no live API calls).
"""

from types import SimpleNamespace

import pytest

from chatsnack.runtime import ResponsesAdapter
from chatsnack.chat.mixin_params import ChatParams


class _FakeObj:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self):
        return self.payload


# ═══════════════════════════════════════════════════════════════════════════
# 1. params.responses options reach the Responses API
# ═══════════════════════════════════════════════════════════════════════════

class TestResponsesOptionsReachProvider:

    def test_responses_api_options_extracted_correctly(self):
        """_get_responses_api_options should return provider-facing fields and skip internal ones."""
        params = ChatParams(
            model="gpt-5.4",
            responses={
                "text": {"format": {"type": "text"}},
                "reasoning": {"effort": "medium", "summary": "auto"},
                "include": ["reasoning.encrypted_content"],
                "store": True,
                # Internal keys that should be stripped:
                "export_state": True,
                "state": {"response_id": "resp_123"},
                "export_diagnostics": False,
                "provider_dump": {"raw": "data"},
            },
        )
        opts = params._get_responses_api_options()
        assert opts["text"] == {"format": {"type": "text"}}
        assert opts["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert opts["include"] == ["reasoning.encrypted_content"]
        assert opts["store"] is True
        # Internal keys must NOT be present:
        assert "export_state" not in opts
        assert "state" not in opts
        assert "export_diagnostics" not in opts
        assert "provider_dump" not in opts

    def test_responses_api_options_empty_when_no_responses(self):
        params = ChatParams(model="gpt-4o")
        assert params._get_responses_api_options() == {}

    def test_store_from_responses_config_reaches_adapter(self):
        """store=True from params.responses should reach the adapter request."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_1", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        # Simulate what _submit_for_response_and_prompt does: merge responses options into kwargs
        params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"store": True, "reasoning": {"effort": "medium"}},
        )
        kwargs = params._get_non_none_params()
        responses_opts = params._get_responses_api_options()
        merged = responses_opts.copy()
        merged.update(kwargs)

        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            **merged,
        )

        assert captured["store"] is True
        assert captured["reasoning"] == {"effort": "medium"}

    def test_include_from_responses_config_reaches_adapter(self):
        """include list from params.responses should reach the adapter request."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_2", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={
                "include": ["reasoning.encrypted_content", "web_search_call.action.sources"],
            },
        )
        kwargs = params._get_non_none_params()
        responses_opts = params._get_responses_api_options()
        merged = responses_opts.copy()
        merged.update(kwargs)

        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            **merged,
        )

        assert captured["include"] == ["reasoning.encrypted_content", "web_search_call.action.sources"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. Expanded turns produce mixed-content input items
# ═══════════════════════════════════════════════════════════════════════════

class TestExpandedTurnsProduceMixedContent:

    def test_user_images_produce_input_image_items(self):
        """User turn with images should produce input_image content parts."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_img", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{
                "role": "user",
                "content": "Describe this image.",
                "images": [{"url": "https://example.com/photo.png"}],
            }],
            model="gpt-5.4",
        )

        input_items = captured["input"]
        assert len(input_items) == 1
        content_parts = input_items[0]["content"]
        assert any(p["type"] == "input_text" for p in content_parts)
        assert any(p["type"] == "input_image" for p in content_parts)
        img_part = [p for p in content_parts if p["type"] == "input_image"][0]
        assert img_part["image_url"] == "https://example.com/photo.png"

    def test_user_files_produce_input_file_items(self):
        """User turn with files should produce input_file content parts."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_file", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{
                "role": "user",
                "content": "Summarize this file.",
                "files": [{"file_id": "file_abc123"}],
            }],
            model="gpt-5.4",
        )

        input_items = captured["input"]
        content_parts = input_items[0]["content"]
        assert any(p["type"] == "input_text" for p in content_parts)
        assert any(p["type"] == "input_file" for p in content_parts)
        file_part = [p for p in content_parts if p["type"] == "input_file"][0]
        assert file_part["file_id"] == "file_abc123"

    def test_user_images_via_file_id(self):
        """User image via file_id should produce correct input_image."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_fid", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{
                "role": "user",
                "content": "What is this?",
                "images": [{"file_id": "file_img_456"}],
            }],
            model="gpt-5.4",
        )

        content_parts = captured["input"][0]["content"]
        img_part = [p for p in content_parts if p["type"] == "input_image"][0]
        assert img_part["file_id"] == "file_img_456"

    def test_text_only_user_still_works(self):
        """A plain text user message should still produce just input_text."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_plain", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{"role": "user", "content": "Hello"}],
            model="gpt-5.4",
        )

        content_parts = captured["input"][0]["content"]
        assert len(content_parts) == 1
        assert content_parts[0] == {"type": "input_text", "text": "Hello"}

    def test_local_path_image_raises_before_request(self):
        """A missing local image path should fail before any provider request."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_skip", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        with pytest.raises(Exception, match="photo.png"):
            adapter.create_completion(
                messages=[{
                    "role": "user",
                    "content": "Describe this image.",
                    "images": [{"path": "/tmp/photo.png"}],
                }],
                model="gpt-5.4",
            )
        assert captured == {}

    def test_local_path_file_raises_before_request(self):
        """A missing local file path should fail before any provider request."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_skip2", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        with pytest.raises(Exception, match="sales-missing.csv"):
            adapter.create_completion(
                messages=[{
                    "role": "user",
                    "content": "Summarize this file.",
                    "files": [{"path": "./data/sales-missing.csv"}],
                }],
                model="gpt-5.4",
            )
        assert captured == {}

    def test_mixed_file_id_and_local_path_raises_before_request(self):
        """A missing local attachment should fail even when another file_id is present."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_mix", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        with pytest.raises(Exception, match="data-missing.csv"):
            adapter.create_completion(
                messages=[{
                    "role": "user",
                    "content": "Analyze these.",
                    "files": [
                        {"file_id": "file_real_123"},
                        {"path": "./local/data-missing.csv"},
                    ],
                }],
                model="gpt-5.4",
            )
        assert captured == {}


# ═══════════════════════════════════════════════════════════════════════════
# 3. get_messages carries images/files through for expanded turns
# ═══════════════════════════════════════════════════════════════════════════

class TestGetMessagesCarriesAssets:

    def test_expanded_user_with_images_passes_through(self):
        """get_messages should include images metadata from expanded user turns."""
        from chatsnack import Chat
        chat = Chat(name="p3_img_passthrough")
        chat.messages = [
            {"user": {
                "text": "Describe this.",
                "images": [{"url": "https://example.com/photo.png"}],
            }},
        ]
        msgs = chat.get_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Describe this."
        assert msgs[0]["images"] == [{"url": "https://example.com/photo.png"}]

    def test_expanded_user_with_files_passes_through(self):
        """get_messages should include files metadata from expanded user turns."""
        from chatsnack import Chat
        chat = Chat(name="p3_file_passthrough")
        chat.messages = [
            {"user": {
                "text": "Summarize.",
                "files": [{"file_id": "file_abc"}],
            }},
        ]
        msgs = chat.get_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Summarize."
        assert msgs[0]["files"] == [{"file_id": "file_abc"}]

    def test_scalar_user_has_no_extra_keys(self):
        """Scalar user turn should not have images or files keys."""
        from chatsnack import Chat
        chat = Chat(name="p3_scalar_clean")
        chat.messages = [{"user": "Hello"}]
        msgs = chat.get_messages()
        assert "images" not in msgs[0]
        assert "files" not in msgs[0]

    def test_attachment_only_turn_without_text(self):
        """Expanded turn with images but no text key should still carry through."""
        from chatsnack import Chat
        chat = Chat(name="p3_attach_only")
        chat.messages = [
            {"user": {
                "images": [{"url": "https://example.com/photo.png"}],
            }},
        ]
        msgs = chat.get_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == ""
        assert msgs[0]["images"] == [{"url": "https://example.com/photo.png"}]

    def test_attachment_only_files_without_text(self):
        """Expanded turn with files but no text key should still carry through."""
        from chatsnack import Chat
        chat = Chat(name="p3_files_only")
        chat.messages = [
            {"user": {
                "files": [{"file_id": "file_xyz"}],
            }},
        ]
        msgs = chat.get_messages()
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == ""
        assert msgs[0]["files"] == [{"file_id": "file_xyz"}]


# ═══════════════════════════════════════════════════════════════════════════
# 4. Runtime metadata bridges into params.responses.state
# ═══════════════════════════════════════════════════════════════════════════

class TestRuntimeMetadataBridgesToState:

    def test_metadata_written_when_export_state_enabled(self):
        """_set_last_runtime_metadata should populate params.responses.state
        when export_state is true.  previous_response_id is a top-level metadata
        key (matching the production normalize_completion output)."""
        from chatsnack import Chat
        chat = Chat(name="p3_meta_bridge")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"export_state": True, "store": True},
        )

        # Simulate the shape that _normalize_runtime_metadata produces from
        # normalize_completion: previous_response_id is top-level.
        chat._set_last_runtime_metadata({
            "response_id": "resp_abc123",
            "previous_response_id": "resp_prev",
            "usage": {"total_tokens": 42},
            "assistant_phase": "completed",
            "provider_extras": {
                "status": "completed",
            },
        })

        state = chat.params.responses.get("state")
        assert state is not None
        assert state["response_id"] == "resp_abc123"
        assert state["status"] == "completed"
        assert state["previous_response_id"] == "resp_prev"

    def test_metadata_not_written_when_export_state_disabled(self):
        """_set_last_runtime_metadata should NOT write state when export_state is off."""
        from chatsnack import Chat
        chat = Chat(name="p3_no_meta_bridge")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"store": True},
        )

        chat._set_last_runtime_metadata({
            "response_id": "resp_abc123",
            "usage": {"total_tokens": 42},
            "assistant_phase": "completed",
            "provider_extras": {"status": "completed"},
        })

        assert "state" not in chat.params.responses

    def test_metadata_not_written_when_no_responses_config(self):
        """_set_last_runtime_metadata should not crash when params.responses is None."""
        from chatsnack import Chat
        chat = Chat(name="p3_no_responses_cfg")
        chat.params = ChatParams(model="gpt-5.4")

        # Should not raise
        chat._set_last_runtime_metadata({
            "response_id": "resp_xyz",
            "provider_extras": {"status": "completed"},
        })

        assert chat.params.responses is None

    def test_production_flow_previous_response_id_reaches_state(self):
        """End-to-end: normalize_completion → _normalize_runtime_metadata →
        _set_last_runtime_metadata → _sync_runtime_metadata_to_params.
        Verifies previous_response_id survives the full production path."""
        from chatsnack import Chat
        from chatsnack.runtime.responses_common import ResponsesNormalizationMixin

        mixin = ResponsesNormalizationMixin()
        # Simulate a Responses API result with a previous_response_id in request_kwargs
        fake_response = {
            "id": "resp_new_456",
            "status": "completed",
            "model": "gpt-5.4",
            "output": [
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "Hello"}]},
            ],
        }
        request_kwargs = {"previous_response_id": "resp_old_123", "model": "gpt-5.4"}
        result = mixin.normalize_completion(fake_response, request_kwargs)

        # Wire through the chat's metadata pipeline
        chat = Chat(name="p3_e2e_prev_id")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"export_state": True, "store": True},
        )
        normalized_meta = chat._normalize_runtime_metadata(result)
        chat._set_last_runtime_metadata(normalized_meta)

        state = chat.params.responses.get("state")
        assert state is not None
        assert state["response_id"] == "resp_new_456"
        assert state["status"] == "completed"
        assert state["previous_response_id"] == "resp_old_123"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Store policy respects params.responses
# ═══════════════════════════════════════════════════════════════════════════

class TestStorePolicy:

    def test_store_defaults_to_false_without_explicit_config(self):
        """build_responses_request should default store to False."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_1", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.4",
        )

        assert captured["store"] is False

    def test_continuation_does_not_auto_enable_store(self):
        """Continuation with previous_response_id should NOT auto-enable store."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_2", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[
                {"role": "user", "content": "turn1"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "turn2"},
            ],
            model="gpt-5.4",
            previous_response_id="resp_prev",
        )

        assert captured["store"] is False

    def test_explicit_store_true_is_honored(self):
        """Explicit store=True should be preserved."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_3", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-5.4",
            store=True,
        )

        assert captured["store"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 6. Provider-native tool passthrough
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderNativeToolPassthrough:

    def test_web_search_tool_passes_through_unchanged(self):
        """A web_search tool dict should survive set_tools/get_tools without function wrapping."""
        params = ChatParams(model="gpt-5.4")
        params.set_tools([
            {"type": "web_search"},
        ])

        result = params.get_tools()
        assert len(result) == 1
        assert result[0] == {"type": "web_search"}

    def test_code_interpreter_tool_passes_through(self):
        """code_interpreter tool should pass through unchanged."""
        params = ChatParams(model="gpt-5.4")
        params.set_tools([
            {"type": "code_interpreter", "container": {"type": "auto"}},
        ])

        result = params.get_tools()
        assert len(result) == 1
        assert result[0]["type"] == "code_interpreter"
        assert result[0]["container"]["type"] == "auto"

    def test_mixed_function_and_native_tools(self):
        """Mixing function tools and native tools should preserve both."""
        params = ChatParams(model="gpt-5.4")
        params.set_tools([
            {"type": "function", "function": {"name": "my_func", "parameters": {}}},
            {"type": "web_search"},
            {"type": "code_interpreter"},
        ])

        result = params.get_tools()
        assert len(result) == 3
        types = [t["type"] for t in result]
        assert "function" in types
        assert "web_search" in types
        assert "code_interpreter" in types
        # Function tool should have nested function object
        func_tool = [t for t in result if t["type"] == "function"][0]
        assert "function" in func_tool

    def test_image_generation_tool_passes_through(self):
        """image_generation tool should pass through unchanged."""
        params = ChatParams(model="gpt-5.4")
        params.set_tools([
            {"type": "image_generation"},
        ])

        result = params.get_tools()
        assert len(result) == 1
        assert result[0] == {"type": "image_generation"}

    def test_add_tool_from_dict_handles_native(self):
        """add_tool_from_dict should handle native tools correctly."""
        params = ChatParams(model="gpt-5.4")
        params.add_tool_from_dict({"type": "web_search"})
        params.add_tool_from_dict({"type": "function", "function": {"name": "foo"}})

        result = params.get_tools()
        assert len(result) == 2
        types = [t["type"] for t in result]
        assert "web_search" in types
        assert "function" in types

    def test_native_tools_reach_adapter_request(self):
        """Provider-native tools should reach the adapter request."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_tools", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{"role": "user", "content": "Search for X"}],
            model="gpt-5.4",
            tools=[{"type": "web_search"}, {"type": "function", "function": {"name": "my_func"}}],
        )

        # After normalization, function tools are flattened for Responses API.
        assert captured["tools"] == [
            {"type": "web_search"},
            {"type": "function", "name": "my_func"},
        ]


# ═══════════════════════════════════════════════════════════════════════════
# 7. AttachmentResolver – local path upload, caching, integration
# ═══════════════════════════════════════════════════════════════════════════

class TestAttachmentResolver:
    """Tests for the shared AttachmentResolver that auto-uploads local paths."""

    def test_url_entries_pass_through_unchanged(self):
        """url: entries should not trigger upload or resolution."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        resolver = AttachmentResolver(ai_client=None)
        entry = {"url": "https://example.com/photo.png"}
        result = resolver.resolve_attachment(entry, kind="image")
        assert result == entry

    def test_file_id_entries_pass_through_unchanged(self):
        """file_id: entries should not trigger upload or resolution."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        resolver = AttachmentResolver(ai_client=None)
        entry = {"file_id": "file_abc123"}
        result = resolver.resolve_attachment(entry, kind="file")
        assert result == entry

    def test_path_entry_without_ai_client_raises(self):
        """path: entry with no ai_client should fail fast."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver, AttachmentResolutionError
        resolver = AttachmentResolver(ai_client=None)
        with pytest.raises(AttachmentResolutionError, match="no ai_client upload support"):
            resolver.resolve_attachment({"path": "/tmp/test.png"}, kind="image")

    def test_path_entry_nonexistent_file_raises(self, tmp_path):
        """path: entry for a file that doesn't exist should fail fast."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver, AttachmentNotFoundError
        fake_client = SimpleNamespace(
            upload_file=lambda path, purpose="assistants": "file_123",
        )
        resolver = AttachmentResolver(ai_client=fake_client)
        with pytest.raises(AttachmentNotFoundError, match="file not found"):
            resolver.resolve_attachment(
                {"path": str(tmp_path / "nonexistent.png")}, kind="image",
            )

    def test_path_entry_uploads_and_returns_file_id(self, tmp_path):
        """path: entry for a real file should upload and return file_id."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        test_file = tmp_path / "data.csv"
        test_file.write_text("a,b,c\n1,2,3\n")

        upload_calls = []
        def fake_upload(path, purpose="assistants"):
            upload_calls.append(path)
            return "file_uploaded_xyz"

        fake_client = SimpleNamespace(upload_file=fake_upload)
        resolver = AttachmentResolver(ai_client=fake_client)
        result = resolver.resolve_attachment({"path": str(test_file)}, kind="file")
        assert result == {"file_id": "file_uploaded_xyz"}
        assert len(upload_calls) == 1

    def test_image_path_upload_uses_vision_purpose(self, tmp_path):
        """Image uploads should use the Files API vision purpose."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        test_file = tmp_path / "photo.png"
        test_file.write_bytes(b"\x89PNG\r\n")

        upload_calls = []

        def fake_upload(path, purpose="assistants"):
            upload_calls.append((path, purpose))
            return "file_uploaded_img"

        fake_client = SimpleNamespace(upload_file=fake_upload)
        resolver = AttachmentResolver(ai_client=fake_client)

        result = resolver.resolve_attachment({"path": str(test_file)}, kind="image")

        assert result == {"file_id": "file_uploaded_img"}
        assert upload_calls == [(str(test_file), "vision")]

    def test_upload_cache_prevents_re_upload(self, tmp_path):
        """Same file should only be uploaded once (cache hit on second call)."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        test_file = tmp_path / "image.png"
        test_file.write_bytes(b"\x89PNG\r\n")

        upload_count = [0]
        upload_purposes = []
        def fake_upload(path, purpose="assistants"):
            upload_count[0] += 1
            upload_purposes.append(purpose)
            return "file_cached_abc"

        fake_client = SimpleNamespace(upload_file=fake_upload)
        resolver = AttachmentResolver(ai_client=fake_client)

        r1 = resolver.resolve_attachment({"path": str(test_file)}, kind="image")
        r2 = resolver.resolve_attachment({"path": str(test_file)}, kind="image")
        assert r1 == {"file_id": "file_cached_abc"}
        assert r2 == {"file_id": "file_cached_abc"}
        assert upload_count[0] == 1  # Only uploaded once
        assert upload_purposes == ["vision"]

    def test_cache_invalidated_when_file_changes(self, tmp_path):
        """Changing the file content (and mtime) should trigger a new upload."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        import time as _time
        test_file = tmp_path / "data.csv"
        test_file.write_text("v1")

        upload_count = [0]
        def fake_upload(path, purpose="assistants"):
            upload_count[0] += 1
            return f"file_v{upload_count[0]}"

        fake_client = SimpleNamespace(upload_file=fake_upload)
        resolver = AttachmentResolver(ai_client=fake_client)

        r1 = resolver.resolve_attachment({"path": str(test_file)}, kind="file")
        assert r1 == {"file_id": "file_v1"}

        # Modify file (size + mtime change)
        _time.sleep(0.05)
        test_file.write_text("v2 with more content")

        r2 = resolver.resolve_attachment({"path": str(test_file)}, kind="file")
        assert r2 == {"file_id": "file_v2"}
        assert upload_count[0] == 2

    def test_upload_failure_raises(self, tmp_path):
        """If upload raises, the explicit local attachment should fail fast."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver, AttachmentUploadError
        test_file = tmp_path / "bad.csv"
        test_file.write_text("data")

        def failing_upload(path, purpose="assistants"):
            raise RuntimeError("API quota exceeded")

        fake_client = SimpleNamespace(upload_file=failing_upload)
        resolver = AttachmentResolver(ai_client=fake_client)

        with pytest.raises(AttachmentUploadError, match="upload failed"):
            resolver.resolve_attachment({"path": str(test_file)}, kind="file")

    def test_resolve_messages_resolves_paths_in_batch(self, tmp_path):
        """resolve_messages should resolve all local path entries in a message list."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver

        img_file = tmp_path / "photo.png"
        img_file.write_bytes(b"\x89PNG")
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("a,b\n1,2")

        upload_map = {}
        def fake_upload(path, purpose="assistants"):
            fid = f"file_{len(upload_map)}"
            upload_map[path] = fid
            return fid

        fake_client = SimpleNamespace(upload_file=fake_upload)
        resolver = AttachmentResolver(ai_client=fake_client)

        messages = [
            {
                "role": "user",
                "content": "Describe and analyze.",
                "images": [{"path": str(img_file)}, {"url": "https://example.com/x.png"}],
                "files": [{"path": str(csv_file)}, {"file_id": "file_existing"}],
            },
        ]

        resolved = resolver.resolve_messages(messages)
        assert len(resolved) == 1
        msg = resolved[0]
        # image: path resolved to file_id, url passes through
        assert msg["images"][0].get("file_id") is not None
        assert msg["images"][1] == {"url": "https://example.com/x.png"}
        # file: path resolved to file_id, existing file_id passes through
        assert msg["files"][0].get("file_id") is not None
        assert msg["files"][1] == {"file_id": "file_existing"}
        # Original messages should be unmodified
        assert messages[0]["images"][0] == {"path": str(img_file)}
        assert messages[0]["files"][0] == {"path": str(csv_file)}

    def test_adapter_resolves_before_building_request(self, tmp_path):
        """Full integration: ResponsesAdapter should resolve paths before building input."""
        test_file = tmp_path / "report.pdf"
        test_file.write_text("PDF content here")

        captured = {}
        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_upload", "status": "completed", "model": "gpt-5.4", "output": []})

        def fake_upload(path, purpose="assistants"):
            return "file_uploaded_pdf"

        ai = SimpleNamespace(
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            upload_file=fake_upload,
        )
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{
                "role": "user",
                "content": "Summarize this PDF.",
                "files": [{"path": str(test_file)}],
            }],
            model="gpt-5.4",
        )

        content_parts = captured["input"][0]["content"]
        file_parts = [p for p in content_parts if p["type"] == "input_file"]
        assert len(file_parts) == 1
        assert file_parts[0]["file_id"] == "file_uploaded_pdf"

    def test_adapter_resolves_images_before_building_request(self, tmp_path):
        """Full integration: ResponsesAdapter should resolve image paths to file_id."""
        test_img = tmp_path / "photo.png"
        test_img.write_bytes(b"\x89PNG\r\n")

        captured = {}
        upload_purposes = []
        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_img_upload", "status": "completed", "model": "gpt-5.4", "output": []})

        def fake_upload(path, purpose="assistants"):
            upload_purposes.append(purpose)
            return "file_uploaded_img"

        ai = SimpleNamespace(
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            upload_file=fake_upload,
        )
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{
                "role": "user",
                "content": "Describe this image.",
                "images": [{"path": str(test_img)}],
            }],
            model="gpt-5.4",
        )

        content_parts = captured["input"][0]["content"]
        img_parts = [p for p in content_parts if p["type"] == "input_image"]
        assert len(img_parts) == 1
        assert img_parts[0]["file_id"] == "file_uploaded_img"
        assert upload_purposes == ["vision"]

    def test_adapter_mixed_path_and_file_id(self, tmp_path):
        """Adapter resolves path entries while passing through existing file_id entries."""
        test_file = tmp_path / "data.csv"
        test_file.write_text("col1,col2\n1,2")

        captured = {}
        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_mixed", "status": "completed", "model": "gpt-5.4", "output": []})

        def fake_upload(path, purpose="assistants"):
            return "file_from_upload"

        ai = SimpleNamespace(
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            upload_file=fake_upload,
        )
        adapter = ResponsesAdapter(ai)

        adapter.create_completion(
            messages=[{
                "role": "user",
                "content": "Analyze both files.",
                "files": [
                    {"file_id": "file_existing_123"},
                    {"path": str(test_file)},
                ],
            }],
            model="gpt-5.4",
        )

        content_parts = captured["input"][0]["content"]
        file_parts = [p for p in content_parts if p["type"] == "input_file"]
        assert len(file_parts) == 2
        file_ids = {p["file_id"] for p in file_parts}
        assert "file_existing_123" in file_ids
        assert "file_from_upload" in file_ids

    def test_original_messages_not_mutated(self, tmp_path):
        """The resolver must not mutate the original message dicts (YAML preservation)."""
        test_file = tmp_path / "keep_path.csv"
        test_file.write_text("data")

        def fake_upload(path, purpose="assistants"):
            return "file_resolved"

        captured = {}
        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_no_mutate", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(
            client=SimpleNamespace(responses=SimpleNamespace(create=create)),
            upload_file=fake_upload,
        )
        adapter = ResponsesAdapter(ai)

        original_msg = {
            "role": "user",
            "content": "Check this.",
            "files": [{"path": str(test_file)}],
        }
        import copy
        original_snapshot = copy.deepcopy(original_msg)

        adapter.create_completion(messages=[original_msg], model="gpt-5.4")

        # Original should be completely untouched
        assert original_msg == original_snapshot


class TestAttachmentResolverAsync:
    """Async tests for AttachmentResolver."""

    @pytest.mark.asyncio
    async def test_async_path_upload_and_cache(self, tmp_path):
        """Async resolve should upload and cache like the sync path."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        test_file = tmp_path / "async_test.csv"
        test_file.write_text("async data")

        upload_count = [0]
        async def fake_upload_async(path, purpose="assistants"):
            upload_count[0] += 1
            return "file_async_123"

        fake_client = SimpleNamespace(upload_file_async=fake_upload_async)
        resolver = AttachmentResolver(ai_client=fake_client)

        r1 = await resolver.resolve_attachment_async({"path": str(test_file)}, kind="file")
        assert r1 == {"file_id": "file_async_123"}

        r2 = await resolver.resolve_attachment_async({"path": str(test_file)}, kind="file")
        assert r2 == {"file_id": "file_async_123"}
        assert upload_count[0] == 1  # Cached

    @pytest.mark.asyncio
    async def test_async_path_entry_nonexistent_file_raises(self, tmp_path):
        """Async resolve should fail fast for a missing explicit local path."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver, AttachmentNotFoundError
        fake_client = SimpleNamespace(
            upload_file_async=lambda path, purpose="assistants": "file_async_unused",
        )
        resolver = AttachmentResolver(ai_client=fake_client)

        with pytest.raises(AttachmentNotFoundError, match="file not found"):
            await resolver.resolve_attachment_async(
                {"path": str(tmp_path / "missing-async.csv")},
                kind="file",
            )

    @pytest.mark.asyncio
    async def test_async_resolve_messages(self, tmp_path):
        """Async resolve_messages should resolve all paths."""
        from chatsnack.runtime.attachment_resolver import AttachmentResolver
        test_file = tmp_path / "async_batch.csv"
        test_file.write_text("batch data")

        async def fake_upload_async(path, purpose="assistants"):
            return "file_async_batch"

        fake_client = SimpleNamespace(upload_file_async=fake_upload_async)
        resolver = AttachmentResolver(ai_client=fake_client)

        messages = [{
            "role": "user",
            "content": "Process.",
            "files": [{"path": str(test_file)}],
        }]

        resolved = await resolver.resolve_messages_async(messages)
        assert resolved[0]["files"][0] == {"file_id": "file_async_batch"}
        # Original untouched
        assert messages[0]["files"][0] == {"path": str(test_file)}


class TestHostedToolCallFolding:
    """P2c: normalize_output should capture web_search_call and file_search_call."""

    def test_web_search_call_captured(self):
        from chatsnack.runtime.responses_common import ResponsesNormalizationMixin
        mixin = ResponsesNormalizationMixin()

        response_dict = {
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "action": {
                        "type": "search",
                        "search_queries": ["python docs"],
                        "sources": [
                            {"url": "https://docs.python.org", "title": "Python Docs", "snippet": "..."}
                        ],
                    },
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Here are the results."}],
                },
            ]
        }

        msg, phase = mixin.normalize_output(response_dict)
        assert msg.content == "Here are the results."
        assert msg.sources[0]["url"] == "https://docs.python.org"
        assert len(msg.provider_extras["hosted_tool_calls"]) == 1
        assert msg.provider_extras["hosted_tool_calls"][0]["type"] == "web_search_call"
        assert msg.provider_extras["hosted_tool_calls"][0]["action"]["sources"][0]["url"] == "https://docs.python.org"

    def test_file_search_call_captured(self):
        from chatsnack.runtime.responses_common import ResponsesNormalizationMixin
        mixin = ResponsesNormalizationMixin()

        response_dict = {
            "output": [
                {
                    "type": "file_search_call",
                    "id": "fs_1",
                    "results": [
                        {"file_id": "file_123", "text": "Matching doc content."}
                    ],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Found it."}],
                },
            ]
        }

        msg, phase = mixin.normalize_output(response_dict)
        assert msg.content == "Found it."
        assert len(msg.provider_extras["hosted_tool_calls"]) == 1
        assert msg.provider_extras["hosted_tool_calls"][0]["type"] == "file_search_call"

    def test_hosted_tool_calls_land_in_provider_extras_on_turn(self):
        from chatsnack.chat.mixin_query import ChatQueryMixin
        from chatsnack.runtime.types import NormalizedAssistantMessage

        msg = NormalizedAssistantMessage(
            content="Results found.",
            provider_extras={"hosted_tool_calls": [{"type": "web_search_call", "id": "ws_1", "action": {"type": "search"}}]},
        )
        turn = ChatQueryMixin._assistant_response_to_turn(msg)
        # When provider_extras are present, should be expanded form
        assert isinstance(turn, dict)
        assert turn["text"] == "Results found."
        assert len(turn["provider_extras"]["hosted_tool_calls"]) == 1
        assert turn["provider_extras"]["hosted_tool_calls"][0]["type"] == "web_search_call"

    def test_no_provider_extras_stays_scalar(self):
        from chatsnack.chat.mixin_query import ChatQueryMixin
        from chatsnack.runtime.types import NormalizedAssistantMessage

        msg = NormalizedAssistantMessage(content="Plain response.")
        turn = ChatQueryMixin._assistant_response_to_turn(msg)
        assert turn == "Plain response."
