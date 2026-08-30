"""Unit: writing a verified diff back to the real workspace (apply.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.services.build.apply import apply_task_result

_DIFF = """diff --git a/calc.py b/calc.py
index 0000000..1111111 100644
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


def _repo(tmp_path: Path) -> str:
    d = tmp_path / "r"
    d.mkdir()
    (d / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8", newline="\n")
    for a in (["init", "-q"], ["add", "-A"],
              ["-c", "user.email=x@x", "-c", "user.name=x", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)
    return str(d)


def _log_completed(diff: str = _DIFF) -> tuple[EventLog, str]:
    log = EventLog()
    tid = "t1"
    log.append(tid, EventKind.ARTIFACT, {"diff": diff, "changed_paths": ["calc.py"]})
    log.append(tid, EventKind.VERIFICATION, {"overall": "pass"})
    log.append(tid, EventKind.RESULT, {"state": "COMPLETED", "verified": True})
    return log, tid


def test_applies_verified_diff_to_workspace(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    log, tid = _log_completed()
    res = apply_task_result(log, tid, ws)
    assert res.applied and res.changed_paths == ["calc.py"]
    assert (Path(ws) / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    applied_ev = [e for e in log.read(tid) if e.kind == EventKind.APPLIED]
    assert applied_ev and applied_ev[-1].payload["applied"] is True


def test_refuses_when_not_verified(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    log = EventLog()
    log.append("t2", EventKind.ARTIFACT, {"diff": _DIFF, "changed_paths": ["calc.py"]})
    log.append("t2", EventKind.RESULT, {"state": "WAITING_FOR_USER", "verified": False})
    res = apply_task_result(log, "t2", ws)
    assert not res.applied and "not applying" in res.reason
    assert (Path(ws) / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"


def test_refuses_when_no_diff(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    log = EventLog()
    log.append("t3", EventKind.VERIFICATION, {"overall": "pass"})
    log.append("t3", EventKind.RESULT, {"state": "COMPLETED", "verified": True})
    res = apply_task_result(log, "t3", ws)
    assert not res.applied and "no diff" in res.reason


def test_require_verified_false_applies_anyway(tmp_path: Path) -> None:
    ws = _repo(tmp_path)
    log = EventLog()
    log.append("t4", EventKind.ARTIFACT, {"diff": _DIFF, "changed_paths": ["calc.py"]})
    log.append("t4", EventKind.RESULT, {"state": "FAILED", "verified": False})
    res = apply_task_result(log, "t4", ws, require_verified=False)
    assert res.applied
