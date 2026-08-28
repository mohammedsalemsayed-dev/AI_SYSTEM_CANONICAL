"""Read models (MILESTONE_H_PLAN.md §2, DESIGN_TIGHTENING §11.2).

Pure folds of the append-only event log into the views the shell renders. Each
function takes an `EventLog` (and, where scoped, a task-id list) and returns
JSON-able dicts. No state, no wall-clock dependence beyond event `ts`. If a view
and the log disagree, the log wins.
"""

from __future__ import annotations

from typing import Any

from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from app.services.eval.metrics import rebuild_metrics

_PAGE = 200

# roles that speak on the AGENT_MESSAGE channel
_ROLES = (
    "interpreter", "planner", "builder", "verifier", "verifier_t2",
    "critic", "researcher", "experience",
)

# one-line headline per event kind; anything unmapped shows as a generic row
_HEADLINES = {
    EventKind.REQUEST: "request received",
    EventKind.CONTRACT: "contract compiled",
    EventKind.CLARIFICATION: "waiting on the user",
    EventKind.PLAN: "plan produced",
    EventKind.ACTION_PROPOSAL: "action proposed",
    EventKind.POLICY_DECISION: "policy decision",
    EventKind.CAPABILITY_GRANT: "capability granted",
    EventKind.CAPABILITY_DENY: "capability denied",
    EventKind.APPROVAL_REQUEST: "approval requested",
    EventKind.APPROVAL_DECISION: "approval recorded",
    EventKind.EGRESS_BLOCKED: "egress blocked",
    EventKind.TAINT_BLOCKED: "tainted action blocked",
    EventKind.OBSERVATION: "observation",
    EventKind.ARTIFACT: "artifact written",
    EventKind.VERIFICATION: "verification",
    EventKind.MODEL_RUN: "model run",
    EventKind.PROGRESS: "progress measured",
    EventKind.CHECKPOINT: "checkpoint",
    EventKind.RECONCILE: "reconciliation",
    EventKind.BUDGET: "budget",
    EventKind.ESCALATION: "escalation ladder",
    EventKind.AGENT_MESSAGE: "agent message",
    EventKind.CRITIC: "critic report",
    EventKind.DISAGREEMENT: "disagreement",
    EventKind.EVIDENCE: "evidence recorded",
    EventKind.COMPOSITION: "role composition",
    EventKind.MEMORY: "memory",
    EventKind.EXPERIENCE: "experience captured",
    EventKind.EXPERIENCE_TRANSITION: "experience lifecycle",
    EventKind.ROUTE: "route decision",
    EventKind.HARDWARE: "hardware mode",
    EventKind.EVAL: "offline eval",
    EventKind.CANARY: "canary",
    EventKind.REGRESSION: "regression gate",
    EventKind.RESULT: "task settled",
    EventKind.STATE: "state transition",
    EventKind.ERROR: "error",
}


def _all_task_ids(log: EventLog) -> list[str]:
    return log.task_ids()


# --------------------------------------------------------------------- #
def task_list(log: EventLog) -> dict[str, Any]:
    out = []
    for tid in _all_task_ids(log)[-_PAGE:]:
        events = log.read(tid)
        if not events:
            continue
        snap = project_task(events)
        req = next((e.payload for e in events if e.kind == EventKind.REQUEST), {})
        result = snap.result or {}
        out.append(
            {
                "task_id": tid,
                "state": snap.state.value,
                "task_class": (snap.contract.task_class if snap.contract else None),
                "objective": (snap.contract.objective if snap.contract else req.get("text", "")),
                "started_ts": events[0].ts,
                "updated_ts": events[-1].ts,
                "verified": bool(result.get("verified")),
                "summary": result.get("summary", ""),
            }
        )
    out.reverse()  # newest first
    return {"tasks": out, "count": len(out)}


def task_timeline(log: EventLog, task_id: str) -> dict[str, Any] | None:
    events = log.read(task_id)
    if not events:
        return None
    snap = project_task(events)

    rows = []
    transitions = []
    prev_state = None
    for e in events:
        if e.kind == EventKind.STATE:
            to = e.payload.get("state") or e.payload.get("to")
            transitions.append({"ts": e.ts, "from": prev_state, "to": to})
            prev_state = to
        rows.append(
            {
                "seq": e.seq,
                "ts": e.ts,
                "kind": e.kind,
                "headline": _HEADLINES.get(e.kind, e.kind.lower().replace("_", " ")),
                "detail": _detail(e.kind, e.payload),
            }
        )

    return {
        "task_id": task_id,
        "state": snap.state.value,
        "objective": (snap.contract.objective if snap.contract else None),
        "task_class": (snap.contract.task_class if snap.contract else None),
        "transitions": transitions,
        "spend": _spend(events),
        "verification": (
            {"tier": snap.verification.tier, "overall": snap.verification.overall}
            if snap.verification else None
        ),
        "events": rows[-_PAGE:],
    }


def agents_panel(log: EventLog, task_id: str) -> dict[str, Any]:
    events = log.read(task_id)
    latest: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.kind != EventKind.AGENT_MESSAGE:
            continue
        sender = e.payload.get("sender") or e.payload.get("role") or "?"
        latest[sender] = {
            "ts": e.ts,
            "intent": e.payload.get("intent"),
            "claims": e.payload.get("claims", [])[:3],
            "confidence": e.payload.get("confidence_summary"),
        }
    roles = []
    for r in _ROLES:
        msg = latest.get(r)
        roles.append({"role": r, "active": msg is not None, **(msg or {})})
    return {"task_id": task_id, "roles": roles}


