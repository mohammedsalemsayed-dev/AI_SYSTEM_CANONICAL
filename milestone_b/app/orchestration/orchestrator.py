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
    ApprovalDecision,
    ApprovalRequest,
    ArtifactVersion,
    ClarificationRequest,
    Observation,
    Plan,
    TaskContract,
    TaskResult,
    new_id,
)
from app.services.build.workspace_copy import cleanup, copy_workspace
from app.services.capability.issue import CapabilityError, issue_grant
from app.services.capability.registry import primary_operation
from app.services.escalation.ladder import Ladder
from app.services.progress.loop import LoopDetector, action_hash
from app.services.progress.measure import measure_step
from app.services.progress.patience import patience_for
from app.services.progress.service import ProgressService
from app.services.sandbox import SandboxSpec, select_runner
from app.services.verify.verifier_t0 import extract_pytest_target
from app.services.workspace.listing import list_workspace

_PYTEST_TIMEOUT_S = 300
_MAX_STEPS = 16  # hard safety cap on the execution loop


class TransitionError(RuntimeError):
    pass


class BuildError(RuntimeError):
    pass


class ApprovalPause(Exception):
    """Raised inside execution when a step needs human approval."""

    def __init__(self, action_id: str, step_id: str, reason: str) -> None:
        super().__init__(reason)
        self.action_id = action_id
        self.step_id = step_id
        self.reason = reason


