"""
Crew assembly: loads agents and tasks from YAML config, uses env-configured LLMs.
"""

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from src.settings import TEMPLATES_DIR
from .llm import get_llm


def _templates_reference() -> str:
    """Load all seed templates into a reference block for the drafter.

    The drafter is told to follow template structure; this puts the actual
    template content in-context so it can mirror standard clauses.
    """
    if not TEMPLATES_DIR.is_dir():
        return ""
    parts = []
    for tpl in sorted(TEMPLATES_DIR.glob("*.md")):
        parts.append(f"### 模板：{tpl.stem}\n\n{tpl.read_text(encoding='utf-8').strip()}\n")
    return "\n".join(parts)


@CrewBase
class ContractDraftingCrew:
    """Chinese Contract Drafting Crew with specialized agents."""

    # Paths to YAML configs — relative to this file (src/crew.py), so src/config/
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def intake_clarifier(self) -> Agent:
        return Agent(
            config=self.agents_config["intake_clarifier"],
            llm=get_llm("INTAKE"),
            verbose=True,
            max_iter=5,
            allow_delegation=False,
        )

    @agent
    def drafter(self) -> Agent:
        tools = []
        try:
            from src.search.rag_tool import get_rag_tool

            rag_tool = get_rag_tool()
            if rag_tool is not None:
                tools.append(rag_tool)
        except Exception:
            # Search deps unavailable or RAG disabled -> drafter proceeds
            # without retrieval (graceful degradation).
            pass
        try:
            from src.law_api.tool import get_law_search_tool

            law_tool = get_law_search_tool()
            if law_tool is not None:
                tools.append(law_tool)
        except Exception:
            # law-api deps/config unavailable -> drafting proceeds without
            # statute retrieval (same degradation contract).
            pass
        return Agent(
            config=self.agents_config["drafter"],
            llm=get_llm("DRAFTER"),
            tools=tools or None,
            verbose=True,
            max_iter=10,
            allow_delegation=False,
        )

    @agent
    def auditor(self) -> Agent:
        return Agent(
            config=self.agents_config["auditor"],
            llm=get_llm("AUDITOR"),
            verbose=True,
            max_iter=8,
            allow_delegation=False,
        )

    @task
    def clarify_requirements(self) -> Task:
        return Task(
            config=self.tasks_config["clarify_requirements"],
        )

    @task
    def draft_contract(self) -> Task:
        task = Task(config=self.tasks_config["draft_contract"])
        reference = _templates_reference()
        if reference:
            task.description = (
                f"{task.description}\n\n"
                "以下为参考模板，请参考其结构与标准条款，按本次需求选用并调整：\n\n"
                f"{reference}"
            )
        return task

    @task
    def audit_contract(self) -> Task:
        return Task(
            config=self.tasks_config["audit_contract"],
        )

    @task
    def revise_contract(self) -> Task:
        return Task(
            config=self.tasks_config["revise_contract"],
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

