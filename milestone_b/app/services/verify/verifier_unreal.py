"""T0 verifier for Unreal Engine projects — via an MCP-connected live editor.

Same `verify(...)` shape as `VerifierT0`, but the evidence target is a UE
Automation Test filter run through the project's own MCP server (declared in
`<workspace>/.mcp.json`, e.g. `unreal-mcp` on http://127.0.0.1:8000/mcp):

    "T0: unreal automation Project.Functional.Jump passes"
    "T0: unreal automation MyGame. passes"      # a group prefix

DEVIATION from the workspace-untouched invariant (unavoidable for UE): the editor
works on the *real* project, and a full C++ build is minutes, so there is no
throwaway-copy verify. This verifier applies the diff to the real workspace,
asks the MCP to compile/hot-reload and run the tests, and — if they fail —
reverts the diff so the tree is left as it was found.

Needs the UE editor open with the MCP plugin running. If the MCP is unreachable
the check fails loudly with that instruction; it never silently passes.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from app.schemas.contracts import CriterionVerdict, TaskContract, VerificationRecord
from app.services.tools.adapters.mcp_tool import McpToolAdapter, from_mcp_json
from app.services.tools.base import DispatchContext

_PASS_RE = re.compile(r"(\d+)\s+passed", re.I)
_FAIL_RE = re.compile(r"(\d+)\s+fail", re.I)
_HARD_FAIL = ("test failed", "compile failed", "compilation failed",
              "script error", "assertion failed", "fatal error")

# MCP tool-name preferences: a dedicated test runner first, else a console exec
_RUNNER_RE = re.compile(r"(run.*test|automation.*run|run.*automation|test.*runner)", re.I)
_CONSOLE_RE = re.compile(r"(run.*console|console.*command|exec.*command|execute.*console|^exec$)", re.I)
_COMPILE_RE = re.compile(r"(compile|hot.?reload|build.*project|rebuild)", re.I)

# a proxy MCP (e.g. Epic's UnrealMCP) exposes only list_toolsets/describe_toolset/
# call_tool; the real runners live in an "automation test" toolset reached via
# call_tool(toolset_name=..., tool_name="RunTests"/"RunTestsByFilter").
_PROXY_CALL_RE = re.compile(r"(^|\.)call_tool$", re.I)
_PROXY_LIST_RE = re.compile(r"(^|\.)list_toolsets$", re.I)
_AUTOMATION_TS_RE = re.compile(r"automation.*test", re.I)
_FILTER_HINT_RE = re.compile(r"(startswith:|group:|[\^$]|\+)", re.I)


def _unwrap(output: str) -> dict:
    """MCP tool output is JSON; a proxy double-encodes the payload as a JSON
    string under `returnValue`. Return the innermost dict (or {} on anything odd)."""
    try:
        obj = json.loads(output)
    except (ValueError, TypeError):
        return {}
    rv = obj.get("returnValue", obj) if isinstance(obj, dict) else obj
    if isinstance(rv, str):
        try:
            rv = json.loads(rv)
        except ValueError:
            return {}
    return rv if isinstance(rv, dict) else {}


def extract_unreal_target(required_evidence: list[str]) -> str | None:
    for entry in required_evidence:
        low = entry.lower()
        if "t0" in low and ("unreal" in low or "automation" in low):
            rest = entry
            for k in ("unreal", "automation"):
                i = rest.lower().find(k)
                if i >= 0:
                    rest = rest[i + len(k):]
            rest = re.sub(r"\s+passes?\s*$", "", rest.strip(), flags=re.I).strip()
            return rest or None
    return None


def find_unreal_mcp(workspace: str) -> McpToolAdapter | None:
    mj = Path(workspace) / ".mcp.json"
    if not mj.is_file():
        return None
    for ad in from_mcp_json(str(mj)):
        if ad.available():
            return ad
    return None


def _git(ws: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", ws, *args], capture_output=True, text=True, timeout=60)


class UnrealVerifier:
    tier = "T0"

    def __init__(self, mcp: McpToolAdapter | None = None) -> None:
        self._mcp = mcp

    @property
    def backend(self) -> str:
        return "unreal-mcp" if self._mcp else "unreal-mcp-missing"

    # -- helpers -------------------------------------------- #
    def _op(self, mcp: McpToolAdapter, pattern: re.Pattern) -> str | None:
        for o in mcp.manifest().ops:
            tool = o.op.split(".", 1)[-1]
            if pattern.search(tool):
                return o.op
        return None

    def _call(self, mcp, op, args, ws):
        return mcp.invoke(op, args, DispatchContext(task_id="", workspace=ws))

    # -- proxy MCP (call_tool -> automation-test toolset) -------------- #
    def _proxy_setup(self, mcp) -> tuple[str, str] | None:
        """-> (call_tool_op, automation_toolset_name) if this is a proxy MCP with
        an automation-test toolset, else None."""
        ops = [o.op for o in mcp.manifest().ops]
        call_op = next((o for o in ops if _PROXY_CALL_RE.search(o)), None)
        list_op = next((o for o in ops if _PROXY_LIST_RE.search(o)), None)
        if not (call_op and list_op):
            return None
        r = self._call(mcp, list_op, {}, ".")
        if not r.ok:
            return None
        ts = None
        for line in str(r.output or "").splitlines():
            # lines look like "- AutomationTestToolset.AutomationTestToolset: Automation test ..."
            name = line.lstrip("- ").split(":", 1)[0].strip()
            if name and _AUTOMATION_TS_RE.search(line):
                ts = name
                break
        return (call_op, ts) if ts else None

    def _proxy_run(self, mcp, call_op: str, toolset: str, target: str, ws: str):
        """DiscoverTests then RunTests(ByFilter). -> (passed, failed, hard, text)."""
        def ct(tool, args):
            return self._call(mcp, call_op,
                              {"toolset_name": toolset, "tool_name": tool, "arguments": args}, ws)
        ct("DiscoverTests", {})
        if _FILTER_HINT_RE.search(target):
            tr = ct("RunTestsByFilter", {"filterExpression": target})
        elif " " in target or target.count(".") >= 2:
            tr = ct("RunTests", {"testNames": [target]})
            if not _unwrap(str(tr.output or "")).get("total"):
                tr = ct("RunTestsByFilter", {"filterExpression": f"StartsWith:{target}"})
        else:
            tr = ct("RunTestsByFilter", {"filterExpression": f"StartsWith:{target}"})
        data = _unwrap(str(tr.output or ""))
        passed = int(data.get("passed", 0) or 0)
        failed = int(data.get("failed", 0) or 0)
        text = json.dumps(data)[:800] if data else str(tr.output or "")[:800]
        hard = (not tr.ok) or any(h in text.lower() for h in _HARD_FAIL)
        if not data and tr.ok:
            hard = True  # ran but returned nothing parseable
        return passed, failed, hard, text

    # -- verify -------------------------------------------- #
    def verify(self, *, task_id: str, contract: TaskContract, diff: str,
               original_workspace: str, extra_targets: list[str] | None = None) -> VerificationRecord:
        ws = original_workspace
        tgt = extract_unreal_target(contract.required_evidence)
        crit = CriterionVerdict(criterion=f"T0: unreal automation {tgt or '<?>'} passes",
                                verdict="unknown")

        def rec(overall: str, detail: str = "") -> VerificationRecord:
            crit.verdict = "pass" if overall == "pass" else "fail"
            return VerificationRecord(task_id=task_id, tier="T0", criteria=[crit],
                                      overall=overall, residual_uncertainty=detail,
                                      discriminating_tests_run=[tgt] if tgt and overall == "pass" else [])

        mcp = self._mcp or find_unreal_mcp(ws)
        if mcp is None or not mcp.available():
            return rec("fail", "Unreal MCP not reachable — open the project in the UE "
                               "editor with the MCP plugin running (see .mcp.json)")
        if tgt is None:
            return rec("fail", "no 'T0: unreal automation <filter> passes' entry in required_evidence")
        if not diff.strip():
            return rec("fail", "builder produced no change")

        run_op = self._op(mcp, _RUNNER_RE)
        console_op = self._op(mcp, _CONSOLE_RE) if run_op is None else None
        proxy = self._proxy_setup(mcp) if (run_op is None and console_op is None) else None
        if run_op is None and console_op is None and proxy is None:
            return rec("fail", "the MCP server exposes no test-run or console-command tool; "
                               "cannot run automation tests")

        # apply the change to the real project (see module docstring)
        is_git = (Path(ws) / ".git").is_dir()
        applied = False
        patch = Path(ws) / ".nexus_ue.patch"
        try:
            if is_git:
                patch.write_bytes(diff.encode("utf-8"))
                r = _git(ws, "apply", "--whitespace=nowarn", str(patch))
                if r.returncode != 0:
                    return rec("fail", f"diff did not apply to the project: {r.stderr[:200]}")
                applied = True

            # compile / hot-reload if the MCP offers a flat tool for it (a proxy
            # MCP's editor toolset can too, but a blueprint/content change on a
            # sample project has nothing to compile — skip rather than guess)
            comp_op = self._op(mcp, _COMPILE_RE) if not proxy else None
            if comp_op:
                cr = self._call(mcp, comp_op, {}, ws)
                comp_out = str(cr.output or "")
                if not cr.ok or any(h in comp_out.lower() for h in _HARD_FAIL):
                    return rec("fail", f"compile/hot-reload failed: {comp_out[:300]}")

            # run the tests
            if proxy:
                passed_n, failed_n, hard, out = self._proxy_run(mcp, proxy[0], proxy[1], tgt, ws)
                ok = not hard and failed_n == 0 and passed_n > 0
            else:
                if run_op:
                    tr = self._call(mcp, run_op, {"filter": tgt, "tests": tgt}, ws)
                else:
                    tr = self._call(mcp, console_op, {"command": f"Automation RunTests {tgt}",
                                                      "cmd": f"Automation RunTests {tgt}"}, ws)
                out = str(tr.output or "")
                low = out.lower()
                passed_n = int(_PASS_RE.search(out).group(1)) if _PASS_RE.search(out) else 0
                failed_n = int(_FAIL_RE.search(out).group(1)) if _FAIL_RE.search(out) else 0
                hard = any(h in low for h in _HARD_FAIL)
                ok = tr.ok and not hard and failed_n == 0 and (passed_n > 0 or "success" in low)

            if ok:
                return rec("pass", "")
            return rec("fail", (f"{failed_n} failed / {passed_n} passed. " + out[:600]).strip())
        finally:
            patch.unlink(missing_ok=True)
            # on anything other than a clean pass, put the tree back as found
            if applied and crit.verdict != "pass":
                try:
                    p2 = Path(ws) / ".nexus_ue_rev.patch"
                    p2.write_bytes(diff.encode("utf-8"))
                    _git(ws, "apply", "-R", "--whitespace=nowarn", str(p2))
                    p2.unlink(missing_ok=True)
                except OSError:
                    pass
