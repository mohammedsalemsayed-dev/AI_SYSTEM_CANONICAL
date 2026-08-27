"""Cheap workspace context for the Interpreter and Planner — a flat file list.

No indexing, no dependency graph (that is the repo-intelligence capability domain,
not the slice). `git ls-files` when available, else a bounded recursive walk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(path: str) -> bool:
    return (Path(path) / ".git").exists()


def list_workspace(path: str, max_files: int = 400) -> str:
    root = Path(path)
    files: list[str] = []
    if is_git_repo(path):
        try:
            out = subprocess.run(
                ["git", "-C", str(root), "ls-files"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            files = [line for line in out.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            files = []
    if not files:
        files = [
            str(f.relative_to(root)).replace("\\", "/")
            for f in root.rglob("*")
            if f.is_file() and ".git" not in f.parts
        ]
    files.sort()
    return "\n".join(files[:max_files])
