import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agents.guardrails import EligibilityPolicy, evaluate_ticket
from app.agents.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from app.agents.state import RootCauseAnalysis, Ticket2PatchState
from app.mcp.github import get_github_tools
from app.mcp.jira import get_jira_tools
from app.workspace import WorkspaceManager, get_workspace_read_tools


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    purpose: str
    prompt_version: str
    stages: tuple[str, ...]
    allowed_outcomes: tuple[str, ...]
    prohibited_actions: tuple[str, ...]


TICKET2PATCH_DEFINITION = AgentDefinition(
    name="Ticket2Patch",
    purpose=(
        "Investigate an eligible production ticket, reproduce its failure, "
        "create and validate a minimal patch, and open an approved draft PR."
    ),
    prompt_version=PROMPT_VERSION,
    stages=(
        "ingest",
        "eligibility",
        "investigation",
        "root_cause_analysis",
        "reproduction",
        "workspace",
        "patch",
        "validation",
        "independent_review",
        "draft_pr",
    ),
    allowed_outcomes=(
        "ineligible",
        "needs_information",
        "investigation_only",
        "patch_rejected",
        "draft_pr_created",
        "failed_safely",
        "cancelled",
    ),
    prohibited_actions=(
        "access production hosts or databases",
        "read or expose credentials",
        "edit outside the assigned workspace",
        "bypass repository validation",
        "push before publication support is implemented",
        "merge a pull request",
        "deploy a change",
    ),
)


async def create_agent(
    *,
    model: BaseChatModel,
    eligibility_policy: EligibilityPolicy,
    checkpointer: Any | None = None,
) -> "Ticket2PatchAgent":
    """Create the agent with its configured MCP tools."""

    return await Ticket2PatchAgent.create(
        model=model,
        eligibility_policy=eligibility_policy,
        checkpointer=checkpointer,
    )