def system_health(log: EventLog, task_ids: list[str] | None = None) -> dict[str, Any]:
    ids = task_ids if task_ids is not None else _all_task_ids(log)
    hw_mode = "NORMAL"
    hw_ts = None
    live: dict[str, Any] = {}
    budget_posture = "ok"
    active_canaries = 0
    rolled_back = 0
    quarantines = 0
    for tid in ids:
        for e in log.read(tid):
            if e.kind in (EventKind.HARDWARE, EventKind.TELEMETRY):
                hw_mode, hw_ts = e.payload.get("mode", hw_mode), e.ts
                if e.payload.get("source", "").startswith("live"):
                    live = {
                        k: e.payload[k] for k in
                        ("ram_percent", "cpu_percent", "disk_free_percent",
                         "gpu_temp_c", "gpu_percent", "vram_percent", "source")
                        if k in e.payload
                    }
            elif e.kind == EventKind.BUDGET:
                budget_posture = e.payload.get("level", budget_posture)
            elif e.kind == EventKind.CANARY:
                v = e.payload.get("verdict")
                if v == "HOLD":
                    active_canaries += 1
                elif v == "ROLLBACK":
                    rolled_back += 1
            elif e.kind == EventKind.EXPERIENCE_TRANSITION and e.payload.get("state") == "QUARANTINED":
                quarantines += 1
    return {
        "hardware_mode": hw_mode,
        "hardware_ts": hw_ts,
        "hardware_live": live or None,
        "budget_posture": budget_posture,
        "canaries_active": active_canaries,
        "canaries_rolled_back": rolled_back,
        "quarantine_events": quarantines,
        "tasks_tracked": len(ids),
    }


def metrics_panel(log: EventLog, task_ids: list[str] | None = None) -> dict[str, Any]:
    ids = task_ids if task_ids is not None else _all_task_ids(log)
    return rebuild_metrics(log, ids).model_dump()


def routes_panel(log: EventLog, task_ids: list[str] | None = None) -> dict[str, Any]:
    ids = task_ids if task_ids is not None else _all_task_ids(log)
    decisions = []
    by_class: dict[str, dict[str, int]] = {}
    for tid in ids:
        for e in log.read(tid):
            if e.kind != EventKind.ROUTE:
                continue
            p = e.payload
            decisions.append(
                {
                    "ts": e.ts, "task_id": tid, "task_class": p.get("task_class"),
                    "provider_id": p.get("provider_id"), "reason": p.get("reason"),
                    "escalated": p.get("escalated"), "data_driven": p.get("data_driven"),
                    "explored": p.get("explored"),
                }
            )
            tc = p.get("task_class") or "?"
            prov = p.get("provider_id") or "(paused)"
            by_class.setdefault(tc, {})
            by_class[tc][prov] = by_class[tc].get(prov, 0) + 1
    return {"recent": decisions[-_PAGE:][::-1], "by_class": by_class}


# --------------------------------------------------------------------- #
def _detail(kind: str, payload: dict[str, Any]) -> str:
    if kind == EventKind.STATE:
        return str(payload.get("state") or payload.get("to") or "")
    if kind == EventKind.AGENT_MESSAGE:
        sender = payload.get("sender", "?")
        claims = payload.get("claims", [])
        return f"{sender}/{payload.get('intent')}: " + ("; ".join(claims[:2]) if claims else "")
    if kind == EventKind.VERIFICATION:
        return f"{payload.get('tier', 'T0')} {payload.get('overall', '?')}"
    if kind == EventKind.ROUTE:
        return f"{payload.get('provider_id') or '(paused)'} — {payload.get('reason', '')}"
    if kind == EventKind.HARDWARE:
        return f"mode {payload.get('mode')}"
    if kind == EventKind.ESCALATION:
        return f"rung {payload.get('rung')} (actionable={payload.get('actionable')})"
    if kind == EventKind.PROGRESS:
        return str(payload.get("effective_class", ""))
    if kind == EventKind.CANARY:
        return f"{payload.get('kind')} {payload.get('subject')}: {payload.get('verdict')}"
    if kind == EventKind.EXPERIENCE_TRANSITION:
        return f"{payload.get('id')} -> {payload.get('state')} ({payload.get('trigger')})"
    if kind == EventKind.RESULT:
        return payload.get("summary", "")
    if kind == EventKind.CONTRACT:
        return payload.get("objective", "")
    if kind == EventKind.ERROR:
        return str(payload.get("error", ""))[:200]
    return ""


def _spend(events: list) -> dict[str, Any]:
    in_tok = out_tok = runs = 0
    for e in events:
        if e.kind == EventKind.MODEL_RUN:
            in_tok += int(e.payload.get("input_tokens", 0) or 0)
            out_tok += int(e.payload.get("output_tokens", 0) or 0)
            runs += 1
    wall = (events[-1].ts - events[0].ts) if len(events) > 1 else 0.0
    return {"model_runs": runs, "input_tokens": in_tok, "output_tokens": out_tok,
            "wall_clock_s": round(wall, 2)}
