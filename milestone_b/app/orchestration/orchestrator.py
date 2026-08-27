"""Orchestrator — drives the DESIGN_TIGHTENING.md section 1 object flow.

Every emitted record is appended to the event log *before* the state transition it
enables. Each transition is checked with `transition_ok` (allowed edge + gate
predicate). Every component is called through its seam; agents never call each
other.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.state import State, transition_ok
from app.events.log import EventKind, EventLog
from app.events.projections import TaskSnapshot, project_task
from app.schemas.contracts import (
    ActionProposal,
    ArtifactVersion,
    ClarificationRequest,
    Observation,
    TaskResult,
    new_id,
)
from app.services.build.workspace_copy import cleanup, copy_workspace
from app.services.workspace.listing import list_workspace


class TransitionError(RuntimeError):
    pass


class BuildError(RuntimeError):
    pass


_TERMINAL = {State.COMPLETED, State.FAILED, State.CANCELLED}


class Orchestrator:
    def __init__(
        self,
        log: EventLog,
        interpreter,
        planner,
        builder,
        verifier,
        policy,
        *,
        workspace_lister: Callable[[str], str] = list_workspace,
    ) -> None:
        self.log = log
        self.interpreter = interpreter
        self.planner = planner
        self.builder = builder
        self.verifier = verifier
        self.policy = policy
        self.workspace_lister = workspace_lister

    # ------------------------------------------------------------------ #
    def run(self, request_text: str, workspace_path: str) -> TaskResult:
        task_id = new_id("task")
        self.log.append(
            task_id,
            EventKind.REQUEST,
            {"text": request_text, "workspace_path": workspace_path},
        )
        return self._drive(task_id, request_text, workspace_path)

    def resume(self, task_id: str) -> TaskResult:
        """Light recovery (DESIGN_TIGHTENING.md section 1 checkpoint note; full
        reconciliation is Milestone D). An interrupted non-terminal task is not
        auto-continued in the slice — it is failed with the pre-interruption state
        left visible in the log. The user's workspace was never mutated (all work
        happens in temp copies), so the task is safe to re-run from scratch."""
        snap = self._snap(task_id)
        if snap.state in _TERMINAL:
            return self._result_from_log(task_id)
        if snap.state is State.WAITING_FOR_USER:
            return self._finish(task_id, "waiting for user input", state=snap.state)
        self.log.append(
            task_id,
            EventKind.ERROR,
            {"error": f"interrupted in {snap.state}; not auto-resumed in the slice"},
        )
        self._force_fail(task_id)
        return self._finish(
            task_id,
            f"interrupted in {snap.state}; re-run the request",
            state=State.FAILED,
        )

    # ------------------------------------------------------------------ #
    def _drive(
        self, task_id: str, request_text: str, workspace_path: str
    ) -> TaskResult:
        try:
            self._transition(task_id, State.INTERPRETING)
            listing = self.workspace_lister(workspace_path)

            contract, run = self.interpreter.compile(task_id, request_text, listing)
            self.log.append(task_id, EventKind.CONTRACT, contract)
            self.log.append(task_id, EventKind.MODEL_RUN, run)

            snap = self._snap(task_id)
            if snap.contract is not None and (
                snap.contract.ambiguity or snap.contract_problems
            ):
                questions = list(snap.contract.ambiguity) or [
                    f"cannot verify: {p}" for p in snap.contract_problems
                ]
                self.log.append(
                    task_id,
                    EventKind.CLARIFICATION,
                    ClarificationRequest(
                        task_id=task_id,
                        questions=questions,
                        why="objective ambiguous or not verifiable",
                    ),
                )
                self._transition(task_id, State.WAITING_FOR_USER)
                return self._finish(
                    task_id, "waiting for user input", state=State.WAITING_FOR_USER
                )

            self._transition(task_id, State.PLANNING)
            plan, prun = self.planner.plan(contract, listing)
            self.log.append(task_id, EventKind.PLAN, plan)
            self.log.append(task_id, EventKind.MODEL_RUN, prun)

            self._transition(task_id, State.EXECUTING)
            combined_diff = self._execute(task_id, contract, plan, workspace_path)

            self._transition(task_id, State.VERIFYING)
            verification = self.verifier.verify(
                task_id=task_id,
                contract=contract,
                diff=combined_diff,
                original_workspace=workspace_path,
            )
            self.log.append(task_id, EventKind.VERIFICATION, verification)

            if verification.overall == "pass":
                self._transition(task_id, State.COMPLETED)
                return self._finish(
                    task_id,
                    "completed",
                    state=State.COMPLETED,
                    verified=True,
                    verification_ref=verification.id,
                )
            self._transition(task_id, State.FAILED)
            return self._finish(
                task_id,
                "verification failed: "
                + (verification.residual_uncertainty[:200] or "test target did not pass"),
                state=State.FAILED,
                verification_ref=verification.id,
            )

        except Exception as exc:  # noqa: BLE001 - slice: any failure -> FAILED + logged
            self.log.append(task_id, EventKind.ERROR, {"error": repr(exc)})
            self._force_fail(task_id)
            return self._finish(task_id, f"error: {exc!r}", state=State.FAILED)

    def _execute(self, task_id, contract, plan, workspace_path) -> str:
        ws = copy_workspace(workspace_path)
        combined_diff = ""
        try:
            for step in plan.steps:
                proposal = ActionProposal(
                    task_id=task_id,
                    step_id=step.id,
                    operation="builder.execute",
                    arguments={"intent": step.intent},
                    required_capability=step.required_capability,
                    workspace_scope=ws,
                    expected_effect=step.expected_artifact_delta,
                    idempotency_key=f"{task_id}:{step.id}",
                )
                self.log.append(task_id, EventKind.ACTION_PROPOSAL, proposal)

                decision = self.policy.decide(proposal, contract)
                self.log.append(task_id, EventKind.POLICY_DECISION, decision)
                if decision.decision != "ALLOW":
                    raise BuildError(
                        f"policy returned {decision.decision}: {decision.reason}"
                    )

                out = self.builder.execute(
                    task_id=task_id, step=step, contract=contract, workspace=ws
                )
                artifact = ArtifactVersion(
                    task_id=task_id,
                    changed_paths=out.changed_paths,
                    diff=out.diff,
                    bytes=len(out.diff.encode("utf-8")),
                )
                self.log.append(task_id, EventKind.ARTIFACT, artifact)
                self.log.append(
                    task_id,
                    EventKind.OBSERVATION,
                    Observation(
                        task_id=task_id,
                        step_id=step.id,
                        exit_code=out.exit_code,
                        stdout=out.stdout[-4000:],
                        stderr=out.stderr[-4000:],
                        artifact_ref=artifact.id,
                        error=out.error,
                    ),
                )
                if out.error or out.exit_code != 0:
                    raise BuildError(out.error or f"builder exited {out.exit_code}")
                combined_diff = out.diff
            return combined_diff
        finally:
            cleanup(ws)

    # ------------------------------------------------------------------ #
    def _snap(self, task_id: str) -> TaskSnapshot:
        return project_task(self.log.read(task_id))

    def _transition(self, task_id: str, target: State) -> None:
        snap = self._snap(task_id)
        ok, reason = transition_ok(snap.state, target, snap)
        if not ok:
            raise TransitionError(f"{snap.state} -> {target}: {reason}")
        self.log.append(task_id, EventKind.STATE, {"state": target})

    def _force_fail(self, task_id: str) -> None:
        snap = self._snap(task_id)
        if snap.state in _TERMINAL or snap.state is State.WAITING_FOR_USER:
            return
        if State.FAILED in _allowed_from(snap.state):
            self.log.append(task_id, EventKind.STATE, {"state": State.FAILED})

    def _finish(self, task_id: str, summary: str, *, state: State, **kw) -> TaskResult:
        result = TaskResult(
            task_id=task_id, state=state.value, summary=summary, **kw
        )
        self.log.append(task_id, EventKind.RESULT, result)
        return result

    def _result_from_log(self, task_id: str) -> TaskResult:
        for event in reversed(self.log.read(task_id)):
            if event.kind == EventKind.RESULT:
                return TaskResult.model_validate(event.payload)
        snap = self._snap(task_id)
        return TaskResult(
            task_id=task_id, state=snap.state.value, summary="(no result event)"
        )


def _allowed_from(state: State) -> set[State]:
    from app.core.state import ALLOWED

    return ALLOWED[state]
