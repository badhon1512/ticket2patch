import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState

from app.workspace.manager import WorkspaceError, WorkspaceManager

MAX_DIFF_BYTES = 300_000
MAX_FILE_BYTES = 256_000
BLOCKED_PARTS = {".git", ".ssh", "node_modules", "__pycache__"}
BLOCKED_NAMES = {".env", ".npmrc", ".pypirc", "credentials.json"}
BLOCKED_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}

class WorkspaceChangeError(RuntimeError):
    pass


class WorkspaceChanges:
    def __init__(self, manager: WorkspaceManager, timeout_seconds: int = 300) -> None:
        self.manager = manager
        self.timeout_seconds = timeout_seconds

    def write_file(
        self,
        workspace_id: str,
        path: str,
        content: str,
    ) -> dict[str, Any]:
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceChangeError("file content exceeds 256000 UTF-8 bytes")

        root = self.manager.resolve(workspace_id)
        target = self._safe_path(root, path)
        if target.exists() and not target.is_file():
            raise WorkspaceChangeError("path must identify a regular file")
        if not target.parent.is_dir():
            raise WorkspaceChangeError("parent directory does not exist")

        target.write_text(content, encoding="utf-8")
        return {
            "status": "written",
            "changed_files": self.changed_files(workspace_id),
        }

    def edit_file(
        self,
        workspace_id: str,
        path: str,
        old_content: str,
        new_content: str,
    ) -> dict[str, Any]:
        if not old_content:
            raise WorkspaceChangeError("old_content must not be empty")

        root = self.manager.resolve(workspace_id)
        target = self._safe_path(root, path)
        if not target.is_file():
            raise WorkspaceChangeError("path must identify a regular file")
        content = target.read_text(encoding="utf-8")
        matches = content.count(old_content)
        if matches != 1:
            raise WorkspaceChangeError(
                f"old_content must match exactly once; found {matches} matches"
            )
        updated = content.replace(old_content, new_content, 1)
        if len(updated.encode("utf-8")) > MAX_FILE_BYTES:
            raise WorkspaceChangeError("updated file exceeds 256000 UTF-8 bytes")
        target.write_text(updated, encoding="utf-8")
        return {
            "status": "replaced",
            "changed_files": self.changed_files(workspace_id),
        }

    def checkout_branch(self, workspace_id: str, branch: str) -> dict[str, str]:
        root = self.manager.resolve(workspace_id)
        self.manager._validate_branch(branch, field="branch")
        if self._git(root, ["status", "--porcelain"]).strip():
            raise WorkspaceChangeError("workspace must be clean before changing branches")
        self._git(root, ["fetch", "--depth", "1", "origin", branch])
        self._git(root, ["switch", "-C", branch, "FETCH_HEAD"])
        return {"status": "checked_out", "branch_name": branch}

    def restore_files(self, workspace_id: str, paths: list[str]) -> dict[str, Any]:
        if not paths or len(paths) > 20:
            raise WorkspaceChangeError("restore requires between 1 and 20 file paths")

        root = self.manager.resolve(workspace_id)
        safe_paths = [self._safe_path(root, path) for path in paths]
        for path, target in zip(paths, safe_paths, strict=True):
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", path],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            ).returncode == 0
            if tracked:
                self._git(root, ["restore", "--staged", "--worktree", "--", path])
            elif target.is_file():
                target.unlink()
            elif target.exists():
                raise WorkspaceChangeError("restore path must identify a file")

        return {
            "status": "restored",
            "restored_files": paths,
            "changed_files": self.changed_files(workspace_id),
        }

    def diff(self, workspace_id: str) -> str:
        root = self.manager.resolve(workspace_id)
        output = self._git(root, ["diff", "--no-ext-diff", "--unified=3", "--"])
        if len(output.encode("utf-8")) > MAX_DIFF_BYTES:
            raise WorkspaceChangeError("workspace diff exceeds 300000 bytes")
        return output or "No workspace changes"

    def diff_from_base(self, workspace_id: str, base_branch: str) -> str:
        root = self.manager.resolve(workspace_id)
        self.manager._validate_branch(base_branch, field="base_branch")
        output = self._git(
            root,
            [
                "diff",
                "--no-ext-diff",
                "--unified=3",
                f"origin/{base_branch}",
                "HEAD",
                "--",
            ],
        )
        if len(output.encode("utf-8")) > MAX_DIFF_BYTES:
            raise WorkspaceChangeError("base comparison exceeds 300000 bytes")
        return output or "No committed changes from the base branch"

    def changed_files(self, workspace_id: str) -> list[str]:
        root = self.manager.resolve(workspace_id)
        output = self._git(root, ["diff", "--name-only", "--"])
        paths = [line for line in output.splitlines() if line]
        if len(paths) > 20:
            raise WorkspaceChangeError("patch changes more than 20 files")
        for path in paths:
            self._safe_path(root, path)
        return paths

    def _safe_path(
        self,
        root: Path,
        value: str,
        *,
        directory: bool = False,
    ) -> Path:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise WorkspaceChangeError("path must stay inside the repository")
        lowered = {part.casefold() for part in path.parts}
        if lowered & BLOCKED_PARTS:
            raise WorkspaceChangeError("path contains a blocked directory")
        name = path.name.casefold()
        if (
            name in BLOCKED_NAMES
            or name.startswith(".env.")
            or Path(name).suffix in BLOCKED_SUFFIXES
        ):
            raise WorkspaceChangeError("path is protected")

        target = (root / Path(*path.parts)).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkspaceChangeError("path escaped the repository") from exc
        if target.is_symlink():
            raise WorkspaceChangeError("symbolic links cannot be changed")
        if directory and not target.is_dir():
            raise WorkspaceChangeError("check path must be an existing directory")
        return target

    def _git(self, root: Path, arguments: list[str], input_text: str | None = None) -> str:
        result = self._run(["git", *arguments], cwd=root, input_text=input_text)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise WorkspaceChangeError(detail or "git command failed")
        return result.stdout

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceChangeError(f"command could not complete: {command[0]}") from exc


