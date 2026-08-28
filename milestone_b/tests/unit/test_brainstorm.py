"""Unit: the Creative/Brainstorming agent (advisory, fail-open)."""

from __future__ import annotations

import json

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.schemas.contracts import TaskContract
from app.services.agents.brainstorm import Brainstorm
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def _contract() -> TaskContract:
    return TaskContract(
        task_id="t", original_request="x", objective="make add() return a+b",
        task_class="code_edit_local", success_criteria=["add(2,3)==5"],
        required_evidence=["T0: pytest test_calc.py passes"],
    )


def test_returns_parsed_approaches_and_a_run_record() -> None:
    llm = ScriptedLLM([json.dumps({"approaches": ["fix the operator", "rewrite the function", ""]})])
    got, run = Brainstorm(llm).approaches("t", _contract(), "calc.py\n")
    assert got == ["fix the operator", "rewrite the function"]  # blanks dropped
    assert run.role == "creative" and run.task_id == "t"


def test_fails_open_on_bad_json() -> None:
    got, run = Brainstorm(ScriptedLLM(["not json at all"])).approaches("t", _contract())
    assert got == [] and run.failure_mode


def test_caps_at_four() -> None:
    llm = ScriptedLLM([json.dumps({"approaches": [f"a{i}" for i in range(9)]})])
    got, _ = Brainstorm(llm).approaches("t", _contract())
    assert len(got) == 4


def test_orchestrator_injects_approaches_into_the_planner_context(sample_repo: str) -> None:
    captured: dict[str, str] = {}
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(),
                     json.dumps({"approaches": ["flip the minus to a plus"]}),
                     planner_reply()],
        builder_edits={"calc.py": "def add(a, b):\n    return a + b\n"},
    )
    orig = orch.planner.plan

    def spy(contract, listing=""):
        captured["listing"] = listing
        return orig(contract, listing)

    orch.planner.plan = spy  # type: ignore[method-assign]
    orch.brainstorm = Brainstorm(orch.interpreter.llm)  # shares the scripted queue

    r = orch.run("fix add", sample_repo)
    assert r.state == "COMPLETED"
    assert "CANDIDATE APPROACHES" in captured["listing"]
    assert "flip the minus to a plus" in captured["listing"]
    bs = [e for e in log.read(r.task_id) if e.kind == EventKind.BRAINSTORM]
    assert bs and bs[0].payload["approaches"] == ["flip the minus to a plus"]
