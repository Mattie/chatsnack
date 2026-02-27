"""Chatsnack-thonic planner-routing example with YAML + text fillings.

Flow per user question:
1) Use planner calls on `codex-mini-latest` to rank relevance for tools/skills/memory.
2) Curate those three lists in parallel.
3) Update text fillings and submit the question through a YAML-backed base prompt
   on the original model (for example, `gpt-5.2-codex`).

This keeps conversation continuity while dynamically changing context each turn.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from chatsnack import Chat, Text


@dataclass
class RelevanceRecommendation:
    most_relevant: List[str]
    least_relevant: List[str]
    rationale: str


class ToolCuratedConversation:
    """Curate tools, skills, and memory before each routed chatsnack submission."""

    PLANNER_SYSTEM_PROMPT = (
        "You are a relevance analyst. Do not solve the user task. "
        "Only classify which candidates are most relevant and least relevant. "
        "Respond ONLY as JSON with keys: most_relevant, least_relevant, rationale."
    )

    BASE_SYSTEM_PROMPT_ORIGINAL = (
        "You are a senior coding agent running on gpt-5.2-codex. "
        "Use the Skills and Memory sections as constraints/context. "
        "Give implementation-focused answers and include tradeoffs."
    )

    SYSTEM_REFINER_PROMPT = (
        "You refine system prompts. Produce a shorter version of the provided prompt while "
        "preserving complete intent and behavior. Keep all constraints, remove verbosity, and "
        "avoid adding new requirements. Respond only as JSON with keys: refined_prompt, rationale."
    )

    def __init__(
        self,
        *,
        base_model: str,
        tools: List[Dict[str, Any]],
        skills: List[Dict[str, str]],
        memory: List[Dict[str, str]],
        template_name: str = "ToolCuratorBasePrompt",
    ) -> None:
        self.base_model = base_model
        self.tools = tools
        self.skills = skills
        self.memory = memory
        self.template_name = template_name

        self._ensure_prompt_assets()

        # Start from a YAML-backed prompt template.
        self.agent_chat = Chat(name=self.template_name)
        self.agent_chat.model = self.base_model

    @staticmethod
    def _tool_name(tool: Dict[str, Any]) -> str:
        return tool.get("function", {}).get("name", "")

    @staticmethod
    def _name(item: Dict[str, Any]) -> str:
        return item.get("name", "")

    def _ensure_text(self, name: str, default_content: str) -> None:
        text_obj = Text.objects.get_or_none(name)
        if text_obj is None:
            text_obj = Text(name, default_content)
            text_obj.save()

    def _ensure_prompt_assets(self) -> None:
        """Create YAML template and backing text fillings once."""
        self._ensure_text("ToolCuratorSkills", "- (skills will be curated per turn)")
        self._ensure_text("ToolCuratorMemory", "- (memory will be curated per turn)")
        self._ensure_text("ToolCuratorBaseSystemOriginal", self.BASE_SYSTEM_PROMPT_ORIGINAL)

        refined_prompt = self._ensure_refined_system_prompt()

        template = Chat.objects.get_or_none(self.template_name)
        if template is None:
            template = Chat(
                self.template_name,
                (
                    f"{refined_prompt}\n\n"
                    "## Skills\n{text.ToolCuratorSkills}\n\n"
                    "## Memory\n{text.ToolCuratorMemory}"
                ),
            )
            template.model = self.base_model
            template.save()

    def _ensure_refined_system_prompt(self) -> str:
        """Create (or load) a concise system prompt derived from the original."""
        existing = Text.objects.get_or_none("ToolCuratorBaseSystemRefined")
        if existing is not None and existing.content:
            return existing.content

        source_obj = Text.objects.get_or_none("ToolCuratorBaseSystemOriginal")
        source_prompt = (
            source_obj.content
            if source_obj is not None and source_obj.content
            else self.BASE_SYSTEM_PROMPT_ORIGINAL
        )

        refiner = Chat(system=self.SYSTEM_REFINER_PROMPT)
        refiner.model = "codex-mini-latest"
        payload = json.dumps(
            {
                "source_prompt": source_prompt,
                "goal": "Preserve complete coverage while reducing token count.",
            }
        )

        try:
            raw = refiner.ask(payload)
            data = json.loads(raw)
            refined = data.get("refined_prompt", "").strip()
        except Exception:
            refined = ""

        if not refined:
            refined = source_prompt

        Text("ToolCuratorBaseSystemRefined", refined).save()
        return refined

    def _build_planner_payload(
        self,
        *,
        user_query: str,
        dimension: str,
        candidates: List[Dict[str, str]],
    ) -> str:
        return json.dumps(
            {
                "user_query": user_query,
                "dimension": dimension,
                "candidates": candidates,
                "instruction": "Rank relevance only. Do not answer the question.",
            }
        )

    def _recommend_dimension(
        self,
        *,
        user_query: str,
        dimension: str,
        candidates: List[Dict[str, str]],
    ) -> RelevanceRecommendation:
        planner = Chat(system=self.PLANNER_SYSTEM_PROMPT)
        planner.model = "codex-mini-latest"
        raw = planner.ask(
            self._build_planner_payload(
                user_query=user_query,
                dimension=dimension,
                candidates=candidates,
            )
        )
        data = json.loads(raw)
        return RelevanceRecommendation(
            most_relevant=data.get("most_relevant", []),
            least_relevant=data.get("least_relevant", []),
            rationale=data.get("rationale", ""),
        )

    def _run_parallel_curation(
        self, user_query: str
    ) -> Tuple[RelevanceRecommendation, RelevanceRecommendation, RelevanceRecommendation]:
        tool_candidates = [
            {
                "name": self._tool_name(tool),
                "description": tool.get("function", {}).get("description", ""),
            }
            for tool in self.tools
        ]

        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_tools = pool.submit(
                self._recommend_dimension,
                user_query=user_query,
                dimension="tools",
                candidates=tool_candidates,
            )
            fut_skills = pool.submit(
                self._recommend_dimension,
                user_query=user_query,
                dimension="skills",
                candidates=self.skills,
            )
            fut_memory = pool.submit(
                self._recommend_dimension,
                user_query=user_query,
                dimension="memory",
                candidates=self.memory,
            )
            return fut_tools.result(), fut_skills.result(), fut_memory.result()

    @staticmethod
    def _select_by_names(
        items: List[Dict[str, Any]], selected_names: List[str], name_resolver: Callable[[Dict[str, Any]], str]
    ) -> List[Dict[str, Any]]:
        selected_set = set(selected_names)
        selected = [item for item in items if name_resolver(item) in selected_set]
        return selected if selected else items

    @staticmethod
    def _to_skills_block(items: List[Dict[str, str]]) -> str:
        return "\n".join(f"- {i['name']}: {i.get('description', '')}" for i in items)

    @staticmethod
    def _to_memory_block(items: List[Dict[str, str]]) -> str:
        return "\n".join(f"- {i['name']}: {i.get('content', '')}" for i in items)

    def ask(self, user_query: str) -> Dict[str, Any]:
        """Planner -> parallel curation -> YAML/text-filled final submit."""
        tool_rec, skill_rec, memory_rec = self._run_parallel_curation(user_query)

        selected_tools = self._select_by_names(self.tools, tool_rec.most_relevant, self._tool_name)
        selected_skills = self._select_by_names(self.skills, skill_rec.most_relevant, self._name)
        selected_memory = self._select_by_names(self.memory, memory_rec.most_relevant, self._name)

        # Update chatsnack text fillings used by the YAML template prompt.
        Text("ToolCuratorSkills", self._to_skills_block(selected_skills)).save()
        Text("ToolCuratorMemory", self._to_memory_block(selected_memory)).save()

        routed_chat = self.agent_chat.copy()
        routed_chat.set_tools(selected_tools)
        response_text = routed_chat.ask(user_query)

        # preserve chat continuity for future turns
        self.agent_chat = routed_chat

        return {
            "question": user_query,
            "curated_tool_names": [self._tool_name(t) for t in selected_tools],
            "curated_skill_names": [self._name(s) for s in selected_skills],
            "curated_memory_names": [self._name(m) for m in selected_memory],
            "tool_recommendation": tool_rec,
            "skill_recommendation": skill_rec,
            "memory_recommendation": memory_rec,
            "answer": response_text,
        }


EXAMPLE_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search internal docs for architecture and API usage.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Run read-only SQL against analytics warehouse.",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string", "description": "SELECT statement"}},
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "weather_lookup",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "City"}},
                "required": ["city"],
            },
        },
    },
]

EXAMPLE_SKILLS = [
    {"name": "backend-architecture", "description": "API migration and service boundary planning."},
    {"name": "data-analysis", "description": "Metric triage, cohorting, anomaly analysis."},
    {"name": "ux-writing", "description": "UI copy and tone guidelines."},
]

EXAMPLE_MEMORY = [
    {"name": "team-constraints", "content": "Python 3.12, FastAPI standard, no ORM switch this quarter."},
    {"name": "release-notes", "content": "APAC rollout happened first in release 2026.01."},
    {"name": "style-guide", "content": "Keep answers concise and implementation-oriented."},
]


if __name__ == "__main__":
    session = ToolCuratedConversation(
        base_model="gpt-5.2-codex",
        tools=EXAMPLE_TOOLS,
        skills=EXAMPLE_SKILLS,
        memory=EXAMPLE_MEMORY,
    )

    turn_1 = session.ask("How should I migrate our Flask auth middleware to FastAPI dependencies?")
    print("TURN 1 TOOLS:", turn_1["curated_tool_names"])
    print("TURN 1 SKILLS:", turn_1["curated_skill_names"])
    print("TURN 1 MEMORY:", turn_1["curated_memory_names"])

    turn_2 = session.ask("Can you analyze why weekly active users dipped in APAC after release 2026.01?")
    print("TURN 2 TOOLS:", turn_2["curated_tool_names"])
    print("TURN 2 SKILLS:", turn_2["curated_skill_names"])
    print("TURN 2 MEMORY:", turn_2["curated_memory_names"])
