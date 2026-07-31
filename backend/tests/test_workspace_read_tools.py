import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agents.agent import Ticket2PatchAgent
from app.agents.guardrails import EligibilityPolicy
from app.workspace import WorkspaceManager, WorkspaceReader, get_workspace_read_tools
from app.workspace.read_tools import WorkspaceReadError


class FakeModel:
    def __init__(self):
        self.tool_bindings = []

    def bind_tools(self, tools):
        self.tool_bindings.append(tools)
        return self

    def with_structured_output(self, _schema):
        return FakeAnalysisModel()

    async def ainvoke(self, _messages):
        return AIMessage(content="workspace inspected")


class FakeAnalysisModel:
    async def ainvoke(self, _messages):
        return {
            "symptom": "The reported behavior is reproducible.",
            "evidence": ["src/agent.py contains the relevant implementation"],
            "root_cause": "The implementation does not handle the ticket case.",
            "confidence": "medium",
            "proposed_fix": "Add the missing bounded behavior.",
            "affected_files": ["src/agent.py"],
            "test_plan": ["Add a focused regression test"],
            "open_questions": [],
        }


class FakePreparingManager:
    def __init__(self, root: Path):
        self.root = root
        self.calls = []

    def prepare(self, **arguments):
        self.calls.append(arguments)
        workspace_id = f"mcp-1-{arguments['run_id']}"
        return type(
            "Workspace",
            (),
            {
                "workspace_id": workspace_id,
                "base_branch": arguments["base_branch"],
                "base_sha": "a" * 40,
                "branch_name": "ticket2patch/mcp-1",
            },
        )()

    def resolve(self, workspace_id):
        return self.root / workspace_id


def create_workspace(tmp_path: Path):
    root = tmp_path / "runs"
    workspace = root / "mcp-1-run-123"
    (workspace / ".git").mkdir(parents=True)
    (workspace / "src").mkdir()
    (workspace / "src" / "agent.py").write_text(
        "def create_agent():\n    return 'Ticket2Patch'\n",
        encoding="utf-8",
    )
    (workspace / "README.md").write_text("Ticket2Patch agent\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=value\n", encoding="utf-8")
    (workspace / "private.pem").write_text("secret-key\n", encoding="utf-8")
    (workspace / "image.bin").write_bytes(b"text\x00binary")
    return WorkspaceManager(root=root), workspace


def test_list_search_and_read_stay_bounded(tmp_path):
    manager, _ = create_workspace(tmp_path)
    reader = WorkspaceReader(manager)

    files = reader.list_files("mcp-1-run-123")
    matches = reader.search_code("mcp-1-run-123", "ticket2patch")
    content = reader.read_file("mcp-1-run-123", "src/agent.py")

    assert files == ["README.md", "src/agent.py"]
    assert {match["path"] for match in matches} == {"README.md", "src/agent.py"}
    assert "create_agent" in content


@pytest.mark.parametrize("path", ["../outside.txt", ".git/config", ".env", "private.pem"])
def test_read_rejects_escaped_and_sensitive_paths(tmp_path, path):
    manager, _ = create_workspace(tmp_path)
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")

    with pytest.raises(WorkspaceReadError):
        WorkspaceReader(manager).read_file("mcp-1-run-123", path)


def test_read_rejects_binary_files(tmp_path):
    manager, _ = create_workspace(tmp_path)

    with pytest.raises(WorkspaceReadError, match="Binary"):
        WorkspaceReader(manager).read_file("mcp-1-run-123", "image.bin")


def test_langchain_tools_are_read_only(tmp_path):
    manager, _ = create_workspace(tmp_path)

    tools = get_workspace_read_tools(manager)

    assert {tool.name for tool in tools} == {
        "workspace_list_files",
        "workspace_read_file",
        "workspace_search_code",
    }
    assert all("write" not in tool.name and "patch" not in tool.name for tool in tools)
    for workspace_tool in tools:
        schema = workspace_tool.tool_call_schema.model_json_schema()
        assert "workspace_id" not in schema["properties"]
        assert "state" not in schema["properties"]


def test_tool_node_injects_workspace_id_from_state(tmp_path):
    manager, _ = create_workspace(tmp_path)
    node = ToolNode(list(get_workspace_read_tools(manager)))
    graph_builder = StateGraph(dict)
    graph_builder.add_node("tools", node)
    graph_builder.add_edge(START, "tools")
    graph_builder.add_edge("tools", END)
    graph = graph_builder.compile()
    state = {
        "workspace_id": "mcp-1-run-123",
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "workspace_read_file",
                        "args": {"path": "src/agent.py"},
                        "id": "tool-1",
                        "type": "tool_call",
                    }
                ],
            )
        ],
    }

    result = asyncio.run(graph.ainvoke(state))

    assert "create_agent" in result["messages"][0].content


def test_workspace_tools_are_bound_to_active_agent(tmp_path):
    manager, _ = create_workspace(tmp_path)
    model = FakeModel()
    policy = EligibilityPolicy(
        allowed_projects=frozenset({"MCP"}),
        allowed_issue_types=frozenset({"Bug"}),
    )

    @tool
    def jira_stub() -> str:
        """Return a fake Jira result."""

        return "ok"

    agent = Ticket2PatchAgent(
        model=model,
        eligibility_policy=policy,
        read_tools=(jira_stub,),
        workspace_manager=manager,
    )

    expected = {
        "workspace_list_files",
        "workspace_read_file",
        "workspace_search_code",
    }
    assert expected <= {tool.name for tool in agent.read_tools}
    assert expected <= {tool.name for tool in model.tool_bindings[-1]}
    assert not expected.intersection(
        tool.name for tool in model.tool_bindings[0]
    )


def test_main_graph_prepares_workspace_once_and_reuses_it(tmp_path):
    manager = FakePreparingManager(tmp_path)
    model = FakeModel()
    policy = EligibilityPolicy(
        allowed_projects=frozenset({"MCP"}),
        allowed_issue_types=frozenset({"Bug"}),
    )
    agent = Ticket2PatchAgent(
        model=model,
        eligibility_policy=policy,
        workspace_manager=manager,
    )
    state = {
        "messages": [],
        "run_id": "run-123",
        "attempt": 1,
        "status": "received",
        "trigger_event_id": "event-1",
        "ticket_key": "MCP-1",
        "ticket_snapshot": {
            "project_key": "MCP",
            "issue_type": "Bug",
            "status": "Ready for Agent",
            "labels": ["ticket2patch"],
            "repository": "owner/repo",
        },
        "repository": "owner/repo",
        "evidence": [],
        "hypotheses": [],
        "risk": "low",
        "approvals": [],
        "changed_files": [],
        "validation_results": [],
        "review_findings": [],
    }

    async def run_twice():
        first = await agent.ainvoke(state, thread_id="run-123")
        second = await agent.ainvoke(first, thread_id="run-123")
        return first, second

    first, second = asyncio.run(run_twice())

    assert first["workspace_id"] == "mcp-1-run-123"
    assert first["status"] == "analysis_complete"
    assert first["analysis"]["confidence"] == "medium"
    assert second["workspace_id"] == "mcp-1-run-123"
    assert len(manager.calls) == 1
