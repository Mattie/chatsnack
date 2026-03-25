"""Phase 3 YAML tests – round-trip, normalization, fidelity, and acceptance criteria.

These tests cover the Phase 3 RFC requirements without needing live API access.
They validate the YAML serializer/parser, developer alias handling, expanded turn
normalization, canonical field ordering, fidelity gating, and provider_extras routing.
"""

import copy
import os
import shutil
import textwrap

import pytest
from ruamel.yaml import YAML as RuamelYAML

from chatsnack import Chat, ChatParams, CHATSNACK_BASE_DIR


# ── Helpers ──────────────────────────────────────────────────────────────

def _yaml():
    y = RuamelYAML()
    y.preserve_quotes = True
    return y


def _parse_yaml(text: str):
    """Parse a YAML string into a Python dict."""
    from io import StringIO
    return _yaml().load(StringIO(text))


@pytest.fixture(scope="function", autouse=True)
def setup_and_cleanup():
    chatsnack_dir = os.path.abspath(CHATSNACK_BASE_DIR)
    safe_to_cleanup = os.path.commonpath([os.path.abspath(os.getcwd()), chatsnack_dir]) == os.path.abspath(os.getcwd())
    if safe_to_cleanup and os.path.exists(chatsnack_dir):
        shutil.rmtree(chatsnack_dir)
    os.makedirs(chatsnack_dir, exist_ok=True)
    yield
    import time
    time.sleep(0.5)
    if safe_to_cleanup and os.path.exists(chatsnack_dir):
        try:
            shutil.rmtree(chatsnack_dir)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 1. Basic YAML shape
# ═══════════════════════════════════════════════════════════════════════════

class TestBasicYAMLShape:
    """messages: stays the main transcript surface and params: stays the config surface."""

    def test_simple_text_chat_round_trip(self):
        chat = Chat(name="phase3_simple")
        chat.system("Respond tersely.")
        chat.user("What is chatsnack?")
        chat.assistant("A chat-oriented prompt library.")
        chat.params = ChatParams(model="gpt-5.4", runtime="responses")
        chat.save()

        loaded = Chat(name="phase3_simple")
        assert loaded.system_message == "Respond tersely."
        msgs = loaded.messages
        assert len(msgs) == 3
        assert msgs[0] == {"system": "Respond tersely."}
        assert msgs[1] == {"user": "What is chatsnack?"}
        assert msgs[2] == {"assistant": "A chat-oriented prompt library."}

    def test_params_session_round_trips(self):
        chat = Chat(name="phase3_session")
        chat.system("Keep the reply short.")
        chat.params = ChatParams(model="gpt-5.4", runtime="responses", session="inherit")
        chat.save()

        loaded = Chat(name="phase3_session")
        assert loaded.params.session == "inherit"
        assert loaded.params.runtime == "responses"

    def test_params_session_omitted_when_unset(self):
        chat = Chat(name="phase3_no_session")
        chat.system("Respond tersely.")
        chat.params = ChatParams(model="gpt-5.4", runtime="responses")
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        # session should not appear when it's None
        assert "session" not in (parsed.get("params") or {})

    def test_params_responses_nested_config_round_trips(self):
        chat = Chat(name="phase3_responses_config")
        chat.system("Support the user's request.")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={
                "store": True,
                "text": {"format": {"type": "text"}, "verbosity": "medium"},
                "reasoning": {"effort": "medium", "summary": "auto"},
                "include": ["reasoning.encrypted_content", "web_search_call.action.sources"],
            },
        )
        chat.save()

        loaded = Chat(name="phase3_responses_config")
        assert loaded.params.responses is not None
        assert loaded.params.responses["store"] is True
        assert loaded.params.responses["reasoning"]["effort"] == "medium"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Role aliasing and save order
# ═══════════════════════════════════════════════════════════════════════════

