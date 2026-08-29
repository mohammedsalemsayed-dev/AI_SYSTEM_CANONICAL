"""Generic MCP client tool adapter (Streamable HTTP transport).

Lets the orchestrator's tool loop call an external MCP server's tools as
`<name>.<tool>` operations — e.g. an Unreal-editor MCP on http://127.0.0.1:8000/mcp
exposed by a project's own `.mcp.json`.

stdlib only (urllib). JSON-RPC 2.0 over POST; the server may answer with
`application/json` or an SSE stream (`text/event-stream`) — both are handled.
Tool output is `tool_output` trust (a fact, never a directive — §12), so it can
inform a plan but never originate a side effect on its own.
"""

from __future__ import annotations

import itertools
import json
import urllib.error
import urllib.request

from app.services.tools.base import DispatchContext, ToolManifest, ToolOp, ToolResult

_PROTOCOL = "2025-06-18"
_MAX_OUT = 24_000


class McpToolAdapter:
    def __init__(self, url: str, *, name: str = "mcp", capability: str = "net.fetch",
                 timeout_s: float = 60.0, headers: dict | None = None) -> None:
        self.name = name
        self.url = url
        self.capability = capability
        self.timeout_s = timeout_s
        self._headers = {"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream", **(headers or {})}
        self._ids = itertools.count(1)
        self._session_id: str | None = None
        self._initialised = False
        self._tools: list[dict] | None = None
        self._err: str | None = None

    # -- transport --------------------------------------------- #
    def _rpc(self, method: str, params: dict | None = None, *, notify: bool = False):
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = next(self._ids)
        if params is not None:
            body["params"] = params
        h = dict(self._headers)
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid
            if notify:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read().decode("utf-8", "replace")
        if "text/event-stream" in ctype:
            for chunk in raw.split("\n\n"):
                data = "".join(ln[5:].strip() for ln in chunk.splitlines()
                               if ln.startswith("data:"))
                if not data:
                    continue
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                    return msg
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {"error": {"message": f"non-JSON reply: {raw[:200]}"}}

    def _ensure(self) -> bool:
        if self._initialised:
            return self._tools is not None
        if self._err:
            return False
        try:
            r = self._rpc("initialize", {
                "protocolVersion": _PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "nexus", "version": "0.1"},
            })
            if r.get("error"):
                self._err = str(r["error"])
                return False
            try:
                self._rpc("notifications/initialized", notify=True)
            except Exception:  # noqa: BLE001
                pass
            lst = self._rpc("tools/list", {})
            self._tools = (lst.get("result") or {}).get("tools") or []
            self._initialised = True
            return True
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._err = f"{type(exc).__name__}: {exc}"
            return False

    def available(self) -> bool:
        return self._ensure()

    # -- ToolAdapter ------------------------------------------ #
    def manifest(self) -> ToolManifest:
        ops: list[ToolOp] = []
        if self._ensure():
            for t in (self._tools or []):
                tn = t.get("name", "")
                if not tn:
                    continue
                desc = (t.get("description") or tn).strip().splitlines()[0][:120]
                ops.append(ToolOp(
                    op=f"{self.name}.{tn}", summary=desc, capability=self.capability,
                    args_hint=_hint(t.get("inputSchema") or {}),
                    output_trust="tool_output", side_effecting=True,
                ))
        else:
            ops.append(ToolOp(op=f"{self.name}.__unavailable__",
                              summary=f"MCP server {self.url} unreachable: {self._err}",
                              capability=self.capability, output_trust="tool_output"))
        return ToolManifest(name=self.name,
                            summary=f"external MCP server at {self.url}", ops=ops)

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult:  # noqa: ARG002
        if not self._ensure():
            return ToolResult(False, op, error=f"MCP unavailable: {self._err}")
        tool = op.split(".", 1)[1] if "." in op else op
        try:
            r = self._rpc("tools/call", {"name": tool, "arguments": args or {}})
        except (urllib.error.URLError, OSError) as exc:
            return ToolResult(False, op, error=f"MCP call failed: {exc}", trust="tool_output")
        if r.get("error"):
            return ToolResult(False, op, error=str(r["error"])[:400], trust="tool_output")
        res = r.get("result") or {}
        text = "\n".join(
            c.get("text", "") for c in (res.get("content") or [])
            if isinstance(c, dict) and c.get("type") == "text"
        )
        if not text:
            text = json.dumps(res)[:_MAX_OUT]
        return ToolResult(
            ok=not res.get("isError", False), op=op, output=text[:_MAX_OUT],
            trust="tool_output", meta={"tool": tool, "is_error": bool(res.get("isError"))},
        )


def _hint(schema: dict) -> str:
    props = (schema or {}).get("properties") or {}
    if not props:
        return "{}"
    req = set((schema or {}).get("required") or [])
    parts = [f'"{k}"{"" if k in req else "?"}: {(v or {}).get("type", "any")}'
             for k, v in list(props.items())[:8]]
    return "{" + ", ".join(parts) + "}"


def from_mcp_json(path: str, *, timeout_s: float = 60.0) -> list[McpToolAdapter]:
    """Build adapters from a project's `.mcp.json` (http/streamable entries only)."""
    try:
        cfg = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return []
    out: list[McpToolAdapter] = []
    for name, spec in (cfg.get("mcpServers") or {}).items():
        url = spec.get("url")
        if not url or spec.get("type", "http") not in ("http", "streamable-http", "sse", None):
            continue
        safe = "mcp_" + "".join(ch if ch.isalnum() else "_" for ch in name)[:24]
        out.append(McpToolAdapter(url, name=safe, timeout_s=timeout_s,
                                  headers=spec.get("headers")))
    return out
