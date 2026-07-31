import argparse
import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

INVESTIGATOR_TOOLS = frozenset(
    {
        "issue_read",
        "issue_write",
    }
)

PUBLISHER_TOOLS = frozenset(
    {
        "create_branch",
        "push_files",
        "create_pull_request",
    }
)

DEFAULT_GITHUB_MCP_IMAGE = (
    "ghcr.io/github/github-mcp-server"
    "@sha256:c491ffdf6f4c85cb5397021bc655edb8ab825c6f5f568e7597d77a1bd7c4d308"
)


@dataclass(frozen=True)
class GitHubMCPConfig:
    """Configuration for one least-privilege GitHub MCP process."""

    token: str = field(repr=False)
    profile: Literal["investigator", "publisher"]
    image: str = DEFAULT_GITHUB_MCP_IMAGE
    github_host: str | None = None

    def __post_init__(self) -> None:
        if not self.token.strip():
            raise ValueError("A short-lived GitHub token is required")
        if not self.image.startswith("ghcr.io/github/github-mcp-server"):
            raise ValueError("Only GitHub's official MCP image is allowed")
        if "@sha256:" not in self.image:
            raise ValueError("GitHub MCP image must be pinned by digest")


class GitHubMCP:
    """Load a narrowly scoped tool profile from GitHub's official MCP server."""

    def __init__(self, config: GitHubMCPConfig) -> None:
        self.config = config

    @property
    def allowed_tools(self) -> frozenset[str]:
        if self.config.profile == "investigator":
            return INVESTIGATOR_TOOLS
        return PUBLISHER_TOOLS

    def _server_config(self) -> dict:
        environment = {
            "GITHUB_PERSONAL_ACCESS_TOKEN": self.config.token,
            "GITHUB_TOOLSETS": "all",
        }
        docker_args = [
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_TOOLSETS",
        ]

        if self.config.github_host:
            environment["GITHUB_HOST"] = self.config.github_host
            docker_args.extend(["-e", "GITHUB_HOST"])

        docker_args.append(self.config.image)
        return {
            "transport": "stdio",
            "command": "docker",
            "args": docker_args,
            "env": environment,
        }

    async def load_tools(self) -> tuple[BaseTool, ...]:
        """Start the scoped MCP process and return only expected tools."""

        client = MultiServerMCPClient(
            {
                f"github_{self.config.profile}": self._server_config(),
            }
        )
        discovered = await client.get_tools()
        if not discovered:
            raise RuntimeError("GitHub MCP returned no tools")
        return tuple(discovered)


async def get_github_tools(
    profile: Literal["investigator", "publisher"] = "investigator",
) -> tuple[BaseTool, ...]:
    """Load GitHub tools using the backend environment configuration."""

    token = (
        os.getenv("GITHUB_MCP_TOKEN", "").strip()
        or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "").strip()
    )
    if not token:
        raise ValueError(
            "GITHUB_MCP_TOKEN or GITHUB_PERSONAL_ACCESS_TOKEN is required"
        )

    return await GitHubMCP(
        GitHubMCPConfig(
            token=token,
            profile=profile,
            github_host=os.getenv("GITHUB_HOST") or None,
        )
    ).load_tools()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect tools exposed by the configured GitHub MCP profile."
    )
    parser.add_argument(
        "--profile",
        choices=("investigator", "publisher"),
        default="investigator",
        help="Tool profile to inspect (default: issue read/write).",
    )
    return parser.parse_args()


async def _inspect_tools(profile: Literal["investigator", "publisher"]) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    load_dotenv(backend_root / ".env", override=False)

    token = os.getenv("GITHUB_MCP_TOKEN") or os.getenv(
        "GITHUB_PERSONAL_ACCESS_TOKEN"
    )
    if not token:
        raise SystemExit(
            "Configuration error: set GITHUB_MCP_TOKEN or "
            "GITHUB_PERSONAL_ACCESS_TOKEN in backend/.env"
        )

    tools = await GitHubMCP(
        GitHubMCPConfig(token=token, profile=profile)
    ).load_tools()

    print(f"\nGitHub MCP profile: {profile}")
    print(f"Discovered {len(tools)} allowed tool(s):\n")
    for tool in sorted(tools, key=lambda item: item.name):
        schema = tool.args_schema
        if hasattr(schema, "model_json_schema"):
            schema = schema.model_json_schema()
        elif hasattr(schema, "schema"):
            schema = schema.schema()

        print(f"- {tool.name}")
        if tool.description:
            print(f"  {tool.description.strip()}")
        print("  Input schema: " + json.dumps(schema, indent=2))
        print()


def main() -> None:
    args = _parse_args()
    asyncio.run(_inspect_tools(args.profile))


if __name__ == "__main__":
    main()
