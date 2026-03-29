"""Hosted tool/utensil surface tests.

Tests cover the _UtensilNamespace callable object, hosted utensil specs,
group namespaces, Chat integration, and YAML round-trip.
"""
import json
import pytest
from pathlib import Path
from ruamel.yaml import YAML

from chatsnack import Chat, utensil, HostedUtensil, CHATSNACK_BASE_DIR
from chatsnack.chat.mixin_params import ChatParams
from chatsnack.utensil import (
    UtensilGroup, UtensilFunction, HostedUtensil,
    get_openai_tools, extract_utensil_functions, collect_include_entries,
    _REGISTRY,
)


# ── Goal test ─────────────────────────────────────────────────────────

class TestGoalReadmeStyleExample:
    """Goal: README-style example works end-to-end without set_tools()
    or direct params.responses mutation."""

    def test_mixed_utensils_no_set_tools_no_params_mutation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data_dir = Path(CHATSNACK_BASE_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)

        crm = utensil.group("crm", "CRM tools for customer lookup and order management.")

        @crm
        def get_customer(customer_id: str):
            """Look up one customer by ID."""
            return {"id": customer_id}

        @crm
        def list_open_orders(customer_id: str):
            """List open orders for a customer ID."""
            return []

        docs_search = utensil.web_search(domains=["docs.python.org"], sources=True)

        chat = Chat(
            "Use tools only when useful.",
            utensils=[crm, utensil.tool_search, docs_search],
        )
        chat.reasoning.summary = "auto"

        # Tools present
        tools = chat.params.get_tools()
        tool_types = [t.get("type") for t in tools]
        assert "namespace" in tool_types
        assert "tool_search" in tool_types
        assert "web_search" in tool_types

        # Includes auto-populated
        includes = chat.params.responses.get("include", [])
        assert "web_search_call.action.sources" in includes

        # YAML round-trip
        yaml_text = chat.yaml
        assert "crm:" in yaml_text
        assert "- tool_search" in yaml_text
        assert "web_search_call.action.sources" in yaml_text

        # No set_tools() or params.responses["include"] manual mutation used
        # — all wired through utensils=[] only.


# ── Steer tests ───────────────────────────────────────────────────────

class TestDecoratorBackwardCompat:
    """@utensil still works as a decorator, unchanged."""

    def test_plain_decorator(self):
        initial_count = len(_REGISTRY)

        @utensil
        def sample_tool(x: int):
            """A sample."""
            return x

        assert hasattr(sample_tool, "__utensil__")
        assert isinstance(sample_tool.__utensil__, UtensilFunction)
        assert len(_REGISTRY) > initial_count

    def test_keyword_decorator(self):
        @utensil(name="custom_name", description="Custom desc")
        def another_tool(a: str):
            """Another."""
            return a

        assert another_tool.__utensil__.name == "custom_name"
        assert another_tool.__utensil__.description == "Custom desc"


class TestUtensilGroup:
    """utensil.group() creates decorator/group objects passable in utensils=[]."""

    def test_group_creation_and_decoration(self):
        grp = utensil.group("mytools", "My tool group.")
        assert isinstance(grp, UtensilGroup)
        assert grp.name == "mytools"
        assert grp.description == "My tool group."

        @grp
        def tool_a(q: str):
            """Tool A."""
            return q

        @grp
        def tool_b(n: int):
            """Tool B."""
            return n

        assert len(grp.utensils) == 2
        assert grp.utensils[0].name == "tool_a"
        assert grp.utensils[1].name == "tool_b"

    def test_group_to_namespace_tool_dict(self):
        grp = utensil.group("ns", "Namespace desc.")

        @grp
        def fn(x: str):
            """Do something."""
            return x

        ns_dict = grp.to_namespace_tool_dict()
        assert ns_dict["type"] == "namespace"
        assert ns_dict["name"] == "ns"
        assert ns_dict["description"] == "Namespace desc."
        assert len(ns_dict["tools"]) == 1
        assert ns_dict["tools"][0]["function"]["name"] == "fn"

    def test_group_replaces_duplicate_names(self):
        grp = utensil.group("dedup", "Dedup group.")

        @grp
        def same_name(x: str):
            """Version 1."""
            return x

        @grp(name="same_name")
        def updated(x: str):
            """Version 2."""
            return x

        assert len(grp.utensils) == 1
        assert grp.utensils[0].description == "Version 2."

    def test_group_legacy_add_still_works(self):
        grp = utensil.group("legacy_grp", "Legacy.")

        @grp.add
        def old_style(a: int):
            """Old style."""
            return a

        assert len(grp.utensils) == 1


