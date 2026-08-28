"""Deterministic Git adapter (MILESTONE_J_PLAN.md §2).

A thin, capability-gated wrapper over the `git` CLI. Read subcommands are always
available; `create_branch` / `commit` require a caller-supplied `write_allowed`
predicate (the orchestrator wires this to a `vcs.write` grant). No network
subcommand is exposed — no `fetch` / `pull` / `push` / `remote`. Every call goes
through `_run_git` as an argument list (never a shell string), with a timeout and
return-code capture; a non-zero exit raises `GitError`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_S = 20

# identity used only for the adapter's own local commits (vcs.write); it never
# touches the user's global config and never pushes anywhere.
_BOT_IDENTITY = ["-c", "user.name=nexus", "-c", "user.email=nexus@localhost"]


class GitError(RuntimeError):
    def __init__(self, args: list[str], rc: int, stderr: str) -> None:
        super().__init__(f"git {' '.join(args)} -> rc={rc}: {stderr.strip()[:400]}")
        self.args = args
        self.rc = rc
        self.stderr = stderr


@dataclass
class GitStatus:
    branch: str
    head_sha: str
    clean: bool
    staged: list[str] = field(default_factory=list)
    unstaged: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)


class GitAdapter:
    def __init__(self, root: str | Path, *, write_allowed=None) -> None:
        self.root = str(Path(root).resolve())
        self._write_allowed = write_allowed or (lambda: False)

    # -- plumbing ------------------------------------------------ #
    def _run_git(self, args: list[str], *, check: bool = True) -> str:
        # identity is only consulted when a subcommand actually records one
        # (commit); harmless on reads.
        proc = subprocess.run(
            ["git", "-C", self.root, *_BOT_IDENTITY, *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
        )
        if check and proc.returncode != 0:
            raise GitError(args, proc.returncode, proc.stderr)
        return proc.stdout

    def is_repo(self) -> bool:
        try:
            return self._run_git(["rev-parse", "--is-inside-work-tree"]).strip() == "true"
        except (GitError, OSError, subprocess.SubprocessError):
            return False

    # -- read -------------------------------------------------- #
    def current_branch(self) -> str:
        return self._run_git(["rev-parse", "--abbrev-ref", "HEAD"]).strip()

    def head_sha(self) -> str:
        return self._run_git(["rev-parse", "HEAD"]).strip()

    def is_clean(self) -> bool:
        return self._run_git(["status", "--porcelain"]).strip() == ""

    def status(self) -> GitStatus:
        porcelain = self._run_git(["status", "--porcelain"]).splitlines()
        staged, unstaged, untracked = [], [], []
        for line in porcelain:
            if not line:
                continue
            x, y, path = line[0], line[1], line[3:]
            if x == "?" and y == "?":
                untracked.append(path)
                continue
            if x not in " ?":
                staged.append(path)
            if y not in " ?":
                unstaged.append(path)
        return GitStatus(
            branch=self.current_branch(),
            head_sha=self.head_sha(),
            clean=not porcelain or all(not l for l in porcelain),
            staged=staged, unstaged=unstaged, untracked=untracked,
        )

    def tracked_files(self) -> list[str]:
        return [l for l in self._run_git(["ls-files"]).splitlines() if l.strip()]

    def log(self, path: str | None = None, *, limit: int = 20) -> list[dict]:
        args = ["log", f"-n{limit}", "--pretty=format:%H%x1f%an%x1f%at%x1f%s"]
        if path:
            args += ["--", path]
        out = []
        for line in self._run_git(args).splitlines():
            if not line:
                continue
            sha, author, ts, subject = line.split("\x1f", 3)
            out.append({"sha": sha, "author": author, "ts": int(ts), "subject": subject})
        return out

    def blame(self, path: str, *, lines: tuple[int, int] | None = None) -> list[dict]:
        args = ["blame", "--line-porcelain"]
        if lines:
            args += ["-L", f"{lines[0]},{lines[1]}"]
        args += ["--", path]
        out, cur = [], {}
        for line in self._run_git(args).splitlines():
            if line and line[0:1].isalnum() and len(line.split()) >= 3 and len(line.split()[0]) == 40:
                cur = {"sha": line.split()[0]}
            elif line.startswith("author "):
                cur["author"] = line[len("author "):]
            elif line.startswith("\t"):
                cur["line"] = line[1:]
                out.append(cur)
                cur = {}
        return out

    def show(self, sha: str) -> str:
        return self._run_git(["show", "--no-color", sha])

    def diff(self, ref_a: str, ref_b: str = "", *, paths: list[str] | None = None) -> str:
        args = ["diff", "--no-color", ref_a]
        if ref_b:
            args.append(ref_b)
        if paths:
            args += ["--", *paths]
        return self._run_git(args)

    def changed_files(self, base_ref: str = "HEAD") -> list[str]:
        """Files that differ between `base_ref` and the working tree."""
        out = self._run_git(["diff", "--name-only", base_ref])
        tracked_changed = [l for l in out.splitlines() if l.strip()]
        untracked = self._run_git(["ls-files", "--others", "--exclude-standard"]).splitlines()
        return sorted(set(tracked_changed) | {u for u in untracked if u.strip()})

    # -- write (gated) --------------------------------------- #
    def _require_write(self, op: str) -> None:
        if not self._write_allowed():
            raise GitError([op], 1, "vcs.write capability not granted for this step")

    def create_branch(self, name: str) -> str:
        self._require_write("branch")
        self._run_git(["checkout", "-b", name])
        return self.current_branch()

    def commit(self, message: str, *, paths: list[str] | None = None) -> str:
        self._require_write("commit")
        self._run_git(["add", "--", *(paths or ["."])])
        self._run_git(["commit", "-m", message])
        return self.head_sha()
