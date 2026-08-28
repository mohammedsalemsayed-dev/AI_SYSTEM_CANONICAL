"""Static routing table + escalation triggers (DESIGN_TIGHTENING §7.1).

The bootstrap policy, used until a `(task_class, model)` pair has >= 20 verified
runs (see `stats.py`). `prefer` is an ordered list of provider ids; the router
takes the first that is available. `escalation_reason` encodes the "escalate to
cloud when ..." column as predicates over the live task state.
"""

from __future__ import annotations

from dataclasses import dataclass

# a plan touching more modules than this (or any risk-glob path) is "broad"
BROAD_MODULE_THRESHOLD = 3


@dataclass(frozen=True)
class RoutePolicy:
    task_class: str
    prefer: tuple[str, ...]           # ordered provider-id preference
    cloud_review_plan: bool = False   # the plan gets a cloud review pass regardless
    always_cloud: bool = False        # this class *is* the "second opinion" case
    local_window: int = 16_384        # context size above which local can't hold it
    notes: str = ""


STATIC_TABLE: dict[str, RoutePolicy] = {
    "qa_explain": RoutePolicy(
        "qa_explain", ("local-small", "agent_sdk"), local_window=8_192,
        notes="local-small; escalate on user ask or context over the local window",
    ),
    "code_edit_local": RoutePolicy(
        "code_edit_local", ("local-coder", "agent_sdk"),
        notes="local-coder; escalate after 2 failed verify cycles",
    ),
    "code_edit_broad": RoutePolicy(
        "code_edit_broad", ("local-coder", "agent_sdk"), cloud_review_plan=True,
        notes="local-coder + cloud review of the plan; escalate on >N modules or risk paths",
    ),
    "debug": RoutePolicy(
        "debug", ("local-coder", "agent_sdk"),
        notes="local-coder; escalate after 2 failed hypotheses with no new evidence",
    ),
    "research_web": RoutePolicy(
        "research_web", ("local-reasoner", "agent_sdk"), local_window=32_768,
        notes="local-reasoner synthesis; escalate on an unresolved contradiction",
    ),
    "doc_analysis": RoutePolicy(
        "doc_analysis", ("local-reasoner", "agent_sdk"), local_window=32_768,
        notes="local-reasoner; escalate when the document exceeds the local window",
    ),
    "authoring": RoutePolicy(
        "authoring", ("local-reasoner", "agent_sdk"), cloud_review_plan=True,
        notes="local draft + cloud review; escalate fully when marked high-stakes",
    ),
    "planning_arch": RoutePolicy(
        "planning_arch", ("agent_sdk",), always_cloud=True,
        notes="cloud-frontier by design — this is the second-opinion case",
    ),
    "ops": RoutePolicy(
        "ops", ("local-small", "agent_sdk"),
        notes="local-small drives deterministic tools; no escalation",
    ),
}

# a safe default for an unknown / not-yet-classified task
FALLBACK_POLICY = RoutePolicy("_fallback", ("agent_sdk",))


def policy_for(task_class: str) -> RoutePolicy:
    return STATIC_TABLE.get(task_class, FALLBACK_POLICY)


def escalation_reason(
    task_class: str,
    *,
    attempt: int = 0,
    context_tokens: int = 0,
    risk_level: str = "low",
    modules_touched: int = 0,
    contradiction_unresolved: bool = False,
    user_requested_cloud: bool = False,
    high_stakes: bool = False,
) -> str | None:
    """Return a reason string if this task should be pushed to a cloud model now,
    else None. `attempt` is the count of failed verify/hypothesis cycles so far."""
    pol = policy_for(task_class)
    if pol.always_cloud:
        return "class routes to cloud by design"
    if user_requested_cloud:
        return "user asked for a cloud model"
    if context_tokens > pol.local_window:
        return f"context {context_tokens} tokens exceeds the local window ({pol.local_window})"

    if task_class in ("code_edit_local", "debug") and attempt >= 2:
        return f"{attempt} failed cycles with no new evidence"
    if task_class == "code_edit_broad":
        if modules_touched > BROAD_MODULE_THRESHOLD:
            return f"plan touches {modules_touched} modules (> {BROAD_MODULE_THRESHOLD})"
        if risk_level in ("medium", "high"):
            return f"plan touches security-relevant paths (risk={risk_level})"
    if task_class == "research_web" and contradiction_unresolved:
        return "contradiction unresolved after cross-check"
    if task_class == "authoring" and high_stakes:
        return "user marked the deliverable high-stakes"
    return None