class TestRoleAliasing:
    def test_system_saves_as_canonical_key(self):
        chat = Chat(name="phase3_system")
        chat.system("Follow the house style guide.")
        chat.user("Draft a release note.")
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        assert any("system" in m for m in parsed["messages"])
        assert not any("developer" in m for m in parsed["messages"])

    def test_developer_loads_as_alias_and_saves_as_system(self):
        """Load a YAML file with developer, verify it normalizes to system."""
        chat = Chat(name="phase3_dev_alias")
        # Manually inject a developer message (simulating YAML load)
        chat.messages = [
            {"developer": "Follow the house style guide."},
            {"user": "Draft a release note."},
        ]
        chat.save()

        # After save, it should be system
        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        msgs = parsed["messages"]
        assert msgs[0].get("system") == "Follow the house style guide."
        assert "developer" not in msgs[0]

    def test_mixed_system_and_developer_preserve_turn_boundaries(self):
        """Mixed system and developer should keep separate turns, both saved as system."""
        chat = Chat(name="phase3_mixed_roles")
        chat.messages = [
            {"system": "First instruction."},
            {"developer": "Second instruction."},
            {"user": "A question."},
        ]
        chat.save()

        loaded = Chat(name="phase3_mixed_roles")
        msgs = loaded.messages
        assert len(msgs) == 3
        assert msgs[0] == {"system": "First instruction."}
        assert msgs[1] == {"system": "Second instruction."}
        assert msgs[2] == {"user": "A question."}

    def test_no_accidental_turn_collapse(self):
        """Adjacent system turns should not be collapsed into one."""
        chat = Chat(name="phase3_no_collapse")
        chat.messages = [
            {"system": "Rule one."},
            {"system": "Rule two."},
            {"user": "Question."},
        ]
        chat.save()

        loaded = Chat(name="phase3_no_collapse")
        assert len(loaded.messages) == 3

    def test_developer_alias_in_get_messages(self):
        """get_messages() should return 'system' role even when source had 'developer'."""
        chat = Chat(name="phase3_dev_get_msgs")
        chat.messages = [
            {"developer": "Follow the house style guide."},
            {"user": "Draft a release note."},
        ]
        api_msgs = chat.get_messages()
        assert api_msgs[0]["role"] == "system"
        assert api_msgs[0]["content"] == "Follow the house style guide."

    def test_developer_method_stores_as_system(self):
        """The developer() convenience method should store as system."""
        chat = Chat(name="phase3_dev_method")
        chat.developer("Follow the house style guide.")
        assert chat.messages[0] == {"system": "Follow the house style guide."}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Mixed turns and normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestMixedTurnsAndNormalization:
    def test_scalar_turns_stay_scalar_after_round_trip(self):
        chat = Chat(name="phase3_scalar_rt")
        chat.system("Respond tersely.")
        chat.user("What is chatsnack?")
        chat.assistant("A chat-oriented prompt library.")
        chat.save()

        loaded = Chat(name="phase3_scalar_rt")
        assert loaded.messages[2] == {"assistant": "A chat-oriented prompt library."}

    def test_expanded_assistant_turn_round_trips(self):
        chat = Chat(name="phase3_expanded_asst")
        chat.system("Support the user's request.")
        chat.messages.append({
            "user": "What's the current population of Nigeria?"
        })
        chat.messages.append({
            "assistant": {
                "text": "Nigeria's current population is about 242.4 million.",
                "reasoning": "Searching Wikipedia for population data.",
                "sources": [
                    {"title": "Demographics of Nigeria", "url": "https://en.wikipedia.org/wiki/Demographics_of_Nigeria"}
                ],
            }
        })
        chat.save()

        loaded = Chat(name="phase3_expanded_asst")
        asst = loaded.messages[2]
        assert "assistant" in asst
        content = asst["assistant"]
        assert isinstance(content, dict)
        assert content["text"] == "Nigeria's current population is about 242.4 million."
        assert content["reasoning"] == "Searching Wikipedia for population data."
        assert len(content["sources"]) == 1

    def test_expanded_user_turn_with_images(self):
        chat = Chat(name="phase3_user_images")
        chat.messages = [
            {"user": {
                "text": "Describe the UI problems in this screenshot.",
                "images": [{"path": "./assets/dashboard.png"}],
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_user_images")
        user_msg = loaded.messages[0]
        assert "user" in user_msg
        content = user_msg["user"]
        assert content["text"] == "Describe the UI problems in this screenshot."
        assert len(content["images"]) == 1

    def test_expanded_user_turn_with_files(self):
        chat = Chat(name="phase3_user_files")
        chat.messages = [
            {"user": {
                "text": "Summarize this PDF.",
                "files": [{"path": "./reports/annual-letter.pdf"}],
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_user_files")
        user_msg = loaded.messages[0]
        content = user_msg["user"]
        assert content["text"] == "Summarize this PDF."
        assert len(content["files"]) == 1

    def test_canonical_field_ordering_on_save(self):
        """Fields out of order in source should be re-saved in canonical order."""
        chat = Chat(name="phase3_field_order")
        chat.messages = [
            {"assistant": {
                "images": [{"file_id": "file_img_456"}],
                "text": "Generated one chart.",
                "reasoning": "Summarized the table first.",
            }},
        ]
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        asst = parsed["messages"][0]["assistant"]
        keys = list(asst.keys())
        assert keys.index("text") < keys.index("reasoning")
        assert keys.index("reasoning") < keys.index("images")

    def test_expanded_assistant_with_files_and_images(self):
        chat = Chat(name="phase3_asst_mixed_assets")
        chat.messages = [
            {"assistant": {
                "text": "I created a cleaned CSV and a chart.",
                "reasoning": "Grouped the rows before generating the chart.",
                "files": [{"file_id": "file_csv_123", "filename": "sales-cleaned.csv"}],
                "images": [{"file_id": "file_img_456", "filename": "sales-chart.png"}],
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_asst_mixed_assets")
        asst = loaded.messages[0]["assistant"]
        assert asst["text"] == "I created a cleaned CSV and a chart."
        assert len(asst["files"]) == 1
        assert len(asst["images"]) == 1

    def test_unknown_fields_routed_to_provider_extras(self):
        """Unknown top-level fields on expanded turn → provider_extras."""
        chat = Chat(name="phase3_unknown_fields")
        chat.messages = [
            {"assistant": {
                "text": "Here is the answer.",
                "debug_trace": {"cache_hit": True},
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_unknown_fields")
        asst = loaded.messages[0]["assistant"]
        assert "debug_trace" not in asst
        assert "provider_extras" in asst
        assert asst["provider_extras"]["debug_trace"]["cache_hit"] is True

    def test_explicit_provider_extras_survive_round_trip(self):
        chat = Chat(name="phase3_explicit_extras")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"export_state": True},
        )
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "provider_extras": {"custom_field": "preserved"},
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_explicit_extras")
        asst = loaded.messages[0]["assistant"]
        assert asst["provider_extras"]["custom_field"] == "preserved"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Fidelity and persistence boundaries
# ═══════════════════════════════════════════════════════════════════════════

class TestFidelity:
    def test_authoring_fidelity_omits_state_and_provider_extras(self):
        """Default authoring fidelity should omit state and provider_extras."""
        chat = Chat(name="phase3_auth_fidelity")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"store": True},
        )
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "provider_extras": {"internal_id": "xyz"},
            }},
        ]
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        # In authoring fidelity, provider_extras and encrypted_content are dropped
        asst = parsed["messages"][0]
        # Should collapse to scalar since only text remains after fidelity gating
        assert asst.get("assistant") == "Answer."

    def test_authoring_fidelity_drops_encrypted_content(self):
        chat = Chat(name="phase3_auth_no_encrypted")
        chat.params = ChatParams(model="gpt-5.4", runtime="responses")
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "encrypted_content": "gAAAAAB...trimmed...",
                "reasoning": "Thinking about the answer.",
            }},
        ]
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        asst = parsed["messages"][0]["assistant"]
        assert "encrypted_content" not in asst
        assert asst["reasoning"] == "Thinking about the answer."

    def test_continuation_fidelity_keeps_state(self):
        chat = Chat(name="phase3_cont_fidelity")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={
                "store": True,
                "export_state": True,
                "state": {
                    "response_id": "resp_latest",
                    "previous_response_id": "resp_prev",
                    "status": "completed",
                },
            },
        )
        chat.messages = [
            {"system": "Continue the draft."},
            {"user": "Add one more paragraph."},
        ]
        chat.save()

        loaded = Chat(name="phase3_cont_fidelity")
        state = loaded.params.responses.get("state")
        assert state is not None
        assert state["response_id"] == "resp_latest"
        assert state["status"] == "completed"

    def test_continuation_fidelity_keeps_provider_extras(self):
        chat = Chat(name="phase3_cont_extras")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"export_state": True},
        )
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "provider_extras": {"internal_id": "xyz"},
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_cont_extras")
        asst = loaded.messages[0]["assistant"]
        assert asst["provider_extras"]["internal_id"] == "xyz"

    def test_continuation_fidelity_keeps_encrypted_content(self):
        chat = Chat(name="phase3_cont_encrypted")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={"export_state": True},
        )
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "encrypted_content": "gAAAAAB...trimmed...",
                "reasoning": "Thinking.",
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_cont_encrypted")
        asst = loaded.messages[0]["assistant"]
        assert asst["encrypted_content"] == "gAAAAAB...trimmed..."

    def test_authoring_fidelity_omits_state(self):
        """State should be omitted when export_state is not true."""
        chat = Chat(name="phase3_auth_no_state")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={
                "store": True,
                "state": {
                    "response_id": "resp_123",
                    "status": "completed",
                },
            },
        )
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        responses = parsed.get("params", {}).get("responses", {})
        assert "state" not in responses

    def test_diagnostic_fidelity_keeps_provider_dump(self):
        chat = Chat(name="phase3_diag_fidelity")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={
                "export_diagnostics": True,
                "provider_dump": {"raw_response": {"id": "resp_123"}},
            },
        )
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "provider_extras": {"internal_id": "xyz"},
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_diag_fidelity")
        assert loaded.params.responses["provider_dump"]["raw_response"]["id"] == "resp_123"
        asst = loaded.messages[0]["assistant"]
        assert asst["provider_extras"]["internal_id"] == "xyz"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Params and tools
