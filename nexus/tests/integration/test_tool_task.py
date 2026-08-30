"""Acceptance (Integration): the `ops` task class drives the Milestone T
tool-use loop, every call gated by the existing Policy Engine
(MILESTONE_T_PLAN.md §6)."""

from __future__ import annotations

import json
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.services.artifacts.store import ArtifactStore
from app.services.egress.broker import EgressBroker
from app.services.tools.adapters.egress_tool import EgressToolAdapter
from app.services.tools.adapters.fs_tool import FsToolAdapter
from app.services.tools.adapters.shell_tool import ShellToolAdapter
from app.services.tools.dispatch import ToolDispatcher
from app.services.tools.loop import ToolLoop
from app.services.tools.registry import ToolRegistry
from tests.integration.conftest import build_orchestrator, interpreter_reply


def _registry() -> ToolRegistry:
    return (ToolRegistry()
            .register(FsToolAdapter())
            .register(ShellToolAdapter())
            .register(EgressToolAdapter(EgressBroker(allowlist=[], opener=lambda u, t: b""))))


def _ops_contract() -> str:
    return interpreter_reply(
        objective="inspect the workspace: list files then read notes.txt",
        task_class="ops",
        success_criteria=["the files were listed and notes.txt was read"],
        required_evidence=["the tool transcript shows the listing and the file contents"],
    )


def _wire(log: EventLog, replies: list[str]):
    orch = build_orchestrator(log, llm_replies=replies, builder_edits={})
    reg = _registry()
    orch.tools = reg
    orch.artifacts = ArtifactStore()
    llm = orch.interpreter.llm
    orch.tool_loop = lambda: ToolLoop(ToolDispatcher(reg, orch.policy), llm)
    return orch


def test_ops_task_runs_the_loop_and_completes(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "notes.txt").write_text("remember the milk\n", encoding="utf-8", newline="\n")

    log = EventLog()
    orch = _wire(log, [
        _ops_contract(),
        json.dumps({"op": "fs.list", "args": {}}),
        json.dumps({"op": "fs.read", "args": {"path": "notes.txt"}}),
        json.dumps({"done": True, "summary": "listed 1 file and read notes.txt"}),
    ])
    r = orch.run("inspect the workspace", str(ws))
    assert r.state == "COMPLETED" and r.verified is True

    ev = log.read(r.task_id)
    loop_ev = [e for e in ev if e.kind == EventKind.TOOL_LOOP]
    assert len(loop_ev) == 1 and loop_ev[0].payload["ok"] is True
    assert loop_ev[0].payload["denials"] == 0
    tool_ev = [e for e in ev if e.kind == EventKind.TOOL]
    assert [e.payload["op"] for e in tool_ev] == ["fs.list", "fs.read"]
    art = [e for e in ev if e.kind == EventKind.ARTIFACT]
    assert art and art[-1].payload["trust"] == "tool_output"
    assert art[-1].payload["artifact_kind"] == "tool_transcript"


def test_denied_side_effecting_op_still_completes_workspace_untouched(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "notes.txt").write_text("data\n", encoding="utf-8", newline="\n")
    before = sorted(p.name for p in ws.iterdir())

    log = EventLog()
    orch = _wire(log, [
        _ops_contract(),
        # no shell.run in the auto-derived grant (shell.exec is side-effecting) -> DENY
        json.dumps({"op": "shell.exec", "args": {"command": ["python", "-c", "open('x','w')"]}}),
        json.dumps({"op": "fs.read", "args": {"path": "notes.txt"}}),
        json.dumps({"done": True, "summary": "shell denied; read the file instead"}),
    ])
    r = orch.run("inspect the workspace", str(ws))
    assert r.state == "COMPLETED"

    ev = log.read(r.task_id)
    loop_ev = [e for e in ev if e.kind == EventKind.TOOL_LOOP][0]
    assert loop_ev.payload["denials"] >= 1
    assert any(e.kind == EventKind.POLICY_DECISION and e.payload.get("decision") == "DENY"
               for e in ev)
    # the loop worked on a copy; the real tree is byte-unchanged
    assert sorted(p.name for p in ws.iterdir()) == before
    assert (ws / "notes.txt").read_text() == "data\n"


def test_looping_ops_task_escalates_to_waiting_for_user(tmp_path: Path) -> None:
    """A tool loop that repeats a failing op is caught by the D loop detector and
    escalated to the user (Milestone U), not left to fail on the iteration cap."""
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "real.txt").write_text("x\n", encoding="utf-8", newline="\n")

    log = EventLog()
    # every turn: read a file that isn't there -> identical failure, forever
    orch = build_orchestrator(log, llm_replies=[_ops_contract()], builder_edits={})
    reg = _registry()
    orch.tools = reg
    orch.artifacts = ArtifactStore()

    class _Repeat:
        provider = "fake"
        model = "repeat-1"

        def complete(self, *, system: str, prompt: str):
            from app.llm.base import LLMResponse
            return LLMResponse(text=json.dumps({"op": "fs.read", "args": {"path": "ghost.txt"}}),
                               input_tokens=1, output_tokens=1, latency_s=0.0,
                               provider="fake", model="repeat-1")

    orch.tool_loop = lambda: ToolLoop(ToolDispatcher(reg, orch.policy), _Repeat(), max_iters=10)

    r = orch.run("keep reading a missing file", str(ws))
    assert r.state == "WAITING_FOR_USER"
    ev = log.read(r.task_id)
    loop_ev = [e for e in ev if e.kind == EventKind.TOOL_LOOP][0]
    assert loop_ev.payload["loop_risk"] is True and loop_ev.payload["loop_flags"]
    assert loop_ev.payload["iterations"] < 10
    clar = [e for e in ev if e.kind == EventKind.CLARIFICATION]
    assert clar and "repeating without progress" in clar[0].payload["questions"][0]
    assert [e for e in ev if e.kind == EventKind.PROGRESS
            and e.payload.get("classification") == "LOOP_RISK"]
    # the transcript is still captured
    art = [e for e in ev if e.kind == EventKind.ARTIFACT]
    assert art and art[-1].payload["artifact_kind"] == "tool_transcript"


def test_ops_unset_tool_loop_uses_the_normal_pipeline(tmp_path: Path) -> None:
    """`ops` with no tool_loop wired -> the contract still flows through the
    ordinary plan->build path (byte-identical to Milestone S)."""
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "notes.txt").write_text("x\n", encoding="utf-8", newline="\n")

    log = EventLog()
    orch = build_orchestrator(log, llm_replies=[_ops_contract()], builder_edits={})
    orch.tools = _registry()  # registry wired, loop NOT
    r = orch.run("inspect the workspace", str(ws))
    # no tool loop -> no TOOL_LOOP event; the run goes down the normal path
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.TOOL_LOOP]