class StalledEscalation(Exception):
    """Raised when the escalation ladder for a STALLED / LOOP_RISK step reaches
    'ask_user' — the task pauses for human input."""

    def __init__(self, classification: str, detail: str) -> None:
        super().__init__(detail)
        self.classification = classification
        self.detail = detail


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
        runner=None,
    ) -> None:
        self.log = log
        self.interpreter = interpreter
        self.planner = planner
        self.builder = builder
        self.verifier = verifier
        self.policy = policy
        self.workspace_lister = workspace_lister
        self._runner = runner  # per-step measurement sandbox; lazy if None

    def _step_runner(self):
        if self._runner is None:
            self._runner = select_runner(require_isolation=False)
        return self._runner

    # ------------------------------------------------------------------ #
    def run(self, request_text: str, workspace_path: str) -> TaskResult:
        task_id = new_id("task")
        self.log.append(
            task_id,
            EventKind.REQUEST,
            {"text": request_text, "workspace_path": workspace_path},
        )
        return self._drive(task_id, request_text, workspace_path)

    def resume(self, task_id: str, approval: str | None = None) -> TaskResult:
        """Continue a paused/interrupted task.

        - terminal -> return the recorded result
        - WAITING_FOR_USER with a pending approval + `approval` in {"approve","deny"}
          -> record the decision and either resume execution or fail
        - WAITING_FOR_USER (ambiguity) or `approval` is None -> unchanged
        - any other non-terminal state -> fail cleanly (interrupted); the user's
          workspace was never mutated (all work happens in temp copies)
        """
        snap = self._snap(task_id)
        if snap.state in _TERMINAL:
            return self._result_from_log(task_id)

        if snap.state is State.WAITING_FOR_USER and snap.pending_approval:
            if approval not in ("approve", "deny"):
                return self._finish(
                    task_id, "waiting for approval", state=State.WAITING_FOR_USER
                )
            return self._apply_approval(task_id, approval)

        if snap.state is State.WAITING_FOR_USER:
            return self._finish(
                task_id, "waiting for user input", state=State.WAITING_FOR_USER
            )

        self.log.append(
            task_id,
            EventKind.ERROR,
            {"error": f"interrupted in {snap.state}; not auto-resumed in the slice"},
        )
        self._force_fail(task_id)
        return self._finish(
            task_id, f"interrupted in {snap.state}; re-run the request", state=State.FAILED
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
            return self._execute_verify_settle(
                task_id, contract, plan, workspace_path, approved_steps=set()
            )

        except Exception as exc:  # noqa: BLE001 - slice: any failure -> FAILED + logged
            self.log.append(task_id, EventKind.ERROR, {"error": repr(exc)})
            self._force_fail(task_id)
            return self._finish(task_id, f"error: {exc!r}", state=State.FAILED)

    def _execute_verify_settle(
        self,
        task_id: str,
        contract: TaskContract,
        plan: Plan,
        workspace_path: str,
        *,
        approved_steps: set[str],
    ) -> TaskResult:
        try:
            combined_diff = self._execute(
                task_id, contract, plan, workspace_path, approved_steps
            )
        except ApprovalPause as pause:
            self.log.append(
                task_id,
                EventKind.APPROVAL_REQUEST,
                ApprovalRequest(
                    task_id=task_id,
                    action_id=pause.action_id,
                    operation="builder.execute",
                    reason=pause.reason,
                    summary=f"step {pause.step_id} needs approval",
                ).model_dump(mode="json")
                | {"step_id": pause.step_id},
            )
            self._transition(task_id, State.WAITING_FOR_USER)
            return self._finish(
                task_id,
                f"waiting for approval: {pause.reason}",
                state=State.WAITING_FOR_USER,
            )
        except StalledEscalation as stall:
            self.log.append(
                task_id,
                EventKind.CLARIFICATION,
                ClarificationRequest(
                    task_id=task_id,
                    questions=[
                        f"Task is {stall.classification} after the escalation ladder "
                        f"({stall.detail}). How should it proceed?"
                    ],
                    why="stalled / looping after automated recovery",
                ),
            )
            self._transition(task_id, State.WAITING_FOR_USER)
            return self._finish(
                task_id,
                f"{stall.classification.lower()} after escalation ladder: {stall.detail}",
                state=State.WAITING_FOR_USER,
            )

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
                task_id, "completed", state=State.COMPLETED,
                verified=True, verification_ref=verification.id,
            )
        self._transition(task_id, State.FAILED)
        return self._finish(
            task_id,
            "verification failed: "
            + (verification.residual_uncertainty[:200] or "test target did not pass"),
            state=State.FAILED,
            verification_ref=verification.id,
        )

    def _apply_approval(self, task_id: str, approval: str) -> TaskResult:
        snap = self._snap(task_id)
        action_id = snap.pending_approval or ""
        step_id = self._step_id_for_action(task_id, action_id)
        approved = approval == "approve"
        self.log.append(
            task_id,
            EventKind.APPROVAL_DECISION,
            ApprovalDecision(
                task_id=task_id, action_id=action_id, approved=approved
            ).model_dump(mode="json")
            | {"step_id": step_id},
        )
        if not approved:
            self.log.append(
                task_id, EventKind.ERROR, {"error": "approval denied by user"}
            )
            self._transition(task_id, State.FAILED)
            return self._finish(task_id, "approval denied", state=State.FAILED)

        # resume execution from the start; the builder works on a fresh copy each
        # time, and the now-approved step is allowed through.
        try:
            self._transition(task_id, State.EXECUTING)
            request = next(
                e.payload for e in self.log.read(task_id) if e.kind == EventKind.REQUEST
            )
            plan = next(
                Plan.model_validate(e.payload)
                for e in reversed(self.log.read(task_id))
                if e.kind == EventKind.PLAN
            )
            contract = next(
                TaskContract.model_validate(e.payload)
                for e in reversed(self.log.read(task_id))
                if e.kind == EventKind.CONTRACT
            )
        except StopIteration as exc:
            self.log.append(task_id, EventKind.ERROR, {"error": f"resume: {exc!r}"})
            self._force_fail(task_id)
            return self._finish(task_id, "resume failed", state=State.FAILED)

        try:
            return self._execute_verify_settle(
                task_id,
                contract,
                plan,
                request["workspace_path"],
                approved_steps=self._snap(task_id).approved_steps,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.append(task_id, EventKind.ERROR, {"error": repr(exc)})
            self._force_fail(task_id)
            return self._finish(task_id, f"error: {exc!r}", state=State.FAILED)

    def _execute(
        self,
        task_id: str,
        contract: TaskContract,
        plan: Plan,
        workspace_path: str,
        approved_steps: set[str],
    ) -> str:
        ws = copy_workspace(workspace_path)
        target = extract_pytest_target(contract.required_evidence)
        progress = ProgressService(task_id, patience_for(contract.task_class))
        loop = LoopDetector()
        ladder = Ladder()
        combined_diff = ""
        try:
            # baseline measurement — tests before any edit
            base_out = self._run_target(ws, target)
            progress.observe(
                measure_step(0, pytest_output=base_out, changed_paths=[], diff_text="")
            )

            steps = list(plan.steps)
            i = 0
            executed = 0
            while i < len(steps):
                if executed >= _MAX_STEPS:
                    raise BuildError(f"execution exceeded {_MAX_STEPS} steps")
                step = steps[i]
                executed += 1

                proposal, out = self._run_step(
                    task_id, contract, step, ws, approved_steps
                )
                if out is None:  # REQUIRE_APPROVAL pause was raised inside _run_step
                    return combined_diff  # unreachable; _run_step raises
                combined_diff = out.diff or combined_diff

                step_out = self._run_target(ws, target)
                m = measure_step(
                    executed,
                    pytest_output=step_out,
                    changed_paths=out.changed_paths,
                    diff_text=out.diff,
                    stderr=out.stderr,
                )
                pe = progress.observe(m)
                lr = loop.record(
                    act_hash=action_hash(proposal.operation, ws, proposal.arguments),
                    error_signature=m.error_signature,
                    diff_text=out.diff,
                    made_progress=pe.hard_progress,
                )
                effective = "LOOP_RISK" if lr.loop_risk else pe.classification
                self.log.append(
                    task_id,
                    EventKind.PROGRESS,
                    pe.model_dump(mode="json")
                    | {"loop_flags": lr.flags, "effective_class": effective},
                )

                if effective in ("STALLED", "LOOP_RISK"):
                    outcome, new_steps = self._run_ladder(
                        task_id, contract, workspace_path, ladder,
                        reason=effective, tried=pe.detail,
                    )
                    if outcome == "replanned":
                        steps, i = new_steps, 0
                        progress = ProgressService(
                            task_id, patience_for(contract.task_class)
                        )
                        loop = LoopDetector()
                        self._run_target(ws, target)  # rebaseline silently
                        continue
                    raise StalledEscalation(effective, pe.detail)

                i += 1
            return combined_diff
        finally:
            cleanup(ws)

    def _run_step(self, task_id, contract, step, ws, approved_steps):
        """Grant -> proposal -> policy -> builder for one step. Returns
        (proposal, BuildOutput). Raises ApprovalPause / BuildError."""
        try:
            grant = issue_grant(task_id, step, workspace_root=ws, network_allowlist=[])
        except CapabilityError as exc:
            raise BuildError(str(exc)) from exc
        self.log.append(task_id, EventKind.CAPABILITY_GRANT, grant)

        proposal = ActionProposal(
            task_id=task_id,
            step_id=step.id,
            operation=primary_operation(step.required_capability),
            arguments={"path": ws, "intent": step.intent},
            required_capability=step.required_capability,
            workspace_scope=ws,
            expected_effect=step.expected_artifact_delta,
            idempotency_key=f"{task_id}:{step.id}",
        )
        self.log.append(task_id, EventKind.ACTION_PROPOSAL, proposal)

        decision = self.policy.decide(proposal, contract, grant)
        self.log.append(task_id, EventKind.POLICY_DECISION, decision)
        if decision.decision == "REQUIRE_APPROVAL":
            if step.id not in approved_steps:
                raise ApprovalPause(proposal.action_id, step.id, decision.reason)
        elif decision.decision != "ALLOW":
            if decision.rule == "tainted-side-effect":
                self.log.append(
                    task_id,
                    EventKind.TAINT_BLOCKED,
                    {"action_id": proposal.action_id, "reason": decision.reason},
                )
            raise BuildError(
                f"policy {decision.decision} [{decision.rule}]: {decision.reason}"
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
        return proposal, out

    def _run_target(self, ws: str, target: str | None) -> str:
        if not target:
            return ""
        result = self._step_runner().run(
            SandboxSpec(
                workdir=ws,
                command=["python", "-m", "pytest", *target.split(), "-q"],
                network=False,
                timeout_s=_PYTEST_TIMEOUT_S,
            )
        )
        return (result.stdout or "") + (result.stderr or "")

    def _run_ladder(self, task_id, contract, workspace_path, ladder, *, reason, tried):
        """Advance the escalation ladder until an actionable rung. Returns
        ("replanned", new_steps) or ("ask_user", None)."""
        while not ladder.exhausted():
            rung = ladder.advance()
            self.log.append(
                task_id,
                EventKind.ESCALATION,
                {
                    "rung": rung.name,
                    "reason": reason,
                    "tried": tried,
                    "actionable": rung.actionable,
                },
            )
            if not rung.actionable:
                continue
            if rung.name == "change_strategy":
                listing = self.workspace_lister(workspace_path)
                note = (
                    f"\n\nNOTE: the previous plan was {reason} ({tried}). "
                    "Produce a materially different plan; do not repeat the same edit."
                )
                new_plan, prun = self.planner.plan(contract, listing + note)
                self.log.append(task_id, EventKind.PLAN, new_plan)
                self.log.append(task_id, EventKind.MODEL_RUN, prun)
                return "replanned", list(new_plan.steps)
            if rung.name == "ask_user":
                return "ask_user", None
        return "ask_user", None

    # ------------------------------------------------------------------ #
    def _snap(self, task_id: str) -> TaskSnapshot:
        return project_task(self.log.read(task_id))

    def _step_id_for_action(self, task_id: str, action_id: str) -> str:
        for e in self.log.read(task_id):
            if e.kind == EventKind.ACTION_PROPOSAL and e.payload.get("action_id") == action_id:
                return e.payload.get("step_id", "")
        return ""

    def _transition(self, task_id: str, target: State) -> None:
        snap = self._snap(task_id)
        ok, reason = transition_ok(snap.state, target, snap)
        if not ok:
            raise TransitionError(f"{snap.state} -> {target}: {reason}")
        self.log.append(task_id, EventKind.STATE, {"state": target})

    def _force_fail(self, task_id: str) -> None:
        snap = self._snap(task_id)
        if snap.state in _TERMINAL:
            return
        if State.FAILED in _allowed_from(snap.state):
            self.log.append(task_id, EventKind.STATE, {"state": State.FAILED})

    def _finish(self, task_id: str, summary: str, *, state: State, **kw) -> TaskResult:
        result = TaskResult(task_id=task_id, state=state.value, summary=summary, **kw)
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
