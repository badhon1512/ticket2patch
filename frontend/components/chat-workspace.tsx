"use client";

import { FormEvent, useMemo, useRef, useState } from "react";

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
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const repository = useMemo(() => `${owner}/${repo}`, [owner, repo]);
  const repositoryLocked = sessionId !== null;

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
    if (!message || sending || !owner.trim() || !repo.trim()) return;

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
              <input
                disabled={repositoryLocked}
                onChange={(event) => setRepo(event.target.value)}
                value={repo}
              />
            </label>
          </div>

          <div className="sessionCard">
            <span>Session status</span>
            <strong>{status.replaceAll("_", " ")}</strong>
            <dl>
              <div>
                <dt>Repository</dt>
                <dd>{repository}</dd>
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
                  Start with a GitHub issue, ask about available capabilities,
                  or create a clearly scoped engineering ticket.
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
              disabled={sending}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="Ask about an issue or create a new one…"
              ref={inputRef}
              rows={3}
              value={draft}
            />
            <div className="composerFooter">
              <span>Enter to send · Shift + Enter for a new line</span>
              <button
                disabled={sending || !draft.trim()}
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