# ═══════════════════════════════════════════════════════════════════════════

class TestParamsAndTools:
    def test_params_responses_nested_fields(self):
        chat = Chat(name="phase3_responses_fields")
        chat.params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
            responses={
                "store": True,
                "export_state": True,
                "text": {"format": {"type": "text"}, "verbosity": "medium"},
                "reasoning": {"effort": "medium", "summary": "auto"},
                "include": ["reasoning.encrypted_content"],
            },
        )
        chat.save()

        loaded = Chat(name="phase3_responses_fields")
        r = loaded.params.responses
        assert r["store"] is True
        assert r["text"]["verbosity"] == "medium"
        assert r["reasoning"]["summary"] == "auto"
        assert "reasoning.encrypted_content" in r["include"]

    def test_provider_native_tool_raw_dict_passthrough(self):
        """params.tools should accept raw provider-native tool dicts like web_search."""
        params = ChatParams(
            model="gpt-5.4",
            runtime="responses",
        )
        params.set_tools([
            {"type": "web_search"},
            {"type": "function", "function": {"name": "lookup", "parameters": {}}},
        ])

        result = params.get_tools()
        assert len(result) == 2
        types = [t["type"] for t in result]
        assert "web_search" in types
        assert "function" in types
        # web_search should NOT have a function wrapper
        ws = [t for t in result if t["type"] == "web_search"][0]
        assert "function" not in ws

    def test_local_function_tool_history_format(self):
        """Existing chatsnack tool call format should be preserved."""
        chat = Chat(name="phase3_tool_format")
        chat.messages = [
            {"assistant": {
                "tool_calls": [
                    {"name": "get_weather", "arguments": {"location": "Austin"}},
                ],
            }},
            {"tool": {"tool_call_id": "call_123", "content": {"forecast": "sunny"}}},
            {"assistant": "It is sunny in Austin."},
        ]
        chat.save()

        loaded = Chat(name="phase3_tool_format")
        assert loaded.messages[0]["assistant"]["tool_calls"][0]["name"] == "get_weather"
        assert loaded.messages[1]["tool"]["tool_call_id"] == "call_123"
        assert loaded.messages[2]["assistant"] == "It is sunny in Austin."


