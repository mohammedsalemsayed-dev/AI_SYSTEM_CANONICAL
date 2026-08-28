"""Fault-suite helpers (MILESTONE_Q_PLAN.md §2, §6).

`assert_safe` checks the three invariants: safe terminal, workspace untouched,
clean `reconcile()`. A scripted orchestrator factory builds a real loop over the
`SubprocessSandbox` with scripted LLM/builder so the suite runs offline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from app.services.recovery.reconcile import reconcile


def workspace_hash(root: str) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            h.update(str(p.relative_to(root)).replace("\\", "/").encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


_SAFE_TERMINAL = {"FAILED", "WAITING_FOR_USER", "CANCELLED", "COMPLETED"}


def assert_safe(result, log: EventLog, workspace_before: str, workspace_root: str) -> None:
    # 1. safe terminal
    assert result.state in _SAFE_TERMINAL, f"unsafe terminal state {result.state}"
    events = log.read(result.task_id)
    if result.state == "COMPLETED":
        v = next((e.payload for e in reversed(events)
                  if e.kind == EventKind.VERIFICATION), None)
        assert v is not None and v.get("overall") == "pass", (
            "COMPLETED without a passing VerificationRecord"
        )
        assert result.verified is True

    # 2. workspace untouched
    assert workspace_hash(workspace_root) == workspace_before, (
        "the user workspace was mutated"
    )

    # 3. clean reconcile
    decision = reconcile(events)
    assert decision.decision in ("RESUME", "REPAIR", "ESCALATE", "NOOP")
    snap = project_task(events)
    if snap.state.value in ("COMPLETED", "FAILED", "CANCELLED"):
        assert decision.decision == "NOOP", (
            f"terminal task should reconcile to NOOP, got {decision.decision}"
        )


def scripted_orchestrator(log, *, llm_replies, builder_edits, sandbox=None, builder=None,
                          llm=None):
    """A real Orchestrator over scripted providers + the fast subprocess sandbox."""
    from app.llm.fake import ScriptedLLM
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.sandbox.subprocess_backend import SubprocessSandbox
    from app.services.verify.verifier_t0 import VerifierT0

    runner = sandbox or SubprocessSandbox()
    llm = llm or ScriptedLLM(llm_replies)
    return Orchestrator(
        log,
        Interpreter(llm),
        Planner(llm),
        builder or ScriptedBuilder(builder_edits),
        VerifierT0(runner=runner),
        PolicyEngine(),
        runner=runner,
    )
