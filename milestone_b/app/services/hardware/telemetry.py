"""Live machine telemetry (MILESTONE_R_PLAN.md §2).

stdlib + `ctypes` (Windows) + a best-effort `nvidia-smi` probe. Every read
degrades to a conservative value; `read_telemetry()` never raises.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

from app.schemas.contracts import HardwareSnapshot

_NVIDIA_QUERY = (
    "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total"
)


def _ram_percent() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = _MS()
            m.dwLength = ctypes.sizeof(_MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))  # type: ignore[attr-defined]
            return float(m.dwMemoryLoad)
        if sys.platform.startswith("linux"):
            info = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    k, _, v = line.partition(":")
                    info[k.strip()] = float(v.strip().split()[0])
            total = info.get("MemTotal", 0.0)
            avail = info.get("MemAvailable", info.get("MemFree", 0.0))
            return round(100.0 * (1 - avail / total), 1) if total else None
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=1).stdout
            pages = {}
            for line in out.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    pages[k.strip()] = float(v.strip().rstrip(".") or 0)
            free = pages.get("Pages free", 0) + pages.get("Pages inactive", 0)
            used = pages.get("Pages active", 0) + pages.get("Pages wired down", 0)
            tot = free + used + pages.get("Pages speculative", 0)
            return round(100.0 * used / tot, 1) if tot else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _cpu_percent() -> float | None:
    try:
        if hasattr(os, "getloadavg"):
            la1 = os.getloadavg()[0]
            n = os.cpu_count() or 1
            return round(min(100.0, 100.0 * la1 / n), 1)
        # Windows / no loadavg: a short busy-vs-wall estimate is unreliable; report
        # a neutral value so the mode policy stays NORMAL unless RAM/GPU says otherwise.
        return 0.0
    except Exception:  # noqa: BLE001
        return None


def _disk_free_percent(path: str = ".") -> float:
    try:
        du = shutil.disk_usage(path)
        return round(100.0 * du.free / du.total, 1) if du.total else 100.0
    except Exception:  # noqa: BLE001
        return 100.0


def _gpu() -> dict:
    """Returns {gpu_temp_c, gpu_percent, vram_percent} — all None/0 when no probe."""
    blank = {"gpu_temp_c": None, "gpu_percent": 0.0, "vram_percent": 0.0}
    smi = shutil.which("nvidia-smi")
    if not smi:
        return blank
    try:
        out = subprocess.run(
            [smi, _NVIDIA_QUERY, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=0.5,
        ).stdout.strip().splitlines()
        if not out:
            return blank
        temp, util, used, total = (x.strip() for x in out[0].split(","))
        vram = (float(used) / float(total) * 100.0) if float(total) else 0.0
        return {"gpu_temp_c": float(temp), "gpu_percent": float(util),
                "vram_percent": round(vram, 1)}
    except Exception:  # noqa: BLE001
        return blank


def read_telemetry(disk_path: str = ".") -> HardwareSnapshot:
    ram = _ram_percent()
    cpu = _cpu_percent()
    g = _gpu()
    degraded = ram is None or cpu is None
    return HardwareSnapshot(
        ram_percent=ram if ram is not None else 0.0,
        cpu_percent=cpu if cpu is not None else 0.0,
        disk_free_percent=_disk_free_percent(disk_path),
        gpu_temp_c=g["gpu_temp_c"],
        gpu_percent=g["gpu_percent"],
        vram_percent=g["vram_percent"],
        source="live-degraded" if degraded else "live",
        ts=time.time(),
    )
