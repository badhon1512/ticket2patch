# Ticket2Patch

> A ticket-to-patch AI agent that investigates Jira issues, changes code in an
> isolated workspace, and opens a draft pull request for review.

## Demo

![Ticket2Patch agent workflow](docs/assets/ticket2patch-demo.gif)

The Ticket2Patch Agent LLM selects scoped Jira MCP, GitHub MCP, and workspace
tools from live run state, then publishes the verified diff as a guarded draft
pull request.

## Problem

Production issues are captured in Jira, while the technical context needed to
resolve them spans GitHub, source code, pull requests, and local tooling.
Engineers spend valuable incident time connecting that context,
testing hypotheses, and coordinating repetitive handoffs. General coding agents
can generate code, but without isolation, scoped permissions, traceable state,
and publication controls, they are unsafe for production maintenance workflows.

## Goal

Build an auditable production-engineering system that converts a Jira issue into
an evidence-backed, minimal draft pull request. The system should reduce manual
triage while keeping tool access bounded, workspace changes isolated, decisions
recoverable, and every published file attributable to the ticket and run.

## Solution

Ticket2Patch is a stateful AI orchestration system built with LangGraph and MCP.
Its orchestrator dynamically coordinates Jira MCP, GitHub MCP, an investigator,
structured root-cause analysis, and constrained coding tools. Each run operates
inside an isolated Git workspace, verifies the exact diff before publication,
and creates or updates a guarded draft PR. Recoverable tool failures return to
the orchestrator for another decision, while messages, tool activity, and run
outcomes are persisted in PostgreSQL for traceability and operational review.

## Highlights

- End-to-end Jira-to-draft-PR workflow using LangGraph and MCP
- Structured root-cause analysis before code modification
- Isolated Git workspaces with constrained read and write tools
- Guarded publication that verifies repository, branch, and exact changed files
- Existing PR detection to update active work instead of creating duplicates
- Recoverable tool errors returned to the agent for correction and retry
- Shared agent across CLI and web chat with PostgreSQL activity history
- Automated backend tests, lint checks, and a lightweight VS Code extension

## Tech stack

Python, LangGraph, LangChain, OpenAI, Model Context Protocol, Atlassian Rovo
MCP, GitHub MCP, FastAPI, PostgreSQL, Next.js, TypeScript, Docker, and VS Code
Extension API.

## Architecture

```mermaid
flowchart TB
    JIRA{{Jira MCP}} <-->|ticket context| O[Ticket2Patch Orchestrator]
    STATE[Typed graph state] <--> O

    O <--> GITHUB[GitHub MCP]
    O <--> I[Investigator]
    O <--> R[Root-Cause Analysis]
    O <--> C[Coding Tools]
    O <--> P[Guarded PR Publisher]

    O --> PR[Draft pull request]
    PR --> END((End))
    O --> DB[(Activity and trace store)]

    style JIRA fill:#0C66E4,color:#ffffff,stroke:#0747A6,stroke-width:3px
    style END fill:#059669,color:#ffffff,stroke:#047857,stroke-width:3px
```

See the [detailed architecture](docs/ARCHITECTURE.md) for the complete agent
graph, dynamic ToolNode loops, state handoffs, and runtime boundaries.

The orchestrator is the LangGraph routing and state layer around the Agent LLM.
It delegates work, captures every tool result, updates run state, and decides
whether to investigate further, analyze, implement, recover, or publish.
The diagram shows possible decisions, not a fixed tool execution order.

## Agent workflow

```text
Jira ticket + selected repository
    -> eligibility and workspace safety gates
    -> agent decision loop
         - inspect current state and evidence
         - select the most relevant MCP or workspace tool
         - incorporate the tool result
         - recover, retry, or choose another tool when needed
    -> publication guards
    -> draft PR and final run summary
```

Tool usage is not a hard-coded sequence. The agent chooses capabilities from the
current state, while deterministic gates enforce workspace and publication
safety. Every published file must match the local diff. Recoverable failures are
returned to the agent; genuine permission, credential, or policy blockers stop
the run and are reported.

## Project structure

