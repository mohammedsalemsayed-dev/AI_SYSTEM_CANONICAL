"""In-app task runner for the desktop shell (`--allow-submit`).

A **session** is a working directory. Every message you send from the shell runs
one orchestrator task against that directory; successive messages in the same
session are threaded — the next task is given a short context preamble built from
the earlier tasks (their objectives and the files already changed), so it
continues coherently instead of starting cold.

No git requirement: the orchestrator works on throwaway copies it inits itself,
and the diff is written straight back to the folder. A run takes minutes, so the
callable validates cheaply, starts the orchestrator on a background thread, and
returns at once — the WebView follows progress over `/api/stream`.
One run at a time (single-user desktop).
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import traceback
from typing import Any, Callable

_LOCAL = "local:qwen3:8b"                 # interpret / plan / reason
# a code-specialised local model does the actual editing when it's pulled;
# `ollama pull qwen2.5-coder:7b` (or :14b) to enable — falls back to _LOCAL.
_CODER_CANDIDATES = ("qwen2.5-coder:14b", "qwen2.5-coder:7b-instruct-q5_K_M",
                     "qwen2.5-coder:7b-instruct-q5_0", "qwen2.5-coder:7b", "qwen2.5-coder",
                     "deepseek-coder-v2:16b", "codellama:13b")
_coder_cache: dict[str, str] = {}


def _local_coder() -> str:
    """`local:<model>` string for the best pulled coder model, else `_LOCAL`."""
    if "v" in _coder_cache:
        return _coder_cache["v"]
    import json as _json
    import urllib.request as _u
    tags: set[str] = set()
    try:
        with _u.urlopen("http://localhost:11434/api/tags", timeout=4) as r:
            tags = {m.get("name", "") for m in _json.loads(r.read()).get("models", [])}
    except Exception:  # noqa: BLE001
        tags = set()
    pick = next((c for c in _CODER_CANDIDATES
                 if c in tags or any(t.split(":")[0] == c for t in tags)), None)
    _coder_cache["v"] = f"local:{pick}" if pick else _LOCAL
    return _coder_cache["v"]

# escalation choices offered in the shell — label -> get_builder() kind string.
# "" = the Agent SDK's own default model.
ESCALATION_CHOICES: dict[str, str] = {
    "sonnet": "agent_sdk:claude-sonnet-5",
    "opus": "agent_sdk:claude-opus-5",
    "default": "agent_sdk",
}
_settings: dict[str, Any] = {"escalation": "sonnet", "apply": True}


def get_settings() -> dict[str, Any]:
    return {**_settings, "escalation_choices": list(ESCALATION_CHOICES)}


def set_settings(patch: dict[str, Any]) -> dict[str, Any]:
    if "escalation" in patch and patch["escalation"] in ESCALATION_CHOICES:
        _settings["escalation"] = patch["escalation"]
    if "apply" in patch:
        _settings["apply"] = bool(patch["apply"])
    return get_settings()


_state: dict[str, Any] = {
    "running": False,
    "started_ts": None,
    "session_id": None,
    "workspace": None,
    "request": None,
    "last_task_id": None,
    "last_error": None,
    "last_finished_ts": None,
    "cancelling": False,
}
_lock = threading.Lock()


def session_id_for(workspace: str) -> str:
    norm = os.path.normcase(os.path.abspath(workspace))
    return "s_" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def run_status() -> dict[str, Any]:
    return dict(_state)


def request_cancel() -> dict[str, Any]:
    """Ask the in-flight run to stop at its next checkpoint (Stop button)."""
    from app import runtime_cancel

    with _lock:
        if not _state["running"]:
            return {"cancelling": False, "running": False}
        runtime_cancel.request()
        _state["cancelling"] = True
        return {"cancelling": True, "running": True}


class _CancelLLM:
    """Wraps an LLM so every .complete() first honours a Stop request."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        from app.runtime_cancel import check
        check()
        return self._inner.complete(*args, **kwargs)


