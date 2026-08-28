"""Workspace copies + diffing for the slice.

The Builder never touches the user's workspace. It works in a throwaway copy that
is re-initialised as a git repo so a unified diff of the change can be produced.
The Verifier later takes its *own* fresh copy of the original and applies that
diff — so the diff must be self-contained.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_GIT_ENV = [
    "-c",
    "user.email=slice@local",
    "-c",
    "user.name=slice",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
]


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *_GIT_ENV, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


_CACHE_IGNORE = (
    "__pycache__/\n*.pyc\n.pytest_cache/\n.coverage\n.mypy_cache/\n.ruff_cache/\n"
    ".slice_change.patch\n"
)


def copy_workspace(src: str, prefix: str = "slice_ws_") -> str:
    """Copy `src` (without .git) into a fresh temp dir, init a git repo, commit a
    baseline. A local .git/info/exclude keeps test-run cache files out of any
    diff taken later. Returns the temp dir path (caller deletes it)."""
    dst = tempfile.mkdtemp(prefix=prefix)
    shutil.copytree(
        src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
    )
    _git(dst, "init", "-q")
    exclude = Path(dst) / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(exclude.read_text() + _CACHE_IGNORE if exclude.exists() else _CACHE_IGNORE)
    _git(dst, "add", "-A")
    _git(dst, "commit", "-q", "--allow-empty", "-m", "baseline")
    return dst


def diff_workspace(ws: str) -> tuple[str, list[str]]:
    """Unified diff of all changes since baseline, plus changed path list."""
    _git(ws, "add", "-A")
    diff = _git(ws, "diff", "--cached").stdout
    names = [
        n for n in _git(ws, "diff", "--cached", "--name-only").stdout.splitlines() if n
    ]
    return diff, names


def apply_diff(ws: str, diff: str) -> bool:
    """Apply a unified diff to a fresh workspace copy. Returns success."""
    if not diff.strip():
        return False
    patch = Path(ws) / ".slice_change.patch"
    # write raw bytes: text mode would rewrite newlines and corrupt the patch
    patch.write_bytes(diff.encode("utf-8"))
    try:
        res = _git(ws, "apply", "--whitespace=nowarn", ".slice_change.patch")
        if res.returncode != 0:
            res = _git(
                ws, "apply", "--whitespace=nowarn", "--ignore-whitespace", ".slice_change.patch"
            )
        return res.returncode == 0
    finally:
        patch.unlink(missing_ok=True)


def cleanup(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