```text
ticket2patch/
|-- backend/
|   |-- app/
|   |   |-- agents/            # LangGraph, prompts, state, and guardrails
|   |   |-- api/               # Chat and activity HTTP API
|   |   |-- db/                # PostgreSQL activity persistence
|   |   |-- mcp/               # GitHub and Jira MCP connections
|   |   |-- observability/     # Agent and tool activity callbacks
|   |   |-- schemas/           # API and activity models
|   |   |-- services/          # Shared chat service
|   |   |-- workspace/         # Repository manager and local file tools
|   |   `-- cli.py             # Terminal chat
|   |-- .env.example
|   |-- pyproject.toml
|   `-- uv.lock
|-- extension/
|   |-- media/
|   |-- src/extension.js
|   |-- package.json
|   `-- README.md
|-- frontend/                   # Next.js chat and activity dashboard
|-- deployment/                 # Local service configuration
|-- docs/
|   `-- PLAN_DRAFT.md
`-- README.md
```

## Requirements

- Python 3.11–3.13
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop with the Docker engine running
- PostgreSQL 17 (provided by the local Docker Compose configuration)
- An OpenAI API key
- A GitHub fine-grained personal access token for local development

Restrict the GitHub token to the target repositories and grant only the
permissions required for investigation and draft-PR publication:

- Metadata: read
- Issues: read and write
- Contents: read and write
- Pull requests: read and write

Use a short-lived GitHub App installation token instead of a personal access
token in production.

## Backend setup

From the repository root:

```powershell
cd backend
Copy-Item .env.example .env
uv sync --extra dev
```

Configure `backend/.env`:

```dotenv
GITHUB_MCP_TOKEN=your_fine_grained_github_token
OPENAI_API_KEY=your_openai_api_key
TICKET2PATCH_MODEL=gpt-4.1-mini
TICKET2PATCH_DATABASE_URL=postgresql://ticket2patch:ticket2patch@127.0.0.1:5432/ticket2patch
```

Do not commit `.env` or expose its values in logs, prompts, screenshots, or
issue content.

## Chat with the agent

From `backend`:

```powershell
uv run python -m app.cli --owner badhon1512 --repo ticket2patch
```

Example prompts:

```text
Read issue 12 and summarize the expected behavior.
```

```text
Create an issue titled "Investigate flaky authentication test" with a concise
description and acceptance criteria.
```

The `--owner` and `--repo` values determine the repository context supplied to
the agent. Exit with `/exit`.

## Inspect the MCP tools

Show the tools returned by the current GitHub MCP profile:

```powershell
uv run python app/mcp/github.py
```

The command prints each tool's name, description, and input JSON schema. It only
discovers tools; it does not call them.

Inspect the tools available to the publisher profile:

```powershell
uv run python app/mcp/github.py --profile publisher
```

Publisher tools are available only during the publication phase and are checked
by deterministic guards before they can change a remote branch or pull request.

## Run the VS Code extension

1. Open the `extension` directory in VS Code.
2. Press `F5`.
3. In the Extension Development Host, select the Ticket2Patch Activity Bar icon.
4. Select **Start from Jira Ticket**.

The extension currently provides navigation and input scaffolding only. It is
not yet connected to the backend.

Validate its JavaScript:

```powershell
cd extension
npm run check
```

## Run the activity dashboard

Start PostgreSQL from the repository root:

```powershell
docker compose -f deployment/docker-compose.yml up -d postgres
```

Start the activity API from `backend`:

```powershell
uv run uvicorn app.api.main:app --reload --port 8000
```

Start the Next.js frontend in another terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. CLI runs and their developer, agent, and MCP tool
events are stored in PostgreSQL and appear automatically in the dashboard.

Open `http://localhost:3000/chat` to talk to the LangGraph agent from the
browser. The web chat uses the same scoped GitHub MCP tools as the CLI and
records its messages and tool calls in the activity dashboard.

The API initializes one shared LangGraph agent during startup and reuses it
across browser sessions. Each session keeps separate conversation state and a
unique LangGraph `thread_id`, avoiding repeated MCP tool discovery on every new
chat.

## Development checks

From `backend`:

```powershell
uv run ruff check app
uv run pytest
```

The backend test suite covers the graph flow, workspace tools, publisher guards,
and supporting services.

## Roadmap

The core ticket-to-draft-PR workflow is complete. Remaining work focuses on
production hardening:

- Repository-specific test, lint, type, and security validation
- Human approval checkpoints for sensitive publication actions
- Webhook-triggered background runs with streaming status updates
- Short-lived credentials, stronger prompt-injection defenses, and rate limits
- LLMOps dashboards for traces, token usage, latency, and cost analytics
- Historical-ticket evaluations, monitoring, and deployment automation

## Safety principles

- The model never grants itself permissions.
- Tool availability and credentials enforce authorization outside the prompt.
- Investigation, workspace modification, and publication use separate
  capabilities.
- Every mutation should be attributable, auditable, and reversible.
- Production access, autonomous merging, and autonomous deployment are outside
  the agent's authority.
- Draft PRs remain reviewable artifacts; the agent cannot merge or deploy them.

## Documentation

See [docs/PLAN_DRAFT.md](docs/PLAN_DRAFT.md) for the longer product and technical
plan. Component-specific notes are also available in:

- [Agent design](backend/app/agents/README.md)
- [System architecture](docs/ARCHITECTURE.md)
- [GitHub MCP integration](backend/app/mcp/README.md)
- [VS Code extension](extension/README.md)

## Project status

Core workflow complete; production hardening is in progress. Ticket2Patch can
currently investigate a Jira issue, prepare a repository patch, and create or
update a guarded draft pull request with a traceable run summary.