class TestHostedUtensils:
    """Hosted utensil specs for built-in OpenAI tools."""

    def test_zero_config_tool_search(self):
        ts = utensil.tool_search
        assert isinstance(ts, HostedUtensil)
        assert ts.to_tool_dict() == {"type": "tool_search"}
        assert ts.get_include_entries() == []

    def test_zero_config_code_interpreter(self):
        ci = utensil.code_interpreter
        assert isinstance(ci, HostedUtensil)
        assert ci.to_tool_dict() == {"type": "code_interpreter"}

    def test_zero_config_image_generation(self):
        ig = utensil.image_generation
        assert isinstance(ig, HostedUtensil)
        assert ig.to_tool_dict() == {"type": "image_generation"}

    def test_web_search_with_domains_and_sources(self):
        ws = utensil.web_search(domains=["docs.python.org"], sources=True)
        assert isinstance(ws, HostedUtensil)
        td = ws.to_tool_dict()
        assert td["type"] == "web_search"
        assert td["filters"]["allowed_domains"] == ["docs.python.org"]
        assert ws.get_include_entries() == ["web_search_call.action.sources"]

    def test_web_search_no_sources(self):
        ws = utensil.web_search(domains=["example.com"])
        assert ws.get_include_entries() == []

    def test_web_search_extra_kwargs(self):
        ws = utensil.web_search(external_web_access=True, user_location={"type": "approximate", "country": "US"})
        td = ws.to_tool_dict()
        assert td["external_web_access"] is True
        assert td["user_location"]["country"] == "US"

    def test_file_search_with_results(self):
        fs = utensil.file_search(vector_store_ids=["vs_123"], max_num_results=5, results=True)
        td = fs.to_tool_dict()
        assert td["type"] == "file_search"
        assert td["vector_store_ids"] == ["vs_123"]
        assert td["max_num_results"] == 5
        assert fs.get_include_entries() == ["file_search_call.results"]

    def test_mcp_builder(self):
        m = utensil.mcp(server_label="github", connector_id="conn_gh",
                        allowed_tools=["search_repos"], require_approval="always")
        td = m.to_tool_dict()
        assert td["type"] == "mcp"
        assert td["server_label"] == "github"
        assert td["connector_id"] == "conn_gh"
        assert td["allowed_tools"] == ["search_repos"]
        assert td["require_approval"] == "always"
        assert m.get_include_entries() == []


class TestGetOpenaiToolsMixed:
    """get_openai_tools handles local, group, and hosted items."""

    def test_mixed_list(self):
        grp = utensil.group("mixed_ns", "Mix.")

        @grp
        def fn(x: str):
            """Fn."""
            return x

        @utensil
        def standalone(y: int):
            """Standalone."""
            return y

        hosted = utensil.web_search(domains=["example.com"])
        tools = get_openai_tools([standalone, grp, utensil.tool_search, hosted])
        types_and_names = [(t.get("type"), t.get("name") or t.get("function", {}).get("name")) for t in tools]

        # standalone function → type="function"
        assert ("function", "standalone") in types_and_names
        # group → type="namespace"
        assert ("namespace", "mixed_ns") in types_and_names
        # tool_search → type="tool_search"
        assert any(t == "tool_search" for t, _ in types_and_names)
        # web_search → type="web_search"
        assert any(t == "web_search" for t, _ in types_and_names)


class TestCollectIncludeEntries:
    """collect_include_entries gathers implied includes."""

    def test_multiple_hosted_with_includes(self):
        ws = utensil.web_search(domains=["a.com"], sources=True)
        fs = utensil.file_search(vector_store_ids=["vs_1"], results=True)
        ts = utensil.tool_search
        entries = collect_include_entries([ws, fs, ts])
        assert "web_search_call.action.sources" in entries
        assert "file_search_call.results" in entries
        assert len(entries) == 2

    def test_no_hosted(self):
        @utensil
        def plain(x: str):
            """P."""
            return x
        assert collect_include_entries([plain]) == []


