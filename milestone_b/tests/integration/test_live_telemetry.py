"""Acceptance (Integration): a live hardware monitor feeds a real snapshot into
the loop; a calibrated profile persists and scales the budget; the shell shows
the live numbers (MILESTONE_R_PLAN.md §6)."""

from __future__ import annotations

import threading
import urllib.request

from app.events.log import EventKind, EventLog
from app.services.hardware.calibration import calibrate, load, persist
from app.services.hardware.monitor import LiveHardwareMonitor
from app.services.memory.store import MemoryStore
from tests.conftest import FIXED_CALC
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def test_live_monitor_logs_a_real_hardware_snapshot(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.router = None
    orch.hardware = LiveHardwareMonitor()

    r = orch.run("fix the add function", sample_repo)
    # a healthy live machine does not trip the pause
    assert r.state == "COMPLETED"
    hw = [e for e in log.read(r.task_id) if e.kind == EventKind.HARDWARE]
    assert hw and hw[0].payload["source"].startswith("live")
    assert 0.0 <= hw[0].payload["ram_percent"] <= 100.0
    log.close()


def test_calibrated_profile_persists_across_stores_and_scales_budget(tmp_path) -> None:
    from app.services.budget.tracker import default_budget

    db = str(tmp_path / "mem.db")
    mem = MemoryStore(db)
    persist(calibrate(), mem)
    mem.close()

    mem2 = MemoryStore(db)
    prof = load(mem2)
    assert prof is not None and prof.cpu_count >= 1
    b_no = default_budget("code_edit_local")
    b_prof = default_budget("code_edit_local", profile=prof)
    assert b_prof["wall_clock_s"] != b_no["wall_clock_s"] or prof.cpu_bench_score == 1.0
    assert 150 <= b_prof["wall_clock_s"] <= 900
    mem2.close()


def test_shell_system_health_includes_live_fields(sample_repo: str, tmp_path) -> None:
    from app.ui.server import UIServer

    dbf = str(tmp_path / "ev.db")
    log = EventLog(dbf)
    orch = build_orchestrator(
        log, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.router = None
    orch.hardware = LiveHardwareMonitor()
    orch.run("fix the add function", sample_repo)
    log.close()

    srv = UIServer(("127.0.0.1", 0), db_path=dbf)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        import json

        with urllib.request.urlopen(base + "/api/system", timeout=5) as resp:
            body = json.loads(resp.read())
        assert body["hardware_live"] is not None
        assert body["hardware_live"]["source"].startswith("live")
    finally:
        srv.shutdown()
