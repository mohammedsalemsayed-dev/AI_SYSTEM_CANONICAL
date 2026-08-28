"""Git tool adapter — wraps `GitAdapter` (MILESTONE_S_PLAN.md §2)."""

from __future__ import annotations

from app.services.repo.git_adapter import GitAdapter, GitError
from app.services.tools.base import DispatchContext, ToolManifest, ToolOp, ToolResult


class GitToolAdapter:
    name = "git"

    def __init__(self, git: GitAdapter) -> None:
        self._git = git

    def manifest(self) -> ToolManifest:
        r = "vcs.read"
        return ToolManifest(
            name="git", summary="read and (gated) write the local git repo",
            ops=[
                ToolOp("git.status", "working-tree status", r, "{}"),
                ToolOp("git.log", "recent commits", r, '{"path"?: str, "limit"?: int}'),
                ToolOp("git.blame", "line authorship", r, '{"path": str, "lines"?: [int,int]}'),
                ToolOp("git.diff", "diff between refs", r, '{"a": str, "b"?: str, "paths"?: [str]}'),
                ToolOp("git.changed_files", "files changed vs a base ref", r, '{"base_ref"?: str}'),
                ToolOp("git.branch", "create a local branch", "vcs.branch",
                       '{"name": str}', side_effecting=True),
                ToolOp("git.commit", "local commit (never push)", "vcs.commit",
                       '{"message": str, "paths"?: [str]}', side_effecting=True),
            ],
        )

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult:
        try:
            if op == "git.status":
                st = self._git.status()
                return ToolResult(True, op, _asdict(st))
            if op == "git.log":
                return ToolResult(True, op, self._git.log(args.get("path"),
                                                          limit=int(args.get("limit", 20))))
            if op == "git.blame":
                lines = args.get("lines")
                return ToolResult(True, op, self._git.blame(args["path"],
                                                            lines=tuple(lines) if lines else None))
            if op == "git.diff":
                return ToolResult(True, op, self._git.diff(args["a"], args.get("b", ""),
                                                           paths=args.get("paths")))
            if op == "git.changed_files":
                return ToolResult(True, op, self._git.changed_files(args.get("base_ref", "HEAD")))
            if op == "git.branch":
                return ToolResult(True, op, self._git.create_branch(args["name"]))
            if op == "git.commit":
                return ToolResult(True, op, self._git.commit(args["message"],
                                                             paths=args.get("paths")))
        except (GitError, KeyError, ValueError, TypeError) as exc:
            return ToolResult(False, op, error=repr(exc))
        return ToolResult(False, op, error=f"unknown op {op!r}")


def _asdict(obj):
    return {k: getattr(obj, k) for k in getattr(obj, "__dataclass_fields__", {})}
