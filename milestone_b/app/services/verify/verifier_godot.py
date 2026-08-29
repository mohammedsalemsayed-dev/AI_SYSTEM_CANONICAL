"""T0 verifier for Godot projects — deterministic, no model.

Same contract as `VerifierT0` (`verify(...) -> VerificationRecord`), but the
evidence target is a GDScript check instead of pytest:

    "T0: godot res://test/run_tests.gd passes"        # a plain script that exit(1)s on failure
    "T0: godot gut test/unit passes"                  # a GUT (Godot Unit Test) directory

Runs `godot --headless` against a fresh copy of the workspace with the diff
applied. If the `godot` binary is not on PATH the check fails loudly with an
install hint — it never silently passes.

Wired automatically when the workspace has a `project.godot` (see app/ui/runner).
UNTESTED in this environment (no Godot installed); the shape follows VerifierT0.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

from app.schemas.contracts import CriterionVerdict, TaskContract, VerificationRecord
from app.services.build.workspace_copy import apply_diff, cleanup, copy_workspace

_TIMEOUT_S = 420
_GODOT_BINS = ("godot", "godot4", "godot-headless", "Godot", "Godot_v4")

# common places a portable Godot lands on each OS (the Windows build is often
# just an unzipped exe in Downloads / Desktop, not on PATH).
_SCAN_GLOBS = (
    os.path.expanduser(r"~\Downloads\**\Godot*.exe"),
    os.path.expanduser(r"~\Desktop\**\Godot*.exe"),
    os.path.expanduser(r"~\AppData\Local\Programs\**\Godot*.exe"),
    r"C:\Program Files\Godot\**\Godot*.exe",
    r"C:\Godot\**\Godot*.exe",
    os.path.expanduser("~/Applications/Godot*.app/Contents/MacOS/Godot"),
    "/Applications/Godot*.app/Contents/MacOS/Godot",
    os.path.expanduser("~/.local/share/godot*/**/godot*"),
    "/usr/local/bin/godot*", "/usr/bin/godot*",
)


def godot_binary() -> str | None:
    env = os.environ.get("NEXUS_GODOT_BIN") or os.environ.get("GODOT_BIN")
    if env and Path(env).is_file():
        return env
    for name in _GODOT_BINS:
        p = shutil.which(name)
        if p:
            return p
    for pat in _SCAN_GLOBS:
        hits = sorted(g for g in glob.glob(pat, recursive=True)
                      if "console" not in g.lower() and Path(g).is_file())
        if hits:
            return hits[-1]  # newest-sorting version wins
    return None


def extract_godot_target(required_evidence: list[str]) -> tuple[str, str] | None:
    """-> (mode, target) where mode is 'script' or 'gut'. None if no godot entry."""
    for entry in required_evidence:
        low = entry.lower()
        if "t0" in low and "godot" in low:
            rest = entry[low.index("godot") + len("godot"):].strip()
            rest = re.sub(r"\s+passes\s*$", "", rest, flags=re.I).strip()
            if rest.lower().startswith("gut "):
                return "gut", rest[4:].strip()
            return "script", rest
    return None


class GodotVerifier:
    tier = "T0"

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or godot_binary()

    @property
    def backend(self) -> str:
        return "godot-headless" if self.binary else "godot-missing"

    def verify(self, *, task_id: str, contract: TaskContract, diff: str,
               original_workspace: str, extra_targets: list[str] | None = None) -> VerificationRecord:
        tgt = extract_godot_target(contract.required_evidence)
        crit = CriterionVerdict(
            criterion=f"T0: godot {tgt[1] if tgt else '<?>'} passes", verdict="unknown"
        )

        def fail(msg: str) -> VerificationRecord:
            crit.verdict = "fail"
            return VerificationRecord(task_id=task_id, tier="T0", criteria=[crit],
                                      overall="fail", residual_uncertainty=msg)

        if self.binary is None:
            return fail("godot binary not on PATH — install Godot 4.x "
                        "(https://godotengine.org/download) to verify GDScript changes")
        if tgt is None:
            return fail("no 'T0: godot <script|gut ...> passes' entry in required_evidence")
        if not diff.strip():
            return fail("builder produced no change")

        mode, target = tgt
        ws = copy_workspace(original_workspace, prefix="slice_godot_")
        try:
            if not apply_diff(ws, diff):
                return fail("diff did not apply to a clean checkout")
            if mode == "gut":
                cmd = [self.binary, "--headless", "--path", ws,
                       "-s", "addons/gut/gut_cmdln.gd",
                       f"-gdir=res://{target}", "-gexit"]
            else:
                script = target if target.startswith("res://") else "res://" + target.lstrip("/")
                cmd = [self.binary, "--headless", "--path", ws, "--script", script]
            try:
                proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True,
                                      timeout=_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                return fail(f"godot run timed out after {_TIMEOUT_S}s")
            except OSError as exc:
                return fail(f"could not launch godot: {exc}")

            passed = proc.returncode == 0 and "SCRIPT ERROR" not in (proc.stdout + proc.stderr)
            crit.verdict = "pass" if passed else "fail"
            tail = (proc.stdout + proc.stderr).strip()[-1200:]
            return VerificationRecord(
                task_id=task_id, tier="T0", criteria=[crit],
                overall="pass" if passed else "fail",
                discriminating_tests_run=[target],
                residual_uncertainty="" if passed else tail or f"godot exit {proc.returncode}",
            )
        finally:
            cleanup(ws)
