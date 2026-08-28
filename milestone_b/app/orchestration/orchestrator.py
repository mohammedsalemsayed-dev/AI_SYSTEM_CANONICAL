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
from app.services.budget.tracker import BudgetTracker
from app.services.build.workspace_copy import cleanup, copy_workspace
from app.services.capability.issue import CapabilityError, issue_grant
from app.services.capability.registry import primary_operation
from app.services.escalation.ladder import Ladder
from app.services.progress.loop import LoopDetector, action_hash
from app.services.progress.measure import measure_step
from app.services.progress.patience import patience_for
from app.services.progress.service import ProgressService
from app.services.recovery.checkpoint import build_checkpoint
from app.services.recovery.reconcile import reconcile
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


class BudgetExhausted(Exception):
    """Raised when a budget dimension hits 100% — the task pauses for the user."""

    def __init__(self, summary: str) -> None:
        super().__init__(summary)
        self.summary = summary


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
        critic=None,
    ) -> None:
        self.log = log
        self.interpreter = interpreter
        self.planner = planner
        self.builder = builder
        self.verifier = verifier
        self.policy = policy
        self.workspace_lister = workspace_lister
        self._runner = runner  # per-step measurement sandbox; lazy if None
        self.critic = critic  # Milestone E — opt-in; None = single-agent path
        self.verifier_t2 = None  # Milestone E — set to a VerifierT2 to enable the ensemble
        self.researcher = None  # Milestone E — set to a Researcher to enable the ladder rung
        self.role_perf = None  # Milestone E — RolePerformanceStore for shadow metrics
        self.memory = None  # Milestone F — set to a MemoryStore to enable context
        self.experience = None  # Milestone F — set to an ExperienceStore
        self.router = None  # Milestone G — set to a Router to enable provider routing
        self.route_stats = None  # Milestone G — RouteStatsStore; auto-built from memory
        self.hardware = None  # Milestone G — set to a HardwareMonitor for mode policy
        self.repo = None  # Milestone J — set to a RepoIntelligence to enable repo context + impact
        self.research = None  # Milestone K — set to a ResearchPipeline for research_web tasks
        self.kb = None  # Milestone L — set to a KnowledgeBase for doc_analysis tasks
        self.authoring = None  # Milestone M — set to an AuthoringPipeline for authoring tasks
        self.engines = None  # Milestone N — set to an EngineRegistry for engine-aware context
        self.selection = None  # Milestone O — set to a ModelSelectionController for fitted routing
        self.artifacts = None  # Milestone P — set to an ArtifactStore for versioned artifacts
        self.tools = None  # Milestone S — set to a ToolRegistry to enumerate + dispatch tools
        self._tool_dispatch = None
        self.tool_loop = None  # Milestone T — a ToolLoop (or zero-arg factory) for `ops` tasks
        self.per_file_policy = False  # Milestone V — re-run the Policy Engine per changed file
        self.canary_enabled = False  # Milestone I — canary-gate freshly promoted changes
        self.canary_fraction = 0.20  # Milestone I — live cohort fraction
        self.canary_min_samples = 10  # Milestone I — uses before a canary verdict
        self._exp_canaries: dict[str, object] = {}
        self._route_canaries: dict[str, object] = {}

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

        return self._reconcile_and_resume(task_id)

    def _reconcile_and_resume(self, task_id: str) -> TaskResult:
        """Interrupted mid-run: inspect the log, decide, act (MILESTONE_D_PLAN §2)."""
        events = self.log.read(task_id)
        decision = reconcile(events)
        self.log.append(task_id, EventKind.RECONCILE, decision.model_dump(mode="json"))

        if decision.decision == "NOOP":
            return self._result_from_log(task_id)

        if decision.decision in ("ESCALATE", "REPAIR"):
            q = (
                "Interrupted with an uncertain external effect — needs manual review."
                if decision.decision == "ESCALATE"
                else "Interrupted before it could plan — re-run the request."
            )
            self.log.append(
                task_id,
                EventKind.CLARIFICATION,
                ClarificationRequest(
                    task_id=task_id, questions=[q], why="restart reconciliation"
                ).model_dump(mode="json"),
            )
            self._transition(task_id, State.WAITING_FOR_USER)
            return self._finish(
                task_id, f"{decision.decision.lower()}: {decision.detail}",
                state=State.WAITING_FOR_USER,
            )

        # RESUME — steer the state machine to EXECUTING, then re-run the pipeline
        snap = self._snap(task_id)
        try:
            if snap.state is State.INTERPRETING:
                self._transition(task_id, State.PLANNING)
                self._transition(task_id, State.EXECUTING)
            elif snap.state in (State.PLANNING, State.RECOVERING):
                self._transition(task_id, State.EXECUTING)
            elif snap.state is State.STALLED:
                self._transition(task_id, State.RECOVERING)
                self._transition(task_id, State.EXECUTING)
            elif snap.state is State.VERIFYING:
                self._transition(task_id, State.WAITING_FOR_USER)
                # a crash during verify -> let a human decide; safe default
                self.log.append(
                    task_id, EventKind.CLARIFICATION,
                    ClarificationRequest(
                        task_id=task_id,
                        questions=["Interrupted during verification — re-verify?"],
                        why="restart reconciliation",
                    ).model_dump(mode="json"),
                )
                return self._finish(
                    task_id, "interrupted during verify", state=State.WAITING_FOR_USER
                )
            # EXECUTING: already there

            request = next(
                e.payload for e in events if e.kind == EventKind.REQUEST
            )
            plan = next(
                Plan.model_validate(e.payload)
                for e in reversed(events)
                if e.kind == EventKind.PLAN
            )
            contract = next(
                TaskContract.model_validate(e.payload)
                for e in reversed(events)
                if e.kind == EventKind.CONTRACT
            )
            return self._execute_verify_settle(
                task_id, contract, plan, request["workspace_path"],
                approved_steps=snap.approved_steps,
            )
        except Exception as exc:  # noqa: BLE001
            self.log.append(task_id, EventKind.ERROR, {"error": repr(exc)})
            self._force_fail(task_id)
            return self._finish(task_id, f"resume error: {exc!r}", state=State.FAILED)

    # ------------------------------------------------------------------ #
    def _drive(
        self, task_id: str, request_text: str, workspace_path: str
    ) -> TaskResult:
        try:
            self._transition(task_id, State.INTERPRETING)
            listing = self.workspace_lister(workspace_path)
            mem_ctx = self._memory_context(request_text)
            if mem_ctx:
                self.log.append(task_id, EventKind.MEMORY, {"used": "context", "chars": len(mem_ctx)})
                listing = mem_ctx + "\n\n" + listing

            repo_ctx = self._repo_context(task_id, workspace_path, request_text)
            if repo_ctx:
                listing = repo_ctx + "\n\n" + listing

            engine_ctx = self._engine_context(task_id, workspace_path, request_text)
            if engine_ctx:
                listing = engine_ctx + "\n\n" + listing

            if self.tools is not None:
                listing = self.tools.manifest_block() + "\n" + listing

            contract, run = self.interpreter.compile(task_id, request_text, listing)
            self.log.append(task_id, EventKind.CONTRACT, contract)
            self.log.append(task_id, EventKind.MODEL_RUN, run)
            self._msg(
                task_id, "interpreter", "HANDOFF",
                claims=[f"objective: {contract.objective}", f"task_class: {contract.task_class}"],
                assumptions=list(contract.assumptions),
                requested_action="plan",
            )

            if contract.task_class == "research_web" and self.research is not None:
                return self._run_research(task_id, contract, request_text)
            if contract.task_class == "doc_analysis" and self.kb is not None:
                return self._run_doc_analysis(task_id, contract, request_text)
            if contract.task_class == "authoring" and self.authoring is not None:
                return self._run_authoring(task_id, contract, request_text)
            if contract.task_class == "ops" and self.tool_loop is not None:
                return self._run_tool_task(task_id, contract, request_text, workspace_path)

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
            if self._route_and_check_hardware(task_id, contract) is False:
                return self._finish(
                    task_id, "paused: hardware protection", state=State.WAITING_FOR_USER
                )
            self._experience_advice(task_id, contract)
            plan, prun = self.planner.plan(contract, listing)
            self.log.append(task_id, EventKind.PLAN, plan)
            self.log.append(task_id, EventKind.MODEL_RUN, prun)
            self._msg(
                task_id, "planner", "HANDOFF",
                claims=[s.intent for s in plan.steps],
                requested_action="execute",
            )
            self._emit_composition(task_id, contract)

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
        critic_round: int = 0,
    ) -> TaskResult:
        try:
            combined_diff = self._execute(
                task_id, contract, plan, workspace_path, approved_steps
            )
            self._msg(
                task_id, "builder", "HANDOFF",
                claims=[f"diff: {len(combined_diff.encode('utf-8'))} bytes"],
                requested_action="verify",
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
        except BudgetExhausted as be:
            self.log.append(
                task_id,
                EventKind.BUDGET,
                {"level": "hard", "summary": be.summary},
            )
            self.log.append(
                task_id,
                EventKind.CLARIFICATION,
                ClarificationRequest(
                    task_id=task_id,
                    questions=[f"Budget exhausted ({be.summary}). Extend it or stop?"],
                    why="task budget reached 100%",
                ),
            )
            self._transition(task_id, State.WAITING_FOR_USER)
            return self._finish(
                task_id, f"budget exhausted: {be.summary}", state=State.WAITING_FOR_USER
            )

        extra_targets = self._repo_impact(task_id, contract, combined_diff, workspace_path)

        self._transition(task_id, State.VERIFYING)
        verification = self.verifier.verify(
            task_id=task_id,
            contract=contract,
            diff=combined_diff,
            original_workspace=workspace_path,
            extra_targets=extra_targets,
        )
        self.log.append(task_id, EventKind.VERIFICATION, verification)
        self._msg(
            task_id, "verifier", "STATUS",
            claims=[f"T0 {verification.overall}"],
            confidence_summary=verification.tier,
        )

        # Milestone E — independent T2 ensemble verifier (opt-in). Advisory: T0
        # (deterministic) stays authoritative; T2 can only escalate a concern.
        if self.verifier_t2 is not None:
            escalate = self._t2_pass(task_id, contract, combined_diff, verification, workspace_path)
            if escalate is not None:
                self._transition(task_id, State.WAITING_FOR_USER)
                return self._finish(
                    task_id, f"verification disagreement: {escalate}",
                    state=State.WAITING_FOR_USER,
                )

        # Milestone E — Critic pass, positioned so it can never false-reject a
        # T0-passing diff (research: over-rejection is the real risk).
        if self.critic is not None:
            report = self._critic_pass(task_id, contract, combined_diff, workspace_path)
            if verification.overall != "pass" and report.verdict == "reject" and critic_round == 0:
                # T0 already failed; feed the findings into one bounded retry
                revised = contract.model_copy(
                    update={
                        "constraints": list(contract.constraints)
                        + [f"critic: {f.claim}" for f in report.findings if f.claim]
                    }
                )
                self._emit_handoff(task_id, report)
                self._transition(task_id, State.STALLED)
                self._transition(task_id, State.RECOVERING)
                self._transition(task_id, State.EXECUTING)
                return self._execute_verify_settle(
                    task_id, revised, plan, workspace_path,
                    approved_steps=approved_steps, critic_round=1,
                )
            if verification.overall == "pass" and report.verdict == "reject":
                # T0 is authoritative — log the disagreement, do not retry
                self.log.append(
                    task_id,
                    EventKind.DISAGREEMENT,
                    {
                        "between": ["critic", "verifier_t0"],
                        "detail": report.summary
                        or "critic rejected a T0-passing diff",
                        "findings": [f.claim for f in report.findings],
                    },
                )

        if verification.overall == "pass":
            self._transition(task_id, State.COMPLETED)
            self._remember_completion(task_id, contract, combined_diff, verification)
            self._capture_experience(task_id, contract, verification)
            self._ingest_route_stats(task_id, contract, verification)
            self._settle_canaries(task_id, contract, verified=True)
            return self._finish(
                task_id, "completed", state=State.COMPLETED,
                verified=True, verification_ref=verification.id,
                artifact_ref=self._last_store_id(task_id),
            )
        self._settle_canaries(task_id, contract, verified=False)
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
        ladder = Ladder(
            has_critic=self.critic is not None,
            has_researcher=self.researcher is not None,
            has_stronger_model=self.router is not None,
        )
        budget = BudgetTracker(contract.budget, contract.task_class)
        soft_warned = False
        combined_diff = ""
        try:
            steps = list(plan.steps)
            # per-step T0 measurement only earns its cost on multi-step plans;
            # a single step can't stall, and the final verify already runs the target
            measure = len(steps) > 1

            if measure:
                base_out = self._run_target(ws, target)
                progress.observe(
                    measure_step(0, pytest_output=base_out, changed_paths=[], diff_text="")
                )

            i = 0
            executed = 0
            while i < len(steps):
                if executed >= _MAX_STEPS:
                    raise BuildError(f"execution exceeded {_MAX_STEPS} steps")
                if budget.would_exceed(extra_steps=1):
                    raise BudgetExhausted(budget.summary())
                step = steps[i]
                executed += 1
                budget.add_step()

                proposal, out = self._run_step(
                    task_id, contract, step, ws, approved_steps
                )
                combined_diff = out.diff or combined_diff

                if not measure:
                    i += 1
                    continue

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

                if budget.over_hard():
                    raise BudgetExhausted(budget.summary())
                if budget.over_soft() and not soft_warned:
                    soft_warned = True
                    self.log.append(
                        task_id,
                        EventKind.BUDGET,
                        {"level": "soft", "peak_fraction": round(budget.peak_fraction(), 2),
                         "summary": budget.summary()},
                    )

                if effective in ("STALLED", "LOOP_RISK"):
                    outcome, new_steps = self._run_ladder(
                        task_id, contract, workspace_path, ladder,
                        reason=effective, tried=pe.detail, diff=combined_diff,
                    )
                    if outcome == "replanned":
                        steps, i = new_steps, 0
                        measure = True  # a re-plan means we keep watching
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
        if (
            self.per_file_policy
            and out.exit_code == 0
            and not out.error
            and out.changed_paths
        ):
            # Milestone V — the step proposal only carried the workspace root, so
            # the §14.1 risk-class gate never saw the files. Re-run the *same*
            # engine + grant once per changed file, before any artifact is
            # recorded for this step.
            self._per_file_policy(
                task_id, contract, step, ws, grant, out.changed_paths,
                approved_steps, proposal.action_id,
            )
        artifact = ArtifactVersion(
            task_id=task_id,
            changed_paths=out.changed_paths,
            diff=out.diff,
            bytes=len(out.diff.encode("utf-8")),
        )
        art_extra = self._store_artifact(
            task_id, "diff", out.diff,
            logical_key=self._logical_key("objective", contract.objective),
            trust="workspace",
            meta={"changed_paths": out.changed_paths, "step_id": step.id},
        )
        self.log.append(
            task_id, EventKind.ARTIFACT,
            artifact.model_dump(mode="json") | art_extra,
        )
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

    def _per_file_policy(self, task_id, contract, step, ws, grant, changed_paths,
                         approved_steps, step_action_id):
        """Milestone V — one `file.write` ActionProposal per changed file, through
        the existing PolicyEngine + step grant. ALLOW -> a logged decision;
        REQUIRE_APPROVAL on a risk-class path -> ApprovalPause (step-scoped, keyed
        to the step proposal so an approve/resume clears it); DENY -> BuildError.
        No new rule, no new gate."""
        needs_approval: list[tuple[str, str]] = []
        for rel in changed_paths:
            p = ActionProposal(
                task_id=task_id,
                step_id=step.id,
                operation="file.write",
                arguments={"path": rel},
                required_capability="fs.write",
                workspace_scope=ws,
                expected_effect=f"write {rel}",
                idempotency_key=f"{task_id}:{step.id}:{rel}",
            )
            d = self.policy.decide(p, contract, grant)
            self.log.append(
                task_id, EventKind.POLICY_DECISION,
                d.model_dump(mode="json") | {"scope": "per-file", "path": rel},
            )
            if d.decision == "ALLOW":
                continue
            if d.decision == "REQUIRE_APPROVAL":
                needs_approval.append((rel, d.reason))
                continue
            if d.rule == "tainted-side-effect":
                self.log.append(
                    task_id, EventKind.TAINT_BLOCKED,
                    {"action_id": p.action_id, "reason": d.reason, "path": rel},
                )
            raise BuildError(
                f"per-file policy {d.decision} [{d.rule}] on {rel}: {d.reason}"
            )
        if needs_approval and step.id not in approved_steps:
            rels = ", ".join(r for r, _ in needs_approval)
            raise ApprovalPause(
                step_action_id, step.id,
                f"{len(needs_approval)} changed file(s) need approval ({rels}): "
                f"{needs_approval[0][1]}",
            )

    def _read_test_text(self, workspace_path: str, target: str | None) -> str:
        if not target:
            return ""
        from pathlib import Path

        first = target.split()[0].split("::")[0]
        p = Path(workspace_path) / first
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            return ""

    def _critic_pass(self, task_id, contract, combined_diff, workspace_path):
        """Run the Critic on the diff; log CRITIC + CRITIQUE message; return the
        CriticReport. The caller decides what to do with the verdict."""
        from app.services.agents.messages import emit_message
        from app.services.verify.verifier_t0 import extract_pytest_target

        target = extract_pytest_target(contract.required_evidence)
        test_text = self._read_test_text(workspace_path, target)
        report, run = self.critic.review(task_id, contract, combined_diff, test_text)
        self.log.append(task_id, EventKind.CRITIC, report.model_dump(mode="json"))
        self.log.append(task_id, EventKind.MODEL_RUN, run)
        emit_message(
            self.log, task_id,
            sender="critic", role="critic", intent="CRITIQUE",
            claims=[f.claim for f in report.findings],
            confidence_summary=f"verdict={report.verdict}",
        )
        return report

    def _msg(self, task_id, sender, intent, **kw) -> None:
        from app.services.agents.messages import emit_message

        emit_message(self.log, task_id, sender=sender, role=sender, intent=intent, **kw)

    def _memory_context(self, request_text: str, task_class: str | None = None) -> str:
        if self.memory is None:
            return ""
        from app.services.memory.context import build_context

        return build_context(self.memory, request_text, task_class=task_class)

    # ------------------------------------------------------------------ #
    # Milestone P — artifact & version tracking
    # ------------------------------------------------------------------ #
    @staticmethod
    def _logical_key(prefix: str, text: str) -> str:
        import hashlib

        return f"{prefix}:{hashlib.sha1((text or '').encode('utf-8')).hexdigest()[:12]}"

    def _last_store_id(self, task_id) -> str | None:
        if self.artifacts is None:
            return None
        for e in reversed(self.log.read(task_id)):
            if e.kind == EventKind.ARTIFACT and e.payload.get("store_id"):
                return e.payload["store_id"]
        return None

    def _store_artifact(self, task_id, kind, content, *, logical_key, trust="workspace", meta=None) -> dict:
        """Write a versioned, content-addressed artifact when a store is wired.
        Returns a dict of fields to merge into the ARTIFACT event payload
        (empty when no store)."""
        if self.artifacts is None:
            return {}
        try:
            ref = self.artifacts.put(
                kind, content, task_id=task_id, logical_key=logical_key,
                trust=trust, meta=meta or {},
            )
        except Exception as exc:  # noqa: BLE001 — artifact storage is best-effort
            self.log.append(task_id, EventKind.ERROR, {"error": f"artifact store: {exc!r}"})
            return {}
        return {
            "store_id": ref.id, "sha": ref.sha, "parent_id": ref.parent_id,
            "logical_key": ref.logical_key, "artifact_kind": ref.kind,
            "trust": ref.trust,
        }

    def _changed_paths(self, task_id) -> list[str]:
        return sorted(
            {
                p
                for e in self.log.read(task_id)
                if e.kind == EventKind.ARTIFACT
                for p in e.payload.get("changed_paths", [])
            }
        )

    # ------------------------------------------------------------------ #
    # Milestone S — tool adapter framework
    # ------------------------------------------------------------------ #
    def _tool(self, qualified_op, args, ctx):
        """Dispatch one tool op through the framework (which runs it past the
        existing Policy Engine + capability grant) and log a TOOL event.
        Returns the ToolResult. No-op-safe: raises if `self.tools` is unset."""
        if self.tools is None:
            raise RuntimeError("no ToolRegistry wired")
        if self._tool_dispatch is None:
            from app.services.tools.dispatch import ToolDispatcher

            self._tool_dispatch = ToolDispatcher(
                self.tools, self.policy,
                risk_globs=getattr(self.policy, "risk_globs", None),
            )
        result, decision = self._tool_dispatch.run(qualified_op, args, ctx)
        if decision is not None and decision.decision != "ALLOW":
            self.log.append(task_id=getattr(ctx, "task_id", ""),
                            kind=EventKind.POLICY_DECISION,
                            payload=decision.model_dump(mode="json"))
        self.log.append(
            getattr(ctx, "task_id", ""), EventKind.TOOL,
            {"op": qualified_op, "ok": result.ok, "trust": result.trust,
             "error": result.error[:200], "meta": result.meta},
        )
        return result

    # ------------------------------------------------------------------ #
    # Milestone N — engine adapters + expert modes
    # ------------------------------------------------------------------ #
    def _engine_context(self, task_id, workspace_path, request_text) -> str:
        if self.engines is None:
            return ""
        from app.services.engines.base import render_profile
        from app.services.engines.profiles import domain_profile

        try:
            adapter, info = self.engines.detect(workspace_path)
        except Exception as exc:  # noqa: BLE001 — engine context is best-effort
            self.log.append(task_id, EventKind.ENGINE, {"error": repr(exc)})
            return ""

        # a "expert: <name>" hint in the request text also forces a domain profile
        forced = None
        low = request_text.lower()
        if "expert:" in low:
            forced = domain_profile(low.split("expert:", 1)[1].strip().split()[0].strip(" .,:;"))

        ENGINE_MIN_CONF = 0.6
        if info.confidence < ENGINE_MIN_CONF and forced is None:
            return ""

        profile = forced or adapter.expert_profile()
        block = render_profile(profile, info)
        self.log.append(
            task_id, EventKind.ENGINE,
            {"engine": info.engine, "confidence": round(info.confidence, 2),
             "version_hint": info.version_hint, "build_cmd": info.build_cmd,
             "test_cmd": info.test_cmd, "profile": profile.name},
        )
        return block

    # ------------------------------------------------------------------ #
    # Milestone J — repo intelligence
    # ------------------------------------------------------------------ #
    def _repo_context(self, task_id, workspace_path, objective_text) -> str:
        if self.repo is None:
            return ""
        try:
            block = self.repo.context_block(objective_text)
        except Exception as exc:  # noqa: BLE001 — repo context is best-effort
            self.log.append(task_id, EventKind.REPO, {"error": repr(exc)})
            return ""
        if not block:
            return ""
        idx = self.repo.index
        self.log.append(
            task_id, EventKind.REPO,
            {"files": len(idx.files), "modules": len(idx.modules()),
             "head": (self.repo._cache_key or "")[:12]},
        )
        return block

    def _repo_impact(self, task_id, contract, combined_diff, workspace_path) -> list[str]:
        """Post-build blast-radius analysis. Logs an IMPACT event, emits a
        breadth advisory, and returns the extra pytest targets T0 should also
        run. Best-effort — never blocks the loop."""
        if self.repo is None or not combined_diff.strip():
            return []
        try:
            changed = self._changed_paths(task_id)
            impact = self.repo.impact_for(changed, combined_diff)
            advice = self.repo.breadth(contract.task_class, impact)
        except Exception as exc:  # noqa: BLE001
            self.log.append(task_id, EventKind.IMPACT, {"error": repr(exc)})
            return []

        self.log.append(task_id, EventKind.IMPACT, impact.model_dump(mode="json"))
        self._msg(
            task_id, "repo", "STATUS",
            claims=[f"breadth: {advice.level} ({advice.why})"]
            + ([f"risk flags: {', '.join(impact.risk_flags)}"] if impact.risk_flags else []),
            confidence_summary="advisory — T0 stays authoritative"
            + ("; approximate" if impact.approximate else ""),
        )
        if advice.level == "broad" and advice.escalate_review:
            self.log.append(
                task_id, EventKind.ROUTE,
                {"task_class": contract.task_class, "provider_id": "",
                 "reason": f"repo breadth: {advice.why}", "escalated": True,
                 "data_driven": False, "review_only": True},
            )

        named = extract_pytest_target(contract.required_evidence) or ""
        named_files = {tok.split("::")[0] for tok in named.split() if tok}
        extra = [t for t in impact.tests_affected if t not in named_files]
        return extra

    def _remember_completion(self, task_id, contract, diff, verification) -> None:
        """Project-memory artifact index on a verified completion."""
        if self.memory is None:
            return
        from app.services.memory.store import MemoryRecord

        changed = self._changed_paths(task_id)
        if changed:
            self.memory.put(
                MemoryRecord(
                    task_id=task_id, tier="project", kind="artifact_index",
                    scope=contract.task_class,
                    content=f"{contract.objective} -> touched {', '.join(changed)}",
                )
            )
        self.log.append(task_id, EventKind.MEMORY, {"used": "write", "kind": "artifact_index"})

    def _experience_advice(self, task_id, contract) -> None:
        """Retrieve matching PROMOTED/VALIDATED experiences and pass them to the
        Planner as an advisory message. The Planner still writes a fresh plan."""
        if self.experience is None:
            return
        from app.services.agents.messages import emit_message
        from app.services.experience.signature import situation_signature

        sig = situation_signature(contract, tools_used=["builder", "verifier_t0"])
        matches = self.experience.retrieve(sig)
        for exp in matches:
            self.experience.record_use(exp.id, verified=True)  # retrieval == a use
        if matches:
            emit_message(
                self.log, task_id,
                sender="experience", role="experience", intent="PROPOSAL",
                claims=[f"a {m.validation_state} strategy for a similar task: {m.strategy}"
                        for m in matches[:3]],
                evidence_refs=[m.id for m in matches[:3]],
                confidence_summary="advisory — the planner still decides",
            )

    def _capture_experience(self, task_id, contract, verification) -> None:
        if self.experience is None:
            return
        from app.services.experience.signature import situation_signature

        changed = self._changed_paths(task_id)

        plan = next(
            (Plan.model_validate(e.payload) for e in reversed(self.log.read(task_id))
             if e.kind == EventKind.PLAN),
            None,
        )
        strategy = " ; ".join(s.intent for s in plan.steps) if plan else contract.objective
        sig = situation_signature(contract, tools_used=["builder", "verifier_t0"])
        exp = self.experience.capture(
            signature=sig, strategy=strategy, actions=list(changed),
            evidence_refs=[verification.id], success_score=1.0,
            verify_tier=verification.tier,
        )
        if exp is not None:
            self.log.append(
                task_id, EventKind.EXPERIENCE,
                {"id": exp.id, "state": exp.validation_state, "signature": sig},
            )

    def _task_proposed_experiences(self, task_id) -> list[str]:
        """Experience ids that were surfaced to the Planner for this task."""
        ids: list[str] = []
        for e in self.log.read(task_id):
            if e.kind == EventKind.AGENT_MESSAGE and e.payload.get("sender") == "experience":
                ids.extend(e.payload.get("evidence_refs", []))
        return ids

    def flag_catastrophic(self, task_id, reason: str) -> list[str]:
        """Automatic experience rollback (§8 `any -> QUARANTINED`). Called on a
        narrow set of signals — security check bypassed, data loss, or a
        verifier/human contradiction of a claimed success. Every experience that
        was proposed for this task is quarantined immediately (no debounce);
        exit is a manual review + re-entry at CANDIDATE."""
        if self.experience is None:
            return []
        hit: list[str] = []
        for exp_id in dict.fromkeys(self._task_proposed_experiences(task_id)):
            try:
                exp = self.experience.record_use(exp_id, verified=False, catastrophic=True)
            except KeyError:
                continue
            hit.append(exp_id)
            self.log.append(
                task_id, EventKind.EXPERIENCE_TRANSITION,
                {"id": exp_id, "state": exp.validation_state,
                 "trigger": "catastrophic", "reason": reason},
            )
        return hit

    # ------------------------------------------------------------------ #
    # Milestone G — routing + hardware
    # ------------------------------------------------------------------ #
    def _hardware_mode(self, task_id, *, progress_good: bool = True) -> str:
        if self.hardware is None:
            return "NORMAL"
        from app.services.hardware.modes import decide

        snap = self.hardware.sample()
        mode = decide(snap, progress_good=progress_good)
        src = getattr(snap, "source", "static")
        # log on any non-NORMAL mode, or whenever the reading is live (so the
        # health strip has real numbers even on a healthy machine)
        if mode != "NORMAL" or src.startswith("live"):
            self.log.append(
                task_id, EventKind.HARDWARE,
                {"mode": mode, "source": src,
                 "ram_percent": snap.ram_percent, "cpu_percent": snap.cpu_percent,
                 "disk_free_percent": snap.disk_free_percent,
                 "gpu_temp_c": snap.gpu_temp_c, "gpu_percent": snap.gpu_percent,
                 "vram_percent": snap.vram_percent},
            )
        return mode

    def _tried_providers(self, task_id) -> list[str]:
        return [
            e.payload.get("provider_id", "")
            for e in self.log.read(task_id)
            if e.kind == EventKind.ROUTE and e.payload.get("provider_id")
        ]

    def _route_and_check_hardware(self, task_id, contract) -> bool | None:
        """Sample the hardware mode (pausing on EMERGENCY) and, if a Router is
        wired, pick a provider and record a ROUTE event. Returns False when the
        hardware mode says pause (caller finishes into WAITING_FOR_USER), else None."""
        # Milestone R — hardware sampling is independent of routing: a live
        # monitor logs a real snapshot every task, and an EMERGENCY pauses even
        # with no Router wired.
        from app.services.hardware.modes import should_pause

        mode = self._hardware_mode(task_id)
        if self.router is None:
            if should_pause(mode):
                self.log.append(
                    task_id, EventKind.CLARIFICATION,
                    {"task_id": task_id,
                     "questions": [f"hardware mode {mode}. Resume when the machine has cooled?"],
                     "why": "hardware protection"},
                )
                self._transition(task_id, State.WAITING_FOR_USER)
                return False
            return None
        # Milestone O — let the selection controller decide static vs data-driven
        # for this task_class, gated by the guardrail regression check, and hand
        # the fitted weights to the router.
        if self.selection is not None:
            self.router.selection = self.selection
            reg = None
            if self.memory is not None:
                from app.services.eval.regression import RegressionBaseline

                rb = RegressionBaseline(self.memory)
                if rb.latest() is not None:
                    reg = lambda: rb.certify(rb.latest())  # noqa: E731 — trivial thunk
            self.selection.promote(contract.task_class, regression_check=reg,
                                   log=self.log, task_id=task_id)
        risk = getattr(contract, "risk_level", "low")
        decision = self.router.route(
            contract.task_class, "builder",
            task_id=task_id, hardware_mode=mode, risk_level=risk,
        )
        self.log.append(task_id, EventKind.ROUTE, decision.model_dump(mode="json"))
        if not decision.provider_id:
            self.log.append(
                task_id, EventKind.CLARIFICATION,
                {"task_id": task_id,
                 "questions": [f"{decision.reason}. Resume when the machine has cooled?"],
                 "why": "hardware protection"},
            )
            self._transition(task_id, State.WAITING_FOR_USER)
            return False
        return None

    def _ingest_route_stats(self, task_id, contract, verification) -> None:
        if self.router is None or self.memory is None:
            return
        if self.route_stats is None:
            from app.services.routing.stats import RouteStatsStore

            self.route_stats = RouteStatsStore(self.memory)
        chosen = (self._tried_providers(task_id) or [""])[-1]
        spec = self.router.registry.get(chosen) if chosen else None
        from app.schemas.contracts import ModelRunRecord

        for e in self.log.read(task_id):
            if e.kind != EventKind.MODEL_RUN:
                continue
            run = ModelRunRecord.model_validate(e.payload)
            if not run.provider and spec is not None:
                run.provider, run.model = spec.provider, (spec.model or spec.id)
            self.route_stats.ingest(
                run, task_class=contract.task_class,
                verification_tier=verification.tier,
                verification_pass=(verification.overall == "pass"),
            )

    def _stronger_model_route(self, task_id, contract) -> "object | None":
        """The `stronger_model` ladder rung: re-route to the best untried eligible
        cloud provider. Returns a RouteDecision if one is available, else None."""
        if self.router is None:
            return None
        tried = self._tried_providers(task_id)
        decision = self.router.route(
            contract.task_class, "builder", task_id=task_id,
            attempt=99, tried=tried, user_requested_cloud=True,
        )
        if not decision.provider_id or decision.provider_id in tried:
            return None
        decision.escalated = True
        decision.reason = f"stronger_model rung: {decision.reason}"
        self.log.append(task_id, EventKind.ROUTE, decision.model_dump(mode="json"))
        return decision

    # ------------------------------------------------------------------ #
    # Milestone I — canary cohorts for freshly promoted changes
    # ------------------------------------------------------------------ #
    def _settle_canaries(self, task_id, contract, *, verified: bool) -> None:
        if not self.canary_enabled:
            return
        self._settle_experience_canaries(task_id, contract, verified=verified)
        self._settle_route_canary(task_id, contract, verified=verified)

    def _settle_experience_canaries(self, task_id, contract, *, verified: bool) -> None:
        if self.experience is None:
            return
        from app.services.eval.canary import CanaryController

        for exp_id in dict.fromkeys(self._task_proposed_experiences(task_id)):
            exp = self.experience.get(exp_id)
            if exp is None or exp.validation_state not in ("PROMOTED", "MONITORED"):
                continue
            ctrl = self._exp_canaries.get(exp_id)
            if ctrl is None:
                baseline = float(exp.monitoring_metrics.get("canary_baseline", exp.success_score or 0.8))
                ctrl = CanaryController(
                    baseline, fraction=self.canary_fraction,
                    min_samples=self.canary_min_samples, seed=hash(exp_id) & 0xFFFF,
                )
                self._exp_canaries[exp_id] = ctrl
            if getattr(ctrl, "done", False) or not ctrl.sample(task_id):
                continue
            verdict = ctrl.record(verified)
            self.log.append(
                task_id, EventKind.CANARY,
                {"kind": "experience", "subject": exp_id, "verdict": verdict,
                 **ctrl.snapshot()},
            )
            if verdict == "ROLLBACK":
                rolled = self.experience.record_use(exp_id, verified=False, catastrophic=True)
                self.log.append(
                    task_id, EventKind.EXPERIENCE_TRANSITION,
                    {"id": exp_id, "state": rolled.validation_state,
                     "trigger": "canary_rollback",
                     "reason": f"canary success {ctrl.snapshot()['rate']:.0%} vs baseline "
                     f"{ctrl.baseline_success:.0%}"},
                )

    def _settle_route_canary(self, task_id, contract, *, verified: bool) -> None:
        if self.route_stats is None:
            return
        from app.services.eval.canary import CanaryController

        challenger = next(
            (e.payload for e in self.log.read(task_id)
             if e.kind == EventKind.ROUTE and e.payload.get("data_driven")),
            None,
        )
        if challenger is None:
            return
        tc, model = contract.task_class, challenger["provider_id"]
        key = f"{tc}:{model}"
        ctrl = self._route_canaries.get(key)
        if ctrl is None:
            incumbent = self.route_stats.aggregate(tc, model).get("success_rate", 0.8) or 0.8
            ctrl = CanaryController(
                incumbent, fraction=self.canary_fraction,
                min_samples=self.canary_min_samples, seed=hash(key) & 0xFFFF,
            )
            self._route_canaries[key] = ctrl
        if getattr(ctrl, "done", False):
            return
        verdict = ctrl.record(verified)
        self.log.append(
            task_id, EventKind.CANARY,
            {"kind": "route", "subject": key, "verdict": verdict, **ctrl.snapshot()},
        )
        if verdict == "ROLLBACK":
            self.route_stats.freeze(tc, model, reason="canary rollback")
            self.log.append(
                task_id, EventKind.REGRESSION,
                {"kind": "route_freeze", "task_class": tc, "model": model},
            )
            # Milestone O — a data-driven challenger that rolled back sends the
            # whole class back to the static table, not just this one model.
            if self.selection is not None:
                self.selection.demote(tc, "route canary rollback",
                                      log=self.log, task_id=task_id)

    def _emit_composition(self, task_id, contract) -> None:
        from app.services.agents.composition import select_roles

        active = {"builder"}
        if self.critic is not None:
            active.add("critic")
        if self.verifier_t2 is not None:
            active.add("verifier_t2")
        if self.researcher is not None:
            active.add("researcher")
        comp = select_roles(contract, role_perf=self.role_perf)
        self.log.append(
            task_id,
            EventKind.COMPOSITION,
            {
                "active_roles": sorted(active | comp.roles),
                "reasons": comp.reasons,
                "task_class": contract.task_class,
            },
        )

    def _t2_pass(self, task_id, contract, combined_diff, t0, workspace_path):
        """Run the T2 ensemble. Returns an escalation detail string if a human
        should review, else None (T0 verdict stands)."""
        from app.services.agents.disagreement import resolve

        t2, run = self.verifier_t2.verify(
            task_id=task_id, contract=contract, diff=combined_diff,
            original_workspace=workspace_path,
        )
        self.log.append(task_id, EventKind.VERIFICATION, t2.model_dump(mode="json"))
        self.log.append(task_id, EventKind.MODEL_RUN, run)
        self._msg(
            task_id, "verifier_t2", "STATUS",
            claims=[f"T2 {t2.overall}"],
            confidence_summary=t2.residual_uncertainty[:120] or "unanimous",
        )
        if t0.overall == t2.overall:
            return None
        outcome = resolve(contract, t0, t2)
        self.log.append(
            task_id,
            EventKind.DISAGREEMENT,
            {
                "between": ["verifier_t0", "verifier_t2"],
                "detail": outcome.detail,
                "resolution": outcome.resolution,
                "conflicting_claims": outcome.conflicting_claims,
            },
        )
        if outcome.resolution == "escalate":
            self.log.append(
                task_id,
                EventKind.CLARIFICATION,
                {
                    "task_id": task_id,
                    "questions": [outcome.detail],
                    "why": "T0 / T2 verification disagreement",
                },
            )
            if t0.overall == "pass" and t2.overall != "pass":
                # a second verifier contradicting a T0-claimed success is a §8
                # catastrophic signal — roll back any experience used here
                self.flag_catastrophic(
                    task_id, f"T2 contradicted a T0-passing result: {outcome.detail}"
                )
            return outcome.detail
        return None

    def _emit_handoff(self, task_id, report) -> None:
        from app.services.agents.messages import emit_message

        findings = [f"critic: {f.claim}" for f in report.findings if f.claim] or [
            "critic rejected the change; revise it to satisfy the target test exactly"
        ]
        emit_message(
            self.log, task_id,
            sender="critic", role="critic", intent="HANDOFF",
            requested_action="revise", claims=findings,
        )

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

    def _run_ladder(self, task_id, contract, workspace_path, ladder, *, reason, tried, diff=""):
        """Advance the escalation ladder until an actionable rung. Returns
        ("replanned", new_steps) or ("ask_user", None)."""
        research_note = ""
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
            if rung.name == "critic" and self.critic is not None:
                report = self._critic_pass(task_id, contract, diff, workspace_path)
                if report.verdict == "reject" and report.findings:
                    self._emit_handoff(task_id, report)
                    return self._replan(
                        task_id, contract, workspace_path, reason, tried,
                        extra="\n".join(f"- critic: {f.claim}" for f in report.findings),
                    )
                continue  # accept/revise -> advance
            if rung.name == "research" and self.researcher is not None:
                research_note = self._do_research(task_id, contract, reason, tried)
                continue  # research informs the next re-plan
            if rung.name == "stronger_model":
                decision = self._stronger_model_route(task_id, contract)
                if decision is None:
                    continue  # no untried stronger provider -> advance to ask_user
                return self._replan(
                    task_id, contract, workspace_path, reason, tried,
                    extra=f"- escalated to a stronger model: {decision.provider_id} "
                    f"({decision.reason}); take a materially different approach",
                )
            if rung.name == "change_strategy":
                return self._replan(
                    task_id, contract, workspace_path, reason, tried, extra=research_note
                )
            if rung.name == "ask_user":
                return "ask_user", None
        return "ask_user", None

    def _replan(self, task_id, contract, workspace_path, reason, tried, *, extra=""):
        listing = self.workspace_lister(workspace_path)
        note = (
            f"\n\nNOTE: the previous plan was {reason} ({tried}). "
            "Produce a materially different plan; do not repeat the same edit."
        )
        if extra:
            note += "\nRESEARCH / CRITIQUE:\n" + extra
        new_plan, prun = self.planner.plan(contract, listing + note)
        self.log.append(task_id, EventKind.PLAN, new_plan)
        self.log.append(task_id, EventKind.MODEL_RUN, prun)
        return "replanned", list(new_plan.steps)

    def _run_research(self, task_id, contract, request_text) -> TaskResult:
        """`research_web` deliverable path (Milestone K). Runs the research
        pipeline instead of plan->build->verify and returns a cited
        `ResearchAnswer`. Verification for research is the cross-check + the
        mandatory uncertainty statement (§5), recorded as the passing
        VerificationRecord; there is no T0 oracle for an open question."""
        from app.schemas.contracts import (
            CriterionVerdict,
            Observation,
            Plan,
            PlanStep,
            VerificationRecord,
        )

        self._transition(task_id, State.PLANNING)
        step = PlanStep(
            intent="research the question and synthesise a cited answer",
            expected_artifact_delta="produce a ResearchAnswer",
            required_capability="net.fetch",
        )
        plan = Plan(task_id=task_id, steps=[step])
        self.log.append(task_id, EventKind.PLAN, plan)
        self._transition(task_id, State.EXECUTING)
        question = contract.objective or request_text
        result = self.research.run(task_id, question)

        for rnd in result.rounds:
            self.log.append(
                task_id, EventKind.RESEARCH,
                {"sub_question": rnd.sub_question, "urls": rnd.urls,
                 "n_claims": rnd.n_claims, "flags": rnd.flags},
            )
        for ev in result.graph.sources.values():
            self.log.append(task_id, EventKind.EVIDENCE, ev.model_dump(mode="json"))
        for run in result.model_runs:
            self.log.append(task_id, EventKind.MODEL_RUN, run)

        answer = result.answer
        self.log.append(task_id, EventKind.SYNTHESIS, answer.model_dump(mode="json"))
        art = self._store_artifact(
            task_id, "research_answer", answer.model_dump_json(),
            logical_key=self._logical_key("q", question),
            trust=answer.trust_level,
            meta={"sections": len(answer.sections), "citations": len(answer.citations)},
        )
        if art:
            self.log.append(task_id, EventKind.ARTIFACT, art | {"answer_id": answer.id})
        self._msg(
            task_id, "researcher", "ANSWER",
            claims=[s["statement"] for s in answer.sections[:5]],
            evidence_refs=[c["id"] for c in answer.citations[:8]],
            confidence_summary=answer.uncertainty[:200] or "none noted",
        )

        self.log.append(
            task_id, EventKind.OBSERVATION,
            Observation(task_id=task_id, step_id=step.id, exit_code=0,
                        stdout=f"{len(answer.sections)} sections, {len(answer.citations)} sources",
                        artifact_ref=answer.id).model_dump(mode="json"),
        )
        self._transition(task_id, State.VERIFYING)

        unresolved = len(answer.contested)
        crit = CriterionVerdict(
            criterion=(
                f"research: {len(result.graph.sub_questions())} sub-questions, "
                f"{len(answer.citations)} citations, {unresolved} unresolved contradiction(s); "
                "cross-check complete, uncertainty stated"
            ),
            verdict="pass",
        )
        verification = VerificationRecord(
            task_id=task_id, tier="T0", criteria=[crit], overall="pass",
            residual_uncertainty=answer.uncertainty,
        )
        self.log.append(task_id, EventKind.VERIFICATION, verification)

        self._transition(task_id, State.COMPLETED)
        return self._finish(
            task_id,
            f"research answer: {len(answer.sections)} sections, {len(answer.citations)} sources"
            + (f", {unresolved} contested" if unresolved else ""),
            state=State.COMPLETED, verified=True,
            artifact_ref=self._last_store_id(task_id) or answer.id,
            verification_ref=verification.id,
        )

    def _run_doc_analysis(self, task_id, contract, request_text) -> TaskResult:
        """`doc_analysis` deliverable path (Milestone L). Runs the KB answer path
        (retrieve -> claims-only synthesis -> cited `KBAnswer` at `doc_input`
        trust) instead of plan->build->verify."""
        from app.schemas.contracts import (
            CriterionVerdict,
            Observation,
            Plan,
            PlanStep,
            VerificationRecord,
        )
        from app.services.kb.answer import answer as kb_answer

        self._transition(task_id, State.PLANNING)
        step = PlanStep(
            intent="retrieve from the knowledge base and synthesise a cited answer",
            expected_artifact_delta="produce a KBAnswer",
            required_capability="fs.read",
        )
        self.log.append(task_id, EventKind.PLAN, Plan(task_id=task_id, steps=[step]))
        self._transition(task_id, State.EXECUTING)

        question = contract.objective or request_text
        llm = getattr(self.interpreter, "llm", None) or getattr(self.planner, "llm", None)
        ans = kb_answer(self.kb, question, llm, task_id=task_id)

        self.log.append(
            task_id, EventKind.KB,
            {"query": question, "hits": len(ans.citations),
             "flags": ans.flags, "docs": len(self.kb.documents())},
        )
        self.log.append(task_id, EventKind.SYNTHESIS, ans.model_dump(mode="json"))
        art = self._store_artifact(
            task_id, "kb_answer", ans.model_dump_json(),
            logical_key=self._logical_key("q", question), trust=ans.trust_level,
            meta={"sections": len(ans.sections), "citations": len(ans.citations)},
        )
        if art:
            self.log.append(task_id, EventKind.ARTIFACT, art | {"answer_id": ans.id})
        self._msg(
            task_id, "kb", "ANSWER",
            claims=[s["statement"] for s in ans.sections[:5]],
            evidence_refs=[c["id"] for c in ans.citations[:8]],
            confidence_summary=ans.uncertainty[:200] or "none noted",
        )
        self.log.append(
            task_id, EventKind.OBSERVATION,
            Observation(task_id=task_id, step_id=step.id, exit_code=0,
                        stdout=f"{len(ans.sections)} sections, {len(ans.citations)} sources",
                        artifact_ref=ans.id).model_dump(mode="json"),
        )
        self._transition(task_id, State.VERIFYING)
        crit = CriterionVerdict(
            criterion=(
                f"doc_analysis: {len(ans.citations)} chunks retrieved, "
                "claims-only synthesis complete, uncertainty stated"
            ),
            verdict="pass",
        )
        verification = VerificationRecord(
            task_id=task_id, tier="T0", criteria=[crit], overall="pass",
            residual_uncertainty=ans.uncertainty,
        )
        self.log.append(task_id, EventKind.VERIFICATION, verification)
        self._transition(task_id, State.COMPLETED)
        return self._finish(
            task_id,
            f"kb answer: {len(ans.sections)} sections, {len(ans.citations)} sources",
            state=State.COMPLETED, verified=True,
            artifact_ref=self._last_store_id(task_id) or ans.id,
            verification_ref=verification.id,
        )

    def _run_authoring(self, task_id, contract, request_text) -> TaskResult:
        """`authoring` deliverable path (Milestone M): outline -> grounded draft ->
        review -> render. The rendered document is the artifact; `review` issues
        are advisory (§7.1)."""
        from app.schemas.contracts import (
            CriterionVerdict,
            Observation,
            Plan,
            PlanStep,
            VerificationRecord,
        )

        self._transition(task_id, State.PLANNING)
        step = PlanStep(
            intent="outline, draft, review and render the document",
            expected_artifact_delta="produce a rendered document",
            required_capability="fs.read",
        )
        self.log.append(task_id, EventKind.PLAN, Plan(task_id=task_id, steps=[step]))
        self._transition(task_id, State.EXECUTING)

        brief = contract.objective or request_text
        mem_ctx = self._memory_context(request_text, contract.task_class)
        kind = "deck" if "slide" in brief.lower() or "deck" in brief.lower() else "report"
        result = self.authoring.run(task_id, brief, kind=kind, memory_ctx=mem_ctx)

        self.log.append(
            task_id, EventKind.AUTHORING,
            {"title": result.model.title, "kind": result.model.kind,
             "sections": len(list(result.model.walk())),
             "issues": [{"kind": i.kind, "section": i.section, "severity": i.severity}
                        for i in result.issues],
             "flags": result.flags},
        )
        self.log.append(
            task_id, EventKind.SYNTHESIS,
            {"id": result.model.id, "mime": result.rendered.mime,
             "text": result.rendered.text, "citations": result.citations,
             "issues": len(result.issues), "flags": result.flags},
        )
        art = self._store_artifact(
            task_id, "document", result.rendered.text,
            logical_key=self._logical_key("doc", result.model.title),
            trust="workspace",
            meta={"mime": result.rendered.mime, "title": result.model.title,
                  "citations": len(result.citations), "issues": len(result.issues)},
        )
        if art:
            self.log.append(task_id, EventKind.ARTIFACT, art | {"model_id": result.model.id})
        self._msg(
            task_id, "author", "ANSWER",
            claims=[f"{result.model.title}: {len(list(result.model.walk()))} sections, "
                    f"{len(result.citations)} citations"],
            confidence_summary=f"{len(result.issues)} review issue(s)"
            + ("; " + ", ".join(f for f in result.flags) if result.flags else ""),
        )
        self.log.append(
            task_id, EventKind.OBSERVATION,
            Observation(task_id=task_id, step_id=step.id, exit_code=0,
                        stdout=f"{result.rendered.mime}, {len(result.rendered.text)} chars",
                        artifact_ref=result.model.id).model_dump(mode="json"),
        )
        self._transition(task_id, State.VERIFYING)
        blocking = [i for i in result.issues if i.severity == "blocking"]
        crit = CriterionVerdict(
            criterion=(
                f"authoring: outline+draft+review complete, {len(result.issues)} issue(s) "
                f"({len(blocking)} blocking) reported"
            ),
            verdict="pass" if not blocking else "fail",
        )
        verification = VerificationRecord(
            task_id=task_id, tier="T0", criteria=[crit],
            overall="pass" if not blocking else "fail",
            residual_uncertainty="; ".join(i.detail for i in result.issues[:5]),
        )
        self.log.append(task_id, EventKind.VERIFICATION, verification)
        if blocking:
            self._transition(task_id, State.WAITING_FOR_USER)
            return self._finish(
                task_id, f"authoring: {len(blocking)} blocking review issue(s)",
                state=State.WAITING_FOR_USER,
            )
        self._transition(task_id, State.COMPLETED)
        return self._finish(
            task_id,
            f"document: {result.model.title} ({result.rendered.mime}, "
            f"{len(result.citations)} citations, {len(result.issues)} review issues)",
            state=State.COMPLETED, verified=True,
            artifact_ref=self._last_store_id(task_id) or result.model.id,
            verification_ref=verification.id,
        )

    # ------------------------------------------------------------------ #
    # Milestone T — tool-use execution
    # ------------------------------------------------------------------ #
    def _tool_task_grant(self, task_id: str, workspace_path: str):
        """One CapabilityGrant for the tool loop: the union of the operations of
        every read-only op the registry exposes, plus any token named in
        `self.tool_task_capabilities` (e.g. "shell.run"). Least privilege — a
        side-effecting op the caller did not opt into is simply never authorised,
        so the dispatcher denies it and the loop records the denial."""
        from app.schemas.contracts import CapabilityGrant
        from app.services.capability.registry import spec_for

        tokens: set[str] = set(getattr(self, "tool_task_capabilities", None) or [])
        for adapter in self.tools.all():
            for op in adapter.manifest().ops:
                if not op.side_effecting:
                    tokens.add(op.capability)
        ops: set[str] = set()
        for tok in tokens:
            spec = spec_for(tok)
            if spec is not None:
                ops |= set(spec.operations)
        grant = CapabilityGrant(
            task_id=task_id, step_id="tool-loop", token="tool.loop",
            scope_path=workspace_path, operations=sorted(ops),
            network_allowlist=list(getattr(self, "tool_task_network", None) or []),
        )
        self.log.append(task_id, EventKind.CAPABILITY_GRANT, grant)
        return grant

    def _run_tool_task(self, task_id, contract, request_text, workspace_path) -> TaskResult:
        """`ops` deliverable path (Milestone T). Runs the bounded tool-use loop
        instead of plan->build->verify: the model picks one tool op per turn and
        each call goes through the Milestone S dispatcher (== the existing Policy
        Engine + capability grant). The loop works on a workspace COPY, so a
        side-effecting op never touches the user's tree. The transcript is the
        artifact; a clean finish within the iteration cap is the passing
        VerificationRecord."""
        from app.schemas.contracts import (
            CriterionVerdict,
            Observation,
            Plan,
            PlanStep,
            VerificationRecord,
        )
        from app.services.tools.base import DispatchContext
        from app.services.tools.loop import ToolLoop

        loop = self.tool_loop() if callable(self.tool_loop) else self.tool_loop
        if not isinstance(loop, ToolLoop):
            # a bare registry/llm pair or a factory that returned something odd
            raise RuntimeError("self.tool_loop must be a ToolLoop or a zero-arg factory")

        self._transition(task_id, State.PLANNING)
        step = PlanStep(
            intent="drive tools toward the objective, one policy-checked call per turn",
            expected_artifact_delta="produce a tool-use transcript",
            required_capability="fs.read",
        )
        self.log.append(task_id, EventKind.PLAN, Plan(task_id=task_id, steps=[step]))
        self._transition(task_id, State.EXECUTING)

        objective = contract.objective or request_text
        manifest_block = self.tools.manifest_block() if self.tools is not None else "TOOLS\n(none)\n"
        ws = copy_workspace(workspace_path)
        try:
            grant = self._tool_task_grant(task_id, ws)
            ctx = DispatchContext(
                task_id=task_id, grant=grant, workspace=ws, trust="workspace",
            )
            result = loop.run(objective, ctx, manifest_block)
        finally:
            cleanup(ws)

        # a non-ALLOW decision the loop saw -> a POLICY_DECISION event (the loop
        # does no logging; this mirrors what _tool() does for a single dispatch)
        for decision in result.decisions:
            self.log.append(task_id, EventKind.POLICY_DECISION,
                            decision.model_dump(mode="json"))
        # each dispatched op -> a TOOL event (mirrors _tool()'s payload shape)
        for t in result.transcript:
            if t.get("kind") == "result":
                self.log.append(
                    task_id, EventKind.TOOL,
                    {"op": t["op"], "ok": t["ok"], "trust": t["trust"],
                     "error": (t["error"] or "")[:200], "meta": {}},
                )
        self.log.append(
            task_id, EventKind.TOOL_LOOP,
            {"objective": objective[:400], "iterations": result.iterations,
             "ok": result.ok, "done": result.done, "denials": result.denials,
             "loop_risk": result.loop_risk, "loop_flags": result.loop_flags,
             "summary": result.summary[:400], "turns": len(result.transcript)},
        )
        import json as _json

        art = self._store_artifact(
            task_id, "tool_transcript",
            _json.dumps({"objective": objective, "summary": result.summary,
                         "transcript": result.transcript}, indent=2),
            logical_key=self._logical_key("ops", objective),
            trust="tool_output",
            meta={"iterations": result.iterations, "denials": result.denials,
                  "ok": result.ok},
        )
        if art:
            self.log.append(task_id, EventKind.ARTIFACT, art)

        calls = sum(1 for t in result.transcript if t.get("kind") == "result")
        distinct = len({(t["op"], t["output_excerpt"]) for t in result.transcript
                        if t.get("kind") == "result"})
        self.log.append(
            task_id, EventKind.PROGRESS,
            {"phase": "tool_loop", "turns": len(result.transcript), "ok_calls": calls,
             "repeats": max(0, calls - distinct), "loop_flags": result.loop_flags,
             "classification": "LOOP_RISK" if result.loop_risk else
             ("done" if result.done else "incomplete")},
        )
        self.log.append(
            task_id, EventKind.OBSERVATION,
            Observation(task_id=task_id, step_id=step.id,
                        exit_code=0 if result.ok else 1,
                        stdout=f"{calls} tool call(s), {result.iterations} iteration(s), "
                               f"{result.denials} denial(s)",
                        artifact_ref=self._last_store_id(task_id) or "",
                        error="" if result.ok else result.summary).model_dump(mode="json"),
        )

        if result.loop_risk:
            # a repeating, no-progress loop is an escalation, not a silent failure
            # (§1) — mirror the _execute StalledEscalation path.
            self.log.append(
                task_id, EventKind.CLARIFICATION,
                ClarificationRequest(
                    task_id=task_id,
                    questions=[
                        "The tool loop is repeating without progress "
                        f"({', '.join(result.loop_flags)}). How should it proceed?"
                    ],
                    why="tool loop is looping without progress",
                ),
            )
            self._transition(task_id, State.WAITING_FOR_USER)
            return self._finish(
                task_id,
                f"tool loop looping ({', '.join(result.loop_flags)}) after "
                f"{result.iterations} iteration(s)",
                state=State.WAITING_FOR_USER,
                artifact_ref=self._last_store_id(task_id) or None,
            )

        if not result.ok:
            self._transition(task_id, State.FAILED)
            return self._finish(
                task_id,
                f"tool task did not finish cleanly: {result.summary} "
                f"({result.iterations} iteration(s), {result.denials} denial(s))",
                state=State.FAILED,
                artifact_ref=self._last_store_id(task_id) or None,
            )

        self._transition(task_id, State.VERIFYING)
        crit = CriterionVerdict(
            criterion=(
                f"tool task: loop finished in {result.iterations} iteration(s) within the cap, "
                f"all {calls} op(s) dispatched through the Policy Engine, "
                f"{result.denials} denial(s) surfaced as transcript turns"
            ),
            verdict="pass",
        )
        verification = VerificationRecord(
            task_id=task_id, tier="T0", criteria=[crit], overall="pass",
            residual_uncertainty=(
                "" if not result.denials
                else f"{result.denials} tool call(s) were policy-denied; the objective "
                     "may be only partially met"
            ),
        )
        self.log.append(task_id, EventKind.VERIFICATION, verification)
        self._transition(task_id, State.COMPLETED)
        return self._finish(
            task_id,
            f"tool task: {calls} call(s) over {result.iterations} iteration(s)"
            + (f", {result.denials} denied" if result.denials else "")
            + f" — {result.summary}",
            state=State.COMPLETED, verified=True,
            artifact_ref=self._last_store_id(task_id) or None,
            verification_ref=verification.id,
        )

    def _do_research(self, task_id, contract, reason, tried) -> str:
        from app.services.agents.messages import emit_message

        question = f"How to resolve: {contract.objective} (task {reason}: {tried})"
        evidence, claims, run = self.researcher.research(task_id, question)
        self.log.append(task_id, EventKind.MODEL_RUN, run)
        for ev in evidence:
            self.log.append(task_id, EventKind.EVIDENCE, ev.model_dump(mode="json"))
        emit_message(
            self.log, task_id,
            sender="researcher", role="researcher", intent="EVIDENCE",
            claims=[c.text for c in claims],
            evidence_refs=[e.id for e in evidence],
        )
        return "\n".join(f"- {c.text}" for c in claims[:5])

    # ------------------------------------------------------------------ #
    def _snap(self, task_id: str) -> TaskSnapshot:
        return project_task(self.log.read(task_id))

    def _step_id_for_action(self, task_id: str, action_id: str) -> str:
        for e in self.log.read(task_id):
            if e.kind == EventKind.ACTION_PROPOSAL and e.payload.get("action_id") == action_id:
                return e.payload.get("step_id", "")
        return ""

    _CHECKPOINT_STATES = {State.EXECUTING, State.VERIFYING, State.STALLED, State.RECOVERING}

    def _transition(self, task_id: str, target: State) -> None:
        snap = self._snap(task_id)
        ok, reason = transition_ok(snap.state, target, snap)
        if not ok:
            raise TransitionError(f"{snap.state} -> {target}: {reason}")
        self.log.append(task_id, EventKind.STATE, {"state": target})
        if target in self._CHECKPOINT_STATES:
            self.log.append(
                task_id,
                EventKind.CHECKPOINT,
                build_checkpoint(self.log.read(task_id)).model_dump(mode="json"),
            )

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
