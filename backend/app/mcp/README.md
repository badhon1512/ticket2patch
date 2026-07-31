# GitHub MCP integration

Ticket2Patch uses GitHub's official MCP server for production repository and
pull-request operations.

Two independent profiles are required:

## Investigator

Read-only mode is enforced by the MCP server. Only these tools are requested:

- `get_file_contents`
- `search_code`
- `list_commits`
- `get_commit`
- `list_pull_requests`
- `pull_request_read`

These tools may be attached to the investigation agent's normal tool loop.

## Publisher

Only these write tools are requested:

- `create_branch`
- `push_files`
- `create_pull_request`

They must be called from an explicit publication node after a recorded human
approval. They must never be added to the investigation `ToolNode`.

The publisher profile deliberately excludes file deletion, repository creation,
PR merging, workflow dispatch, and administrative tools.

## Authentication

Use short-lived GitHub App installation tokens in production. A personal access
token is acceptable only for local development. Never commit tokens or return
them in logs, traces, model messages, or tool results.

Pin the official container image to a reviewed version or immutable digest
before production deployment.

## Local Git chat

Set a fine-grained GitHub token restricted to the repository being tested and
an OpenAI API key:

```powershell
$env:GITHUB_MCP_TOKEN = "..."
$env:OPENAI_API_KEY = "..."
```

Then run:

```powershell
uv run python -m app.cli --owner badhon1512 --repo ticket2patch
```

The local chat uses only the investigator profile. It cannot create branches,
push files, or open pull requests.