class Ticket2PatchAgent:
    """Class-based LangGraph agent for ticket investigation.

    The initial graph supports deterministic eligibility checking followed by
    an evidence-gathering model/tool loop. Patch publication is not wired yet.
    """

    definition = TICKET2PATCH_DEFINITION
    system_prompt = SYSTEM_PROMPT

    @classmethod
    async def create(
        cls,
        *,
        model: BaseChatModel,
        eligibility_policy: EligibilityPolicy,
        checkpointer: Any | None = None,
    ) -> "Ticket2PatchAgent":
        """Load MCP tools and create a ready-to-run agent."""

        github_tools = await get_github_tools()
        jira_tools = await get_jira_tools()
        return cls(
            model=model,
            eligibility_policy=eligibility_policy,
            read_tools=(*github_tools, *jira_tools),
            checkpointer=checkpointer,
        )

    def __init__(
        self,
        *,
        model: BaseChatModel,
        eligibility_policy: EligibilityPolicy,
        read_tools: Sequence[BaseTool] = (),
        checkpointer: Any | None = None,
        workspace_manager: WorkspaceManager | None = None,
    ) -> None:
        if model is None:
            raise ValueError("model must be injected")

        self.model = model
        self.eligibility_policy = eligibility_policy
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.workspace_read_tools = get_workspace_read_tools(self.workspace_manager)
        self.mcp_tools = tuple(read_tools)
        self.read_tools = (*self.mcp_tools, *self.workspace_read_tools)
        self.tool_model = (
            self.model.bind_tools(list(self.mcp_tools))
            if self.mcp_tools
            else self.model
        )
        self.workspace_tool_model = self.model.bind_tools(list(self.read_tools))
        self.analysis_model = self.model.with_structured_output(RootCauseAnalysis)

        graph = StateGraph(Ticket2PatchState)
        graph.add_node("eligibility_check", self.check_eligibility)
        graph.add_node("prepare_workspace", self.prepare_workspace)
        graph.add_node("call_llm", self.call_llm)
        graph.add_node("analyze_root_cause", self.analyze_root_cause)

        graph.add_node("read_tool_calls", ToolNode(list(self.read_tools)))

        graph.add_edge(START, "eligibility_check")
        graph.add_conditional_edges(
            "eligibility_check",
            self.route_eligibility,
            {
                "prepare_workspace": "prepare_workspace",
                "call_llm": "call_llm",
                END: END,
            },
        )
        graph.add_edge("prepare_workspace", "call_llm")

        graph.add_conditional_edges(
            "call_llm",
            self.route_model_output,
            {
                "read_tool_calls": "read_tool_calls",
                "analyze_root_cause": "analyze_root_cause",
            },
        )
        graph.add_edge("read_tool_calls", "call_llm")
        graph.add_edge("analyze_root_cause", END)

        self.agent = graph.compile(checkpointer=checkpointer)

    def describe(self) -> AgentDefinition:
        return self.definition

    async def prepare_workspace(
        self,
        state: Ticket2PatchState,
    ) -> dict[str, Any]:
        """Automatically prepare an isolated checkout for a ticket run."""

        workspace = await asyncio.to_thread(
            self.workspace_manager.prepare,
            repository=state["repository"],
            ticket_key=state["ticket_key"],
            base_branch=state.get("base_branch", "main"),
            run_id=state["run_id"],
        )
        return {
            "status": "workspace_ready",
            "workspace_id": workspace.workspace_id,
            "base_branch": workspace.base_branch,
            "base_sha": workspace.base_sha,
            "branch_name": workspace.branch_name,
        }
    def check_eligibility(
        self,
        state: Ticket2PatchState,
    ) -> dict[str, Any]:
        result = evaluate_ticket(
            state.get("ticket_snapshot", {}),
            self.eligibility_policy,
        )
        if result.eligible:
            return {
                "status": "investigating",
                "failure_reason": None,
            }

        reason = "; ".join(result.reasons)
        return {
            "status": "ineligible",
            "failure_reason": reason,
            "messages": [
                AIMessage(
                    content=(
                        "Ticket2Patch cannot start this ticket: "
                        f"{reason}."
                    )
                )
            ],
        }

    @staticmethod
    def route_eligibility(state: Ticket2PatchState) -> str:
        if state.get("status") == "ineligible":
            return END
        if not state.get("workspace_id"):
            return "prepare_workspace"
        return "call_llm"

    async def call_llm(
        self,
        state: Ticket2PatchState,
    ) -> dict[str, Any]:
        ticket_key = state.get("ticket_key", "unknown")
        repository = state.get("repository", "not resolved")
        workspace_id = state.get("workspace_id")
        workspace_context = (
            f"- Local workspace ID: {workspace_id}\n"
            if workspace_id
            else "- Local workspace: unavailable; do not call workspace tools\n"
        )
        run_context = SystemMessage(
            content=(
                "Current Ticket2Patch run:\n"
                f"- Ticket: {ticket_key}\n"
                f"- GitHub repository: {repository}\n"
                f"{workspace_context}"
                "- Jira cloudId: not preconfigured; discover it with "
                "getAccessibleAtlassianResources before using Jira tools\n"
                "- Tool routing: Jira requests use Atlassian Jira tools; "
                "GitHub issue tools are only for explicit GitHub requests\n"
                "- Current phase: investigation\n"
                "Use Jira tools for Jira work and GitHub tools for GitHub work. "
                "Use workspace tools only when a local workspace ID is present. "
                "Only update an issue when the user explicitly requests it, "
                "and never substitute one system for the other. Do not propose "
                "that a patch was applied, tested, pushed, or published."
            )
        )
        active_model = (
            self.workspace_tool_model
            if workspace_id
            else self.tool_model
        )
        response = await active_model.ainvoke(
            [
                SystemMessage(content=self.system_prompt),
                run_context,
                *state.get("messages", []),
            ]
        )
        return {"messages": [response]}

    @staticmethod
    def route_model_output(state: Ticket2PatchState) -> str:
        messages = state.get("messages", [])
        if not messages:
            return "analyze_root_cause"

        last_message = messages[-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "read_tool_calls"
        return "analyze_root_cause"

    async def analyze_root_cause(
        self,
        state: Ticket2PatchState,
    ) -> dict[str, Any]:
        """Turn gathered ticket and code evidence into a bounded patch plan."""

        result = await self.analysis_model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Create a concise root-cause analysis from the conversation and "
                        "tool evidence. Do not invent evidence. Repository paths must be "
                        "relative to the cloned repository root. If evidence is weak, set "
                        "confidence to low and record what is missing in open_questions."
                    )
                ),
                *state.get("messages", []),
            ]
        )
        analysis = (
            result
            if isinstance(result, RootCauseAnalysis)
            else RootCauseAnalysis.model_validate(result)
        )
        return {
            "analysis": analysis.model_dump(),
            "proposed_plan": {
                "fix": analysis.proposed_fix,
                "files": analysis.affected_files,
                "tests": analysis.test_plan,
            },
            "status": "analysis_complete",
            "messages": [AIMessage(content=self._format_analysis(analysis))],
        }

    @staticmethod
    def _format_analysis(analysis: RootCauseAnalysis) -> str:
        def items(values: list[str]) -> str:
            return "\n".join(f"- {value}" for value in values) or "- None"

        return (
            "Root-cause analysis\n\n"
            f"Symptom: {analysis.symptom}\n\n"
            f"Evidence:\n{items(analysis.evidence)}\n\n"
            f"Root cause: {analysis.root_cause}\n\n"
            f"Confidence: {analysis.confidence}\n\n"
            f"Proposed fix: {analysis.proposed_fix}\n\n"
            f"Likely files:\n{items(analysis.affected_files)}\n\n"
            f"Test plan:\n{items(analysis.test_plan)}\n\n"
            f"Open questions:\n{items(analysis.open_questions)}"
        )

    async def ainvoke(
        self,
        state: Ticket2PatchState,
        *,
        thread_id: str,
        callbacks: Sequence[Any] = (),
    ) -> Ticket2PatchState:
        """Asynchronously invoke the graph and MCP-backed tools."""

        invocation_state = dict(state)
        if not invocation_state.get("messages"):
            invocation_state["messages"] = [
                HumanMessage(
                    content=(
                        f"Investigate Jira ticket {state['ticket_key']}. "
                        "Collect evidence, identify the most likely root cause, "
                        "state your confidence, and propose a bounded fix plan. "
                        "Do not modify or publish code."
                    )
                )
            ]

        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": list(callbacks),
        }
        return await self.agent.ainvoke(invocation_state, config=config)
