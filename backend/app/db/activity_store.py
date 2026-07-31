import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DEFAULT_DATABASE_URL = (
    "postgresql://ticket2patch:ticket2patch@127.0.0.1:5432/ticket2patch"
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActivityStore:
    """Persist agent run summaries and timelines in PostgreSQL."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = (
            database_url
            or os.getenv("TICKET2PATCH_DATABASE_URL")
            or DEFAULT_DATABASE_URL
        )
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("TICKET2PATCH_DATABASE_URL must be a PostgreSQL URL")
        self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(
            self.database_url,
            row_factory=dict_row,
            connect_timeout=10,
        ) as connection:
            yield connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    ticket_key TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    summary TEXT,
                    failure_reason TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_events (
                    id UUID PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT,
                    level TEXT NOT NULL CHECK (
                        level IN ('info', 'success', 'warning', 'error')
                    ),
                    actor TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE (run_id, sequence)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_activity_events_run_sequence
                ON activity_events(run_id, sequence)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runs_updated_at
                ON runs(updated_at DESC)
                """
            )

    def create_run(
        self,
        *,
        run_id: str,
        ticket_key: str,
        repository: str,
        status: str = "received",
    ) -> dict[str, Any]:
        timestamp = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, ticket_key, repository, status, started_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (run_id, ticket_key, repository, status, timestamp, timestamp),
            )
        run = self.get_run(run_id)
        if run is None:
            raise RuntimeError(f"Unable to create run {run_id}")
        return run

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        summary: str | None = None,
        failure_reason: str | None = None,
        completed: bool = False,
    ) -> dict[str, Any]:
        timestamp = utc_now()
        completed_at = timestamp if completed else None
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = %s,
                    updated_at = %s,
                    summary = COALESCE(%s, summary),
                    failure_reason = %s,
                    completed_at = COALESCE(%s, completed_at)
                WHERE id = %s
                """,
                (
                    status,
                    timestamp,
                    summary,
                    failure_reason,
                    completed_at,
                    run_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Run not found: {run_id}")
        run = self.get_run(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        return run

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        title: str,
        detail: str | None = None,
        level: str = "info",
        actor: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = utc_now()
        event_id = uuid4()
        with self._connect() as connection:
            run = connection.execute(
                "SELECT id FROM runs WHERE id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if run is None:
                raise KeyError(f"Run not found: {run_id}")

            sequence_row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                FROM activity_events
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
            next_sequence = sequence_row["next_sequence"]
            connection.execute(
                """
                INSERT INTO activity_events (
                    id, run_id, sequence, event_type, title, detail,
                    level, actor, payload, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id,
                    run_id,
                    next_sequence,
                    event_type,
                    title,
                    detail,
                    level,
                    actor,
                    Jsonb(payload or {}),
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE runs SET updated_at = %s WHERE id = %s",
                (timestamp, run_id),
            )
        event = self.get_event(str(event_id))
        if event is None:
            raise RuntimeError(f"Unable to create event {event_id}")
        return event

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM activity_events WHERE id = %s",
                (event_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT runs.*,
                       COUNT(activity_events.id)::INTEGER AS event_count,
                       MAX(activity_events.created_at) AS last_activity_at
                FROM runs
                LEFT JOIN activity_events ON activity_events.run_id = runs.id
                WHERE runs.id = %s
                GROUP BY runs.id
                """,
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT runs.*,
                       COUNT(activity_events.id)::INTEGER AS event_count,
                       MAX(activity_events.created_at) AS last_activity_at
                FROM runs
                LEFT JOIN activity_events ON activity_events.run_id = runs.id
                GROUP BY runs.id
                ORDER BY runs.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM activity_events
                WHERE run_id = %s
                ORDER BY sequence ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_run(self, run_id: str) -> None:
        """Delete a run and its events. Intended for integration-test cleanup."""

        with self._connect() as connection:
            connection.execute("DELETE FROM runs WHERE id = %s", (run_id,))