def get_workspace_change_tools(manager: WorkspaceManager) -> tuple[BaseTool, ...]:
    changes = WorkspaceChanges(manager)

    @tool
    def workspace_checkout_branch(
        branch: str,
        state: Annotated[dict[str, Any], InjectedState],
    ) -> dict[str, str]:
        """Switch a clean workspace to the head branch of a matching active PR.

        Call this only after pull_request_read confirms the active PR belongs
        to the selected repository and before applying any local changes.
        """

        try:
            return changes.checkout_branch(_workspace_id(state), branch)
        except (WorkspaceChangeError, WorkspaceError, ValueError) as exc:
            return _error_response("workspace_checkout", exc)

    @tool
    def workspace_write_file(
        path: str,
        content: str,
        state: Annotated[dict[str, Any], InjectedState],
    ) -> dict[str, Any]:
        """Write one complete UTF-8 file inside the disposable workspace.

        Use a repository-relative path returned by the list, search, or read
        tools. Read an existing file before replacing it and preserve unrelated
        content. Use workspace_edit_file for small replacements. Protected
        paths, symlinks, and missing parent directories are rejected.
        """

        try:
            return changes.write_file(_workspace_id(state), path, content)
        except (WorkspaceChangeError, WorkspaceError, ValueError) as exc:
            return _error_response("workspace_write", exc)

    @tool
    def workspace_restore_files(
        paths: list[str],
        state: Annotated[dict[str, Any], InjectedState],
    ) -> dict[str, Any]:
        """Restore explicitly named files in the disposable workspace.

        Use only after reviewing workspace_git_diff when pending changes block a
        required branch checkout. Preserve the intended diff first, restore only
        the listed repository-relative files, retry checkout, then reapply the
        intended patch on the correct branch.
        """

        try:
            return changes.restore_files(_workspace_id(state), paths)
        except (WorkspaceChangeError, WorkspaceError, ValueError) as exc:
            return _error_response("workspace_restore", exc)

    @tool
    def workspace_edit_file(
        path: str,
        old_content: str,
        new_content: str,
        state: Annotated[dict[str, Any], InjectedState],
    ) -> dict[str, Any]:
        """Replace one exact text occurrence in a workspace file.

        Read the file first and copy an exact, unique old_content value from it.
        This is preferred for small edits because it avoids manually generated
        Git patch syntax. The tool rejects zero or multiple matches.
        """

        try:
            return changes.edit_file(
                _workspace_id(state), path, old_content, new_content
            )
        except (WorkspaceChangeError, WorkspaceError, ValueError) as exc:
            return _error_response("workspace_edit", exc)

    @tool
    def workspace_git_diff(
        state: Annotated[dict[str, Any], InjectedState],
        comparison: Literal["working", "base"] = "working",
    ) -> str:
        """Return the working diff or compare the current branch with its base.

        Use comparison "base" after checking out an existing PR to inspect its
        committed changes. Use "working" after editing to review unpublished
        workspace changes.
        """

        try:
            workspace_id = _workspace_id(state)
            if comparison == "base":
                base_branch = state.get("base_branch")
                if not isinstance(base_branch, str) or not base_branch:
                    raise WorkspaceChangeError("No base branch is attached to this run")
                return changes.diff_from_base(workspace_id, base_branch)
            return changes.diff(workspace_id)
        except (WorkspaceChangeError, WorkspaceError, ValueError) as exc:
            return _error_response("workspace_diff", exc)

    return (
        workspace_checkout_branch,
        workspace_write_file,
        workspace_restore_files,
        workspace_edit_file,
        workspace_git_diff,
    )


def _workspace_id(state: dict[str, Any]) -> str:
    workspace_id = state.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise WorkspaceChangeError("No prepared workspace is attached to this run")
    return workspace_id


def _error_response(operation: str, error: Exception) -> dict[str, str]:
    reason = str(error)
    rejected = any(
        marker in reason.lower()
        for marker in (
            "blocked",
            "protected",
            "escaped",
            "symbolic link",
            "outside the repository",
        )
    )
    return {
        "status": "rejected" if rejected else "retry",
        "stage": operation,
        "reason": reason,
        "required_action": _recovery_action(reason),
    }


def _recovery_action(reason: str) -> str:
    lowered = reason.lower()
    if "workspace must be clean" in lowered:
        return (
            "Call workspace_git_diff to inspect the pending changes. Preserve the "
            "intended patch; otherwise start a fresh workspace, then retry checkout"
        )
    if "parent directory" in lowered or "existing directory" in lowered:
        return "List the repository paths and retry with an existing parent directory"
    if "old_content" in lowered:
        return "Reread the file and retry with an exact text block that occurs once"
    if "no prepared workspace" in lowered:
        return "Prepare a workspace before retrying this operation"
    if any(word in lowered for word in ("blocked", "protected", "escaped")):
        return "Choose an allowed repository-relative path; do not retry the rejected path"
    return "Inspect the reported condition, correct the tool arguments, and retry"
