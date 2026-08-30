"""Hardware-mode policy (MILESTONE_G_PLAN.md §7; ports + extends the prior
foundation `services/hardware/policy.py`).

    NORMAL -> EFFICIENT -> CONSERVATION -> PROTECTIVE -> EMERGENCY

The router reads the mode: EMERGENCY pauses work; PROTECTIVE / CONSERVATION bias
toward local (or the cheapest cloud) and shrink the step budget; EFFICIENT is a
soft nudge. Thresholds are §7 starting values.
"""

from __future__ import annotations

from app.schemas.contracts import HardwareMode, HardwareSnapshot

# °C / percent thresholds (starting values; recalibrate on the target machine)
EMERGENCY_TEMP = 90.0
PROTECTIVE_TEMP = 85.0
CONSERVATION_TEMP = 80.0
CONSERVATION_RAM = 92.0
CONSERVATION_GPU_NO_PROGRESS = 95.0
EFFICIENT_GPU = 75.0
EFFICIENT_RAM = 80.0

_ORDER = ("NORMAL", "EFFICIENT", "CONSERVATION", "PROTECTIVE", "EMERGENCY")

# modes at or above which the router must prefer local / cheapest and pause on EMERGENCY
BIAS_LOCAL_MODES = ("CONSERVATION", "PROTECTIVE", "EMERGENCY")
PAUSE_MODES = ("EMERGENCY",)


def decide(snapshot: HardwareSnapshot | dict, progress_good: bool = True) -> HardwareMode:
    s = snapshot if isinstance(snapshot, dict) else snapshot.model_dump()
    temp = s.get("gpu_temp_c")
    ram = s.get("ram_percent", 0.0) or 0.0
    gpu = s.get("gpu_percent", 0.0) or 0.0

    if temp is not None and temp >= EMERGENCY_TEMP:
        return "EMERGENCY"
    if temp is not None and temp >= PROTECTIVE_TEMP:
        return "PROTECTIVE"
    if (
        (temp is not None and temp >= CONSERVATION_TEMP)
        or ram >= CONSERVATION_RAM
        or (gpu >= CONSERVATION_GPU_NO_PROGRESS and not progress_good)
    ):
        return "CONSERVATION"
    if gpu >= EFFICIENT_GPU or ram >= EFFICIENT_RAM:
        return "EFFICIENT"
    return "NORMAL"


def at_least(mode: HardwareMode, floor: HardwareMode) -> bool:
    return _ORDER.index(mode) >= _ORDER.index(floor)


def biases_local(mode: HardwareMode) -> bool:
    return mode in BIAS_LOCAL_MODES


def should_pause(mode: HardwareMode) -> bool:
    return mode in PAUSE_MODES
