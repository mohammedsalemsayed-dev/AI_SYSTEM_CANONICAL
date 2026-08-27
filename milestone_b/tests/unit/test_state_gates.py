"""Acceptance (Unit): the state-transition gate predicates from
DESIGN_TIGHTENING.md section 1 — a transition needs both an allowed edge and a
satisfied gate."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.state import State, gate_reason, transition_ok
from app.schemas.contracts import (
    Observation,
    Plan,
    PlanStep,
    TaskContract,
    VerificationRecord,
)


@dataclass
class FakeSnapshot:
    """Duck-typed stand-in for TaskSnapshot, built directly for unit isolation."""

    state: State = State.CREATED
    contract: TaskContract | None = None
    plan: Plan | None = None
    observations: list = field(default_factory=list)
    verification: VerificationRecord | None = None

    @property
    def contract_problems(self) -> list[str]:
        from app.schemas.contracts import validate_contract

        if self.contract is None:
            return ["no contract"]
        return validate_contract(self.contract)


def _valid_contract(**overrides) -> TaskContract:
    base = dict(
        task_id="t1",
        original_request="r",
        objective="make tests/test_x.py::test_y pass",
        success_criteria=["test_y passes"],
        required_evidence=["T0: pytest tests/test_x.py::test_y passes"],
    )
    base.update(overrides)
    return TaskContract(**base)


def _good_plan() -> Plan:
    return Plan(
        task_id="t1",
        steps=[
            PlanStep(
                intent="edit",
                expected_artifact_delta="patch src/x.py",
                required_capability="fs.write",
            )
        ],
    )


# --- allowed-edge check ---------------------------------------------------- #
def test_disallowed_edge_is_rejected() -> None:
    ok, reason = transition_ok(State.CREATED, State.EXECUTING, FakeSnapshot())
    assert not ok
    assert "not an allowed transition" in reason


def test_allowed_edge_with_trivial_gate() -> None:
    ok, _ = transition_ok(State.CREATED, State.INTERPRETING, FakeSnapshot())
    assert ok


# --- PLANNING gate ------------------------------------------------------- #
def test_planning_gate_needs_contract() -> None:
    ok, reason = gate_reason(State.PLANNING, FakeSnapshot())
    assert not ok and "no contract" in reason


def test_planning_gate_rejects_invalid_contract() -> None:
    snap = FakeSnapshot(contract=_valid_contract(required_evidence=["just run it"]))
    ok, reason = gate_reason(State.PLANNING, snap)
    assert not ok and "contract invalid" in reason


def test_planning_gate_rejects_open_ambiguity() -> None:
    snap = FakeSnapshot(contract=_valid_contract(ambiguity=["which module?"]))
    ok, reason = gate_reason(State.PLANNING, snap)
    assert not ok and "ambiguity" in reason


def test_planning_gate_passes_for_valid_contract() -> None:
    ok, reason = gate_reason(State.PLANNING, FakeSnapshot(contract=_valid_contract()))
    assert ok and reason == ""


# --- WAITING_FOR_USER gate --------------------------------------------- #
def test_waiting_gate_requires_a_reason_to_ask() -> None:
    ok, reason = gate_reason(State.WAITING_FOR_USER, FakeSnapshot(contract=_valid_contract()))
    assert not ok and "nothing to ask" in reason


def test_waiting_gate_opens_on_ambiguity() -> None:
    snap = FakeSnapshot(contract=_valid_contract(ambiguity=["which framework?"]))
    ok, _ = gate_reason(State.WAITING_FOR_USER, snap)
    assert ok


def test_waiting_gate_opens_on_contract_defect() -> None:
    snap = FakeSnapshot(contract=_valid_contract(success_criteria=[]))
    ok, _ = gate_reason(State.WAITING_FOR_USER, snap)
    assert ok


# --- EXECUTING gate ---------------------------------------------------- #
def test_executing_gate_needs_plan_steps() -> None:
    ok, reason = gate_reason(State.EXECUTING, FakeSnapshot(plan=Plan(task_id="t1", steps=[])))
    assert not ok and "no plan steps" in reason


def test_executing_gate_rejects_step_missing_capability() -> None:
    bad = Plan(
        task_id="t1",
        steps=[PlanStep(intent="x", expected_artifact_delta="y", required_capability="")],
    )
    ok, reason = gate_reason(State.EXECUTING, FakeSnapshot(plan=bad))
    assert not ok and "missing capability" in reason


def test_executing_gate_passes_for_good_plan() -> None:
    ok, _ = gate_reason(State.EXECUTING, FakeSnapshot(plan=_good_plan()))
    assert ok


# --- VERIFYING gate -------------------------------------------------- #
def test_verifying_gate_needs_an_observation() -> None:
    ok, reason = gate_reason(State.VERIFYING, FakeSnapshot())
    assert not ok and "no observation" in reason


def test_verifying_gate_passes_with_observation() -> None:
    snap = FakeSnapshot(observations=[Observation(task_id="t1", step_id="s1")])
    ok, _ = gate_reason(State.VERIFYING, snap)
    assert ok


# --- COMPLETED gate ------------------------------------------------ #
def test_completed_gate_needs_verification() -> None:
    ok, reason = gate_reason(State.COMPLETED, FakeSnapshot())
    assert not ok and "no verification" in reason


def test_completed_gate_rejects_failed_verification() -> None:
    snap = FakeSnapshot(verification=VerificationRecord(task_id="t1", overall="fail"))
    ok, reason = gate_reason(State.COMPLETED, snap)
    assert not ok and "did not pass" in reason


def test_completed_gate_passes_on_verification_pass() -> None:
    snap = FakeSnapshot(verification=VerificationRecord(task_id="t1", overall="pass"))
    ok, _ = gate_reason(State.COMPLETED, snap)
    assert ok


def test_full_transition_check_combines_edge_and_gate() -> None:
    # edge VERIFYING -> COMPLETED is allowed, but the gate fails without a pass
    snap = FakeSnapshot(
        state=State.VERIFYING,
        verification=VerificationRecord(task_id="t1", overall="fail"),
    )
    ok, reason = transition_ok(State.VERIFYING, State.COMPLETED, snap)
    assert not ok and "did not pass" in reason
