"""T0 verifier for Android / Gradle projects — deterministic, no model.

Same contract as `VerifierT0` (`verify(...) -> VerificationRecord`), but the
evidence target is a Gradle task instead of pytest:

    "T0: android gradle :app:testDebugUnitTest passes"
    "T0: gradle test passes"                       # whatever the module calls it
    "T0: android passes"                           # -> defaults to testDebugUnitTest

Runs the project's `./gradlew` (or `gradlew.bat` on Windows, or a `gradle` on
PATH) against a fresh copy of the workspace with the diff applied. Gradle exits
non-zero on a failing unit test, so a clean `BUILD SUCCESSFUL` with return code
0 is the pass. If no Gradle launcher can be found the check fails loudly with a
hint — it never silently passes.

Set NEXUS_GRADLE_OFFLINE=1 to pass `--offline` (deterministic, but needs a warm
dependency cache). Wired automatically when the workspace has a
`settings.gradle`/`settings.gradle.kts` (see app/ui/runner).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from app.schemas.contracts import CriterionVerdict, TaskContract, VerificationRecord
from app.services.build.workspace_copy import apply_diff, cleanup, copy_workspace

_TIMEOUT_S = 1200  # a cold Gradle run compiles + downloads; give it room
_DEFAULT_TASK = "testDebugUnitTest"
_TESTS_RE = re.compile(r"(\d+)\s+tests?\s+completed(?:,\s*(\d+)\s+failed)?", re.I)


def gradle_invocation(workspace: str) -> list[str] | None:
    """The command prefix to run Gradle for this project, or None.

    Prefers the project's own wrapper (pins the Gradle version); falls back to a
    `gradle` on PATH. `NEXUS_GRADLE_BIN` overrides everything."""
    env = os.environ.get("NEXUS_GRADLE_BIN")
    if env and Path(env).is_file():
        return [env]
    root = Path(workspace)
    if os.name == "nt":
        for n in ("gradlew.bat", "gradlew.cmd"):
            if (root / n).is_file():
                return [str(root / n)]
    if (root / "gradlew").is_file():
        return ["sh", str(root / "gradlew")] if os.name == "nt" else [str(root / "gradlew")]
    import shutil

    found = shutil.which("gradle")
    return [found] if found else None


def extract_android_target(required_evidence: list[str]) -> str | None:
    """-> the Gradle task string, e.g. ':app:testDebugUnitTest'. None if there is
    no android/gradle entry; the default task if the entry names no task."""
    for entry in required_evidence:
        low = entry.lower()
        if "t0" in low and ("android" in low or "gradle" in low):
            rest = entry
            for k in ("android", "gradle"):
                i = rest.lower().find(k)
                if i >= 0:
                    rest = rest[i + len(k):]
            rest = re.sub(r"\s*passes?\s*$", "", rest.strip(), flags=re.I).strip()
            return rest or _DEFAULT_TASK
    return None


class AndroidVerifier:
    tier = "T0"

    def __init__(self, gradle: list[str] | None = None) -> None:
        self._gradle = gradle

    @property
    def backend(self) -> str:
        return "gradle" if (self._gradle is not None) else "gradle-detect"

    def verify(self, *, task_id: str, contract: TaskContract, diff: str,
               original_workspace: str, extra_targets: list[str] | None = None) -> VerificationRecord:
        tgt = extract_android_target(contract.required_evidence)
        crit = CriterionVerdict(criterion=f"T0: gradle {tgt or '<?>'} passes", verdict="unknown")

        def fail(msg: str) -> VerificationRecord:
            crit.verdict = "fail"
            return VerificationRecord(task_id=task_id, tier="T0", criteria=[crit],
                                      overall="fail", residual_uncertainty=msg)

        if tgt is None:
            return fail("no 'T0: android gradle <task> passes' entry in required_evidence")
        if not diff.strip():
            return fail("builder produced no change")

        ws = copy_workspace(original_workspace, prefix="slice_android_")
        try:
            gradle = self._gradle or gradle_invocation(ws)
            if gradle is None:
                return fail("no Gradle launcher — the project has no ./gradlew wrapper and "
                            "`gradle` is not on PATH (install Gradle or commit the wrapper)")
            if not apply_diff(ws, diff):
                return fail("diff did not apply to a clean checkout")

            tasks = [t for t in tgt.split() if t]
            cmd = [*gradle, *tasks, "--console=plain", "-Dorg.gradle.daemon=false"]
            if os.environ.get("NEXUS_GRADLE_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
                cmd.append("--offline")
            try:
                proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                return fail(f"gradle run timed out after {_TIMEOUT_S}s")
            except OSError as exc:
                return fail(f"could not launch gradle: {exc}")

            out = (proc.stdout or "") + (proc.stderr or "")
            m = _TESTS_RE.search(out)
            failed_n = int(m.group(2)) if (m and m.group(2)) else 0
            passed = (
                proc.returncode == 0
                and "BUILD SUCCESSFUL" in out
                and "BUILD FAILED" not in out
                and failed_n == 0
            )
            crit.verdict = "pass" if passed else "fail"
            tail = out.strip()[-1500:]
            return VerificationRecord(
                task_id=task_id, tier="T0", criteria=[crit],
                overall="pass" if passed else "fail",
                discriminating_tests_run=tasks if passed else [],
                residual_uncertainty="" if passed else tail or f"gradle exit {proc.returncode}",
            )
        finally:
            cleanup(ws)
