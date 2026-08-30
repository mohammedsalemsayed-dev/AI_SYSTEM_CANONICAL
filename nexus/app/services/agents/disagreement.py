"""Disagreement resolution (END_TO_END_ARCHITECTURE, MILESTONE_E_PLAN §2).

Five steps: (1) name the conflicting claims, (2) run a discriminating test,
(3) independent review [stub], (4) synthesise with uncertainty, (5) escalate to
the user if the unresolved choice is materially consequential.

In the slice the discriminating test IS the deterministic T0 — so step 2 is
always available and T0 wins. This module decides whether to also *escalate*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.contracts import TaskContract, VerificationRecord


@dataclass
class DisagreementOutcome:
    resolution: str  # "t0_authoritative" | "escalate"
    detail: str
    conflicting_claims: list[str] = field(default_factory=list)


def resolve(
    contract: TaskContract,
    t0: VerificationRecord,
    t2: VerificationRecord,
) -> DisagreementOutcome:
    claims = _conflicting_claims(t0, t2)

    # step 2: the discriminating deterministic test (T0) is authoritative
    if t0.overall == t2.overall:
        return DisagreementOutcome(
            resolution="t0_authoritative",
            detail="T0 and T2 agree",
            conflicting_claims=claims,
        )

    # T0 and T2 disagree. Step 5: escalate only when it is materially consequential.
    consequential = contract.risk_level in ("medium", "high") or any(
        _risky(p) for p in _paths(contract)
    )
    if t0.overall == "pass" and t2.overall == "fail" and consequential:
        return DisagreementOutcome(
            resolution="escalate",
            detail=(
                "T0 passes but the independent T2 verifier flags a failure on a "
                f"{contract.risk_level}-risk task; a human should review"
            ),
            conflicting_claims=claims,
        )

    # otherwise synthesise with uncertainty: T0 stands, the T2 concern is logged
    return DisagreementOutcome(
        resolution="t0_authoritative",
        detail=f"T0={t0.overall}, T2={t2.overall}; T0 (deterministic) stands, T2 concern noted",
        conflicting_claims=claims,
    )


def _conflicting_claims(a: VerificationRecord, b: VerificationRecord) -> list[str]:
    out = [f"T0 overall={a.overall}", f"T2 overall={b.overall}"]
    for c in b.criteria:
        if c.verdict == "fail":
            out.append(f"T2 fails criterion: {c.criterion}")
    return out


_RISKY_MARKERS = ("auth", "secret", "migration", "payment", "billing", ".pem", ".key")


def _paths(contract: TaskContract) -> list[str]:
    return list(contract.deliverables) + list(contract.constraints)


def _risky(text: str) -> bool:
    t = text.lower()
    return any(m in t for m in _RISKY_MARKERS)
