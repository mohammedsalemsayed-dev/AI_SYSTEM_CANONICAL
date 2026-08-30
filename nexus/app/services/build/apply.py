"""Write a verified diff back to the real workspace.

The Orchestrator never touches the user's workspace — it proposes and verifies a
diff on throwaway copies (the "workspace-untouched" invariant). Applying that diff
is a deliberate, separate, logged step, gated on a passing verification. This is
what turns "the system proved a fix works" into "the fix is in your tree".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.services.build.workspace_copy import apply_diff


@dataclass
class ApplyResult:
    applied: bool
    reason: str
    changed_paths: list[str] = field(default_factory=list)


def _final_diff(events: list) -> tuple[str, list[str]]:
    diff, paths = "", []
    for e in events:
        if e.kind == EventKind.ARTIFACT and e.payload.get("diff"):
            diff = e.payload["diff"]
            paths = list(e.payload.get("changed_paths") or [])
    return diff, paths


def apply_task_result(
    log: EventLog,
    task_id: str,
    workspace_path: str,
    *,
    require_verified: bool = True,
) -> ApplyResult:
    """Apply the task's final verified diff to `workspace_path` (in place).

    Refuses unless the task reached COMPLETED with a passing VERIFICATION, unless
    `require_verified=False`. Logs an APPLIED event with the outcome. Idempotent
    in spirit — a second call re-applies the same patch, which `git apply` will
    reject cleanly (returns applied=False, reason names the git failure)."""
    events = log.read(task_id)
    state = None
    verified = False
    for e in events:
        if e.kind == EventKind.RESULT:
            state = e.payload.get("state")
            verified = bool(e.payload.get("verified"))
        if e.kind == EventKind.VERIFICATION and e.payload.get("overall") == "pass":
            verified = True

    if require_verified and not (state == "COMPLETED" and verified):
        res = ApplyResult(False, f"not applying: state={state!r} verified={verified}")
        log.append(task_id, EventKind.APPLIED, {"applied": False, "reason": res.reason})
        return res

    diff, paths = _final_diff(events)
    if not diff.strip():
        res = ApplyResult(False, "no diff on the event log to apply")
        log.append(task_id, EventKind.APPLIED, {"applied": False, "reason": res.reason})
        return res

    root = Path(workspace_path)
    if not root.is_dir():
        res = ApplyResult(False, f"workspace not found: {workspace_path}")
        log.append(task_id, EventKind.APPLIED, {"applied": False, "reason": res.reason})
        return res

    ok = apply_diff(str(root), diff)
    res = ApplyResult(
        applied=ok,
        reason="applied" if ok else "git apply failed (tree drifted since the run?)",
        changed_paths=paths if ok else [],
    )
    log.append(
        task_id, EventKind.APPLIED,
        {"applied": ok, "reason": res.reason, "changed_paths": res.changed_paths,
         "target": str(root), "bytes": len(diff.encode("utf-8"))},
    )
    return res
