# Ticket2Patch

> An AI engineering agent that turns a production ticket into an investigated,
> tested patch and a review-ready pull request.

Ticket2Patch is an early-stage developer tool built with LangGraph and the Model
Context Protocol (MCP). Its target workflow starts with a Jira production issue,
investigates the relevant repository, proposes a bounded fix, validates the
change, and opens a draft pull request for human review.

The project currently includes an executable LangGraph agent, a scoped
integration with GitHub's official MCP server, a terminal chat interface, and a
small VS Code extension scaffold. Automated patching and PR publication remain
planned work.

## Why Ticket2Patch?

Production issues often require the same sequence of manual work: understand the
ticket, locate the responsible code, inspect recent changes, reproduce the
failure, create a minimal fix, run checks, and prepare a pull request.
Ticket2Patch aims to coordinate that workflow while preserving clear permission
boundaries and human approval for consequential actions.

## Current capabilities

- [x] Class-based LangGraph agent with typed state
- [x] Ticket eligibility guardrail
- [x] Model/tool execution loop using LangGraph `ToolNode`
- [x] GitHub's official MCP server running through a pinned Docker image
- [x] Dynamic conversion of MCP tools into LangChain tools
- [x] Terminal chat with conversation state
- [x] Loading configuration from `backend/.env`
- [x] Scoped GitHub issue tools: `issue_read` and `issue_write`
- [x] Tool discovery command that prints names, descriptions, and schemas
- [x] Initial zero-build VS Code Activity Bar extension

The current GitHub profile intentionally exposes only issue reading and
creation/update operations. It cannot push files, merge pull requests, delete
repositories, deploy code, or perform repository administration.

## Project plan

Ticket2Patch will be developed as a controlled, stage-based engineering
workflow. Each stage will produce structured evidence for the next stage, and
write operations will be isolated behind deterministic policy checks and human
approval.

The planned end-to-end workflow is:

```text
Jira ticket
    -> eligibility and repository mapping
    -> evidence collection
    -> root-cause investigation
    -> reproduction
    -> fix plan
    -> human approval
    -> isolated patch generation
    -> tests, lint, and security checks
    -> review
    -> publication approval
    -> branch, commit, and draft PR
```

The implementation will progress through four main phases:

1. Connect Jira and normalize eligible production tickets.
2. Investigate repository code, history, pull requests, and CI evidence.
3. Generate and validate a minimal patch inside an isolated workspace.
4. Request approval, publish a branch, and open a detailed draft pull request.

Ticket2Patch will stop safely when evidence is insufficient, validation fails,
or a required approval is declined. Merging and production deployment remain
outside the agent's authority.

## Project structure

```text
ticket2patch/
|-- backend/
|   |-- app/
|   |   |-- agents/
|   |   |   |-- agent.py       # LangGraph construction and routing
|   |   |   |-- factory.py     # Model, MCP, and agent composition
|   |   |   |-- guardrails.py  # Deterministic eligibility policy
|   |   |   |-- prompts.py     # Agent instructions
|   |   |   `-- state.py       # Typed LangGraph state
|   |   |-- mcp/
|   |   |   `-- github.py      # Official GitHub MCP connection and inspector
|   |   `-- cli.py             # Local terminal chat
|   |-- .env.example
|   |-- pyproject.toml
|   `-- uv.lock
|-- extension/
|   |-- media/
|   |-- src/extension.js
|   |-- package.json
|   `-- README.md
|-- docs/
|   `-- PLAN_DRAFT.md
`-- README.md
```

The broader backend folders described in the plan will be introduced only when
their functionality is implemented.

## Requirements

- Python 3.11–3.13
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop with the Docker engine running
- An OpenAI API key
- A GitHub fine-grained personal access token for local development

For the current issue-only integration, restrict the GitHub token to the target
repository and grant only:

- Metadata: read
- Issues: read and write

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

Inspect the separately defined future publisher profile:

```powershell
uv run python app/mcp/github.py --profile publisher
```

Publisher tools are not attached to the current chat agent.

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

## Development checks

From `backend`:

```powershell
uv run ruff check app
uv run pytest
```

The test suite is still a TODO; `pytest` may report that no tests were
collected until the first test cases are added.

## Later roadmap

### Foundation

- [x] Define agent mission, state, and safety boundaries
- [x] Build the initial LangGraph model/tool loop
- [x] Connect the official GitHub MCP server
- [x] Add local CLI and MCP tool inspection
- [ ] Add unit tests for state, routing, guardrails, and MCP filtering
- [ ] Add structured logs and LangGraph/MCP tracing
- [ ] Add durable checkpoint storage

### Jira ingestion

- [ ] Add Jira Cloud authentication
- [ ] Add Jira MCP or a narrowly scoped Jira API adapter
- [ ] Normalize Jira tickets into the graph state
- [ ] Map Jira projects/components to allowed repositories
- [ ] Support Jira webhook and manual-trigger ingestion
- [ ] Add duplicate-run and idempotency protection

### Repository investigation

- [ ] Restore scoped repository read tools for code and commit investigation
- [ ] Collect relevant files, commits, pull requests, and CI evidence
- [ ] Produce a structured root-cause report with confidence and citations
- [ ] Add repository size and context-budget controls

### Patch generation and validation

- [ ] Create an isolated local workspace for each run
- [ ] Add bounded filesystem editing tools
- [ ] Generate the smallest viable patch
- [ ] Run repository-specific tests, lint, type checks, and security checks
- [ ] Record commands, results, changed files, and artifacts
- [ ] Add retry and failure-recovery policies

### Approval and pull requests

- [ ] Add LangGraph interrupts for plan and publication approval
- [ ] Use a separate least-privilege GitHub publisher identity
- [ ] Create a ticket-specific branch
- [ ] Commit and push validated changes
- [ ] Open a draft PR with evidence, risk, and validation results
- [ ] Never allow autonomous merge or deployment

### Backend and interfaces

- [ ] Add an authenticated HTTP API
- [ ] Add background jobs and run-status streaming
- [ ] Persist runs, approvals, audit events, and artifacts
- [ ] Connect the VS Code extension to the backend
- [ ] Add approval, diff, logs, and PR views to the extension
- [ ] Add a small operator dashboard

### Production readiness

- [ ] Replace local PATs with short-lived installation tokens
- [ ] Run MCP servers as managed services or scoped run sessions
- [ ] Add secret redaction and prompt-injection defenses
- [ ] Add rate limits, timeouts, cancellation, and cost budgets
- [ ] Add historical-ticket evaluations and regression gates
- [ ] Add deployment manifests, monitoring, alerts, and operational runbooks

## Safety principles

- The model never grants itself permissions.
- Tool availability and credentials enforce authorization outside the prompt.
- Investigation, workspace modification, and publication use separate
  capabilities.
- Every mutation should be attributable, auditable, and reversible.
- Production access, autonomous merging, and autonomous deployment are outside
  the agent's authority.
- Human approval is required before code publication.

## Documentation

See [docs/PLAN_DRAFT.md](docs/PLAN_DRAFT.md) for the longer product and technical
plan. Component-specific notes are also available in:

- [Agent design](backend/app/agents/README.md)
- [GitHub MCP integration](backend/app/mcp/README.md)
- [VS Code extension](extension/README.md)

## Project status

Ticket2Patch is an experimental project under active development. The current
issue-tool prototype is useful for learning and validating the LangGraph + MCP
integration, but it is not yet a production ticket-to-PR system.
