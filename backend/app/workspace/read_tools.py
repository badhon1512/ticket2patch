import os
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import BaseTool, tool
from langgraph.prebuilt import InjectedState

from app.workspace.manager import WorkspaceError, WorkspaceManager

MAX_FILE_BYTES = 256_000
MAX_LIST_RESULTS = 500
MAX_SEARCH_FILES = 2_000
MAX_SEARCH_RESULTS = 100
MAX_LINE_CHARS = 500

BLOCKED_DIRECTORY_NAMES = frozenset(
    {".git", ".hg", ".svn", ".ssh", "node_modules", "__pycache__"}
)
BLOCKED_FILE_NAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ed25519",
        "id_rsa",
    }
)
BLOCKED_SUFFIXES = frozenset({".key", ".p12", ".pfx", ".pem"})


class WorkspaceReadError(RuntimeError):
    """Raised when a workspace read violates a boundary or limit."""


class WorkspaceReader:
    """List, search, and read files within one prepared workspace."""

    def __init__(self, manager: WorkspaceManager) -> None:
        self.manager = manager

    def list_files(
        self,
        workspace_id: str,
        path: str = ".",
        limit: int = 200,
    ) -> list[str]:
        """List readable files recursively beneath a workspace-relative path."""

        limit = self._bounded_limit(limit, maximum=MAX_LIST_RESULTS)
        root, target = self._resolve(workspace_id, path)
        if not target.is_dir():
            raise WorkspaceReadError("path must identify a directory")

        files: list[str] = []
        for candidate in self._iter_files(root, target):
            if len(files) >= limit:
                break
            if (
                candidate.stat().st_size <= MAX_FILE_BYTES
                and self._is_readable_text(candidate)
            ):
                files.append(candidate.relative_to(root).as_posix())
        return files

    def read_file(self, workspace_id: str, path: str) -> str:
        """Read one bounded UTF-8 text file from the workspace."""

        print("Reading file :", path)

        root, target = self._resolve(workspace_id, path)
        if self._is_blocked(root, target):
            raise WorkspaceReadError("Access to this file is blocked")
        if target.is_symlink() or not target.is_file():
            raise WorkspaceReadError("path must identify a regular file")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceReadError("File exceeds the read-size limit")

        content = target.read_bytes()
        if b"\x00" in content:
            raise WorkspaceReadError("Binary files cannot be read")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceReadError("File is not valid UTF-8 text") from exc

    def search_code(
        self,
        workspace_id: str,
        query: str,
        path: str = ".",
        limit: int = 50,
    ) -> list[dict[str, str | int]]:
        """Find a fixed text string in bounded readable workspace files."""

        query = query.strip()
        if not query or len(query) > 200:
            raise ValueError("query must contain 1 to 200 characters")
        limit = self._bounded_limit(limit, maximum=MAX_SEARCH_RESULTS)
        root, target = self._resolve(workspace_id, path)
        if not target.is_dir():
            raise WorkspaceReadError("path must identify a directory")

        matches: list[dict[str, str | int]] = []
        inspected = 0
        for candidate in self._iter_files(root, target):
            if len(matches) >= limit or inspected >= MAX_SEARCH_FILES:
                break
            if candidate.stat().st_size > MAX_FILE_BYTES:
                continue

            inspected += 1
            content = candidate.read_bytes()
            if b"\x00" in content:
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue

            for line_number, line in enumerate(text.splitlines(), start=1):
                if query.casefold() not in line.casefold():
                    continue
                matches.append(
                    {
                        "path": candidate.relative_to(root).as_posix(),
                        "line": line_number,
                        "text": line[:MAX_LINE_CHARS],
                    }
                )
                if len(matches) >= limit:
                    break
        return matches

    def _resolve(self, workspace_id: str, path: str) -> tuple[Path, Path]:
        root = self.manager.resolve(workspace_id)
        relative = Path(path)
        if relative.is_absolute():
            raise WorkspaceReadError("path must be relative to the workspace")
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise WorkspaceReadError("path escaped the workspace") from exc
        if not target.exists():
            raise WorkspaceReadError("path does not exist")
        if self._is_blocked(root, target):
            raise WorkspaceReadError("Access to this path is blocked")
        return root, target

    def _iter_files(self, root: Path, target: Path) -> Iterator[Path]:
        for current, directory_names, file_names in os.walk(
            target,
            followlinks=False,
        ):
            current_path = Path(current)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not (current_path / name).is_symlink()
                and not self._is_blocked(root, current_path / name)
            )
            for name in sorted(file_names):
                candidate = current_path / name
                if candidate.is_symlink() or self._is_blocked(root, candidate):
                    continue
                if candidate.is_file():
                    yield candidate

    @staticmethod
    def _is_blocked(root: Path, path: Path) -> bool:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise WorkspaceError("Resolved path escaped the workspace") from exc

        lowered_parts = [part.casefold() for part in relative.parts]
        if any(part in BLOCKED_DIRECTORY_NAMES for part in lowered_parts):
            return True
        name = path.name.casefold()
        return (
            name in BLOCKED_FILE_NAMES
            or name.startswith(".env.")
            or path.suffix.casefold() in BLOCKED_SUFFIXES
        )

    @staticmethod
    def _bounded_limit(value: int, *, maximum: int) -> int:
        if value < 1 or value > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}")
        return value

    @staticmethod
    def _is_readable_text(path: Path) -> bool:
        content = path.read_bytes()
        if b"\x00" in content:
            return False
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True


def get_workspace_read_tools(manager: WorkspaceManager) -> tuple[BaseTool, ...]:
    """Create LangChain tools scoped through the supplied workspace manager."""

    reader = WorkspaceReader(manager)

    @tool
    def workspace_list_files(
        state: Annotated[dict[str, Any], InjectedState],
        path: str = ".",
        limit: int = 200,
    ) -> list[str]:
        """List readable files below a repository-relative path.

        The workspace root is the cloned repository root, not its backend,
        frontend, or source directory. Use path "." first to discover the
        repository layout before assuming file locations. Every returned path
        can be passed unchanged to workspace_read_file. Never pass an absolute
        filesystem path or a path relative to the process working directory.
        """

        return reader.list_files(_workspace_id(state), path, limit)

    @tool
    def workspace_read_file(
        path: str,
        state: Annotated[dict[str, Any], InjectedState],
    ) -> str:
        """Read one bounded UTF-8 file using a repository-relative path.

        The path starts at the cloned repository root. Do not assume the
        repository root is a backend or source directory. Prefer a path
        returned by workspace_list_files or workspace_search_code; when the
        layout is unknown, call workspace_list_files with path "." first.
        Absolute filesystem paths are not accepted.
        """

        return reader.read_file(_workspace_id(state), path)

    @tool
    def workspace_search_code(
        query: str,
        state: Annotated[dict[str, Any], InjectedState],
        path: str = ".",
        limit: int = 50,
    ) -> list[dict[str, str | int]]:
        """Search fixed text below a repository-relative path.

        The default path "." searches from the cloned repository root and is
        safest when the project layout is unknown. A narrower path must first
        be discovered with workspace_list_files or a prior search result.
        Returned match paths can be passed unchanged to workspace_read_file.
        Never pass an absolute filesystem path.
        """

        return reader.search_code(_workspace_id(state), query, path, limit)

    return workspace_list_files, workspace_read_file, workspace_search_code


def _workspace_id(state: dict[str, Any]) -> str:
    workspace_id = state.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise WorkspaceReadError("No prepared workspace is attached to this run")
    return workspace_id
