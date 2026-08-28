"""Canonical records for the slice.

Ports the three records that already existed in the prior foundation
(`TaskContract`, `ActionProposal`, `AgentMessage`) and adds the records named in
DESIGN_TIGHTENING.md sections 1 and 3 that the end-to-end flow needs:
`OriginalRequest`, `Plan`/`PlanStep`, `Observation`, `ArtifactVersion`,
`VerificationRecord`, `ModelRunRecord`, `TaskResult`.

`validate_contract` implements the gate for leaving `INTERPRETING`
(DESIGN_TIGHTENING.md section 1): objective + >=1 success criterion + a
`required_evidence` entry naming a runnable pytest T0 target.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskClass = Literal[
    "qa_explain",
    "code_edit_local",
    "code_edit_broad",
    "debug",
    "research_web",
    "doc_analysis",
    "authoring",
    "planning_arch",
    "ops",
]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_ts() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# capture / interpret
# --------------------------------------------------------------------------- #
class OriginalRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("req"))
    text: str
    workspace_path: str
    ts: float = Field(default_factory=now_ts)
    attachments: list[str] = Field(default_factory=list)


class TaskContract(BaseModel):
    task_id: str
    original_request: str  # frozen copy of OriginalRequest.text
    objective: str
    task_class: TaskClass = "code_edit_local"
    deliverables: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ambiguity: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    workspace_id: str = ""
    resource_sensitivity: str = "normal"
    # DESIGN_TIGHTENING §11.1 — filled by the Interpreter per task_class, user-overridable.
    # model_cost_usd is 0/unmetered on the subscription (Agent SDK) path.
    budget: dict[str, float] = Field(default_factory=dict)


class ClarificationRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clr"))
    task_id: str
    questions: list[str] = Field(default_factory=list)
    why: str = ""
    options: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# plan
# --------------------------------------------------------------------------- #
class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: new_id("step"))
    intent: str
    expected_artifact_delta: str
    required_capability: str


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    task_id: str
    steps: list[PlanStep] = Field(default_factory=list)
    supersedes: str | None = None


# --------------------------------------------------------------------------- #
# preflight / execute
# --------------------------------------------------------------------------- #
TrustLevel = Literal["user", "workspace", "tool_output", "retrieved_web", "doc_input"]
"""DESIGN_TIGHTENING.md section 12 / 14.3. `user` and `workspace` authorise; the
rest inform only. `is_tainted` == not authorising."""


class ActionProposal(BaseModel):
    action_id: str = Field(default_factory=lambda: new_id("act"))
    task_id: str
    step_id: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    required_capability: str
    workspace_scope: str
    expected_effect: str
    idempotency_key: str
    # structural taint: the trust of the inputs that produced this proposal
    trust: TrustLevel = "user"
    taint_sources: list[str] = Field(default_factory=list)

    @property
    def is_tainted(self) -> bool:
        return self.trust not in ("user", "workspace")


class PolicyDecision(BaseModel):
    action_id: str
    decision: Literal["ALLOW", "DENY", "REQUIRE_APPROVAL", "REQUIRE_VERIFICATION", "ESCALATE"]
    reason: str = ""
    rule: str = ""  # which policy rule produced this decision


class CapabilityGrant(BaseModel):
    id: str = Field(default_factory=lambda: new_id("cap"))
    task_id: str
    step_id: str = ""
    token: str = ""  # the capability token this grant realises
    scope_path: str  # filesystem root the grant is confined to
    operations: list[str] = Field(default_factory=list)
    network_allowlist: list[str] = Field(default_factory=list)
    issued_at: float = Field(default_factory=now_ts)
    ttl_s: float = 3600.0

    def is_expired(self, now: float | None = None) -> bool:
        ref = now if now is not None else now_ts()
        return ref - self.issued_at > self.ttl_s

    def allows_operation(self, operation: str) -> bool:
        return operation in self.operations

    def covers_path(self, target: str) -> bool:
        import os
        from pathlib import Path

        try:
            root = Path(self.scope_path).resolve()
            candidate = Path(target)
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = Path(os.path.normpath(candidate)).resolve()
        except (OSError, RuntimeError, ValueError):
            return False
        return resolved == root or root in resolved.parents

    def allows_host(self, host: str) -> bool:
        h = host.strip().lower()
        return any(
            h == allowed.lower() or h.endswith("." + allowed.lower())
            for allowed in self.network_allowlist
        )


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("apr"))
    task_id: str
    action_id: str
    operation: str
    reason: str
    summary: str = ""


class ApprovalDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("apd"))
    task_id: str
    action_id: str
    approved: bool
    by: str = "user"
    note: str = ""


class ArtifactVersion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    task_id: str
    changed_paths: list[str] = Field(default_factory=list)
    diff: str = ""
    bytes: int = 0


class Observation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obs"))
    task_id: str
    step_id: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    artifact_ref: str | None = None
    error: str | None = None


# --------------------------------------------------------------------------- #
# verify / settle
# --------------------------------------------------------------------------- #
class CriterionVerdict(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crit"))
    criterion: str
    verdict: Literal["pass", "fail", "unknown"] = "unknown"
    evidence_ref: str | None = None


class VerificationRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ver"))
    task_id: str
    tier: Literal["T0", "T1", "T2", "T3"] = "T0"
    criteria: list[CriterionVerdict] = Field(default_factory=list)
    overall: Literal["pass", "fail"] = "fail"
    discriminating_tests_run: list[str] = Field(default_factory=list)
    residual_uncertainty: str = ""


class ModelRunRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    task_id: str
    role: str  # interpreter | planner | builder
    provider: str = ""
    model: str = ""
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    # link to a VerificationRecord.id once the run is "scored" (DESIGN_TIGHTENING.md section 7)
    verification_result: str | None = None
    failure_mode: str | None = None


class TaskResult(BaseModel):
    task_id: str
    state: str
    verified: bool = False
    artifact_ref: str | None = None
    verification_ref: str | None = None
    summary: str = ""


ProgressClass = Literal[
    "HEALTHY_PROGRESS",
    "SLOW_PROGRESS",
    "STALLED",
    "LOOP_RISK",
    "RESOURCE_LIMITED",
]


class ProgressEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prg"))
    task_id: str
    step_index: int
    classification: ProgressClass = "HEALTHY_PROGRESS"
    signals: list[str] = Field(default_factory=list)  # hard-progress signals that fired
    hard_progress: bool = False
    no_progress_run: int = 0
    detail: str = ""


AgentIntent = Literal[
    "QUESTION", "ANSWER", "PROPOSAL", "HANDOFF",
    "EVIDENCE", "CRITIQUE", "STATUS", "ESCALATION",
]


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    sender: str
    role: str
    task_id: str
    intent: AgentIntent
    claims: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    requested_action: str | None = None
    confidence_summary: str | None = None


class CriticFinding(BaseModel):
    severity: Literal["blocking", "major", "minor"] = "minor"
    claim: str
    evidence_ref: str | None = None


class CriticReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crit"))
    task_id: str
    verdict: Literal["accept", "revise", "reject"] = "accept"
    findings: list[CriticFinding] = Field(default_factory=list)
    summary: str = ""


class RolePerformance(BaseModel):
    role: str
    task_class: str
    samples: int = 0
    baseline_success: float = 0.0
    with_role_success: float = 0.0
    defects_caught: int = 0
    rework_delta: float = 0.0


TrustLevelEv = Literal["user", "workspace", "tool_output", "retrieved_web", "doc_input"]


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clm"))
    task_id: str
    text: str
    source_refs: list[str] = Field(default_factory=list)  # EvidenceRecord ids
    trust_level: TrustLevelEv = "retrieved_web"


class EvidenceRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ev"))
    task_id: str
    kind: str = "web_page"  # web_page | doc | tool_output | measurement
    source: str = ""  # URL / path
    trust_level: TrustLevelEv = "retrieved_web"
    content_excerpt: str = ""
    ts: float = Field(default_factory=now_ts)


MemoryTier = Literal["working", "project", "experience", "system"]
ExperienceState = Literal[
    "OBSERVED", "CANDIDATE", "VALIDATED", "PROMOTED", "MONITORED", "STALE", "QUARANTINED"
]


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mem"))
    task_id: str = ""  # "" for project/system-scoped entries
    tier: MemoryTier
    kind: str  # decision | constraint | open_question | artifact_index | note | role_perf
    content: str
    scope: str = "global"  # a task_class, a path glob, or "global"
    trust: TrustLevelEv = "workspace"
    version: int = 1
    ts: float = Field(default_factory=now_ts)
    superseded_by: str | None = None


class ExperienceRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exp"))
    signature: str  # situation signature (see experience/signature.py)
    strategy: str
    actions: list[str] = Field(default_factory=list)
    outcome: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    success_score: float = 0.0
    validation_state: ExperienceState = "OBSERVED"
    scope: str = "global"
    version: int = 1
    promotion_history: list[str] = Field(default_factory=list)
    monitoring_metrics: dict[str, float] = Field(default_factory=dict)
    shadow_replay_log: list[dict[str, Any]] = Field(default_factory=list)
    guardrail_result: float | None = None
    ts: float = Field(default_factory=now_ts)


# --------------------------------------------------------------------------- #
# routing + hardware (Milestone G; DESIGN_TIGHTENING §7)
# --------------------------------------------------------------------------- #
HardwareMode = Literal[
    "NORMAL", "EFFICIENT", "CONSERVATION", "PROTECTIVE", "EMERGENCY"
]


class ProviderSpec(BaseModel):
    id: str  # stable routing key, e.g. "agent_sdk" / "local-coder"
    provider: str  # "agent_sdk" | "anthropic" | "local" | "scripted"
    model: str = ""
    local: bool = False
    context_window: int = 200_000
    quality_prior: float = 0.5  # 0..1, pre-data estimate
    latency_prior_s: float = 8.0
    cost_prior_usd: float = 0.0  # per task; 0 for the subscription path
    resource_cost: float = 0.0  # 0..1 local machine load
    privacy_score: float = 0.5  # 0..1, higher = more private (local == 1)
    available: bool = True
    notes: str = ""


class RouteDecision(BaseModel):
    id: str = Field(default_factory=lambda: new_id("route"))
    task_id: str = ""
    role: str = ""
    task_class: str = ""
    provider_id: str = ""
    reason: str = ""
    escalated: bool = False
    data_driven: bool = False
    explored: bool = False
    hardware_mode: HardwareMode = "NORMAL"
    candidates_considered: list[str] = Field(default_factory=list)
    ts: float = Field(default_factory=now_ts)


class HardwareSnapshot(BaseModel):
    gpu_temp_c: float | None = None
    gpu_percent: float = 0.0
    ram_percent: float = 0.0
    vram_percent: float = 0.0
    source: str = "static"  # "static" until real telemetry lands
    ts: float = Field(default_factory=now_ts)


# --------------------------------------------------------------------------- #
# optimization: guardrail / regression / offline eval / canary (Milestone I)
# DESIGN_TIGHTENING §8, §11.2
# --------------------------------------------------------------------------- #
CanaryVerdict = Literal["PROMOTE", "HOLD", "ROLLBACK"]


class SuiteResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("suite"))
    n: int = 0
    passed: int = 0
    failures: list[str] = Field(default_factory=list)  # task ids that failed
    ts: float = Field(default_factory=now_ts)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.n if self.n else 0.0


class RegressionResult(BaseModel):
    passed: bool = False
    drop_pp: float = 0.0                       # baseline pass-rate minus candidate, in points
    newly_failing: list[str] = Field(default_factory=list)
    recovered: list[str] = Field(default_factory=list)
    baseline_rate: float = 0.0
    candidate_rate: float = 0.0
    why: str = ""


class EvalReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("eval"))
    subject: str = ""                          # experience id / model id / role name
    kind: str = "experience"                   # experience | model | role
    heldout_n: int = 0
    with_success: float = 0.0
    without_success: float = 0.0
    delta: float = 0.0
    guardrail: RegressionResult | None = None
    decision: str = "hold"                     # promote | hold
    needs_human: bool = False
    why: str = ""
    ts: float = Field(default_factory=now_ts)


class Metrics(BaseModel):
    success_rate_by_class: dict[str, float] = Field(default_factory=dict)
    rework_rate: float = 0.0
    verify_tier_distribution: dict[str, int] = Field(default_factory=dict)
    escalation_frequency: float = 0.0
    budget_exhaustion_rate: float = 0.0
    quarantine_events: int = 0
    tasks: int = 0


# --------------------------------------------------------------------------- #
# research pipeline (Milestone K; DESIGN_TIGHTENING §10.2 domain 2, §12)
# --------------------------------------------------------------------------- #
class ContradictionRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("contra"))
    claim_a: str = ""            # Claim id
    claim_b: str = ""           # Claim id
    subject: str = ""
    resolved: bool = False
    resolution: str = ""        # which side won + why, or "" while unresolved


class ResearchAnswer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ans"))
    task_id: str = ""
    question: str = ""
    sections: list[dict[str, Any]] = Field(default_factory=list)   # {statement, citation_ids[]}
    contested: list[dict[str, Any]] = Field(default_factory=list)  # {subject, a, b, a_cites, b_cites}
    citations: list[dict[str, Any]] = Field(default_factory=list)  # {id, source, host}
    uncertainty: str = ""
    flags: list[str] = Field(default_factory=list)                 # injection-scan / coverage flags
    trust_level: TrustLevelEv = "retrieved_web"
    ts: float = Field(default_factory=now_ts)


# --------------------------------------------------------------------------- #
# repo intelligence (Milestone J; DESIGN_TIGHTENING §10.2)
# --------------------------------------------------------------------------- #
class GitStatus(BaseModel):
    branch: str = ""
    head_sha: str = ""
    clean: bool = True
    staged: list[str] = Field(default_factory=list)
    unstaged: list[str] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)


class ImpactReport(BaseModel):
    id: str = Field(default_factory=lambda: new_id("impact"))
    changed_paths: list[str] = Field(default_factory=list)
    changed_modules: list[str] = Field(default_factory=list)
    dependent_modules: list[str] = Field(default_factory=list)   # transitive importers
    touched_symbols: list[str] = Field(default_factory=list)
    dependent_symbols: list[str] = Field(default_factory=list)   # approximate (textual)
    tests_affected: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)          # public-api | risk-path | symbol-removed | signature-changed | wide-change
    approximate: bool = False
    ts: float = Field(default_factory=now_ts)


class BreadthAdvice(BaseModel):
    level: Literal["local", "broad"] = "local"
    why: str = ""
    escalate_review: bool = False


# --------------------------------------------------------------------------- #
# contract gate (leave INTERPRETING)
# --------------------------------------------------------------------------- #
_T0_PYTEST_RE = re.compile(r"pytest\s+\S+", re.IGNORECASE)

# classes whose deliverable is a code diff — these need a runnable T0 oracle.
# Other classes (research_web, doc_analysis, authoring, planning_arch, qa_explain,
# ops) verify differently (§5 ladder / §6 deliverable) and only need *some*
# stated evidence.
_T0_REQUIRED_CLASSES = frozenset({"code_edit_local", "code_edit_broad", "debug"})


def validate_contract(contract: TaskContract) -> list[str]:
    """Return a list of problems. Empty list means the contract passes the
    INTERPRETING gate. A non-empty list is a reason to enter WAITING_FOR_USER."""
    problems: list[str] = []
    if not contract.objective.strip():
        problems.append("objective is empty")
    if not contract.success_criteria:
        problems.append("no success_criteria")
    if not contract.required_evidence:
        problems.append("no required_evidence")
    elif contract.task_class in _T0_REQUIRED_CLASSES:
        has_t0 = any(
            ("t0" in e.lower()) and _T0_PYTEST_RE.search(e) for e in contract.required_evidence
        )
        if not has_t0:
            problems.append(
                "required_evidence names no runnable pytest T0 target "
                "(expected an entry like 'T0: pytest tests/test_x.py::test_y passes')"
            )
    return problems