class TestChatIntegration:
    """Chat.__init__ correctly wires utensils, tools, and includes."""

    def test_hosted_utensils_populate_include(self):
        ws = utensil.web_search(domains=["docs.python.org"], sources=True)
        chat = Chat("Help.", utensils=[ws])
        includes = chat.params.responses.get("include", [])
        assert "web_search_call.action.sources" in includes

    def test_no_duplicate_includes(self):
        ws = utensil.web_search(domains=["a.com"], sources=True)
        chat = Chat("Help.", utensils=[ws])
        # Add same utensil to a new chat forked from this one (simulating reuse)
        includes = chat.params.responses["include"]
        assert includes.count("web_search_call.action.sources") == 1

    def test_group_appears_as_namespace_in_tools(self):
        grp = utensil.group("test_ns", "Test namespace.")

        @grp
        def helper(q: str):
            """Help."""
            return q

        chat = Chat("Be helpful.", utensils=[grp])
        tools = chat.params.get_tools()
        ns_tools = [t for t in tools if t.get("type") == "namespace"]
        assert len(ns_tools) == 1
        assert ns_tools[0]["name"] == "test_ns"


class TestYamlRoundTrip:
    """Hosted utensils and groups round-trip through YAML correctly."""

    def test_mixed_utensils_yaml_save_load(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data_dir = Path(CHATSNACK_BASE_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)

        crm = utensil.group("yaml_crm", "CRM tools.")

        @crm
        def get_customer(customer_id: str):
            """Look up customer."""
            return {}

        ws = utensil.web_search(domains=["docs.python.org"], sources=True)
        chat = Chat(
            "Use tools when useful.",
            name="yaml_round_trip_test",
            utensils=[crm, utensil.tool_search, ws],
        )

        # Save
        yaml_text = chat.yaml
        assert "yaml_crm:" in yaml_text
        assert "- tool_search" in yaml_text
        assert "web_search_call.action.sources" in yaml_text

        # Write to file and reload
        yaml_obj = YAML()
        with open(data_dir / "yaml_round_trip_test.yml", "w", encoding="utf-8") as f:
            yaml_obj.dump(yaml_obj.load(yaml_text), f)

        loaded = Chat(name="yaml_round_trip_test")
        tools = loaded.params.get_tools()
        tool_types = [t.get("type") for t in tools]
        assert "namespace" in tool_types
        assert "tool_search" in tool_types
        assert "web_search" in tool_types

        # Include entries survive the round-trip
        includes = (loaded.params.responses or {}).get("include", [])
        assert "web_search_call.action.sources" in includes


# ── Unit tests ────────────────────────────────────────────────────────

class TestHostedUtensilRepr:
    def test_repr_zero_config(self):
        ts = utensil.tool_search
        assert "tool_search" in repr(ts)

    def test_repr_configured(self):
        ws = utensil.web_search(domains=["a.com"])
        r = repr(ws)
        assert "web_search" in r
        assert "filters" in r


class TestImplicitDeferLoading:
    """P2b: tool_search presence should inject defer_loading for namespace children."""

    def test_namespace_children_get_defer_loading_with_tool_search(self):
        grp = utensil.group("ns", "Namespace.")

        @grp
        def helper(q: str):
            """Help."""
            return q

        tools = get_openai_tools([grp, utensil.tool_search])
        ns = [t for t in tools if t.get("type") == "namespace"][0]
        for child in ns.get("tools", []):
            assert child.get("defer_loading") is True, "Child tools should have defer_loading when tool_search is present"

    def test_no_defer_loading_without_tool_search(self):
        grp = utensil.group("ns2", "Namespace2.")

        @grp
        def fn(x: str):
            """Fn."""
            return x

        tools = get_openai_tools([grp])
        ns = [t for t in tools if t.get("type") == "namespace"][0]
        for child in ns.get("tools", []):
            assert "defer_loading" not in child, "No defer_loading without tool_search"