# ═══════════════════════════════════════════════════════════════════════════
# 6. NormalizedTurn unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizedTurn:
    def test_scalar_system_round_trip(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn.from_message_dict({"system": "Be brief."})
        assert turn.role == "system"
        assert turn.text == "Be brief."
        result = turn.to_message_dict()
        assert result == {"system": "Be brief."}

    def test_developer_normalizes_to_system(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn.from_message_dict({"developer": "House style."})
        assert turn.role == "system"
        result = turn.to_message_dict()
        assert result == {"system": "House style."}

    def test_scalar_assistant_round_trip(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn.from_message_dict({"assistant": "Answer."})
        assert turn.role == "assistant"
        result = turn.to_message_dict()
        assert result == {"assistant": "Answer."}

    def test_expanded_assistant_with_reasoning(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn.from_message_dict({
            "assistant": {
                "text": "Answer.",
                "reasoning": "Thinking.",
            }
        })
        assert turn.text == "Answer."
        assert turn.reasoning == "Thinking."
        result = turn.to_message_dict()
        assert result["assistant"]["text"] == "Answer."
        assert result["assistant"]["reasoning"] == "Thinking."

    def test_unknown_field_goes_to_provider_extras(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn.from_message_dict({
            "assistant": {
                "text": "Answer.",
                "debug_trace": {"cache_hit": True},
            }
        })
        assert turn.provider_extras == {"debug_trace": {"cache_hit": True}}

    def test_tool_message_round_trip(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn.from_message_dict({
            "tool": {"tool_call_id": "call_123", "content": "result"}
        })
        assert turn.role == "tool"
        result = turn.to_message_dict()
        assert result["tool"]["tool_call_id"] == "call_123"

    def test_fidelity_gating_authoring(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn(
            role="assistant",
            text="Answer.",
            encrypted_content="secret",
            provider_extras={"internal": True},
        )
        result = turn.to_message_dict(fidelity="authoring")
        # Both encrypted_content and provider_extras should be dropped
        assert result == {"assistant": "Answer."}

    def test_fidelity_gating_continuation(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn(
            role="assistant",
            text="Answer.",
            encrypted_content="secret",
            provider_extras={"internal": True},
        )
        result = turn.to_message_dict(fidelity="continuation")
        assert result["assistant"]["encrypted_content"] == "secret"
        assert result["assistant"]["provider_extras"]["internal"] is True

    def test_fidelity_gating_diagnostic(self):
        from chatsnack.chat.turns import NormalizedTurn
        turn = NormalizedTurn(
            role="assistant",
            text="Answer.",
            provider_extras={"internal": True},
        )
        result = turn.to_message_dict(fidelity="diagnostic")
        assert result["assistant"]["provider_extras"]["internal"] is True

    def test_normalize_messages_empty_list(self):
        from chatsnack.chat.turns import normalize_messages
        assert normalize_messages([]) == []

    def test_normalize_messages_mixed(self):
        from chatsnack.chat.turns import normalize_messages
        turns = normalize_messages([
            {"developer": "Instruction."},
            {"user": "Question?"},
            {"assistant": {"text": "Answer.", "reasoning": "Thinking."}},
        ])
        assert len(turns) == 3
        assert turns[0].role == "system"
        assert turns[0].text == "Instruction."
        assert turns[1].role == "user"
        assert turns[2].reasoning == "Thinking."

    def test_denormalize_messages_round_trip(self):
        from chatsnack.chat.turns import normalize_messages, denormalize_messages
        original = [
            {"system": "Be helpful."},
            {"user": "Question."},
            {"assistant": "Answer."},
        ]
        turns = normalize_messages(original)
        result = denormalize_messages(turns)
        assert result == original

    def test_denormalize_messages_fidelity(self):
        from chatsnack.chat.turns import NormalizedTurn, denormalize_messages
        turns = [NormalizedTurn(
            role="assistant",
            text="Answer.",
            provider_extras={"internal": True},
        )]
        authoring = denormalize_messages(turns, fidelity="authoring")
        assert authoring[0] == {"assistant": "Answer."}
        diagnostic = denormalize_messages(turns, fidelity="diagnostic")
        assert "provider_extras" in diagnostic[0]["assistant"]


# ═══════════════════════════════════════════════════════════════════════════
# 7. Round-trip stability
# ═══════════════════════════════════════════════════════════════════════════

class TestRoundTripStability:
    def test_idempotent_save_cycles(self):
        """After one save, repeated saves should be idempotent."""
        chat = Chat(name="phase3_idempotent")
        chat.params = ChatParams(model="gpt-5.4", runtime="responses")
        chat.messages = [
            {"system": "Be helpful."},
            {"user": "Question."},
            {"assistant": {
                "text": "Answer.",
                "reasoning": "Thinking.",
                "sources": [{"title": "Source", "url": "https://example.com"}],
            }},
        ]
        chat.save()
        yaml1 = chat.yaml

        # Load and save again
        loaded = Chat(name="phase3_idempotent")
        loaded.save()
        yaml2 = loaded.yaml

        assert yaml1 == yaml2

    def test_mixed_content_stays_expanded(self):
        """Mixed-content turns should remain expanded after canonicalization."""
        chat = Chat(name="phase3_stays_expanded")
        chat.messages = [
            {"assistant": {
                "text": "Answer.",
                "reasoning": "Thinking.",
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_stays_expanded")
        asst = loaded.messages[0]["assistant"]
        assert isinstance(asst, dict)
        assert "text" in asst
        assert "reasoning" in asst

    def test_text_only_collapses_to_scalar(self):
        """A turn with only text should collapse back to scalar form."""
        chat = Chat(name="phase3_collapse")
        chat.messages = [
            {"assistant": {"text": "Just text."}},
        ]
        chat.save()

        loaded = Chat(name="phase3_collapse")
        # Should have collapsed to scalar
        assert loaded.messages[0] == {"assistant": "Just text."}


# ═══════════════════════════════════════════════════════════════════════════
# 8. End-user acceptance examples from the RFC
# ═══════════════════════════════════════════════════════════════════════════

class TestRFCAcceptanceExamples:
    def test_example1_simple_saved_prompt_asset(self):
        """Example 1: Simple saved prompt asset."""
        chat = Chat(name="phase3_ex1")
        chat.params = ChatParams(model="gpt-5.4", runtime="responses")
        chat.system("Respond tersely.")
        chat.user("What is chatsnack?")
        chat.assistant("A chat-oriented prompt library.")
        chat.save()

        yaml_text = chat.yaml
        parsed = _parse_yaml(yaml_text)
        assert parsed["params"]["model"] == "gpt-5.4"
        msgs = parsed["messages"]
        assert msgs[0] == {"system": "Respond tersely."}
        assert msgs[2] == {"assistant": "A chat-oriented prompt library."}

    def test_example2_explicit_transport_choice(self):
        """Example 2: Saving an explicit transport choice."""
        chat = Chat(name="phase3_ex2")
        chat.params = ChatParams(runtime="responses", session="inherit")
        chat.system("Keep the reply short.")
        chat.user("Give me one sentence on reusable prompts.")
        chat.save()

        loaded = Chat(name="phase3_ex2")
        assert loaded.params.session == "inherit"

    def test_example3_developer_alias_load(self):
        """Example 3: Loading developer as an alias."""
        chat = Chat(name="phase3_ex3")
        chat.messages = [
            {"developer": "Follow the house style guide."},
            {"user": "Draft a release note."},
        ]
        chat.save()

        loaded = Chat(name="phase3_ex3")
        assert loaded.messages[0] == {"system": "Follow the house style guide."}
        assert loaded.system_message == "Follow the house style guide."

    def test_example5_local_function_tool_history(self):
        """Example 5: Local function tool history."""
        chat = Chat(name="phase3_ex5")
        chat.messages = [
            {"assistant": {
                "tool_calls": [
                    {"name": "get_weather", "arguments": {"location": "Austin"}},
                ],
            }},
            {"tool": {"tool_call_id": "call_123", "content": {"forecast": "sunny"}}},
            {"assistant": "It is sunny in Austin."},
        ]
        chat.save()

        loaded = Chat(name="phase3_ex5")
        assert len(loaded.messages) == 3
        assert loaded.messages[2] == {"assistant": "It is sunny in Austin."}

    def test_example6_explicit_continuation_snapshot(self):
        """Example 6: Explicit continuation snapshot export."""
        chat = Chat(name="phase3_ex6")
        chat.params = ChatParams(
            runtime="responses",
            session="new",
            responses={
                "store": True,
                "export_state": True,
                "state": {
                    "response_id": "resp_latest",
                    "previous_response_id": "resp_prev",
                    "status": "completed",
                },
            },
        )
        chat.system("Continue the draft.")
        chat.user("Add one more paragraph.")
        chat.save()

        loaded = Chat(name="phase3_ex6")
        state = loaded.params.responses["state"]
        assert state["response_id"] == "resp_latest"

    def test_example7_attachments_and_generated_outputs(self):
        """Example 7: Attachments and generated outputs."""
        chat = Chat(name="phase3_ex7")
        chat.messages = [
            {"user": {
                "text": "Analyze this CSV and give me a cleaned CSV plus a chart.",
                "files": [{"path": "./data/sales.csv"}],
            }},
            {"assistant": {
                "text": "I created a cleaned CSV and a chart.",
                "files": [{"file_id": "file_csv_123", "filename": "sales-cleaned.csv"}],
                "images": [{"file_id": "file_img_456", "filename": "sales-chart.png"}],
            }},
        ]
        chat.save()

        loaded = Chat(name="phase3_ex7")
        user_msg = loaded.messages[0]["user"]
        assert user_msg["text"] == "Analyze this CSV and give me a cleaned CSV plus a chart."
        assert user_msg["files"][0]["path"] == "./data/sales.csv"
        asst_msg = loaded.messages[1]["assistant"]
        assert asst_msg["files"][0]["file_id"] == "file_csv_123"
        assert asst_msg["images"][0]["file_id"] == "file_img_456"


# ═══════════════════════════════════════════════════════════════════════════
# 9. Expanded turns in get_messages() for API calls
# ═══════════════════════════════════════════════════════════════════════════

class TestExpandedTurnsInGetMessages:
    def test_expanded_user_extracts_text(self):
        chat = Chat(name="phase3_exp_user_api")
        chat.messages = [
            {"user": {
                "text": "Describe the UI.",
                "images": [{"path": "./screenshot.png"}],
            }},
        ]
        api_msgs = chat.get_messages()
        assert api_msgs[0]["role"] == "user"
        assert api_msgs[0]["content"] == "Describe the UI."

    def test_expanded_assistant_extracts_text(self):
        chat = Chat(name="phase3_exp_asst_api")
        chat.messages = [
            {"assistant": {
                "text": "Here is the answer.",
                "reasoning": "Let me think.",
                "sources": [{"title": "Src", "url": "https://example.com"}],
            }},
        ]
        api_msgs = chat.get_messages()
        assert api_msgs[0]["role"] == "assistant"
        assert api_msgs[0]["content"] == "Here is the answer."
