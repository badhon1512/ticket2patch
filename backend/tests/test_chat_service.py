import asyncio

from app.services import chat_service
from app.services.chat_service import ChatService


def test_shared_agent_is_initialized_once(monkeypatch):
    calls = 0
    shared_agent = object()

    async def fake_create_agent(**_):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return shared_agent

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("GITHUB_MCP_TOKEN", "test-token")
    monkeypatch.setattr(
        chat_service,
        "create_agent",
        fake_create_agent,
    )

    service = ChatService()

    async def initialize_concurrently():
        await asyncio.gather(
            service.initialize(),
            service.initialize(),
            service.initialize(),
        )
        return await service.get_agent()

    result = asyncio.run(initialize_concurrently())

    assert result is shared_agent
    assert calls == 1
