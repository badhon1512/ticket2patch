import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.agents.agent import Ticket2PatchAgent, create_agent
from app.agents.guardrails import EligibilityPolicy
from app.agents.state import Ticket2PatchState
from app.db import ActivityStore
from app.observability.activity_callbacks import ActivityCallbackHandler

GITHUB_OWNER_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
)


class ChatSessionNotFoundError(KeyError):
    """Raised when a browser references an expired or unknown chat session."""


@dataclass
class ChatSession:
    id: str
    run_id: str
    owner: str
    repo: str
    state: Ticket2PatchState
    callback: ActivityCallbackHandler
    lock: asyncio.Lock


def _initial_state(
    run_id: str,
    owner: str,
    repo: str,
    ticket_key: str,
    base_branch: str,
) -> Ticket2PatchState:
    repository = f"{owner}/{repo}"
    return {
        "messages": [],
        "run_id": run_id,
        "attempt": 1,
        "status": "received",
        "trigger_event_id": run_id,
        "ticket_key": ticket_key,
        "ticket_snapshot": {
            "project_key": "WEB",
            "issue_type": "Developer Investigation",
            "status": "Ready for Agent",
            "labels": ["ticket2patch", "web-chat"],
            "repository": repository,
        },
        "repository": repository,
        "base_branch": base_branch,
        "evidence": [],
        "hypotheses": [],
        "risk": "low",
        "approvals": [],
        "changed_files": [],
        "validation_results": [],
        "review_findings": [],
    }


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return str(content)


