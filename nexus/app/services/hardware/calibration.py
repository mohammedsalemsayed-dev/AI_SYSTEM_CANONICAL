"""Target-machine calibration (MILESTONE_R_PLAN.md §2).

A one-time `calibrate()` → `HardwareProfile` with cpu/ram/disk totals, a GPU
block, and a bounded CPU/disk micro-bench. Persisted to the system memory tier;
`is_stale()` after 30 days.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time

from app.schemas.contracts import HardwareProfile

CPU_BENCH_MS = 50
DISK_BENCH_BYTES = 4 * 1024 * 1024
# ops a mid-range core completes in CPU_BENCH_MS of this pure-Python LCG loop
# (measured ~4.2e5 on a 2024 desktop core). A machine that does more scores > 1.
REF_CPU_OPS = 420_000
STALE_DAYS = 30


def _cpu_bench_score() -> float:
    end = time.perf_counter() + CPU_BENCH_MS / 1000.0
    ops = 0
    x = 0
    while time.perf_counter() < end:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        ops += 1
    return round(ops / REF_CPU_OPS, 4) or 0.0001


def _disk_write_mb_s() -> float:
    try:
        buf = b"\0" * (64 * 1024)
        n = DISK_BENCH_BYTES // len(buf)
        fd, path = tempfile.mkstemp(prefix="hwcal_")
        try:
            t0 = time.perf_counter()
            with os.fdopen(fd, "wb") as fh:
                for _ in range(n):
                    fh.write(buf)
                fh.flush()
                os.fsync(fh.fileno())
            dt = time.perf_counter() - t0
        finally:
            os.unlink(path)
        return round((DISK_BENCH_BYTES / 1e6) / dt, 1) if dt > 0 else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _gpu_block() -> dict | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        name = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=0.5).stdout.strip()
        mem = subprocess.run(
            [smi, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=0.5,
        ).stdout.strip().splitlines()
        vram_gb = round(float(mem[0]) / 1024.0, 1) if mem else 0.0
        first = name.splitlines()[0] if name else "NVIDIA GPU"
        return {"present": True, "name": first[:120], "vram_gb": vram_gb}
    except Exception:  # noqa: BLE001
        return {"present": True, "name": "NVIDIA GPU (probe failed)", "vram_gb": 0.0}


def calibrate(disk_path: str = ".") -> HardwareProfile:
    try:
        du = shutil.disk_usage(disk_path)
        disk_total_gb = round(du.total / 1e9, 1)
    except Exception:  # noqa: BLE001
        disk_total_gb = 0.0

    ram_total_gb = 0.0
    try:
        import ctypes

        if os.name == "nt":
            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            ram_total_gb = round(m.ullTotalPhys / 1e9, 1)
        elif hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            ram_total_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except Exception:  # noqa: BLE001
        ram_total_gb = 0.0

    return HardwareProfile(
        platform=f"{platform.system()} {platform.machine()}",
        cpu_count=os.cpu_count() or 1,
        cpu_bench_score=_cpu_bench_score(),
        ram_total_gb=ram_total_gb,
        disk_total_gb=disk_total_gb,
        disk_write_mb_s=_disk_write_mb_s(),
        gpu=_gpu_block(),
        calibrated_ts=time.time(),
    )


# -- persistence -------------------------------------------------- #
def persist(profile: HardwareProfile, memory) -> None:
    from app.schemas.contracts import MemoryRecord

    memory.put(MemoryRecord(
        tier="system", kind="hardware_profile", scope="machine", trust="workspace",
        content=profile.model_dump_json(),
    ))


def load(memory) -> HardwareProfile | None:
    rows = [m for m in memory.all(tier="system") if m.kind == "hardware_profile"]
    if not rows:
        return None
    try:
        return HardwareProfile.model_validate_json(rows[-1].content)
    except Exception:  # noqa: BLE001
        return None


def is_stale(profile: HardwareProfile, *, days: int = STALE_DAYS, now: float | None = None) -> bool:
    return ((now or time.time()) - profile.calibrated_ts) > days * 86400
