"""Fault model (MILESTONE_Q_PLAN.md §2)."""

from __future__ import annotations

from dataclasses import dataclass, field

FAULT_KINDS = frozenset({
    "llm_refusal", "llm_timeout", "llm_garbage",
    "sandbox_unavailable", "sandbox_timeout", "sandbox_error", "sandbox_crash",
    "partial_diff", "empty_diff", "builder_exception",
    "egress_flap", "policy_exception", "interrupt",
})


@dataclass
class Fault:
    kind: str
    on_call: int = 1        # fire on the Nth matching call (1-based)
    sticky: bool = False    # keep firing on every call at/after on_call
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind {self.kind!r}")


@dataclass
class FaultPlan:
    faults: list[Fault] = field(default_factory=list)
    _counts: dict[str, int] = field(default_factory=dict)

    @classmethod
    def of(cls, *faults: Fault) -> "FaultPlan":
        return cls(list(faults))

    def should_fire(self, kind: str) -> Fault | None:
        """Advance the call counter for `kind` and return the Fault to raise, or None."""
        n = self._counts.get(kind, 0) + 1
        self._counts[kind] = n
        for f in self.faults:
            if f.kind != kind:
                continue
            if n == f.on_call or (f.sticky and n >= f.on_call):
                return f
        return None
