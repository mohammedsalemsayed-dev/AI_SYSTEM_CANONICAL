"""Dependency-free HTTP + SSE server over the event log (MILESTONE_H_PLAN.md §2).

stdlib `http.server` only. Binds loopback. Read-only over history: the GET
routes serve the read models, `/api/stream` tails the log as Server-Sent-Events,
and `POST /api/tasks` is wired only when a `runner` callback is supplied
(`--allow-submit`) — a submitted task still passes every policy / approval gate.
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.events.log import EventLog, open_event_log
from app.ui import readmodels
from app.ui.events import EventFeed, keepalive_frame, sse_frame
from app.ui.paths import web_dir

_WEB = web_dir()
_POLL_S = 0.25
_KEEPALIVE_S = 15.0
_CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class UIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, *, db_path: str, runner=None, web_dir: Path = _WEB,
                 artifacts=None) -> None:
        super().__init__(addr, _Handler)
        self.db_path = db_path
        self.runner = runner
        self.web_dir = web_dir
        self.artifacts = artifacts  # Milestone P — an ArtifactStore for GET /api/artifacts/{id}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing --------------------------------------------------- #
    def log_message(self, *_a) -> None:  # keep the server quiet in tests
        pass

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _open_log(self) -> EventLog:
        return open_event_log(self.server.db_path)  # type: ignore[attr-defined]

    # -- routing --------------------------------------------------- #
    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        try:
            if path == "/api/health":
                out = {
                    "status": "ok", "ts": time.time(),
                    "submit_enabled": self.server.runner is not None,  # type: ignore[attr-defined]
                }
                try:
                    from app.ui.runner import run_status
                    if self.server.runner is not None:  # type: ignore[attr-defined]
                        out["run"] = run_status()
                except Exception:  # noqa: BLE001
                    pass
                return self._json(out)
            if path == "/api/stream":
                return self._stream(q)
            if path.startswith("/api/"):
                return self._api(path, q)
            return self._static(path)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self._json({"error": repr(exc)}, status=500)
            except OSError:
                pass

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.rstrip("/")
        if route not in ("/api/tasks", "/api/settings", "/api/attachments", "/api/cancel"):
            return self._json({"error": "not found"}, status=404)
        runner = self.server.runner  # type: ignore[attr-defined]
        if runner is None:
            return self._json(
                {"error": "task submission disabled; start with --allow-submit"}, status=405
            )
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, status=400)

        if route == "/api/cancel":
            try:
                from app.ui.runner import request_cancel
                return self._json(request_cancel())
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": repr(exc)}, status=500)

        if route == "/api/settings":
            try:
                from app.ui.runner import set_settings
                return self._json(set_settings(body if isinstance(body, dict) else {}))
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": repr(exc)}, status=500)

        if route == "/api/attachments":
            ws = (body.get("workspace") or "").strip()
            if not ws:
                return self._json({"error": "workspace required"}, status=400)
            try:
                from app.ui.attachments import save_attachments
                saved = save_attachments(ws, body.get("files") or [])
                return self._json({"saved": saved})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": repr(exc)}, status=500)

        req, ws = body.get("request", "").strip(), body.get("workspace", "").strip()
        if not req or not ws:
            return self._json({"error": "request and workspace are required"}, status=400)
        apply = bool(body.get("apply", True))
        attach = body.get("attachments") or []
        result = runner(req, ws, apply, attach)
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        if isinstance(payload, dict) and payload.get("error"):
            return self._json({"error": payload["error"]}, status=400)
        return self._json({"submitted": payload}, status=201)

    # -- handlers ------------------------------------------------ #
    def _api(self, path: str, q: dict) -> None:
        log = self._open_log()
        try:
            parts = [p for p in path.split("/") if p]  # ["api", ...]
            if parts == ["api", "tasks"]:
                return self._json(readmodels.task_list(log))
            if parts == ["api", "sessions"]:
                return self._json(readmodels.session_list(log))
            if len(parts) == 3 and parts[:2] == ["api", "sessions"]:
                st = readmodels.session_timeline(log, parts[2])
                return self._json(st) if st else self._json({"error": "no such session"}, 404)
            if parts == ["api", "settings"]:
                try:
                    from app.ui.runner import get_settings
                    return self._json(get_settings())
                except Exception:  # noqa: BLE001
                    return self._json({})
            if parts == ["api", "system"]:
                out = readmodels.system_health(log)
                # take a FRESH live sample so the UI's poll shows current
                # cpu/ram/gpu/temp, not whatever the last orchestrator event held
                try:
                    from app.services.hardware.telemetry import read_telemetry
                    s = read_telemetry(".")
                    if s.source.startswith("live"):
                        out["hardware_live"] = {
                            "cpu_percent": s.cpu_percent, "ram_percent": s.ram_percent,
                            "disk_free_percent": s.disk_free_percent,
                            "gpu_temp_c": s.gpu_temp_c, "gpu_percent": s.gpu_percent,
                            "vram_percent": s.vram_percent, "source": s.source,
                        }
                except Exception:  # noqa: BLE001 — telemetry is best-effort
                    pass
                return self._json(out)
            if parts == ["api", "metrics"]:
                return self._json(readmodels.metrics_panel(log))
            if parts == ["api", "routes"]:
                return self._json(readmodels.routes_panel(log))
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                tl = readmodels.task_timeline(log, parts[2])
                return self._json(tl) if tl else self._json({"error": "no such task"}, 404)
            if len(parts) == 4 and parts[:2] == ["api", "tasks"] and parts[3] == "agents":
                if not log.read(parts[2]):
                    return self._json({"error": "no such task"}, 404)
                return self._json(readmodels.agents_panel(log, parts[2]))
            if len(parts) == 3 and parts[:2] == ["api", "artifacts"]:
                store = getattr(self.server, "artifacts", None)  # type: ignore[attr-defined]
                if store is None:
                    return self._json({"error": "artifact store not wired"}, status=404)
                ref = store.get(parts[2])
                if ref is None:
                    return self._json({"error": "no such artifact"}, status=404)
                return self._json({
                    "ref": ref.model_dump(mode="json"),
                    "text": store.text(parts[2]) if ref.kind != "file_snapshot" else "",
                })
            return self._json({"error": "not found"}, status=404)
        finally:
            log.close()

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        web_dir = self.server.web_dir.resolve()  # type: ignore[attr-defined]
        target = (web_dir / rel).resolve()
        try:
            target.relative_to(web_dir)
        except ValueError:
            return self._text(b"not found", "text/plain", status=404)
        if not target.is_file():
            return self._text(b"not found", "text/plain", status=404)
        ctype = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._text(target.read_bytes(), ctype)

    def _stream(self, q: dict) -> None:
        task_id = (q.get("task_id") or [None])[0]
        log = self._open_log()
        since_q = (q.get("since") or [None])[0]
        # default: tail from now (only events appended after the connection opens);
        # pass ?since=N to replay from a known cursor
        if since_q is None:
            row = log._conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events").fetchone()
            since = int(row[0])
        else:
            since = int(since_q)
        feed = EventFeed(log, task_id=task_id, since_seq=since)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_beat = time.time()
        try:
            self.wfile.write(b": open\n\n")
            while True:
                wrote = False
                for e in feed.poll():
                    self.wfile.write(sse_frame(e).encode())
                    wrote = True
                now = time.time()
                if not wrote and now - last_beat >= _KEEPALIVE_S:
                    self.wfile.write(keepalive_frame().encode())
                if wrote:
                    last_beat = now
                self.wfile.flush()
                time.sleep(_POLL_S)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            log.close()


def serve(db_path: str, *, host: str = "127.0.0.1", port: int = 8770, runner=None) -> UIServer:
    srv = UIServer((host, port), db_path=db_path, runner=runner)
    return srv
