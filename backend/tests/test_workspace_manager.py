import subprocess

import pytest

from app.workspace import WorkspaceManager


def test_prepare_clones_and_creates_ticket_branch(tmp_path, monkeypatch):
    calls = []
    sha = "a" * 40

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1] == "clone":
            (tmp_path / "runs" / "mcp-1-run-123").mkdir(parents=True)
        output = f"{sha}\n" if command[1] == "rev-parse" else ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    manager = WorkspaceManager(root=tmp_path / "runs")

    workspace = manager.prepare(
        repository="badhon1512/ticket2patch",
        ticket_key="MCP-1",
        run_id="run-123",
    )

    assert workspace.base_sha == sha
    assert workspace.branch_name == "ticket2patch/mcp-1"
    assert workspace.path == (tmp_path / "runs" / "mcp-1-run-123").resolve()
    assert calls[0][0] == [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--branch",
        "main",
        "--",
        "https://github.com/badhon1512/ticket2patch.git",
        str(workspace.path),
    ]
    assert calls[1][0] == ["git", "rev-parse", "HEAD"]
    assert calls[2][0] == ["git", "switch", "-c", "ticket2patch/mcp-1"]
    assert all(call[1]["shell"] is False for call in calls)
    assert all(call[1]["env"]["GIT_TERMINAL_PROMPT"] == "0" for call in calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "../ticket2patch"),
        ("repository", "owner/repo/extra"),
        ("ticket_key", "../../escape"),
        ("ticket_key", "MCP-0"),
        ("base_branch", "--upload-pack=evil"),
        ("base_branch", "main..other"),
        ("run_id", "../run"),
    ],
)
def test_prepare_rejects_unsafe_input(tmp_path, field, value):
    arguments = {
        "repository": "owner/repo",
        "ticket_key": "MCP-1",
        "base_branch": "main",
        "run_id": "run-123",
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        WorkspaceManager(root=tmp_path).prepare(**arguments)
