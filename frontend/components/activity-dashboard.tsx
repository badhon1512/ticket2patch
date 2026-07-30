"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { ActivityEvent, AgentRun, RunDetail } from "@/lib/types";

const API_URL =
  process.env.NEXT_PUBLIC_ACTIVITY_API_URL ?? "http://localhost:8000";
const POLL_INTERVAL_MS = 4000;

function formatTime(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function readableStatus(status: string): string {
  return status.replaceAll("_", " ");
}

function eventGlyph(event: ActivityEvent): string {
  if (event.level === "error") return "!";
  if (event.event_type.startsWith("tool_")) return "⌁";
  if (event.actor === "developer") return "D";
  if (event.actor === "agent") return "A";
  return "•";
}

export function ActivityDashboard() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/runs`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Activity API returned ${response.status}`);
      const nextRuns = (await response.json()) as AgentRun[];
      setRuns(nextRuns);
      setSelectedRunId(
        (current) =>
          current ??
          new URLSearchParams(window.location.search).get("run") ??
          nextRuns[0]?.id ??
          null,
      );
      setError(null);
      setLastSyncedAt(new Date());
    } catch (fetchError) {
      setError(
        fetchError instanceof Error
          ? fetchError.message
          : "Unable to reach the activity API",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const loadRun = useCallback(async (runId: string) => {
    try {
      const response = await fetch(`${API_URL}/api/runs/${runId}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Unable to load run ${runId}`);
      setSelectedRun((await response.json()) as RunDetail);
      setError(null);
    } catch (fetchError) {
      setError(
        fetchError instanceof Error ? fetchError.message : "Unable to load run",
      );
    }
  }, []);

  useEffect(() => {
    void loadRuns();
    const timer = window.setInterval(() => void loadRuns(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadRuns]);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRun(null);
      return;
    }
    void loadRun(selectedRunId);
    const timer = window.setInterval(
      () => void loadRun(selectedRunId),
      POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [loadRun, selectedRunId]);

  const metrics = useMemo(() => {
    const active = runs.filter(
      (run) => !["completed", "failed", "cancelled"].includes(run.status),
    ).length;
    const failures = runs.filter((run) => run.status === "failed").length;
    const events = runs.reduce((total, run) => total + run.event_count, 0);
    return { active, failures, events };
  }, [runs]);

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Ticket2Patch home">
          <span className="brandMark">T2P</span>
          <span>
            <strong>Ticket2Patch</strong>
            <small>Agent activity console</small>
          </span>
        </a>
        <nav className="mainNav" aria-label="Primary navigation">
          <a className="active" href="/">Activity</a>
          <a href="/chat">Chat</a>
        </nav>
        <div className="connection">
          <span className={`pulse ${error ? "offline" : ""}`} />
          <span>{error ? "API unavailable" : "Live monitoring"}</span>
          <button type="button" onClick={() => void loadRuns()}>
            Refresh
          </button>
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">OPERATIONS / AGENT RUNS</p>
          <h1>Every decision.<br />Every tool call.</h1>
          <p className="lede">
            Follow Ticket2Patch from developer request to agent response through
            a durable, ordered activity record.
          </p>
        </div>
        <div className="metrics" aria-label="Run metrics">
          <article>
            <span>Active runs</span>
            <strong>{metrics.active.toString().padStart(2, "0")}</strong>
          </article>
          <article>
            <span>Recorded events</span>
            <strong>{metrics.events.toString().padStart(2, "0")}</strong>
          </article>
          <article>
            <span>Failed runs</span>
            <strong>{metrics.failures.toString().padStart(2, "0")}</strong>
          </article>
        </div>
      </section>

      {error && (
        <div className="errorBanner">
          <strong>Connection issue</strong>
          <span>{error}. Start the backend API on port 8000.</span>
        </div>
      )}

      <section className="workspace">
        <aside className="runPanel">
          <div className="panelHeader">
            <div>
              <span className="kicker">Runs</span>
              <h2>Recent sessions</h2>
            </div>
            <span className="count">{runs.length}</span>
          </div>

          <div className="runList">
            {loading && <p className="empty">Loading agent runs…</p>}
            {!loading && runs.length === 0 && (
              <div className="emptyState">
                <span>01</span>
                <h3>No activity yet</h3>
                <p>Start a CLI session to create the first recorded run.</p>
              </div>
            )}
            {runs.map((run) => (
              <button
                className={`runCard ${selectedRunId === run.id ? "selected" : ""}`}
                key={run.id}
                onClick={() => setSelectedRunId(run.id)}
                type="button"
              >
                <div className="runCardTop">
                  <strong>{run.ticket_key}</strong>
                  <span className={`status status-${run.status}`}>
                    {readableStatus(run.status)}
                  </span>
                </div>
                <p>{run.repository}</p>
                <div className="runMeta">
                  <span>{run.event_count} events</span>
                  <time>{formatTime(run.updated_at)}</time>
                </div>
              </button>
            ))}
          </div>
        </aside>

        <section className="timelinePanel">
          {!selectedRun ? (
            <div className="timelineEmpty">
              <p>Select a run to inspect its timeline.</p>
            </div>
          ) : (
            <>
              <div className="runHeading">
                <div>
                  <p className="eyebrow">RUN / {selectedRun.id.slice(0, 13)}</p>
                  <h2>{selectedRun.ticket_key}</h2>
                  <p>{selectedRun.repository}</p>
                </div>
                <div className="runFacts">
                  <span>
                    Started <strong>{formatDate(selectedRun.started_at)}</strong>
                  </span>
                  <span>
                    Status{" "}
                    <strong>{readableStatus(selectedRun.status)}</strong>
                  </span>
                </div>
              </div>

              <div className="timeline">
                {selectedRun.events.map((event) => (
                  <article className="event" key={event.id}>
                    <div className={`eventGlyph level-${event.level}`}>
                      {eventGlyph(event)}
                    </div>
                    <div className="eventBody">
                      <div className="eventTitle">
                        <div>
                          <span>{event.actor}</span>
                          <h3>{event.title}</h3>
                        </div>
                        <time>{formatTime(event.created_at)}</time>
                      </div>
                      {event.detail && <pre>{event.detail}</pre>}
                      <div className="eventFooter">
                        <code>{event.event_type}</code>
                        <span>#{event.sequence.toString().padStart(2, "0")}</span>
                      </div>
                    </div>
                  </article>
                ))}
                {selectedRun.events.length === 0 && (
                  <p className="empty">This run has no recorded events.</p>
                )}
              </div>
            </>
          )}
        </section>
      </section>

      <footer>
        <span>Ticket2Patch / local activity store</span>
        <span>
          Last sync {lastSyncedAt ? formatTime(lastSyncedAt.toISOString()) : "—"}
        </span>
      </footer>
    </main>
  );
}
