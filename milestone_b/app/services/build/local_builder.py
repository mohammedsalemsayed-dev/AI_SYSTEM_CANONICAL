"""`Builder` that drives a LOCAL model (Ollama) through an agentic edit loop.

This is the keystone the design has been deferring: an on-device model doing the
actual multi-turn work — inspect the repo, call tools, read output, edit files,
re-plan on failure. It runs inside the workspace **copy** the Orchestrator already
made and already policy-checked for this step (same contract as `AgentSDKBuilder`).

Tools exposed to the model (deliberately small and safe for the slice):
  list_dir(path)             — names under a dir, recursive, skips .git/pycache
  read_file(path)            — file text (truncated)
  write_file(path, content)  — create/overwrite a file
  edit_file(path, old, new)  — replace the first exact occurrence of `old`
  run_tests()                — run the contract's pytest target, return output
  finish(summary)            — stop; the loop also stops on max_turns

Tool-call parsing is tolerant: it takes Ollama's native `message.tool_calls`
when present, and otherwise parses a JSON object out of `message.content`
(qwen2.5-coder tends to emit calls that way). Every parse outcome is counted so
the benchmark can score tool-call reliability per model.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.contracts import PlanStep, TaskContract
from app.services.build.base import BuildOutput
from app.services.build.workspace_copy import diff_workspace
from app.services.verify.verifier_t0 import extract_pytest_target

_HOST = "http://localhost:11434"
_READ_CAP = 24_000
_OUT_CAP = 8_000
_MAX_TURNS = 24
_TEST_TIMEOUT = 120

_TOOLS = [
    {"type": "function", "function": {
        "name": "list_dir", "description": "List files under a directory (recursive).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Create or overwrite a file with content.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace the first exact occurrence of `old` with `new` in a file. "
                       "(If you pass `content` instead, the whole file is overwritten.)",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
            "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "run_tests", "description": "Run the verification test target and return its output.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "finish", "description": "Signal the change is complete.",
        "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}}}},
]

_SYSTEM = """You are the Builder in an autonomous coding system. You work ONLY inside the given repository, by calling tools.

FIX an existing failing test — do this in order:
1. read_file the verification test file. Note EXACTLY what it asserts — return values, exact exception types and message strings, edge cases, dict keys / attributes.
2. read_file the SOURCE module under test. See the real current code before changing it — never guess.
3. Make the SMALLEST source change that makes the test pass as written. Never edit the test file.
4. Prefer write_file with the full corrected file. (edit_file(path, old, new) is for a surgical replace — only if you copy `old` verbatim from a read_file.)
5. call run_tests. If it fails, read the failure and change the source again.
6. When run_tests reports PASS, call finish.

CREATE from scratch — if read_file on the test target returns "DOES NOT EXIST", or the objective asks you to create/make/build a new file:
1. write_file the implementation module named in the OBJECTIVE (e.g. calculator.py) with complete, working code.
2. If the VERIFICATION TARGET names a test file that does not exist, write_file that test file too:
   - `import pytest` and the module under test at the top.
   - plain `assert` for values; for exceptions use `with pytest.raises(ValueError): ...`.
   - NEVER write `assert x raises Y` — that is not Python.
   - Assert ONLY the plain behaviour the OBJECTIVE states. Do NOT invent edge cases
     (odd whitespace, huge inputs, extra error messages) that you then cannot satisfy.
     3-5 straightforward assertions is enough.
3. call run_tests, fix what it reports, then finish. If two run_tests in a row still fail, finish anyway — a later stage will verify.
Do NOT keep calling list_dir for files that are not there — if a path does not exist, create it.

