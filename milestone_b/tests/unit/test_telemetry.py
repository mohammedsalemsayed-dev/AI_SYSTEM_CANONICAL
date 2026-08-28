"""Acceptance (Unit): live telemetry + target-machine calibration + budget
scaling + the cached live monitor (MILESTONE_R_PLAN.md §6)."""

from __future__ import annotations

import time

from app.services.budget.tracker import default_budget
from app.services.hardware import telemetry
from app.services.hardware.calibration import calibrate, is_stale, load, persist
from app.services.hardware.monitor import LiveHardwareMonitor
from app.services.memory.store import MemoryStore


# --- telemetry --------------------------------------------------- #
def test_read_telemetry_plausible_on_this_host() -> None:
    s = telemetry.read_telemetry()
    assert s.source in ("live", "live-degraded")
    assert 0.0 <= s.ram_percent <= 100.0
    assert 0.0 <= s.cpu_percent <= 100.0
    assert 0.0 <= s.disk_free_percent <= 100.0
    assert s.gpu_temp_c is None or 0.0 <= s.gpu_temp_c <= 130.0


def test_gpu_probe_absent_is_none(monkeypatch) -> None:
    monkeypatch.setattr(telemetry.shutil, "which", lambda _n: None)
    g = telemetry._gpu()
    assert g["gpu_temp_c"] is None and g["gpu_percent"] == 0.0


def test_gpu_probe_parses_a_mocked_csv(monkeypatch) -> None:
    import subprocess

    monkeypatch.setattr(telemetry.shutil, "which", lambda _n: "/usr/bin/nvidia-smi")

    class _R:
        stdout = "55, 30, 2048, 8192\n"

    monkeypatch.setattr(telemetry.subprocess, "run", lambda *a, **k: _R())
    g = telemetry._gpu()
    assert g["gpu_temp_c"] == 55.0 and g["gpu_percent"] == 30.0 and g["vram_percent"] == 25.0


def test_telemetry_degrades_not_raises(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "_ram_percent", lambda: None)
    monkeypatch.setattr(telemetry, "_cpu_percent", lambda: None)
    s = telemetry.read_telemetry()
    assert s.source == "live-degraded" and s.ram_percent == 0.0


# --- calibration ------------------------------------------ #
def test_calibrate_shape_and_bounded_time() -> None:
    t0 = time.perf_counter()
    p = calibrate()
    # micro-bench budget — the fixed-work benches target ~0.2s; allow generous
    # head-room so a loaded CI host does not flake (a real regression would be
    # seconds, not tenths).
    assert (time.perf_counter() - t0) < 1.5
    assert p.cpu_count >= 1 and p.cpu_bench_score > 0
    assert p.gpu is None or p.gpu.get("present") is True
    assert p.disk_total_gb >= 0.0


def test_profile_persist_load_roundtrip_and_stale() -> None:
    mem = MemoryStore()
    p = calibrate()
    assert load(mem) is None
    persist(p, mem)
    got = load(mem)
    assert got is not None and got.cpu_count == p.cpu_count
    assert not is_stale(got, days=30)
    assert is_stale(got, days=30, now=p.calibrated_ts + 40 * 86400)
    mem.close()


# --- budget scaling ------------------------------------ #
def test_default_budget_unchanged_without_profile() -> None:
    assert default_budget("code_edit_local") == {
        "wall_clock_s": 300, "steps": 8, "model_cost_usd": 0.50
    }


def test_slow_cpu_profile_lengthens_wall_budget() -> None:
    from app.schemas.contracts import HardwareProfile

    slow = HardwareProfile(cpu_bench_score=0.4, disk_write_mb_s=500)
    fast = HardwareProfile(cpu_bench_score=3.0, disk_write_mb_s=500)
    base = default_budget("code_edit_local")["wall_clock_s"]
    assert default_budget("code_edit_local", profile=slow)["wall_clock_s"] > base
    assert default_budget("code_edit_local", profile=fast)["wall_clock_s"] <= base
    # a slow disk bumps it further
    slow_disk = HardwareProfile(cpu_bench_score=1.0, disk_write_mb_s=20)
    assert default_budget("code_edit_local", profile=slow_disk)["wall_clock_s"] > base


# --- live monitor cache ------------------------------- #
def test_live_monitor_coalesces_calls(monkeypatch) -> None:
    from app.schemas.contracts import HardwareSnapshot

    calls = {"n": 0}

    def _spy(_p="."):
        calls["n"] += 1
        return HardwareSnapshot(source="live", ram_percent=20.0)

    import app.services.hardware.telemetry as tmod

    monkeypatch.setattr(tmod, "read_telemetry", _spy)
    m = LiveHardwareMonitor(min_interval_s=5.0)
    m.sample()
    m.sample()
    m.sample()
    assert calls["n"] == 1
