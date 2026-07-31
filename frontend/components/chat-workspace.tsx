"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

const API_URL =
  process.env.NEXT_PUBLIC_ACTIVITY_API_URL ?? "http://localhost:8000";

type ChatRole = "developer" | "agent" | "system";

interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: Date;
}

interface ChatResponse {
  session_id: string;
  run_id: string;
  message: string;
  status: string;
}

interface JiraTicket {
  key: string;
  summary: string;
  status: string;
  issue_type: string;
  priority: string | null;
  updated: string | null;
  url: string;
}

interface GitHubRepository {
  name: string;
  full_name: string;
  url: string;
  language: string | null;
  updated_at: string;
  default_branch: string;
  private: boolean;
}

const suggestions = [
  "Read issue 1 and summarize the problem.",
  "Create an issue for adding API authentication.",
  "What GitHub issue tools can you use?",
];

function timeLabel(date: Date): string {
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function ChatWorkspace() {
  const [owner, setOwner] = useState("badhon1512");
  const [repo, setRepo] = useState("ticket2patch");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState("ready");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tickets, setTickets] = useState<JiraTicket[]>([]);
  const [selectedTicketKey, setSelectedTicketKey] = useState<string | null>(null);
  const [ticketsLoading, setTicketsLoading] = useState(true);
  const [ticketError, setTicketError] = useState<string | null>(null);
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [repositoriesLoading, setRepositoriesLoading] = useState(true);
  const [repositoryError, setRepositoryError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const repository = useMemo(() => `${owner}/${repo}`, [owner, repo]);
  const repositoryLocked = sessionId !== null;
  const selectedTicket = tickets.find(
    (ticket) => ticket.key === selectedTicketKey,
  );
  const selectedRepository = repositories.find(
    (repositoryOption) => repositoryOption.name === repo,
  );

  useEffect(() => {
    let active = true;

    async function loadTickets() {
      setTicketsLoading(true);
      setTicketError(null);
      try {
        const response = await fetch(`${API_URL}/api/jira/issues`);
        const payload = (await response.json()) as JiraTicket[] | { detail?: string };
        if (!response.ok) {
          throw new Error(
            !Array.isArray(payload) && payload.detail
              ? payload.detail
              : `Jira API returned ${response.status}`,
          );
        }
        if (active) setTickets(payload as JiraTicket[]);
      } catch (loadError) {
        if (active) {
          setTicketError(
            loadError instanceof Error ? loadError.message : "Unable to load Jira tickets",
          );
        }
      } finally {
        if (active) setTicketsLoading(false);
      }
    }

    void loadTickets();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadRepositories() {
      setRepositoriesLoading(true);
      setRepositoryError(null);
      try {
        const response = await fetch(
          `${API_URL}/api/github/repositories?owner=${encodeURIComponent(owner)}`,
        );
        const payload = (await response.json()) as
          | GitHubRepository[]
          | { detail?: string };
        if (!response.ok) {
          throw new Error(
            !Array.isArray(payload) && payload.detail
              ? payload.detail
              : `GitHub API returned ${response.status}`,
          );
        }
        if (active) {
          const recent = payload as GitHubRepository[];
          setRepositories(recent);
          setRepo((current) =>
            recent.some((repository) => repository.name === current)
              ? current
              : (recent[0]?.name ?? ""),
          );
        }
      } catch (loadError) {
        if (active) {
          setRepositoryError(
            loadError instanceof Error
              ? loadError.message
              : "Unable to load GitHub repositories",
          );
        }
      } finally {
        if (active) setRepositoriesLoading(false);
      }
    }

    const timer = window.setTimeout(() => {
      if (owner.trim()) void loadRepositories();
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [owner]);

  function resetSession() {
    setMessages([]);
    setSessionId(null);
    setRunId(null);
    setStatus("ready");
    setError(null);
    setDraft("");
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }

  async function sendMessage(content: string) {
    const message = content.trim();
    if (
      !message ||
      sending ||
      !owner.trim() ||
      !repo.trim() ||
      !selectedTicketKey ||
      !selectedRepository
    ) {
      return;
    }

    const developerMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "developer",
      content: message,
      createdAt: new Date(),
    };
    setMessages((current) => [...current, developerMessage]);
    setDraft("");
    setSending(true);
    setStatus("thinking");
    setError(null);

    try {
      const response = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          owner: owner.trim(),
          repo: repo.trim(),
          ticket_key: selectedTicketKey,
          base_branch: selectedRepository.default_branch,
          message,
          session_id: sessionId,
        }),
      });
      const payload = (await response.json()) as
        | ChatResponse
        | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in payload && payload.detail
            ? payload.detail
            : `Chat API returned ${response.status}`,
        );
      }

      const result = payload as ChatResponse;
      setSessionId(result.session_id);
      setRunId(result.run_id);
      setStatus(result.status);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "agent",
          content: result.message,
          createdAt: new Date(),
        },
      ]);
    } catch (sendError) {
      const message =
        sendError instanceof Error ? sendError.message : "Unable to reach agent";
      setError(message);
      setStatus("error");
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "system",
          content: message,
          createdAt: new Date(),
        },
      ]);
    } finally {
      setSending(false);
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void sendMessage(draft);
  }

  return (
    <main className="chatShell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Ticket2Patch activity console">
          <span className="brandMark">T2P</span>
          <span>
            <strong>Ticket2Patch</strong>
            <small>Agent workspace</small>
          </span>
        </a>
        <nav className="mainNav" aria-label="Primary navigation">
          <a href="/">Activity</a>
          <a className="active" href="/chat">Chat</a>
        </nav>
        <div className="connection">
          <span className={`pulse ${error ? "offline" : ""}`} />
          <span>{sending ? "Agent working" : status}</span>
          <button type="button" onClick={resetSession}>
            New chat
          </button>
        </div>
      </header>

      <section className="chatLayout">
        <aside className="chatContext">
          <p className="eyebrow">CONTEXT / REPOSITORY</p>
          <h1>Talk to your<br />engineering agent.</h1>
          <p className="contextCopy">
            Ask Ticket2Patch to read or manage GitHub issues. Every message,
            decision, and MCP tool call is recorded in the activity timeline.
          </p>

          <div className="repositoryForm">
            <label>
              Owner
              <input
                disabled={repositoryLocked}
                onChange={(event) => setOwner(event.target.value)}
                value={owner}
              />
            </label>
            <label>
              Repository
              <select
                disabled={repositoryLocked}
                onChange={(event) => setRepo(event.target.value)}
                value={repo}
              >
                {repositoriesLoading && <option value={repo}>Loading repositories…</option>}
                {!repositoriesLoading && repositories.length === 0 && (
                  <option value="">No repositories found</option>
                )}
                {repositories.map((repositoryOption) => (
                  <option key={repositoryOption.full_name} value={repositoryOption.name}>
                    {repositoryOption.name}
                    {repositoryOption.language ? ` · ${repositoryOption.language}` : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {repositoryError && (
            <p className="repositoryError">{repositoryError}</p>
          )}

          <section className="ticketPicker" aria-label="Jira tickets">
            <div className="ticketPickerHeader">
              <div>
                <p className="eyebrow">JIRA / SELECT A TICKET</p>
                <strong>{tickets.length} visible tickets</strong>
              </div>
              {selectedTicketKey && <span>{selectedTicketKey}</span>}
            </div>
            <div className="ticketList">
              {ticketsLoading && <p className="ticketNotice">Loading Jira tickets…</p>}
              {ticketError && <p className="ticketNotice error">{ticketError}</p>}
              {!ticketsLoading && !ticketError && tickets.length === 0 && (
                <p className="ticketNotice">No Jira tickets are visible.</p>
              )}
              {tickets.map((ticket) => (
                <button
                  className={ticket.key === selectedTicketKey ? "selected" : ""}
                  disabled={repositoryLocked}
                  key={ticket.key}
                  onClick={() => setSelectedTicketKey(ticket.key)}
                  type="button"
                >
                  <span className="ticketKey">{ticket.key}</span>
                  <strong>{ticket.summary}</strong>
                  <small>{ticket.status} · {ticket.issue_type}</small>
                </button>
              ))}
            </div>
          </section>

          <div className="sessionCard">
            <span>Session status</span>
            <strong>{status.replaceAll("_", " ")}</strong>
            <dl>
              <div>
                <dt>Repository</dt>
                <dd>{repository}</dd>
              </div>
              <div>
                <dt>Jira ticket</dt>
                <dd>{selectedTicketKey ?? "Select one"}</dd>
              </div>
              <div>
                <dt>Run</dt>
                <dd>{runId ? runId.slice(0, 18) : "Not started"}</dd>
              </div>
            </dl>
            {runId && (
              <a href={`/?run=${encodeURIComponent(runId)}`}>
                Open activity timeline →
              </a>
            )}
          </div>
        </aside>

        <section className="chatPanel">
          <div className="chatPanelHeader">
            <div>
              <p className="kicker">Live conversation</p>
              <h2>{repository}</h2>
              {selectedTicket && (
                <small>{selectedTicket.key} · {selectedTicket.summary}</small>
              )}
            </div>
            <span className="toolScope">issue_read + issue_write</span>
          </div>

          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="chatWelcome">
                <span className="agentMonogram">AI</span>
                <p className="eyebrow">TICKET2PATCH IS READY</p>
                <h2>What should we investigate?</h2>
                <p>
                  Select a Jira ticket first, then ask Ticket2Patch to investigate
                  it and inspect the repository.
                </p>
                <div className="suggestions">
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => void sendMessage(suggestion)}
                      type="button"
                    >
                      {suggestion}
                      <span>↗</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message) => (
              <article className={`chatMessage ${message.role}`} key={message.id}>
                <div className="messageMeta">
                  <span>
                    {message.role === "developer"
                      ? "You"
                      : message.role === "agent"
                        ? "Ticket2Patch"
                        : "System"}
                  </span>
                  <time>{timeLabel(message.createdAt)}</time>
                </div>
                <div className="messageContent">{message.content}</div>
              </article>
            ))}

            {sending && (
              <article className="chatMessage agent thinkingMessage">
                <div className="messageMeta">
                  <span>Ticket2Patch</span>
                  <time>working</time>
                </div>
                <div className="thinkingDots" aria-label="Agent is thinking">
                  <i />
                  <i />
                  <i />
                </div>
              </article>
            )}
          </div>

          <form className="composer" onSubmit={submit}>
            <textarea
              aria-label="Message Ticket2Patch"
              disabled={sending || !selectedTicketKey || !selectedRepository}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={
                selectedTicketKey
                  ? `Ask Ticket2Patch to investigate ${selectedTicketKey}…`
                  : "Select a Jira ticket before starting…"
              }
              ref={inputRef}
              rows={3}
              value={draft}
            />
            <div className="composerFooter">
              <span>Enter to send · Shift + Enter for a new line</span>
              <button
                disabled={
                  sending ||
                  !draft.trim() ||
                  !selectedTicketKey ||
                  !selectedRepository
                }
                type="submit"
              >
                {sending ? "Working…" : "Send message"}
              </button>
            </div>
          </form>
        </section>
      </section>
    </main>
  );
}
