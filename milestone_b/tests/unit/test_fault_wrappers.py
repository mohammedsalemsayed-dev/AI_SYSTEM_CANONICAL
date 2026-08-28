"""Acceptance (Unit): fault model + wrappers fire on schedule and delegate
otherwise (MILESTONE_Q_PLAN.md §6)."""

from __future__ import annotations

import pytest

from app.llm.anthropic_client import RefusalError
from app.llm.fake import ScriptedLLM
from app.services.build.fake import ScriptedBuilder
from app.services.faults.interrupt import InterruptAfter, _Interrupted
from app.services.faults.model import Fault, FaultPlan
from app.services.faults.wrappers import FlakyBuilder, FlakyLLM, FlakyRunner, flaky_opener
from app.services.sandbox.runner import SandboxSpec, SandboxUnavailable
from app.services.sandbox.subprocess_backend import SubprocessSandbox


def test_should_fire_on_call_and_sticky() -> None:
    p = FaultPlan.of(Fault("llm_refusal", on_call=2))
    assert p.should_fire("llm_refusal") is None
    assert p.should_fire("llm_refusal").kind == "llm_refusal"
    assert p.should_fire("llm_refusal") is None

    s = FaultPlan.of(Fault("sandbox_error", on_call=1, sticky=True))
    assert all(s.should_fire("sandbox_error") for _ in range(3))

    with pytest.raises(ValueError):
        Fault("nonsense_kind")


def test_flaky_llm_refuses_then_delegates() -> None:
    inner = ScriptedLLM(["real reply"])
    llm = FlakyLLM(inner, FaultPlan.of(Fault("llm_refusal", on_call=1)))
    with pytest.raises(RefusalError):
        llm.complete(system="s", prompt="p")
    assert llm.complete(system="s", prompt="p").text == "real reply"


def test_flaky_llm_garbage_and_timeout() -> None:
    g = FlakyLLM(ScriptedLLM(["x"]), FaultPlan.of(Fault("llm_garbage")))
    assert "{{{" in g.complete(system="s", prompt="p").text
    t = FlakyLLM(ScriptedLLM(["x"]), FaultPlan.of(Fault("llm_timeout")))
    with pytest.raises(TimeoutError):
        t.complete(system="s", prompt="p")


def test_flaky_runner_shapes() -> None:
    real = SubprocessSandbox()
    spec = SandboxSpec(workdir=".", command=["python", "-c", "print(1)"])

    with pytest.raises(SandboxUnavailable):
        FlakyRunner(real, FaultPlan.of(Fault("sandbox_unavailable"))).run(spec)
    with pytest.raises(RuntimeError):
        FlakyRunner(real, FaultPlan.of(Fault("sandbox_crash"))).run(spec)
    to = FlakyRunner(real, FaultPlan.of(Fault("sandbox_timeout"))).run(spec)
    assert to.timed_out and not to.ok
    er = FlakyRunner(real, FaultPlan.of(Fault("sandbox_error"))).run(spec)
    assert er.error and not er.ok


def test_flaky_builder_partial_and_empty() -> None:
    inner = ScriptedBuilder({"m.py": "x = 1\n"})
    pb = FlakyBuilder(inner, FaultPlan.of(Fault("partial_diff")))
    out = pb.execute(task_id="t", step=None, contract=None, workspace=".")
    assert out.diff and "does_not_exist" in out.diff
    eb = FlakyBuilder(inner, FaultPlan.of(Fault("empty_diff")))
    assert eb.execute(task_id="t", step=None, contract=None, workspace=".").diff == ""
    xb = FlakyBuilder(inner, FaultPlan.of(Fault("builder_exception")))
    with pytest.raises(RuntimeError):
        xb.execute(task_id="t", step=None, contract=None, workspace=".")


def test_flaky_opener() -> None:
    from urllib.error import URLError

    op = flaky_opener(lambda u, t: b"ok", FaultPlan.of(Fault("egress_flap")))
    with pytest.raises(URLError):
        op("http://x", 1)
    assert op("http://x", 1) == b"ok"


def test_interrupt_after_persists_then_raises() -> None:
    from app.events.log import EventKind, EventLog

    log = EventLog()
    wrapped = InterruptAfter(log, EventKind.PLAN)
    wrapped.append("t", EventKind.REQUEST, {"text": "x"})   # not the target
    with pytest.raises(_Interrupted):
        wrapped.append("t", EventKind.PLAN, {"steps": []})
    # the PLAN event was persisted before the raise
    assert [e.kind for e in log.read("t")] == [EventKind.REQUEST, EventKind.PLAN]
    log.close()
