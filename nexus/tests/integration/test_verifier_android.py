"""AndroidVerifier: runs `./gradlew` unit tests on a throwaway copy of the
workspace with the diff applied. A stub `gradlew` stands in for a real Gradle —
it "passes" only when the fix is present in the source."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.schemas.contracts import TaskContract
from app.services.verify.verifier_android import (
    AndroidVerifier,
    extract_android_target,
    gradle_invocation,
)

_STUB = """#!/bin/sh
f="app/src/main/java/Calc.java"
if grep -q "return 42" "$f" 2>/dev/null; then
  echo "> Task :app:testDebugUnitTest"
  echo "1 test completed"
  echo "BUILD SUCCESSFUL in 2s"
  exit 0
else
  echo "> Task :app:testDebugUnitTest FAILED"
  echo "2 tests completed, 1 failed"
  echo "BUILD FAILED in 2s"
  exit 1
fi
"""

_GOOD_DIFF = (
    "--- a/app/src/main/java/Calc.java\n+++ b/app/src/main/java/Calc.java\n@@ -1 +1 @@\n"
    "-int calc() { return 1; }\n+int calc() { return 42; }\n"
)
_NOOP_DIFF = (
    "--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-hi\n+hello\n"
)

_C = TaskContract(
    task_id="t", original_request="fix calc", objective="fix calc()",
    task_class="code_edit_local", success_criteria=["calc is 42"],
    required_evidence=["T0: android gradle :app:testDebugUnitTest passes"],
)


@pytest.fixture
def gradle_repo(tmp_path: Path) -> str:
    ws = tmp_path / "app-proj"
    (ws / "app" / "src" / "main" / "java").mkdir(parents=True)
    (ws / "settings.gradle").write_text("include ':app'\n")
    (ws / "README.md").write_text("hi\n")
    (ws / "app" / "src" / "main" / "java" / "Calc.java").write_text("int calc() { return 1; }\n")
    gw = ws / "gradlew"
    gw.write_text(_STUB, newline="\n")
    gw.chmod(gw.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(ws)


def test_target_parsing():
    assert extract_android_target(
        ["T0: android gradle :app:testDebugUnitTest passes"]
    ) == ":app:testDebugUnitTest"
    assert extract_android_target(["T0: android passes"]) == "testDebugUnitTest"
    assert extract_android_target(["T0: pytest x passes"]) is None


def test_pass_when_build_successful(gradle_repo: str):
    r = AndroidVerifier().verify(task_id="t", contract=_C, diff=_GOOD_DIFF,
                                 original_workspace=gradle_repo)
    assert r.overall == "pass"
    assert r.discriminating_tests_run == [":app:testDebugUnitTest"]


def test_fail_when_tests_fail(gradle_repo: str):
    r = AndroidVerifier().verify(task_id="t", contract=_C, diff=_NOOP_DIFF,
                                 original_workspace=gradle_repo)
    assert r.overall == "fail"
    assert "1 failed" in r.residual_uncertainty or "BUILD FAILED" in r.residual_uncertainty


def test_empty_diff_fails(gradle_repo: str):
    r = AndroidVerifier().verify(task_id="t", contract=_C, diff="",
                                 original_workspace=gradle_repo)
    assert r.overall == "fail" and "no change" in r.residual_uncertainty


def test_no_target_fails(gradle_repo: str):
    c = _C.model_copy(update={"required_evidence": ["T0: pytest foo passes"]})
    r = AndroidVerifier().verify(task_id="t", contract=c, diff=_GOOD_DIFF,
                                 original_workspace=gradle_repo)
    assert r.overall == "fail" and "required_evidence" in r.residual_uncertainty


def test_no_gradle_launcher_fails_loudly(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.delenv("NEXUS_GRADLE_BIN", raising=False)
    ws = tmp_path / "no-wrapper"
    (ws / "app" / "src" / "main" / "java").mkdir(parents=True)
    (ws / "settings.gradle").write_text("include ':app'\n")
    (ws / "app" / "src" / "main" / "java" / "Calc.java").write_text("int calc() { return 1; }\n")
    r = AndroidVerifier().verify(task_id="t", contract=_C, diff=_GOOD_DIFF,
                                 original_workspace=str(ws))
    assert r.overall == "fail" and "gradle" in r.residual_uncertainty.lower()


def test_gradle_invocation_prefers_wrapper(gradle_repo: str):
    inv = gradle_invocation(gradle_repo)
    assert inv is not None and "gradlew" in inv[-1]
