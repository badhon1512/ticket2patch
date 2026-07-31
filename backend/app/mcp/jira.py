import asyncio
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

JIRA_TOOLS = frozenset(
    {
        "getAccessibleAtlassianResources",
        "getJiraIssue",
        "searchJiraIssuesUsingJql",
        "createJiraIssue",
        "editJiraIssue",
    }
)

DEFAULT_ATLASSIAN_MCP_URL = "https://mcp.atlassian.com/v1/mcp"
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _jira_connection() -> dict:
    load_dotenv(BACKEND_ROOT / ".env", override=False)
    email = os.getenv("ATLASSIAN_EMAIL", "").strip()
    api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()
    url = os.getenv("ATLASSIAN_MCP_URL", DEFAULT_ATLASSIAN_MCP_URL)

    if not email:
        raise ValueError("ATLASSIAN_EMAIL is required")
    if not api_token:
        raise ValueError("ATLASSIAN_API_TOKEN is required")
    if not url.startswith("https://"):
        raise ValueError("ATLASSIAN_MCP_URL must use HTTPS")

    credentials = base64.b64encode(
        f"{email}:{api_token}".encode()
    ).decode()
    return {
        "transport": "streamable_http",
        "url": url,
        "headers": {
            "Authorization": f"Basic {credentials}",
        },
    }


async def get_jira_tools() -> tuple[BaseTool, ...]:
    """Return minimal Jira read tools plus explicit issue editing."""

    client = MultiServerMCPClient({"jira": _jira_connection()})
    try:
        discovered = await client.get_tools()
    except UnboundLocalError as exc:
        raise RuntimeError(
            "The MCP adapter lost the Atlassian tool-listing error. "
            "Retry Jira discovery; if it repeats, verify the token and network."
        ) from exc
    tools = tuple(
        tool for tool in discovered if tool.name in JIRA_TOOLS
    )
    if not tools:
        available = ", ".join(sorted(tool.name for tool in discovered))
        raise RuntimeError(
            "Atlassian Rovo MCP returned no Jira read tools. "
            "Enable the read_jira/search_jira permission groups and grant "
            f"read:jira-work and search:jira-work scopes. Available: {available}"
        )
    return tools


def _schema(tool: BaseTool) -> dict:
    schema = tool.args_schema
    if isinstance(schema, dict):
        return schema
    if hasattr(schema, "model_json_schema"):
        return schema.model_json_schema()
    if hasattr(schema, "schema"):
        return schema.schema()
    return {}


async def _inspect_tools() -> None:
    tools = await get_jira_tools()
    print(f"Discovered {len(tools)} Jira tool(s):\n")
    for tool in sorted(tools, key=lambda item: item.name):
        print(f"- {tool.name}")
        print(f"  {tool.description.strip()}")
        print("  Input schema: " + json.dumps(_schema(tool), indent=2))
        print()


def main() -> None:
    asyncio.run(_inspect_tools())


if __name__ == "__main__":
    main()
