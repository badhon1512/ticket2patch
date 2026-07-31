import asyncio
from datetime import UTC, datetime
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.api.main import (
    app,
    get_activity_store,
    get_chat_service,
)


class FakeActivityStore:
    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}

    def create_run(self, *, run_id, ticket_key, repository, status="received"):
        now = datetime.now(UTC)
        self.runs[run_id] = {
            "id": run_id,
            "ticket_key": ticket_key,
            "repository": repository,
            "status": status,
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
            "summary": None,
            "failure_reason": None,
            "event_count": 0,
            "last_activity_at": None,
        }
        self.events[run_id] = []
        return self.runs[run_id]

    def append_event(self, run_id, **event):
        created = {
            "id": str(len(self.events[run_id]) + 1),
            "run_id": run_id,
            "sequence": len(self.events[run_id]) + 1,
            "created_at": datetime.now(UTC),
            "payload": {},
            "detail": None,
            "level": "info",
            "actor": "system",
            **event,
        }
        self.events[run_id].append(created)
        self.runs[run_id]["event_count"] = len(self.events[run_id])
        return created

    def get_run(self, run_id):
        return self.runs.get(run_id)

    def list_events(self, run_id):
        return self.events.get(run_id, [])


class FakeChatService:
    async def send_message(self, **kwargs):
        assert kwargs["message"] == "Read issue 10"
        assert kwargs["ticket_key"] == "MCP-1"
        assert kwargs["base_branch"] == "main"
        return {
            "session_id": "session-1",
            "run_id": "web-session-1",
            "message": "Issue 10 describes a login failure.",
            "status": "investigating",
        }

    async def list_jira_tickets(self):
        return [
            {
                "key": "MCP-1",
                "summary": "Agent cannot read workspace",
                "status": "Waiting for support",
                "issue_type": "Service Request",
                "priority": "Medium",
                "updated": "2026-07-31T12:00:00.000+0200",
                "url": "https://example.atlassian.net/browse/MCP-1",
            }
        ]

    async def list_recent_repositories(self, owner):
        assert owner == "octo"
        return [
            {
                "name": "example",
                "full_name": "octo/example",
                "url": "https://github.com/octo/example",
                "language": "Python",
                "updated_at": "2026-07-31T12:00:00Z",
                "default_branch": "main",
                "private": False,
            }
        ]


def test_activity_api_run_timeline():
    store = FakeActivityStore()
    app.dependency_overrides[get_activity_store] = lambda: store

    async def exercise_api():
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            create_response = client.post(
                "/api/runs",
                json={
                    "id": "api-run",
                    "ticket_key": "LOCAL-3",
                    "repository": "octo/example",
                },
            )
            create_response = await create_response
            assert create_response.status_code == 201

            event_response = await client.post(
                "/api/runs/api-run/events",
                json={
                    "event_type": "developer_message",
                    "title": "Developer sent a message",
                    "detail": "Read issue 10",
                    "actor": "developer",
                },
            )
            assert event_response.status_code == 201

            detail_response = await client.get("/api/runs/api-run")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["event_count"] == 1
            assert detail["events"][0]["detail"] == "Read issue 10"

    try:
        asyncio.run(exercise_api())
    finally:
        app.dependency_overrides.clear()


def test_chat_api_returns_agent_response():
    app.dependency_overrides[get_activity_store] = lambda: FakeActivityStore()
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService()

    async def exercise_api():
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/chat",
                json={
                    "owner": "octo",
                    "repo": "example",
                    "ticket_key": "MCP-1",
                    "base_branch": "main",
                    "message": "Read issue 10",
                },
            )
            assert response.status_code == 200
            assert response.json()["session_id"] == "session-1"
            assert "login failure" in response.json()["message"]

    try:
        asyncio.run(exercise_api())
    finally:
        app.dependency_overrides.clear()


def test_jira_issue_list_api():
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService()

    async def exercise_api():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/jira/issues")
            assert response.status_code == 200
            assert response.json()[0]["key"] == "MCP-1"

    try:
        asyncio.run(exercise_api())
    finally:
        app.dependency_overrides.clear()


def test_recent_github_repository_api():
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService()

    async def exercise_api():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/github/repositories?owner=octo")
            assert response.status_code == 200
            assert response.json()[0]["full_name"] == "octo/example"

    try:
        asyncio.run(exercise_api())
    finally:
        app.dependency_overrides.clear()
