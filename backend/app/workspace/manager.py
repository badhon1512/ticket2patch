import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE_ROOT = BACKEND_ROOT / ".ticket2patch" / "runs"

REPOSITORY_PATTERN = re.compile(
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?)"
)
TICKET_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,29}-[1-9][0-9]*")
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}")
HOST_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")


class WorkspaceError(RuntimeError):
    """Raised when an isolated workspace cannot be prepared safely."""


@dataclass(frozen=True)
class PreparedWorkspace:
    workspace_id: str
    path: Path
    repository: str
    base_branch: str
    base_sha: str
    branch_name: str


class WorkspaceManager:
    """Clone one repository into a unique run directory and create a branch."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        github_host: str | None = None,
        timeout_seconds: int = 180,
    ) -> None:
        configured_root_value = os.getenv("TICKET2PATCH_WORKSPACE_ROOT", "").strip()
        configured_root = root or (
            Path(configured_root_value)
            if configured_root_value
            else DEFAULT_WORKSPACE_ROOT
        )
        self.root = configured_root.expanduser().resolve()
        self.github_host = (
            github_host or os.getenv("GITHUB_HOST", "github.com")
        ).strip()
        self.timeout_seconds = timeout_seconds

        if not HOST_PATTERN.fullmatch(self.github_host):
            raise ValueError("GITHUB_HOST must be a hostname without a URL scheme")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")

    def prepare(
        self,
        *,
        repository: str,
        ticket_key: str,
        base_branch: str = "main",
        run_id: str | None = None,
    ) -> PreparedWorkspace:
        """Create a shallow checkout pinned to its resolved base commit."""

        repository = repository.strip()
        ticket_key = ticket_key.strip().upper()
        base_branch = base_branch.strip()
        run_id = run_id or uuid4().hex

        if not REPOSITORY_PATTERN.fullmatch(repository):
            raise ValueError("repository must use the owner/repo format")
        if not TICKET_PATTERN.fullmatch(ticket_key):
            raise ValueError("ticket_key must look like PROJ-123")
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id contains unsupported characters")
        self._validate_branch(base_branch, field="base_branch")

        workspace_id = f"{ticket_key.lower()}-{run_id}"
        target = (self.root / workspace_id).resolve()
        self._require_inside_root(target)
        if target.exists():
            raise WorkspaceError(f"Workspace already exists: {workspace_id}")

        branch_name = f"ticket2patch/{ticket_key.lower()}"
        clone_url = f"https://{self.github_host}/{repository}.git"
        self.root.mkdir(parents=True, exist_ok=True)

        try:
            self._run(
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                base_branch,
                "--",
                clone_url,
                str(target),
                cwd=self.root,
            )
            base_sha = self._run("rev-parse", "HEAD", cwd=target).strip()
            if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha):
                raise WorkspaceError("Git returned an invalid base commit SHA")
            self._run("switch", "-c", branch_name, cwd=target)
        except Exception:
            if target.exists():
                self._require_inside_root(target)
                shutil.rmtree(target)
            raise

        return PreparedWorkspace(
            workspace_id=workspace_id,
            path=target,
            repository=repository,
            base_branch=base_branch,
            base_sha=base_sha.lower(),
            branch_name=branch_name,
        )

    def resolve(self, workspace_id: str) -> Path:
        """Resolve an existing workspace ID without allowing path traversal."""

        if not RUN_ID_PATTERN.fullmatch(workspace_id):
            raise ValueError(
                "workspace_id is invalid; prepare a workspace before using "
                "local file tools"
            )
        path = (self.root / workspace_id).resolve()
        self._require_inside_root(path)
        if not path.is_dir() or not (path / ".git").exists():
            raise WorkspaceError(f"Workspace does not exist: {workspace_id}")
        return path

    def _run(self, *arguments: str, cwd: Path) -> str:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceError(f"Git command could not complete: git {arguments[0]}") from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise WorkspaceError(
                f"Git command failed: git {arguments[0]}: {detail or 'unknown error'}"
            )
        return result.stdout

    def _require_inside_root(self, path: Path) -> None:
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("Workspace path escaped the configured root") from exc

    @staticmethod
    def _validate_branch(value: str, *, field: str) -> None:
        invalid = (
            not value
            or value.startswith(("-", ".", "/"))
            or value.endswith((".", "/"))
            or ".." in value
            or "@{" in value
            or any(character in value for character in " ~^:?*[\\")
        )
        if invalid:
            raise ValueError(f"{field} is not a safe Git branch name")