def _mcp_payload(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 1:
        item = value[0]
        if isinstance(item, dict) and item.get("type") == "text":
            return _mcp_payload(item.get("text", ""))
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class ChatService:
    """Manage local web-chat sessions and durable activity records."""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._sessions_lock = asyncio.Lock()
        self._agent: Ticket2PatchAgent | None = None
        self._agent_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create the shared agent once and keep it ready for chat requests."""

        if self._agent is not None:
            return

        async with self._agent_lock:
            if self._agent is not None:
                return
            if not os.getenv("OPENAI_API_KEY", "").strip():
                raise RuntimeError("OPENAI_API_KEY is not configured")

            policy = EligibilityPolicy(
                allowed_projects=frozenset({"WEB"}),
                allowed_issue_types=frozenset({"Developer Investigation"}),
            )
            model = ChatOpenAI(
                model=os.getenv("TICKET2PATCH_MODEL", "gpt-5.4-mini"),
                temperature=0,
            )
            self._agent = await create_agent(
                model=model,
                eligibility_policy=policy,
            )

    async def get_agent(self) -> Ticket2PatchAgent:
        await self.initialize()
        if self._agent is None:
            raise RuntimeError("Ticket2Patch agent failed to initialize")
        return self._agent

    async def list_jira_tickets(self) -> list[dict[str, str | None]]:
        """Return normalized Jira issues visible to the configured account."""

        agent = await self.get_agent()
        tools = {tool.name: tool for tool in agent.mcp_tools}
        resource_tool = tools.get("getAccessibleAtlassianResources")
        search_tool = tools.get("searchJiraIssuesUsingJql")
        if resource_tool is None or search_tool is None:
            raise RuntimeError("Required Jira read tools are unavailable")

        resources = _mcp_payload(await resource_tool.ainvoke({}))
        if not isinstance(resources, list) or not resources:
            raise RuntimeError("No accessible Jira site was found")
        resource = next(
            (
                item
                for item in resources
                if isinstance(item, dict)
                and str(item.get("url", "")).endswith(".atlassian.net")
            ),
            None,
        )
        if resource is None:
            raise RuntimeError("No accessible Jira site was found")

        result = _mcp_payload(
            await search_tool.ainvoke(
                {
                    "cloudId": str(resource["id"]),
                    "jql": "project IS NOT EMPTY ORDER BY updated DESC",
                    "maxResults": 100,
                    "fields": [
                        "summary",
                        "status",
                        "issuetype",
                        "priority",
                        "updated",
                    ],
                }
            )
        )
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(str(result.get("message", "Jira search failed")))
        issues = result.get("issues", []) if isinstance(result, dict) else []
        site_url = str(resource["url"]).rstrip("/")
        normalized = []
        for issue in issues:
            if not isinstance(issue, dict) or not issue.get("key"):
                continue
            fields = issue.get("fields") or {}
            normalized.append(
                {
                    "key": str(issue["key"]),
                    "summary": str(fields.get("summary") or "Untitled ticket"),
                    "status": str((fields.get("status") or {}).get("name") or "Unknown"),
                    "issue_type": str(
                        (fields.get("issuetype") or {}).get("name") or "Issue"
                    ),
                    "priority": (
                        str((fields.get("priority") or {}).get("name"))
                        if fields.get("priority")
                        else None
                    ),
                    "updated": str(fields.get("updated")) if fields.get("updated") else None,
                    "url": f"{site_url}/browse/{issue['key']}",
                }
            )
        return normalized

    async def list_recent_repositories(
        self,
        owner: str,
    ) -> list[dict[str, str | bool | None]]:
        """Return the owner's five most recently updated GitHub repositories."""

        owner = owner.strip()
        if not GITHUB_OWNER_PATTERN.fullmatch(owner):
            raise ValueError("Invalid GitHub owner")
        agent = await self.get_agent()
        search_tool = next(
            (tool for tool in agent.mcp_tools if tool.name == "search_repositories"),
            None,
        )
        if search_tool is None:
            raise RuntimeError("GitHub repository search tool is unavailable")
        result = _mcp_payload(
            await search_tool.ainvoke(
                {
                    "query": f"user:{owner}",
                    "sort": "updated",
                    "order": "desc",
                    "perPage": 5,
                    "page": 1,
                    "minimal_output": True,
                }
            )
        )
        if not isinstance(result, dict):
            raise TypeError("GitHub repository search returned an invalid response")

        repositories = []
        for item in result.get("items", []):
            if not isinstance(item, dict) or not item.get("full_name"):
                continue
            repositories.append(
                {
                    "name": str(item.get("name") or ""),
                    "full_name": str(item["full_name"]),
                    "url": str(item.get("html_url") or ""),
                    "language": str(item["language"]) if item.get("language") else None,
                    "updated_at": str(item.get("updated_at") or ""),
                    "default_branch": str(item.get("default_branch") or "main"),
                    "private": bool(item.get("private", False)),
                }
            )
        return repositories[:5]

    async def start_session(
        self,
        *,
        owner: str,
        repo: str,
        ticket_key: str,
        base_branch: str,
        store: ActivityStore,
    ) -> ChatSession:
        session_id = str(uuid4())
        run_id = f"web-{session_id}"
        await self.initialize()
        state = _initial_state(run_id, owner, repo, ticket_key, base_branch)
        store.create_run(
            run_id=run_id,
            ticket_key=state["ticket_key"],
            repository=state["repository"],
            status=state["status"],
        )
        store.append_event(
            run_id,
            event_type="run_started",
            title="Web chat session started",
            detail=f"Repository scope: {state['repository']}",
            level="success",
            actor="system",
        )
        session = ChatSession(
            id=session_id,
            run_id=run_id,
            owner=owner,
            repo=repo,
            state=state,
            callback=ActivityCallbackHandler(store, run_id),
            lock=asyncio.Lock(),
        )
        async with self._sessions_lock:
            self._sessions[session_id] = session
        return session

    async def send_message(
        self,
        *,
        owner: str,
        repo: str,
        ticket_key: str,
        base_branch: str,
        message: str,
        session_id: str | None,
        store: ActivityStore,
    ) -> dict[str, str]:
        if session_id is None:
            session = await self.start_session(
                owner=owner,
                repo=repo,
                ticket_key=ticket_key,
                base_branch=base_branch,
                store=store,
            )
        else:
            session = self._sessions.get(session_id)
            if session is None:
                raise ChatSessionNotFoundError(session_id)
            if (session.owner, session.repo) != (owner, repo):
                raise ValueError("Session repository does not match the request")
            if session.state["ticket_key"] != ticket_key:
                raise ValueError("Session Jira ticket does not match the request")
            if session.state.get("base_branch") != base_branch:
                raise ValueError("Session base branch does not match the request")

        async with session.lock:
            agent = await self.get_agent()
            store.append_event(
                session.run_id,
                event_type="developer_message",
                title="Developer sent a web message",
                detail=message,
                actor="developer",
            )
            store.update_run(session.run_id, status="investigating")
            session.state["messages"] = [
                *session.state.get("messages", []),
                HumanMessage(
                    content=(
                        f"Repository scope: {session.owner}/{session.repo}\n"
                        f"Developer question: {message}"
                    )
                ),
            ]

            try:
                previous_analysis = session.state.get("analysis")
                session.state = await agent.ainvoke(
                    session.state,
                    thread_id=session.run_id,
                    callbacks=[session.callback],
                )
            except Exception as exc:
                store.append_event(
                    session.run_id,
                    event_type="agent_error",
                    title="Web agent request failed",
                    detail=str(exc),
                    level="error",
                    actor="agent",
                )
                store.update_run(
                    session.run_id,
                    status="failed",
                    failure_reason=str(exc),
                )
                raise

            analysis = session.state.get("analysis")
            if analysis and analysis != previous_analysis:
                store.append_event(
                    session.run_id,
                    event_type="analysis_completed",
                    title="Root-cause analysis completed",
                    detail=str(analysis.get("root_cause", "Analysis completed")),
                    level="success",
                    actor="agent",
                    payload=analysis,
                )

            messages = session.state.get("messages", [])
            if not messages:
                raise RuntimeError("Agent returned no response")
            response = _message_text(messages[-1].content)
            current_status = session.state.get("status", "investigating")
            store.append_event(
                session.run_id,
                event_type="agent_response",
                title="Agent responded in web chat",
                detail=response,
                level="success",
                actor="agent",
            )
            store.update_run(
                session.run_id,
                status=current_status,
                summary=response[:1000],
            )
            return {
                "session_id": session.id,
                "run_id": session.run_id,
                "message": response,
                "status": current_status,
            }
