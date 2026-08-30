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
    EventKind.SYNTHESIS: "answer",
    EventKind.AUTHORING: "document",
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


def _session_key(events: list) -> tuple[str | None, str]:
    """(session_id, workspace) for a task. Falls back to a folder hash so tasks
    created before the session concept still thread by working directory."""
    import hashlib
    import os

    req = next((e.payload for e in events if e.kind == EventKind.REQUEST), {})
    ws = req.get("workspace_path") or req.get("workspace") or ""
    sid = req.get("session_id")
    if sid:
        return sid, ws
    if ws:
        return "s_" + hashlib.sha1(os.path.normcase(ws).encode()).hexdigest()[:12], ws
    return None, ""


def session_list(log: EventLog) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for tid in _all_task_ids(log):
        events = log.read(tid)
        if not events:
            continue
        sid, ws = _session_key(events)
        if not sid:
            continue
        snap = project_task(events)
        req = next((e.payload for e in events if e.kind == EventKind.REQUEST), {})
        g = groups.setdefault(sid, {
            "session_id": sid, "workspace": ws, "tasks": 0,
            "started_ts": events[0].ts, "updated_ts": events[-1].ts,
            "last_message": "", "last_state": "",
        })
        g["tasks"] += 1
        g["started_ts"] = min(g["started_ts"], events[0].ts)
        g["updated_ts"] = max(g["updated_ts"], events[-1].ts)
        g["last_message"] = req.get("text", "") or g["last_message"]
        g["last_state"] = snap.state.value
    out = sorted(groups.values(), key=lambda x: x["updated_ts"], reverse=True)
    return {"sessions": out, "count": len(out)}


def session_timeline(log: EventLog, session_id: str) -> dict[str, Any] | None:
    items: list[tuple[float, str, list, str]] = []
    for tid in _all_task_ids(log):
        events = log.read(tid)
        if not events:
            continue
        sid, ws = _session_key(events)
        if sid != session_id:
            continue
        items.append((events[0].ts, tid, events, ws))
    if not items:
        return None
    items.sort()
    workspace = items[-1][3]

    rows: list[dict[str, Any]] = []
    for _ts, tid, events, _ws in items:
        req = next((e.payload for e in events if e.kind == EventKind.REQUEST), {})
        atts = [a for a in (req.get("attachments") or []) if a]
        rows.append({"kind": "MESSAGE", "ts": events[0].ts, "task_id": tid,
                     "headline": req.get("text", ""), "detail": "",
                     "data": {"attachments": atts} if atts else None})
        tl = task_timeline(log, tid)
        for row in (tl["events"] if tl else []):
            rows.append({**row, "task_id": tid})

    latest = task_timeline(log, items[-1][1]) or {}
    return {
        "session_id": session_id,
        "workspace": workspace,
        "state": latest.get("state"),
        "tasks": len(items),
        "objective": latest.get("objective"),
        "task_class": latest.get("task_class"),
        "verification": latest.get("verification"),
        "spend": latest.get("spend"),
        "plan": latest.get("plan", []),
        "runs": latest.get("runs", []),
        "counters": latest.get("counters", {}),
        "events": rows[-(_PAGE * 2):],
    }


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
        row = {
            "seq": e.seq,
            "ts": e.ts,
            "kind": e.kind,
            "headline": _HEADLINES.get(e.kind, e.kind.lower().replace("_", " ")),
            "detail": _detail(e.kind, e.payload),
        }
        data = _row_data(e.kind, e.payload)
        if data:
            row["data"] = data
        rows.append(row)

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
        "plan": _plan(events, snap.state.value),
        "runs": _runs(events),
        "counters": _counters(events),
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
    if kind == EventKind.MODEL_RUN:
        who = payload.get("role", "?")
        prov = payload.get("provider") or payload.get("model") or ""
        lat = payload.get("latency_s")
        tail = f" · {lat:.1f}s" if isinstance(lat, (int, float)) and lat else ""
        return f"{who} on {prov}{tail}" if prov else who
    if kind == EventKind.ARTIFACT:
        paths = payload.get("changed_paths") or []
        return ", ".join(paths[:4]) + (" …" if len(paths) > 4 else "")
    if kind == EventKind.CRITIC:
        v = payload.get("verdict", "")
        findings = payload.get("findings") or []
        return f"{v}" + (f" — {len(findings)} finding(s)" if findings else "")
    if kind == EventKind.BRAINSTORM:
        n = len(payload.get("approaches") or [])
        return f"{n} candidate approach(es)"
    if kind == EventKind.TOOL_LOOP:
        return f"{payload.get('tool_calls', '?')} tool call(s), {payload.get('turns', '?')} turn(s)"
    if kind == EventKind.SYNTHESIS:
        if payload.get("written_path"):
            return f"wrote {payload['written_path']} to your folder"
        ans = payload.get("answer") or payload.get("summary") or payload.get("text") or ""
        return ans[:200] + ("…" if len(ans) > 200 else "")
    if kind == EventKind.AUTHORING:
        wp = payload.get("written_path")
        return (f"{payload.get('title', 'document')} — {payload.get('format', '?')}"
                + (f" → {wp}" if wp else "") + f" · {payload.get('sections', 0)} sections")
    return ""


