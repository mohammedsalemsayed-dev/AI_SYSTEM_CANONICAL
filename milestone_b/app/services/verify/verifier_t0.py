"""Verifier — T0 tier only (DESIGN_TIGHTENING.md section 5).

Deterministic, no model. Takes a fresh copy of the *original* workspace, applies
the Builder's diff, and runs the pytest target named in the contract's
`required_evidence`. Independence: separate checkout, separate process.
"""

from __future__ import annotations

import subprocess
import sys

from app.schemas.contracts import (
    CriterionVerdict,
    TaskContract,
    VerificationRecord,
)
from app.services.build.workspace_copy import apply_diff, cleanup, copy_workspace

_PYTEST_TIMEOUT_S = 300


def extract_pytest_target(required_evidence: list[str]) -> str | None:
    """Pull the pytest target out of a 'T0: pytest <target> passes' entry."""
    for entry in required_evidence:
        low = entry.lower()
        if "t0" in low and "pytest" in low:
            after = entry[low.index("pytest") + len("pytest") :].strip()
            if after.lower().endswith("passes"):
                after = after[: -len("passes")].strip()
            return after or None
    return None


class VerifierT0:
    tier = "T0"

    def verify(
        self,
        *,
        task_id: str,
        contract: TaskContract,
        diff: str,
        original_workspace: str,
    ) -> VerificationRecord:
        target = extract_pytest_target(contract.required_evidence)
        criterion = CriterionVerdict(
            criterion=f"T0: pytest {target or '<?>'} passes", verdict="unknown"
        )

        if not target:
            return VerificationRecord(
                task_id=task_id,
                tier="T0",
                criteria=[criterion],
                overall="fail",
                residual_uncertainty="no runnable pytest target in required_evidence",
            )

        if not diff.strip():
            criterion.verdict = "fail"
            return VerificationRecord(
                task_id=task_id,
                tier="T0",
                criteria=[criterion],
                overall="fail",
                residual_uncertainty="builder produced no change",
            )

        ws = copy_workspace(original_workspace, prefix="slice_verify_")
        try:
            if not apply_diff(ws, diff):
                criterion.verdict = "fail"
                return VerificationRecord(
                    task_id=task_id,
                    tier="T0",
                    criteria=[criterion],
                    overall="fail",
                    residual_uncertainty="diff did not apply to a clean checkout",
                )

            proc = subprocess.run(
                [sys.executable, "-m", "pytest", *target.split(), "-q"],
                cwd=ws,
                capture_output=True,
                text=True,
                timeout=_PYTEST_TIMEOUT_S,
            )
            passed = proc.returncode == 0
            criterion.verdict = "pass" if passed else "fail"
            return VerificationRecord(
                task_id=task_id,
                tier="T0",
                criteria=[criterion],
                overall="pass" if passed else "fail",
                discriminating_tests_run=[target],
                residual_uncertainty=""
                if passed
                else (proc.stdout + proc.stderr)[-2000:],
            )
        except subprocess.TimeoutExpired:
            criterion.verdict = "fail"
            return VerificationRecord(
                task_id=task_id,
                tier="T0",
                criteria=[criterion],
                overall="fail",
                residual_uncertainty=f"pytest timed out after {_PYTEST_TIMEOUT_S}s",
            )
        finally:
            cleanup(ws)
