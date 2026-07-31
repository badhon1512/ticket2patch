import os
from uuid import uuid4

import pytest

from app.db.activity_store import ActivityStore

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="Set TEST_DATABASE_URL to run PostgreSQL integration tests",
)


def test_postgres_store_persists_ordered_run_events():
    run_id = f"test-{uuid4()}"
    store = ActivityStore(TEST_DATABASE_URL)
    try:
        store.create_run(
            run_id=run_id,
            ticket_key="LOCAL-1",
            repository="octo/example",
        )

        first = store.append_event(
            run_id,
            event_type="run_started",
            title="Run started",
        )
        second = store.append_event(
            run_id,
            event_type="tool_completed",
            title="Tool completed",
            level="success",
            payload={"tool": "issue_read"},
        )

        events = store.list_events(run_id)
        assert first["sequence"] == 1
        assert second["sequence"] == 2
        assert [event["event_type"] for event in events] == [
            "run_started",
            "tool_completed",
        ]
        assert events[1]["payload"] == {"tool": "issue_read"}
        assert store.get_run(run_id)["event_count"] == 2
    finally:
        store.delete_run(run_id)


def test_postgres_store_updates_terminal_run_status():
    run_id = f"test-{uuid4()}"
    store = ActivityStore(TEST_DATABASE_URL)
    try:
        store.create_run(
            run_id=run_id,
            ticket_key="LOCAL-2",
            repository="octo/example",
        )

        run = store.update_run(
            run_id,
            status="completed",
            summary="Investigation complete",
            completed=True,
        )

        assert run["status"] == "completed"
        assert run["summary"] == "Investigation complete"
        assert run["completed_at"] is not None
    finally:
        store.delete_run(run_id)
