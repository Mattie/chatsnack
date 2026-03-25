"""Phase 3 runtime-boundary tests.

These tests verify that Phase 3 YAML config actually reaches the provider API,
that expanded turns produce mixed-content input, that runtime metadata bridges
into params.responses.state, and that provider-native tools pass through
without being wrapped in function-tool schema.

All tests are offline (no live API calls).
"""

import warnings
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
        params = ChatParams(model="gpt-5.4")
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

    def test_local_path_image_skipped_with_warning(self):
        """A user image with only path: should be skipped (not sent as file_id)."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_skip", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            adapter.create_completion(
                messages=[{
                    "role": "user",
                    "content": "Describe this image.",
                    "images": [{"path": "/tmp/photo.png"}],
                }],
                model="gpt-5.4",
            )

        # The local-path image should NOT appear in the input.
        content_parts = captured["input"][0]["content"]
        assert all(p["type"] != "input_image" for p in content_parts), \
            "Local-path image should be skipped, not sent as input_image"
        # Only the text part should remain.
        assert len(content_parts) == 1
        assert content_parts[0] == {"type": "input_text", "text": "Describe this image."}
        # A warning should have been emitted.
        path_warnings = [x for x in w if "photo.png" in str(x.message)]
        assert len(path_warnings) == 1

    def test_local_path_file_skipped_with_warning(self):
        """A user file with only path: should be skipped (not sent as file_id)."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_skip2", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            adapter.create_completion(
                messages=[{
                    "role": "user",
                    "content": "Summarize this file.",
                    "files": [{"path": "./data/sales.csv"}],
                }],
                model="gpt-5.4",
            )

        content_parts = captured["input"][0]["content"]
        assert all(p["type"] != "input_file" for p in content_parts), \
            "Local-path file should be skipped, not sent as input_file"
        assert len(content_parts) == 1
        assert content_parts[0] == {"type": "input_text", "text": "Summarize this file."}
        path_warnings = [x for x in w if "sales.csv" in str(x.message)]
        assert len(path_warnings) == 1

    def test_mixed_file_id_and_local_path_keeps_file_id_only(self):
        """When a turn has both file_id and path entries, only file_id should be sent."""
        captured = {}

        def create(**kwargs):
            captured.update(kwargs)
            return _FakeObj({"id": "resp_mix", "status": "completed", "model": "gpt-5.4", "output": []})

        ai = SimpleNamespace(client=SimpleNamespace(responses=SimpleNamespace(create=create)))
        adapter = ResponsesAdapter(ai)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            adapter.create_completion(
                messages=[{
                    "role": "user",
                    "content": "Analyze these.",
                    "files": [
                        {"file_id": "file_real_123"},
                        {"path": "./local/data.csv"},
                    ],
                }],
                model="gpt-5.4",
            )

        content_parts = captured["input"][0]["content"]
        file_parts = [p for p in content_parts if p["type"] == "input_file"]
        assert len(file_parts) == 1
        assert file_parts[0]["file_id"] == "file_real_123"
        path_warnings = [x for x in w if "data.csv" in str(x.message)]
        assert len(path_warnings) == 1


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

        assert captured["tools"] == [
            {"type": "web_search"},
            {"type": "function", "function": {"name": "my_func"}},
        ]