Call exactly one tool per turn. Never answer in prose. At most ONE list_dir call total — you rarely need it."""


@dataclass
class BuilderMetrics:
    model: str = ""
    turns: int = 0
    tool_calls: int = 0
    invalid_tool_calls: int = 0        # unparseable / unknown name
    bad_arg_calls: int = 0             # known tool, missing/wrong required args
    tool_confusion: int = 0            # e.g. edit_file called with write_file's `content`
    edits: int = 0                     # successful write_file / edit_file
    edit_failures: int = 0            # edit_file whose `old` was not found
    test_runs: int = 0
    tests_passed: bool = False
    finished: bool = False             # model called finish()
    hit_turn_cap: bool = False
    wall_s: float = 0.0
    in_tokens: int = 0
    out_tokens: int = 0
    error: str = ""

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class LocalBuilder:
    name = "local"

    def __init__(
        self,
        model: str = "qwen3:8b",
        *,
        host: str = _HOST,
        max_turns: int = _MAX_TURNS,
        keep_alive: str = "30m",
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.max_turns = max_turns
        self.keep_alive = keep_alive
        self.metrics = BuilderMetrics(model=model)

    # -- Builder protocol ------------------------------------------- #
    def execute(
        self, *, task_id: str, step: PlanStep, contract: TaskContract, workspace: str
    ) -> BuildOutput:
        self.metrics = BuilderMetrics(model=self.model)
        t0 = time.time()
        try:
            self._loop(step, contract, workspace)
        except Exception as exc:  # noqa: BLE001 — a builder failure is a result
            self.metrics.error = repr(exc)
        self.metrics.wall_s = round(time.time() - t0, 1)

        diff, names = diff_workspace(workspace)
        if not diff.strip():
            return BuildOutput(
                changed_paths=[], diff="", exit_code=1,
                stdout=json.dumps(self.metrics.as_dict()),
                error=self.metrics.error or "local builder produced no change",
            )
        return BuildOutput(
            changed_paths=names, diff=diff, exit_code=0,
            stdout=json.dumps(self.metrics.as_dict()),
        )

    # -- the agentic loop ----------------------------------------- #
    def _loop(self, step: PlanStep, contract: TaskContract, ws: str) -> None:
        root = Path(ws).resolve()
        target = extract_pytest_target(contract.required_evidence) or ""
        target_file = target.split("::")[0].split()[0] if target else ""
        target_exists = bool(target_file) and (root / target_file).is_file()
        mode = (
            f"The verification target file {target_file!r} EXISTS — read it first, then fix the source."
            if target_exists else
            "The verification target file does NOT exist yet. This is a CREATE task: "
            "write_file the implementation module from the OBJECTIVE now, then (if needed) "
            "write_file the test file, then run_tests. Do not call list_dir more than once."
        )
        user = (
            f"OBJECTIVE\n{contract.objective}\n\nTHIS STEP\n{step.intent}\n\n"
            f"VERIFICATION TARGET\npytest {target or '(none specified)'}\n\n{mode}"
        )
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ]

        unproductive = 0   # turns with no genuinely new information / no edit
        list_dirs = 0      # total list_dir calls — cap the exploration spiral
        seen: set[str] = set()
        for _ in range(self.max_turns):
            self.metrics.turns += 1
            reply = self._chat(messages)
            messages.append(reply)
            calls = self._extract_calls(reply)
            if not calls:
                self.metrics.invalid_tool_calls += 1
                unproductive += 1
                messages.append({"role": "tool", "content":
                                 "No valid tool call found. Reply with exactly one tool call."})
                if unproductive >= 5:
                    return
                continue

            name, args = calls[0]
            self.metrics.tool_calls += 1
            if name == "finish":
                self.metrics.finished = True
                return
            edits_before = self.metrics.edits
            result = self._dispatch(name, args, root, target, ws)
            messages.append({"role": "tool", "name": name, "content": result[:_OUT_CAP]})

            made_edit = self.metrics.edits > edits_before
            fresh_read = (
                name == "read_file"
                and not result.startswith(("error:", "DOES NOT EXIST"))
                and args.get("path") not in seen
            )
            if name == "read_file":
                seen.add(args.get("path"))
            if name == "list_dir":
                list_dirs += 1
                if list_dirs >= 2:
                    messages.append({"role": "user", "content":
                        "Stop exploring. Call write_file / edit_file to make the change now."})

            progressed = made_edit or fresh_read or (name == "list_dir" and list_dirs == 1)
            unproductive = 0 if progressed else unproductive + 1
            if unproductive >= 5:
                return
            if name == "run_tests":
                if self.metrics.tests_passed:
                    messages.append({"role": "user", "content": "Tests pass. Call finish now."})
                elif self.metrics.test_runs >= 4 and self.metrics.edits > 0:
                    # churning on failures — stop and let T0 + escalation judge the
                    # diff we already have rather than burning every turn.
                    return
        self.metrics.hit_turn_cap = True

    # -- Ollama chat -------------------------------------------- #
    def _chat(self, messages: list[dict]) -> dict:
        body = {
            "model": self.model, "messages": messages, "tools": _TOOLS,
            "stream": False, "keep_alive": self.keep_alive,
            # agentic tool-use wants fast direct turns, not a CoT preamble each
            # step; Qwen3 honours this, other models ignore it.
            "think": False,
            "options": {"temperature": 0.0},
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.metrics.in_tokens += int(payload.get("prompt_eval_count", 0) or 0)
        self.metrics.out_tokens += int(payload.get("eval_count", 0) or 0)
        msg = payload.get("message", {}) or {}
        return {"role": "assistant", "content": msg.get("content", ""),
                "tool_calls": msg.get("tool_calls")}

    # -- tolerant tool-call extraction ------------------------- #
    _KNOWN = {"list_dir", "read_file", "write_file", "edit_file", "run_tests", "finish"}

    def _extract_calls(self, reply: dict) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for tc in reply.get("tool_calls") or []:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if name in self._KNOWN:
                out.append((name, args if isinstance(args, dict) else {}))
        if out:
            return out
        # fallback: a JSON object in the content (qwen2.5-coder style)
        content = reply.get("content") or ""
        for m in re.finditer(r"\{(?:[^{}]|\{[^{}]*\})*\}", content):
            try:
                obj = json.loads(m.group(0))
            except ValueError:
                continue
            name = obj.get("name") or obj.get("tool") or obj.get("function")
            args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
            if name in self._KNOWN and isinstance(args, dict):
                out.append((name, args))
                break
        return out

    # -- tool bodies ------------------------------------------- #
    def _safe(self, root: Path, rel: str) -> Path | None:
        try:
            p = (root / (rel or ".")).resolve()
            p.relative_to(root)
            return p
        except (ValueError, OSError):
            return None

    def _dispatch(self, name: str, args: dict, root: Path, target: str, ws: str) -> str:
        if name == "list_dir":
            base = self._safe(root, str(args.get("path", ".")))
            if base is None or not base.exists():
                self.metrics.bad_arg_calls += 1
                return (f"DOES NOT EXIST: {args.get('path')!r}. Nothing to list. "
                        "If you need this file, create it with write_file.")
            if base.is_file():
                return f"{base.name} is a file, not a directory. read_file it instead."
            files = sorted(
                str(f.relative_to(root)).replace("\\", "/")
                for f in base.rglob("*")
                if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts
            )
            return "\n".join(files[:400]) or "(empty)"

        if name == "read_file":
            p = self._safe(root, str(args.get("path", "")))
            if p is None:
                self.metrics.bad_arg_calls += 1
                return "error: path is outside the repo"
            if not p.is_file():
                # not a hard error for a CREATE task — tell the model to make it
                return (f"DOES NOT EXIST: {args.get('path')!r}. "
                        "If the task needs this file, create it with write_file(path, content).")
            return p.read_text("utf-8", "replace")[:_READ_CAP]

        if name == "write_file":
            p = self._safe(root, str(args.get("path", "")))
            content = args.get("content")
            if p is None or not isinstance(content, str):
                self.metrics.bad_arg_calls += 1
                return "error: need path (in repo) and string content"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="\n")
            self.metrics.edits += 1
            return f"wrote {p.relative_to(root)} ({len(content)} chars)"

        if name == "edit_file":
            p = self._safe(root, str(args.get("path", "")))
            if p is None or not p.is_file():
                self.metrics.bad_arg_calls += 1
                return "error: `path` must be an existing file in the repo"
            old, new = args.get("old"), args.get("new")
            # lenient: models often call edit_file the way write_file works
            if isinstance(args.get("content"), str) and not (isinstance(old, str) and isinstance(new, str)):
                self.metrics.tool_confusion += 1
                p.write_text(args["content"], encoding="utf-8", newline="\n")
                self.metrics.edits += 1
                return f"overwrote {p.relative_to(root)} (you passed `content`; use write_file next time)"
            if not isinstance(old, str) or not isinstance(new, str):
                self.metrics.bad_arg_calls += 1
                return "error: need string `old` and string `new` (or `content` to overwrite)"
            txt = p.read_text("utf-8", "replace")
            if old not in txt:
                self.metrics.edit_failures += 1
                return "error: `old` text not found exactly; read the file again and copy it verbatim"
            p.write_text(txt.replace(old, new, 1), encoding="utf-8", newline="\n")
            self.metrics.edits += 1
            return f"edited {p.relative_to(root)}"

        if name == "run_tests":
            self.metrics.test_runs += 1
            out, passed = self._run_pytest(ws, target)
            self.metrics.tests_passed = passed
            return ("PASS\n" if passed else "FAIL\n") + out[:_OUT_CAP]

        self.metrics.invalid_tool_calls += 1
        return f"error: unknown tool {name!r}"

    @staticmethod
    def _run_pytest(ws: str, target: str) -> tuple[str, bool]:
        argv = [sys.executable, "-m", "pytest", "-q"]
        argv += target.split() if target else []
        try:
            p = subprocess.run(argv, cwd=ws, capture_output=True, text=True,
                               timeout=_TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return f"timed out after {_TEST_TIMEOUT}s", False
        return (p.stdout + p.stderr), p.returncode == 0
