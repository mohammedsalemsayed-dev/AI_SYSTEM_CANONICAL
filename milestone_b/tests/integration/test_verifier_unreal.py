"""UnrealVerifier: runs UE Automation Tests through a (mock) MCP-connected editor,
applies the diff to the real project, reverts it if the tests fail."""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.schemas.contracts import TaskContract
from app.services.tools.adapters.mcp_tool import McpToolAdapter
from app.services.verify.verifier_unreal import UnrealVerifier, extract_unreal_target


def _mcp_handler(script: dict):
    """script: {tool_name: result_text or (text, is_error)} ; also decides tool list."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            m, rid = req.get("method"), req.get("id")

            def send(res):
                b = json.dumps({"jsonrpc": "2.0", "id": rid, "result": res}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            if m == "initialize":
                send({"protocolVersion": "2025-06-18"})
            elif m == "notifications/initialized":
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif m == "tools/list":
                send({"tools": [{"name": k, "description": k,
                                 "inputSchema": {"type": "object", "properties": {}}}
                                for k in script]})
            elif m == "tools/call":
                p = req.get("params", {})
                val = script.get(p.get("name"), ("unknown tool", True))
                text, is_err = val if isinstance(val, tuple) else (val, False)
                send({"content": [{"type": "text", "text": text}], "isError": is_err})
            else:
                send({})
    return H


@pytest.fixture
def mcp():
    holder = {}

    def start(script):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _mcp_handler(script))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        holder["srv"] = srv
        return McpToolAdapter(f"http://127.0.0.1:{srv.server_address[1]}/mcp", name="mcp_ue")

    yield start
    if "srv" in holder:
        holder["srv"].shutdown()


@pytest.fixture
def ue_repo(tmp_path: Path) -> str:
    ws = tmp_path / "MyGame"
    ws.mkdir()
    (ws / "MyGame.uproject").write_text("{}")
    src = ws / "Source" / "Jump.cpp"
    src.parent.mkdir(parents=True)
    src.write_text("int Jump() { return 1; }\n")
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(ws), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(ws), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], check=True)
    return str(ws)


_GOOD_DIFF = (
    "--- a/Source/Jump.cpp\n+++ b/Source/Jump.cpp\n@@ -1 +1 @@\n"
    "-int Jump() { return 1; }\n+int Jump() { return 42; }\n"
)

_C = TaskContract(
    task_id="t", original_request="fix jump", objective="fix Jump()",
    task_class="code_edit_local", success_criteria=["jumps"],
    required_evidence=["T0: unreal automation Project.Functional.Jump passes"],
)


def test_target_parsing():
    assert extract_unreal_target(["T0: unreal automation MyGame.Jump passes"]) == "MyGame.Jump"
    assert extract_unreal_target(["T0: pytest x passes"]) is None


def test_pass_via_console_tool(mcp, ue_repo):
    ad = mcp({"run_console_command": "Automation complete: 3 passed, 0 failed"})
    v = UnrealVerifier(ad)
    r = v.verify(task_id="t", contract=_C, diff=_GOOD_DIFF, original_workspace=ue_repo)
    assert r.overall == "pass"
    assert "return 42" in Path(ue_repo, "Source/Jump.cpp").read_text()  # left applied


def test_fail_reverts_the_diff(mcp, ue_repo):
    ad = mcp({"run_automation_tests": "Results: 2 passed, 1 failed — Test Failed"})
    v = UnrealVerifier(ad)
    r = v.verify(task_id="t", contract=_C, diff=_GOOD_DIFF, original_workspace=ue_repo)
    assert r.overall == "fail" and "1 failed" in r.residual_uncertainty
    assert Path(ue_repo, "Source/Jump.cpp").read_text() == "int Jump() { return 1; }\n"  # reverted


def test_compile_failure_is_caught_and_reverted(mcp, ue_repo):
    ad = mcp({"hot_reload": ("error C2065: compilation failed", False),
              "run_automation_tests": "3 passed, 0 failed"})
    v = UnrealVerifier(ad)
    r = v.verify(task_id="t", contract=_C, diff=_GOOD_DIFF, original_workspace=ue_repo)
    assert r.overall == "fail" and "compile" in r.residual_uncertainty.lower()
    assert "return 1" in Path(ue_repo, "Source/Jump.cpp").read_text()


def test_mcp_unreachable_fails_loudly(ue_repo):
    v = UnrealVerifier(McpToolAdapter("http://127.0.0.1:59/mcp", name="dead", timeout_s=1))
    r = v.verify(task_id="t", contract=_C, diff=_GOOD_DIFF, original_workspace=ue_repo)
    assert r.overall == "fail" and "editor" in r.residual_uncertainty.lower()


def test_empty_diff_fails(mcp, ue_repo):
    ad = mcp({"run_automation_tests": "3 passed, 0 failed"})
    r = UnrealVerifier(ad).verify(task_id="t", contract=_C, diff="", original_workspace=ue_repo)
    assert r.overall == "fail" and "no change" in r.residual_uncertainty
