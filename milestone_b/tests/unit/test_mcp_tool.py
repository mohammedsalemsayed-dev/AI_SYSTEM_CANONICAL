"""The generic MCP client tool adapter: handshake, tools/list -> ToolOps,
tools/call round-trip over both JSON and SSE, and graceful failure when the
server is unreachable."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.tools.adapters.mcp_tool import McpToolAdapter, from_mcp_json
from app.services.tools.base import DispatchContext

_TOOLS = [
    {"name": "spawn_actor", "description": "Spawn an actor",
     "inputSchema": {"type": "object", "properties": {"cls": {"type": "string"}},
                     "required": ["cls"]}},
    {"name": "run_tests", "description": "Run automation tests",
     "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}}}},
]


def _make_handler(sse: bool):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            m, rid = req.get("method"), req.get("id")

            def send(res):
                body = {"jsonrpc": "2.0", "id": rid, "result": res}
                if sse:
                    payload = ("event: message\ndata: " + json.dumps(body) + "\n\n").encode()
                    ctype = "text/event-stream"
                else:
                    payload = json.dumps(body).encode()
                    ctype = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Mcp-Session-Id", "s1")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            if m == "initialize":
                send({"protocolVersion": "2025-06-18"})
            elif m == "notifications/initialized":
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif m == "tools/list":
                send({"tools": _TOOLS})
            elif m == "tools/call":
                p = req.get("params", {})
                if p.get("name") == "run_tests":
                    send({"content": [{"type": "text", "text": "3 passed, 0 failed"}],
                          "isError": False})
                elif p.get("name") == "spawn_actor":
                    send({"content": [{"type": "text", "text": f"spawned {p['arguments']['cls']}"}],
                          "isError": False})
                else:
                    send({"content": [{"type": "text", "text": "no such tool"}], "isError": True})
            else:
                send({})
    return H


@pytest.fixture(params=[False, True], ids=["json", "sse"])
def mcp_url(request):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(request.param))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/mcp"
    srv.shutdown()


def test_handshake_and_manifest(mcp_url):
    ad = McpToolAdapter(mcp_url, name="mcp_ue")
    assert ad.available()
    ops = {o.op: o for o in ad.manifest().ops}
    assert set(ops) == {"mcp_ue.spawn_actor", "mcp_ue.run_tests"}
    assert ops["mcp_ue.spawn_actor"].output_trust == "tool_output"
    assert ops["mcp_ue.spawn_actor"].side_effecting
    assert '"cls": string' in ops["mcp_ue.spawn_actor"].args_hint


def test_tool_call_roundtrip(mcp_url):
    ad = McpToolAdapter(mcp_url, name="mcp_ue")
    ctx = DispatchContext(task_id="t", workspace=".")
    r = ad.invoke("mcp_ue.run_tests", {"filter": "Project.Functional"}, ctx)
    assert r.ok and r.trust == "tool_output" and "3 passed" in r.output
    r2 = ad.invoke("mcp_ue.spawn_actor", {"cls": "BP_Enemy"}, ctx)
    assert r2.ok and "spawned BP_Enemy" in r2.output
    r3 = ad.invoke("mcp_ue.nope", {}, ctx)
    assert not r3.ok


def test_unreachable_is_graceful():
    ad = McpToolAdapter("http://127.0.0.1:59/mcp", name="mcp_dead", timeout_s=1)
    assert ad.available() is False
    man = ad.manifest()
    assert man.ops and "unavailable" in man.ops[0].op
    r = ad.invoke("mcp_dead.anything", {}, DispatchContext(workspace="."))
    assert not r.ok and "unavailable" in r.error.lower()


def test_from_mcp_json(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "unreal-mcp": {"type": "http", "url": "http://127.0.0.1:8000/mcp"},
        "stdio-thing": {"command": "foo"},  # no url -> skipped
    }}))
    ads = from_mcp_json(str(tmp_path / ".mcp.json"))
    assert [a.name for a in ads] == ["mcp_unreal_mcp"]
    assert ads[0].url == "http://127.0.0.1:8000/mcp"
