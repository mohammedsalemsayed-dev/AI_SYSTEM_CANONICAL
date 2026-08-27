"""Verifier — T0 tier only (DESIGN_TIGHTENING.md section 5).

Deterministic, no model. Takes a fresh copy of the *original* workspace, applies
the Builder's diff on the host, then runs the pytest target named in the
contract's `required_evidence` **inside the sandbox** (MILESTONE_C_PLAN.md 7-9).
Independence: separate checkout, separate execution environment.
"""

from __future__ import annotations

from app.schemas.contracts import (
    CriterionVerdict,
    TaskContract,
    VerificationRecord,
)
from app.services.build.workspace_copy import apply_diff, cleanup, copy_workspace
from app.services.sandbox import SandboxSpec, select_runner
from app.services.sandbox.runner import SandboxRunner

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


def _resolve_target(target: str, ws: str) -> str:
    """If the target's file part is not in `ws`, retry with its basename — the
    Interpreter sometimes prepends the repo directory."""
    from pathlib import Path

    parts = target.split()
    fixed = []
    for tok in parts:
        path_part, sep, node = tok.partition("::")
        if path_part and not (Path(ws) / path_part).exists():
            base = Path(path_part).name
            if (Path(ws) / base).exists():
                path_part = base
        fixed.append(path_part + sep + node)
    return " ".join(fixed)


class VerifierT0:
    tier = "T0"

    def __init__(
        self, runner: SandboxRunner | None = None, *, require_isolation: bool = False
    ) -> None:
        # require_isolation=True for real / tainted runs; the fallback is refused.
        self._runner = runner or select_runner(require_isolation=require_isolation)

    @property
    def backend(self) -> str:
        return self._runner.name

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
                task_id=task_id, tier="T0", criteria=[criterion], overall="fail",
                residual_uncertainty="no runnable pytest target in required_evidence",
            )

        if not diff.strip():
            criterion.verdict = "fail"
            return VerificationRecord(
                task_id=task_id, tier="T0", criteria=[criterion], overall="fail",
                residual_uncertainty="builder produced no change",
            )

        ws = copy_workspace(original_workspace, prefix="slice_verify_")
        try:
            if not apply_diff(ws, diff):
                criterion.verdict = "fail"
                return VerificationRecord(
                    task_id=task_id, tier="T0", criteria=[criterion], overall="fail",
                    residual_uncertainty="diff did not apply to a clean checkout",
                )

            resolved = _resolve_target(target, ws)
            result = self._runner.run(
                SandboxSpec(
                    workdir=ws,
                    command=["python", "-m", "pytest", *resolved.split(), "-q"],
                    network=False,
                    timeout_s=_PYTEST_TIMEOUT_S,
                )
            )
            if result.timed_out:
                criterion.verdict = "fail"
                return VerificationRecord(
                    task_id=task_id, tier="T0", criteria=[criterion], overall="fail",
                    residual_uncertainty=f"pytest timed out after {_PYTEST_TIMEOUT_S}s "
                    f"[{result.backend}]",
                )
            if result.error:
                criterion.verdict = "fail"
                return VerificationRecord(
                    task_id=task_id, tier="T0", criteria=[criterion], overall="fail",
                    residual_uncertainty=f"sandbox error [{result.backend}]: {result.error}",
                )

            passed = result.exit_code == 0
            criterion.verdict = "pass" if passed else "fail"
            return VerificationRecord(
                task_id=task_id, tier="T0", criteria=[criterion],
                overall="pass" if passed else "fail",
                discriminating_tests_run=[target],
                residual_uncertainty=""
                if passed
                else (result.stdout + result.stderr)[-2000:],
            )
        finally:
            cleanup(ws)
