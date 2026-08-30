"""Fault matrix runner (MILESTONE_Q_PLAN.md §5 day 9).

Runs every (fault kind × injection point) over a canonical task, checks the three
invariants (safe terminal / workspace untouched / clean reconcile), and writes
`nexus/FAULT_FINDINGS.md`. Offline (scripted providers) — runs in CI.

    python -m tests.fault.run_fault_suite
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.services.build.fake import ScriptedBuilder
from app.services.faults.interrupt import InterruptAfter, _Interrupted
from app.services.faults.model import Fault, FaultPlan
from app.services.faults.wrappers import FlakyBuilder, FlakyLLM, FlakyRunner
from app.services.sandbox.subprocess_backend import SubprocessSandbox
from tests.fault.conftest import assert_safe, scripted_orchestrator, workspace_hash

_FINDINGS = Path("FAULT_FINDINGS.md")
_FIXED = "def add(a, b):\n    return a + b\n"


def _repo() -> str:
    d = Path(tempfile.mkdtemp(prefix="fault_"))
    (d / "calc.py").write_text("def add(a, b):\n    return a - b\n", newline="\n")
    (d / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", newline="\n")
    for a in (["init", "-q"], ["add", "-A"],
              ["-c", "user.email=x@x", "-c", "user.name=x", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)
    return str(d)


def _reply(objective="make calc.add return a + b"):
    import json

    return json.dumps({
        "objective": objective, "task_class": "code_edit_local",
        "success_criteria": ["add(2, 3) == 5"],
        "required_evidence": ["T0: pytest test_calc.py::test_add passes"],
        "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
    })


def _plan():
    import json

    return json.dumps({"steps": [{"intent": "fix add", "expected_artifact_delta": "edit calc.py",
                                  "required_capability": "fs.write"}]})


def _run_one(kind: str, point: str) -> tuple[bool, str]:
    repo = _repo()
    before = workspace_hash(repo)
    log = EventLog()
    try:
        if point == "llm":
            from app.llm.fake import ScriptedLLM

            llm = FlakyLLM(ScriptedLLM([_reply(), _plan()]),
                           FaultPlan.of(Fault(kind, sticky=True)))
            orch = scripted_orchestrator(log, llm_replies=[], builder_edits={"calc.py": _FIXED}, llm=llm)
            r = orch.run("fix add", repo)
        elif point == "sandbox":
            runner = FlakyRunner(SubprocessSandbox(), FaultPlan.of(Fault(kind, sticky=True)))
            orch = scripted_orchestrator(log, llm_replies=[_reply(), _plan()],
                                         builder_edits={"calc.py": _FIXED}, sandbox=runner)
            r = orch.run("fix add", repo)
        elif point == "builder":
            b = FlakyBuilder(ScriptedBuilder({"calc.py": _FIXED}), FaultPlan.of(Fault(kind, sticky=True)))
            orch = scripted_orchestrator(log, llm_replies=[_reply(), _plan()], builder_edits={}, builder=b)
            r = orch.run("fix add", repo)
        elif point == "interrupt":
            hooked = InterruptAfter(log, kind)  # here `kind` is an event-kind name
            orch = scripted_orchestrator(hooked, llm_replies=[_reply(), _plan()],
                                         builder_edits={"calc.py": _FIXED})
            try:
                orch.run("fix add", repo)
            except _Interrupted:
                pass
            tid = log.task_ids()[0]
            orch2 = scripted_orchestrator(log, llm_replies=[_reply(), _plan()],
                                          builder_edits={"calc.py": _FIXED})
            r = orch2.resume(tid)
        else:
            return False, "unknown injection point"
        assert_safe(r, log, before, repo)
        return True, r.state
    except AssertionError as exc:
        return False, f"INVARIANT FAILED: {exc}"
    except BaseException as exc:  # noqa: BLE001 — an unhandled fault is itself a failure
        return False, f"UNHANDLED: {type(exc).__name__}: {exc}"
    finally:
        log.close()


_MATRIX = [
    *(("llm", k) for k in ("llm_refusal", "llm_timeout", "llm_garbage")),
    *(("sandbox", k) for k in ("sandbox_unavailable", "sandbox_timeout", "sandbox_error", "sandbox_crash")),
    *(("builder", k) for k in ("partial_diff", "empty_diff", "builder_exception")),
    *(("interrupt", k) for k in (EventKind.PLAN, EventKind.CHECKPOINT, EventKind.ARTIFACT, EventKind.VERIFICATION)),
]


def main() -> int:
    rows, passed = [], 0
    for point, kind in _MATRIX:
        ok, detail = _run_one(kind, point)
        passed += ok
        rows.append((point, kind, "PASS" if ok else "FAIL", detail))

    lines = [
        "# Fault-injection findings", "",
        f"{passed}/{len(rows)} (kind × point) pairs satisfy all three invariants "
        "(safe terminal / workspace untouched / clean reconcile).", "",
        "| injection point | fault | result | detail |", "|---|---|---|---|",
    ]
    lines += [f"| {p} | `{k}` | {res} | {d} |" for p, k, res, d in rows]
    _FINDINGS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {_FINDINGS}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
