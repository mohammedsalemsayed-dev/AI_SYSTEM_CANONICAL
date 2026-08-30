"""Cheap workspace context for the Interpreter and Planner — a flat file list.

No indexing, no dependency graph (that is the repo-intelligence capability domain,
not the slice). `git ls-files` when available, else a bounded recursive walk.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# build / cache / vendored trees to prune — a UE or Unity project's
# Binaries/Intermediate/DerivedDataCache alone can be 100k+ files and turn a
# plain rglob into a multi-minute stall.
_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".gradle", ".idea", ".vs", "dist", "build",
    "target", "bin", "obj",
    # Unreal / Unity
    "Binaries", "Intermediate", "DerivedDataCache", "Saved", "Build",
    "Library", "Temp", "Logs", "Obj",
}


def is_git_repo(path: str) -> bool:
    return (Path(path) / ".git").exists()


def list_workspace(path: str, max_files: int = 400) -> str:
    root = Path(path)
    files: list[str] = []
    if is_git_repo(path):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files"],
                capture_output=True, text=True, timeout=15,
            )
            files = [line for line in out.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            files = []
    if not files:
        # bounded, dir-pruned walk — stop as soon as we have enough
        cap = max_files * 4  # gather a few extra so the sort is representative
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            rel = os.path.relpath(dirpath, root)
            for fn in filenames:
                p = fn if rel == "." else f"{rel}/{fn}"
                files.append(p.replace("\\", "/"))
            if len(files) >= cap:
                break
    files.sort()
    return "\n".join(files[:max_files])
