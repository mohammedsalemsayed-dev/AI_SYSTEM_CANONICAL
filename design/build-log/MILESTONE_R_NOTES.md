# Milestone R notes — what is real, what remains

Status against [../MILESTONE_R_PLAN.md](../MILESTONE_R_PLAN.md). **435 tests green.**
All 10 days built. Removes "full telemetry and target-machine calibration" from the
`STATUS.md` "still requiring real implementation" list.

## Real after Milestone R

| Area | Module | Notes |
|---|---|---|
| Live telemetry | `app/services/hardware/telemetry.py` | `read_telemetry() -> HardwareSnapshot` (`source="live"` / `"live-degraded"`). RAM %: Windows `GlobalMemoryStatusEx` via `ctypes`; Linux `/proc/meminfo`; macOS `vm_stat`. CPU %: `os.getloadavg()` normalised by `os.cpu_count()` where available, else a neutral `0.0`. Disk: `shutil.disk_usage` → `disk_free_percent`. GPU: `nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total` (0.5 s timeout, fixed argv, no shell) → `gpu_temp_c` / `gpu_percent` / `vram_percent`; any failure → `None`/`0`. **Never raises** — every probe degrades. Verified live on this host (RTX 5060, 8 GB; RAM 37 %, GPU 42 °C). |
| Calibration | `app/services/hardware/calibration.py` | `calibrate() -> HardwareProfile{platform, cpu_count, cpu_bench_score, ram_total_gb, disk_total_gb, disk_write_mb_s, gpu:{present,name,vram_gb}|None, calibrated_ts}`. `cpu_bench_score` = ops in a fixed 50 ms pure-Python LCG loop / `REF_CPU_OPS`. `disk_write_mb_s` = a 4 MiB temp-file write, fsync'd, then deleted. Total budget ~200 ms on this host (< 300 ms cap). `persist(profile, memory)` / `load(memory)` (system-tier `MemoryRecord`, `kind="hardware_profile"`) / `is_stale(profile, days=30)`. |
| Live monitor | `app/services/hardware/monitor.py::LiveHardwareMonitor` | `sample()` returns a cached `read_telemetry()` for `min_interval_s` (2.0 s) — a burst of calls is one probe. Implements the existing `HardwareMonitor` interface; a probe failure yields a `source="live-degraded"` snapshot, never an exception. The static monitor stays the default. |
| Budget scaling | `app/services/budget/tracker.py::default_budget(task_class, *, profile=None)` | With a `HardwareProfile`, `wall_clock_s ×= clamp(REF_CPU_SCORE / profile.cpu_bench_score, 0.5, 3.0)`; a `disk_write_mb_s < 50` adds a further ×1.25. No profile → the constants are byte-identical to before. |
| Orchestrator wiring | `orchestrator._hardware_mode` / `_route_and_check_hardware` | Hardware sampling is now **independent of routing**: a `LiveHardwareMonitor` logs a real `HARDWARE` snapshot (`mode` + `source` + `ram/cpu/disk/gpu` fields) on **every** task — even a healthy `NORMAL` machine — so the health strip has real numbers; an `EMERGENCY` pauses to `WAITING_FOR_USER` even with **no Router** wired. The Router path is unchanged when wired. Hardware unset → no change. |
| CLI | `python -m app.services.hardware.calibrate [--persist p.db]` | Prints the `HardwareProfile` JSON; `--persist` saves it to a `MemoryStore`. |
| Shell | `app/ui/readmodels.py::system_health` | `hardware_live` = the latest live `HARDWARE` / `TELEMETRY` snapshot's `ram/cpu/disk/gpu` + `source`, or `None`. `GET /api/system` surfaces it. |
| Schema / events | `+ HardwareProfile`; `HardwareSnapshot` gains `cpu_percent` / `disk_free_percent`; `+ TELEMETRY` event kind. |

## Scope / security posture

- Telemetry is local syscalls + a fixed `nvidia-smi` argv (no shell, no user input); **no
  network**; the only write is the bounded temp file the disk micro-bench deletes.
- Physical safety bands (°C / % in `hardware/modes.py`) are **unchanged** — calibration
  scales *budget* and (documented, off by default) a router cloud bias, not the `EMERGENCY`
  threshold.
- The `HardwareProfile` is config data in the system memory tier; `load()` validates on read
  and returns `None` on a corrupt record.
- `LiveHardwareMonitor` is opt-in; every existing test stays deterministic on the static
  monitor.

## Not yet real / deferred

- **`psutil` / a cross-platform metrics lib** — stdlib + `ctypes` + `nvidia-smi` is the
  slice; a library is a drop-in behind `read_telemetry()`.
- **Non-NVIDIA GPUs** — only `nvidia-smi`. An AMD/Apple/Intel machine reports "no GPU", so a
  future router low-VRAM bias would misfire there; each vendor is an additive branch.
- **Router `hw_profile=` cloud bias** — the plan scoped an optional low-VRAM cloud bias; it
  is documented but **not wired** in this milestone (the budget-scaling half landed; the
  routing half is a small follow-up once a local backend exists to bias *away from*).
- **Continuous background sampling / a metrics time-series** — `LiveHardwareMonitor` is
  on-demand with a short cache; a sampler thread is a desktop-shell concern.
- **Power / battery / thermal-zone deep reads**, **per-process accounting**,
  **auto-recalibration scheduling** — `is_stale()` is the signal; the rest is later.

## Deferred past R (unchanged)

Milestone A hardening (Postgres / Redis); the live-harness runs and the Tauri native build
(subscription / toolchain); real renderer / RAG / engine-toolchain integrations behind their
seams; complete desktop-shell integration.
