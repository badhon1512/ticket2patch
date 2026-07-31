from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

from app.db import ActivityStore


def _preview(value: Any, limit: int = 800) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}…"


class ActivityCallbackHandler(AsyncCallbackHandler):
    """Record tool lifecycle events without storing credentials."""

    def __init__(self, store: ActivityStore, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        tool_name = serialized.get("name") or kwargs.get("name") or "tool"
        self.store.append_event(
            self.run_id,
            event_type="tool_started",
            title=f"Started {tool_name}",
            detail=_preview(input_str),
            actor="agent",
            payload={"tool": tool_name, "tool_run_id": str(run_id)},
        )

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = name or "tool"
        self.store.append_event(
            self.run_id,
            event_type="tool_completed",
            title=f"Completed {tool_name}",
            detail=_preview(output),
            level="success",
            actor="agent",
            payload={"tool": tool_name, "tool_run_id": str(run_id)},
        )

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        tool_name = name or "tool"
        self.store.append_event(
            self.run_id,
            event_type="tool_failed",
            title=f"Failed {tool_name}",
            detail=_preview(error),
            level="error",
            actor="agent",
            payload={"tool": tool_name, "tool_run_id": str(run_id)},
        )
