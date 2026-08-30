"""Acceptance (Unit): the bounded, deterministic tool-use loop
(MILESTONE_T_PLAN.md §6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.llm.fake import ScriptedLLM
from app.schemas.contracts import CapabilityGrant
from app.services.capability.registry import spec_for
from app.services.policy.engine import PolicyEngine
from app.services.tools.adapters.fs_tool import FsToolAdapter
from app.services.tools.adapters.shell_tool import ShellToolAdapter
from app.services.tools.base import DispatchContext
from app.services.tools.dispatch import ToolDispatcher
from app.services.tools.loop import ToolLoop
from app.services.tools.registry import ToolRegistry


def _grant(tokens: list[str], root: str) -> CapabilityGrant:
    ops: set[str] = set()
    for t in tokens:
        ops |= set(spec_for(t).operations)
    return CapabilityGrant(task_id="t", step_id="s", token="tool.loop", scope_path=root,
                           operations=sorted(ops))


@pytest.fixture
def reg() -> ToolRegistry:
    return ToolRegistry().register(FsToolAdapter()).register(ShellToolAdapter())


@pytest.fixture
def ws(tmp_path: Path) -> str:
    (tmp_path / "a.txt").write_text("alpha\n", encoding="utf-8", newline="\n")
    (tmp_path / "b.txt").write_text("beta\n", encoding="utf-8", newline="\n")
    return str(tmp_path)


def _ctx(ws: str, tokens: list[str], **kw) -> DispatchContext:
    return DispatchContext(task_id="t", grant=_grant(tokens, ws), workspace=ws, **kw)


def test_two_ops_then_done(reg: ToolRegistry, ws: str) -> None:
    script = [
        json.dumps({"op": "fs.list", "args": {}}),
        json.dumps({"op": "fs.read", "args": {"path": "a.txt"}}),
        json.dumps({"done": True, "summary": "listed and read"}),
    ]
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()), ScriptedLLM(script))
    r = loop.run("inspect the workspace", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert r.ok and r.done and r.iterations == 3 and r.denials == 0
    kinds = [t["kind"] for t in r.transcript]
    assert kinds.count("result") == 2 and kinds[-1] == "done"
    assert r.transcript[1]["ok"] is True and "alpha" in r.transcript[3]["output_excerpt"]


def test_no_done_hits_iteration_cap(reg: ToolRegistry, ws: str) -> None:
    # detection off -> the blunt iteration cap is the only bound (Milestone T)
    llm = ScriptedLLM(lambda s, p: json.dumps({"op": "fs.list", "args": {}}))
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()), llm, max_iters=4, detect_loops=False)
    r = loop.run("loop forever", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert not r.ok and not r.done and r.iterations == 4 and r.summary == "iteration cap"


def test_junk_replies_stop_on_parse_budget(reg: ToolRegistry, ws: str) -> None:
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()),
                    ScriptedLLM(lambda s, p: "I think I will look around first."),
                    parse_budget=2)
    r = loop.run("do a thing", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert not r.ok and r.summary == "unparseable model replies"
    assert [t["kind"] for t in r.transcript] == ["error", "error"]


def test_forbidden_op_is_a_denial_turn_and_loop_continues(reg: ToolRegistry, ws: str) -> None:
    script = [
        json.dumps({"op": "shell.exec", "args": {"command": ["x"]}}),  # no shell.run grant
        json.dumps({"op": "fs.read", "args": {"path": "b.txt"}}),
        json.dumps({"done": True, "summary": "recovered"}),
    ]
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()), ScriptedLLM(script))
    r = loop.run("try shell then fall back", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert r.ok and r.denials == 1 and r.iterations == 3
    denied = r.transcript[1]
    assert denied["kind"] == "result" and denied["ok"] is False and "beta" in r.transcript[3]["output_excerpt"]


def test_transcript_is_deterministic(reg: ToolRegistry, ws: str) -> None:
    script = [json.dumps({"op": "fs.list", "args": {}}),
              json.dumps({"done": True, "summary": "ok"})]
    d = ToolDispatcher(reg, PolicyEngine())
    a = ToolLoop(d, ScriptedLLM(list(script))).run("x", _ctx(ws, ["fs.read"]), reg.manifest_block())
    b = ToolLoop(d, ScriptedLLM(list(script))).run("x", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert a.transcript == b.transcript and a.summary == b.summary


# --- Milestone U: structural loop detection --------------------- #
def test_repeated_failing_op_is_caught_as_loop_risk(reg: ToolRegistry, ws: str) -> None:
    # the model keeps trying to read a file that does not exist
    llm = ScriptedLLM(lambda s, p: json.dumps({"op": "fs.read", "args": {"path": "nope.txt"}}))
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()), llm, max_iters=8)
    r = loop.run("read the missing file", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert r.loop_risk and not r.ok and not r.done
    assert r.iterations < 8
    assert {"repeated_action", "repeated_error"} & set(r.loop_flags)
    assert r.transcript[-1]["kind"] == "loop_risk"


def test_progress_each_turn_never_trips(reg: ToolRegistry, ws: str) -> None:
    # a distinct successful op every turn -> the detector history keeps clearing
    (Path(ws) / "c.txt").write_text("gamma\n", encoding="utf-8", newline="\n")
    script = [json.dumps({"op": "fs.read", "args": {"path": f}}) for f in ("a.txt", "b.txt", "c.txt")]
    script.append(json.dumps({"done": True, "summary": "read three files"}))
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()), ScriptedLLM(script), max_iters=8)
    r = loop.run("read every file", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert r.ok and r.done and not r.loop_risk and r.loop_flags == []


def test_detection_can_be_disabled(reg: ToolRegistry, ws: str) -> None:
    llm = ScriptedLLM(lambda s, p: json.dumps({"op": "fs.read", "args": {"path": "nope.txt"}}))
    off = ToolLoop(ToolDispatcher(reg, PolicyEngine()), llm, max_iters=5, detect_loops=False)
    r = off.run("read the missing file", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert not r.loop_risk and r.iterations == 5 and r.summary == "iteration cap"


def test_loop_risk_outcome_is_deterministic(reg: ToolRegistry, ws: str) -> None:
    def _mk() -> ToolLoop:
        llm = ScriptedLLM(lambda s, p: json.dumps({"op": "fs.read", "args": {"path": "x.txt"}}))
        return ToolLoop(ToolDispatcher(reg, PolicyEngine()), llm, max_iters=8)
    a = _mk().run("x", _ctx(ws, ["fs.read"]), reg.manifest_block())
    b = _mk().run("x", _ctx(ws, ["fs.read"]), reg.manifest_block())
    assert a.transcript == b.transcript and a.loop_flags == b.loop_flags and a.summary == b.summary


def test_tainted_context_cannot_run_a_side_effecting_op(reg: ToolRegistry, ws: str) -> None:
    script = [json.dumps({"op": "fs.write", "args": {"path": "new.txt", "text": "x"}}),
              json.dumps({"done": True, "summary": "tried"})]
    loop = ToolLoop(ToolDispatcher(reg, PolicyEngine()), ScriptedLLM(script))
    ctx = _ctx(ws, ["fs.write"], trust="retrieved_web", taint_sources=["src1"])
    r = loop.run("write from web content", ctx, reg.manifest_block())
    assert r.denials == 1 and r.transcript[1]["ok"] is False
    assert not (Path(ws) / "new.txt").exists()