class _CancelBuilder:
    """Wraps a Builder so .execute() first honours a Stop request."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.name = getattr(inner, "name", "builder")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        from app.runtime_cancel import check
        check()
        return self._inner.execute(*args, **kwargs)


# --------------------------------------------------------------------------- #
def _session_context(db_path: str, session_id: str, workspace: str) -> str:
    """A compact preamble from earlier tasks in this session (folder)."""
    try:
        from app.events.log import EventKind, open_event_log

        log = open_event_log(db_path)
        try:
            prior: list[tuple[str, list[str]]] = []
            for tid in log.task_ids():
                events = log.read(tid)
                req = next((e.payload for e in events if e.kind == EventKind.REQUEST), {})
                if req.get("session_id") != session_id:
                    continue
                obj = ""
                changed: list[str] = []
                for e in events:
                    if e.kind == EventKind.CONTRACT:
                        obj = e.payload.get("objective", "") or obj
                    elif e.kind == EventKind.ARTIFACT and e.payload.get("changed_paths"):
                        changed = list(e.payload["changed_paths"])
                if obj:
                    prior.append((obj, changed))
        finally:
            log.close()
    except Exception:  # noqa: BLE001
        return ""

    if not prior:
        return ""
    lines = ["[Session context — earlier in this working session you handled:]"]
    for i, (obj, changed) in enumerate(prior[-6:], 1):
        tail = f"  (touched: {', '.join(changed[:6])})" if changed else ""
        lines.append(f"  {i}. {obj}{tail}")
    lines.append(
        "[This is a follow-up in the same folder. Build on that work; "
        "do not redo it unless asked.]\n"
    )
    return "\n".join(lines)


def _do_run(request: str, workspace: str, db_path: str, apply: bool,
            session_id: str, attachments: list | None = None) -> None:
    from app.events.log import EventKind, open_event_log
    from app.llm import get_llm
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build import get_builder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    log = open_event_log(db_path)
    try:
        from pathlib import Path

        from app import runtime_cancel
        runtime_cancel.arm()  # clear any stale Stop flag before this run

        is_godot = Path(workspace, "project.godot").is_file()
        is_unreal = any(Path(workspace).glob("*.uproject"))
        is_android = (Path(workspace, "settings.gradle").is_file()
                      or Path(workspace, "settings.gradle.kts").is_file())
        preamble = _session_context(db_path, session_id, workspace)
        att_note, att_kb = "", None
        if attachments:
            from app.ui.attachments import build_kb, describe_images, prompt_note

            descs = describe_images(attachments)          # local vision model, if pulled
            att_note = prompt_note(attachments, descs)
            att_kb = build_kb(attachments)
        engine_note = ""
        if is_unreal:
            engine_note = ("[This is an Unreal Engine project — the editor is driven over MCP "
                           "(see .mcp.json). Verification runs UE Automation Tests via that MCP; "
                           "keep the UE editor open with the MCP plugin running.]")
        elif is_godot:
            engine_note = ("[This is a Godot project — write GDScript (.gd) files, use "
                           "`extends`/`func`/`var`; verification runs `godot --headless`.]")
        elif is_android:
            engine_note = ("[This is an Android/Gradle project — keep state/logic in a "
                           "ViewModel, strings in res/; verification runs `./gradlew` "
                           "unit tests on a workspace copy.]")
        full_request = "\n".join(x for x in (preamble, engine_note, att_note, request) if x)

        local_llm = _CancelLLM(get_llm(_LOCAL))  # Stop button honoured per model call
        # engine projects don't verify with pytest
        verifier = VerifierT0()
        if is_unreal:
            from app.services.verify.verifier_unreal import UnrealVerifier

            verifier = UnrealVerifier()
        elif is_godot:
            from app.services.verify.verifier_godot import GodotVerifier

            verifier = GodotVerifier()
        elif is_android:
            from app.services.verify.verifier_android import AndroidVerifier

            verifier = AndroidVerifier()
        coder = _local_coder()                       # qwen2.5-coder if pulled, else _LOCAL
        orch = Orchestrator(
            log,
            Interpreter(local_llm),                  # reasoning model interprets + plans
            Planner(local_llm),
            _CancelBuilder(get_builder(coder)),      # code-specialised model does the edits
            verifier,
            PolicyEngine(),
        )
        esc_kind = ESCALATION_CHOICES.get(_settings["escalation"], "agent_sdk")
        orch.fallback_builder = _CancelBuilder(get_builder(esc_kind))  # escalate on verify failure

        from app.cli.full_stack import wire_full_stack

        # per_file_policy on (wire_full_stack default): the §14.1 risk-class gate
        # now also applies to the files a build changed. The recovery/escalation
        # re-drive used to lose write authority here — a re-plan leads with an
        # `fs.read` step and the not-step-scoped Builder's writes were checked
        # against that read grant ("operation 'file.write' is not in the
        # capability grant"). `_plan_file_grant` now widens the per-file check to
        # the current plan's combined step capabilities, so a re-drive allows the
        # writes the first attempt already allowed.
        wire_full_stack(orch, db_path=db_path, workspace=workspace, verbose=False)
        # wire_full_stack resets orch.builder to a plain qwen3 local builder — put
        # the code-specialised model back as the primary (reasoning stays qwen3)
        _cb = _CancelBuilder(get_builder(coder))
        orch.builder = _cb
        for _k in ("local-coder", "local-small", "local-reasoner", "local"):
            if _k in (orch.builder_registry or {}):
                orch.builder_registry[_k] = _cb
        # Stop also reaches the agents wire_full_stack built with their own llm
        for _agent in (getattr(orch, "brainstorm", None), getattr(orch, "critic", None)):
            if _agent is not None and getattr(_agent, "llm", None) is not None:
                _agent.llm = _CancelLLM(_agent.llm)
        # keep the run local when local succeeds: the (cloud) T2 ensemble only
        # runs after an escalation, not on a clean local pass.
        orch.t2_on_escalation_only = True
        # document attachments become the grounding source for an authoring task,
        # and are also folded into the persistent KB so a doc_analysis follow-up
        # ("what does the attached spec say about X?") stays grounded next turn.
        if att_kb is not None and orch.authoring is not None:
            orch.authoring.kb = att_kb
        if attachments and getattr(orch, "kb", None) is not None:
            from app.ui.attachments import ingest_attachments

            ingest_attachments(orch.kb, attachments)

        # mint the task id ourselves so we can tag REQUEST with the session
        from app.schemas.contracts import new_id

        task_id = new_id("task")
        log.append(task_id, EventKind.REQUEST, {
            "text": request, "workspace_path": workspace, "session_id": session_id,
            "attachments": [a.get("name") for a in (attachments or [])],
        })
        _state["last_task_id"] = task_id
        result = orch._drive(task_id, full_request, workspace)  # noqa: SLF001

        if apply and getattr(result, "state", "") == "COMPLETED":
            from app.services.build.apply import apply_task_result

            apply_task_result(log, result.task_id, workspace)
    except Exception as exc:  # noqa: BLE001 — surface, don't crash the server
        from app.runtime_cancel import RunCancelled

        if isinstance(exc, RunCancelled):
            _state["last_error"] = "stopped by you"
        else:
            _state["last_error"] = f"{type(exc).__name__}: {exc}"
            print("[nexus-runner] run failed:\n" + traceback.format_exc(), flush=True)
    finally:
        from app import runtime_cancel
        runtime_cancel.arm()  # drop the flag so it can't leak into the next run
        log.close()
        with _lock:
            _state["running"] = False
            _state["cancelling"] = False
            _state["last_finished_ts"] = time.time()


def build_task_runner(db_path: str) -> Callable[..., dict[str, Any]]:
    """The callable `app.ui.server` invokes for `POST /api/tasks`."""

    def runner(request: str, workspace: str, apply: bool = True,
               attachments: list | None = None) -> dict[str, Any]:
        request = (request or "").strip()
        workspace = os.path.abspath((workspace or "").strip())

        if not request:
            return {"error": "message is empty"}
        if not os.path.isdir(workspace):
            return {"error": f"folder not found: {workspace}"}

        session_id = session_id_for(workspace)
        with _lock:
            if _state["running"]:
                return {"error": "a run is already in progress",
                        "session_id": _state.get("session_id")}
            _state.update(running=True, started_ts=time.time(), session_id=session_id,
                          workspace=workspace, request=request, cancelling=False,
                          last_error=None, last_task_id=None, last_finished_ts=None)

        threading.Thread(
            target=_do_run,
            args=(request, workspace, db_path, bool(apply), session_id, attachments or []),
            daemon=True, name="nexus-task-run",
        ).start()
        return {"accepted": True, "session_id": session_id, "workspace": workspace}

    return runner