# kind-specific structured payload the stream renderer can expand inline
def _row_data(kind: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if kind == EventKind.ARTIFACT:
        diff = (payload.get("diff") or "")
        # keep the wire small — the stream only shows the first hunk
        lines = diff.splitlines()
        return {
            "changed_paths": payload.get("changed_paths") or [],
            "diff": "\n".join(lines[:40]) + ("\n…" if len(lines) > 40 else ""),
        }
    if kind == EventKind.BRAINSTORM:
        return {"approaches": [str(a)[:160] for a in (payload.get("approaches") or [])][:4]}
    if kind == EventKind.SYNTHESIS:
        body = payload.get("answer") or payload.get("summary") or payload.get("text") or ""
        d = {"answer": body[:6000]}
        if payload.get("written_path"):
            d["written_path"] = payload["written_path"]
            d["format"] = payload.get("format")
        return d
    if kind == EventKind.ESCALATION:
        if "from_builder" in payload or "to_builder" in payload:
            return {"from": payload.get("from_builder"), "to": payload.get("to_builder"),
                    "reason": payload.get("reason", "") or payload.get("detail", "")}
        return {"rung": payload.get("rung"),
                "reason": payload.get("reason", "") or payload.get("tried", ""),
                "tried": payload.get("tried", "")}
    if kind == EventKind.VERIFICATION:
        return {"tier": payload.get("tier", "T0"), "overall": payload.get("overall", "?")}
    if kind == EventKind.MODEL_RUN:
        return {"role": payload.get("role"), "provider": payload.get("provider") or payload.get("model"),
                "latency_s": payload.get("latency_s", 0.0)}
    return None


# --- the plan tracker: a fixed ladder folded from the event stream ------- #
def _plan(events: list, state: str) -> list[dict[str, Any]]:
    kinds = {e.kind for e in events}
    verifs = [e.payload.get("overall") for e in events if e.kind == EventKind.VERIFICATION]
    escalated = any(
        e.kind == EventKind.ESCALATION
        and (e.payload.get("to_builder") or e.payload.get("from_builder"))
        for e in events
    )
    steps: list[dict[str, Any]] = []

    def add(key: str, label: str, done: bool, now: bool, meta: str = "") -> None:
        steps.append({"key": key, "label": label,
                      "state": "done" if done else ("now" if now else "wait"),
                      "meta": meta})

    add("interpret", "Interpret the objective",
        EventKind.CONTRACT in kinds, state == "INTERPRETING")
    if EventKind.BRAINSTORM in kinds:
        n = next((len(e.payload.get("approaches") or [])
                  for e in events if e.kind == EventKind.BRAINSTORM), 0)
        add("brainstorm", "Brainstorm approaches", True, False, f"{n} offered")
    add("plan", "Plan the change", EventKind.PLAN in kinds, state == "PLANNING")
    add("edit", "Apply the edit", EventKind.ARTIFACT in kinds,
        state in ("EXECUTING", "RECOVERING"),
        "local → cloud" if escalated else "")
    v_meta = ""
    if verifs:
        v_meta = "fail → pass" if ("fail" in verifs and "pass" in verifs) else (verifs[-1] or "")
    add("verify", "Verify the change",
        bool(verifs) and verifs[-1] == "pass", state == "VERIFYING", v_meta)
    if EventKind.CRITIC in kinds:
        cv = next((e.payload.get("verdict", "")
                   for e in reversed(events) if e.kind == EventKind.CRITIC), "")
        add("critic", "Critic review", True, False, str(cv))
    terminal = state in ("COMPLETED", "FAILED")
    add("settle", "Settle the task", EventKind.RESULT in kinds,
        state in ("STALLED", "RECOVERING", "WAITING_FOR_USER"),
        state.lower() if terminal else "")
    return steps


def _runs(events: list) -> list[dict[str, Any]]:
    out = []
    for e in events:
        if e.kind != EventKind.MODEL_RUN:
            continue
        p = e.payload
        out.append({
            "ts": e.ts,
            "role": p.get("role", "?"),
            "provider": p.get("provider") or p.get("model") or "",
            "latency_s": round(float(p.get("latency_s", 0.0) or 0.0), 2),
            "in": int(p.get("input_tokens", 0) or 0),
            "out": int(p.get("output_tokens", 0) or 0),
        })
    return out


def _counters(events: list) -> dict[str, Any]:
    v_pass = v_fail = escs = recov = runs = t_in = t_out = 0
    for e in events:
        if e.kind == EventKind.VERIFICATION:
            if e.payload.get("overall") == "pass":
                v_pass += 1
            else:
                v_fail += 1
        elif e.kind == EventKind.ESCALATION:
            # a real model escalation is a builder handoff (from/to); the
            # inspect/change_strategy/critic/... ladder rungs are recovery steps,
            # not "we spent a stronger model" — don't inflate the escalation count
            if e.payload.get("to_builder") or e.payload.get("from_builder"):
                escs += 1
            else:
                recov += 1
        elif e.kind == EventKind.MODEL_RUN:
            runs += 1
            t_in += int(e.payload.get("input_tokens", 0) or 0)
            t_out += int(e.payload.get("output_tokens", 0) or 0)
    return {"events": len(events), "model_runs": runs, "escalations": escs,
            "recovery_steps": recov, "verify_pass": v_pass, "verify_fail": v_fail,
            "in_tokens": t_in, "out_tokens": t_out}


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
