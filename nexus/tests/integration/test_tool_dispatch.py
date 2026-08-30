"""Acceptance (Integration): the tool adapter framework wired into the
orchestrator — a TOOLS manifest block at planning, and capability-gated
dispatch through the existing Policy Engine (MILESTONE_S_PLAN.md §6)."""

from __future__ import annotations

from pathlib import Path

from app.events.log import EventKind, EventLog
from app.schemas.contracts import CapabilityGrant
from app.services.capability.registry import spec_for
from app.services.egress.broker import EgressBroker
from app.services.repo.git_adapter import GitAdapter
from app.services.tools.adapters.egress_tool import EgressToolAdapter
from app.services.tools.adapters.fs_tool import FsToolAdapter
from app.services.tools.adapters.git_tool import GitToolAdapter
from app.services.tools.base import DispatchContext
from app.services.tools.registry import ToolRegistry
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def _registry(repo: str) -> ToolRegistry:
    return (ToolRegistry()
            .register(GitToolAdapter(GitAdapter(repo)))
            .register(FsToolAdapter())
            .register(EgressToolAdapter(EgressBroker(allowlist=[], opener=lambda u, t: b""))))


def _grant(token: str, root: str) -> CapabilityGrant:
    return CapabilityGrant(task_id="t", step_id="s", token=token, scope_path=root,
                           operations=sorted(spec_for(token).operations))


def test_tool_manifest_at_planning(sample_repo: str) -> None:
    captured: dict[str, str] = {}

    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": "def add(a, b):\n    return a + b\n"},
    )
    orig_compile = orch.interpreter.compile

    def spy_compile(task_id: str, request_text: str, listing: str):
        captured["listing"] = listing
        return orig_compile(task_id, request_text, listing)

    orch.interpreter.compile = spy_compile  # type: ignore[method-assign]
    orch.tools = _registry(sample_repo)

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    block = captured["listing"]
    assert "TOOLS — available operations" in block
    for op in ("git.status", "git.commit", "fs.read", "fs.write", "net.fetch"):
        assert op in block
    assert "[vcs.read]" in block and "(side-effecting)" in block
    log.close()


def test_manifest_absent_when_tools_unset(sample_repo: str) -> None:
    captured: dict[str, str] = {}
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": "def add(a, b):\n    return a + b\n"},
    )
    orig_compile = orch.interpreter.compile

    def spy_compile(task_id: str, request_text: str, listing: str):
        captured["listing"] = listing
        return orig_compile(task_id, request_text, listing)

    orch.interpreter.compile = spy_compile  # type: ignore[method-assign]

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    assert "TOOLS — available operations" not in captured["listing"]
    log.close()


def test_dispatch_through_policy(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": "def add(a, b):\n    return a + b\n"},
    )
    orch.tools = _registry(sample_repo)

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    tid = r.task_id

    # allowed read op -> TOOL event, workspace trust preserved
    read_ctx = DispatchContext(task_id=tid, grant=_grant("vcs.read", sample_repo),
                               workspace=sample_repo)
    res = orch._tool("git.status", {}, read_ctx)
    assert res.ok and res.trust == "workspace"

    # side-effecting op without a vcs.write grant -> denied, logged, task untouched
    commit_ctx = DispatchContext(task_id=tid, grant=_grant("vcs.read", sample_repo),
                                 workspace=sample_repo)
    denied = orch._tool("git.commit", {"message": "nope"}, commit_ctx)
    assert not denied.ok

    tool_events = [e for e in log.read(tid) if e.kind == EventKind.TOOL]
    assert [e.payload["op"] for e in tool_events] == ["git.status", "git.commit"]
    assert tool_events[0].payload["ok"] is True and tool_events[1].payload["ok"] is False
    pol = [e for e in log.read(tid) if e.kind == EventKind.POLICY_DECISION]
    assert any(e.payload.get("decision") == "DENY" for e in pol)

    # the denied side-effecting op had no effect: no new commit in the repo
    n_commits = GitAdapter(sample_repo).log(limit=20)
    assert len(n_commits) == 1
    log.close()
