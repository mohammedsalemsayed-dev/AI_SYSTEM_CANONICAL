# Milestone R — Telemetry & Target-Machine Calibration Plan

> **Cross-reference**
> - Role: Build plan for real machine telemetry (CPU / RAM / disk / best-effort GPU) and a one-time calibration profile, replacing the static `HardwareMonitor` seam and feeding budget defaults + routing.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §4/§7 (hardware-aware scheduling + the local/cloud router), §7 hardware modes, §11.1 (budget), §11.2 (the system-health strip is a real UI element), §5-C tier C (heavy builds), §15.2 ("hardware-aware scheduling"); [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md) "still requiring real implementation → full telemetry and target-machine calibration".
> - Downstream: Milestone G's hardware modes now read a live snapshot; budget defaults scale to the machine; the desktop-shell health strip shows real numbers.
> - Predecessors: G (`HardwareMode` / `HardwareMonitor` / the router), B (`default_budget`). Continues the `milestone_b/` tree.

---

## 1. Purpose

`HardwareMonitor.sample()` returns a static `NORMAL` snapshot. The mode policy, the
`EMERGENCY` pause, and the router's local bias are all wired to it but never actually
trigger. Budget defaults (`default_budget`) are fixed constants regardless of the machine.

Milestone R makes it real with **stdlib only** (plus `ctypes` on Windows, a best-effort
`nvidia-smi` probe for GPU):

- **live telemetry** — `read_telemetry() -> HardwareSnapshot` with real RAM %, CPU %, disk
  free %, and GPU temp / util *when a probe is available* (else `None`, source-tagged);
- **calibration** — a one-time `calibrate() -> HardwareProfile` (cpu count, RAM/disk totals,
  GPU presence + VRAM, a bounded CPU/disk micro-bench score), persisted to system memory;
- **wiring** — a `LiveHardwareMonitor` the orchestrator / `run_ui` can attach (the static
  one stays the default for deterministic tests); `default_budget` scaled by the profile; a
  low-VRAM profile biases the router toward cloud even at `NORMAL`.

Guiding rules:
- **Best-effort, never fatal** — every probe degrades to `None` / a conservative default;
  a machine with no `nvidia-smi`, a restricted `ctypes`, or an odd platform still boots.
- **Additive** — `LiveHardwareMonitor` is opt-in. The static monitor and the current fixed
  budget defaults are unchanged when it is not wired; every existing test stays
  deterministic.
- **Physical thresholds stay physical** — the °C / % bands in `hardware/modes.py` are not
  "calibrated away"; calibration scales *budget* and *routing bias*, not the safety bands.
- **Cheap** — `read_telemetry()` is a few syscalls (< 5 ms); the micro-bench in
  `calibrate()` is bounded to ~150 ms total and runs once.

## 2. In scope

| Concern | Milestone R implementation |
|---|---|
| Live telemetry | `hardware/telemetry.py`: `read_telemetry() -> HardwareSnapshot` (`source="live"`). RAM %: Windows `GlobalMemoryStatusEx` via `ctypes`; Linux `/proc/meminfo`; macOS `vm_stat` / fallback. CPU %: `os.getloadavg()` normalised by `os.cpu_count()` where available, else a 50 ms `time.process_time` / wall delta estimate. Disk: `shutil.disk_usage` → `disk_free_percent`. GPU: `nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits` (0.5 s timeout) → `gpu_temp_c` / `gpu_percent` / `vram_percent`; any failure → all `None`. |
| Calibration | `hardware/calibration.py`: `calibrate() -> HardwareProfile{cpu_count, cpu_bench_score, ram_total_gb, disk_total_gb, disk_write_mb_s, gpu: {present, name, vram_gb} | None, platform, calibrated_ts}`. `cpu_bench_score` = ops in a fixed 50 ms integer loop / a reference constant. `disk_write_mb_s` = writing a 4 MiB temp file, capped, then deleted. GPU block from `nvidia-smi -L` + the memory query. |
| Persistence | `hardware/calibration.py`: `persist(profile, memory)` → a `system`-tier `MemoryRecord` (`kind="hardware_profile"`); `load(memory) -> HardwareProfile | None`; `is_stale(profile, days=30)`. |
| Live monitor | `hardware/monitor.py`: `LiveHardwareMonitor(min_interval_s=2.0)` — caches `read_telemetry()` for `min_interval_s` so a burst of `sample()` calls is one probe. Implements the existing `HardwareMonitor` interface. |
| Budget scaling | `budget/tracker.py`: `default_budget(task_class, *, profile=None)` — when a `HardwareProfile` is passed, scale `wall_clock_s` by `clamp(ref_cpu_score / profile.cpu_bench_score, 0.5, 3.0)` and `steps` unchanged; a low `disk_write_mb_s` bumps `wall_clock_s`. No profile → today's constants. |
| Router bias | `routing/router.py`: an optional `hw_profile=` — a GPU-absent or `vram_gb < LOW_VRAM_GB` profile adds a small cloud bias to `_static_pick` even at `NORMAL` (local models would not fit). Documented; off when no profile. |
| CLI | `python -m app.services.hardware.calibrate [--persist <memory.db>]` — runs `calibrate()`, prints the profile, optionally persists. |
| Shell | `app/ui/readmodels.py::system_health` — include the latest **live** `HARDWARE` snapshot fields (ram/cpu/disk/gpu) when present, plus the calibrated profile summary if the server was given a memory store. |
| Events | reuse `HARDWARE` — a `LiveHardwareMonitor`-sourced snapshot logs `{mode, source: "live", ram_percent, cpu_percent, disk_free_percent, gpu_temp_c, gpu_percent}`. New `TELEMETRY` event for a standalone reading (calibration / CLI). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| `psutil` / a real cross-platform metrics lib | stdlib + `ctypes` + `nvidia-smi` is the slice; a lib is a drop-in later |
| AMD / Intel / Apple-silicon GPU probes | only `nvidia-smi` now; each vendor is an additive branch in `telemetry.py` |
| Continuous background sampling / a metrics time-series | `LiveHardwareMonitor` samples on demand with a short cache; a sampler thread is a desktop-shell concern |
| Power draw / battery / thermal-zone deep reads | later — temp + util is enough for the mode policy |
| Per-process resource accounting | later — the snapshot is machine-wide |
| Auto-recalibration scheduling | `is_stale()` is the signal; a scheduler drives it later |

## 4. Component layout

```
app/services/hardware/
  telemetry.py     read_telemetry() -> HardwareSnapshot (live); per-OS RAM/CPU + nvidia-smi GPU
  calibration.py   calibrate() -> HardwareProfile; persist/load/is_stale; micro-bench
  monitor.py       + LiveHardwareMonitor (caches read_telemetry)
  calibrate.py     `python -m app.services.hardware.calibrate` CLI
app/schemas/contracts.py   + HardwareProfile (extend HardwareSnapshot with cpu_percent,
                           disk_free_percent, vram_percent)
app/events/log.py          + TELEMETRY
app/services/budget/tracker.py       default_budget(..., profile=)
app/services/routing/router.py       optional hw_profile= cloud bias
app/ui/readmodels.py                 system_health includes live telemetry
tests/
  unit/         test_telemetry (plausible values on this host; graceful no-GPU),
                test_calibration (profile shape; micro-bench bounded; persist/load),
                test_budget_scaling, test_live_monitor_cache
  integration/  test_live_monitor_in_orchestrator (a real HARDWARE snapshot logged)
```

## 5. Work breakdown (~10 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `HardwareSnapshot` extended (`cpu_percent`, `disk_free_percent`, `vram_percent`); `hardware/telemetry.py` RAM (per-OS) + disk. Unit: values are in `[0, 100]` and non-`None` on this host; a forced-failure path returns a conservative snapshot. |
| 3 | `telemetry.py` CPU % (loadavg / delta estimate) + the `nvidia-smi` GPU probe with a 0.5 s timeout. Unit: GPU fields are `None` when `nvidia-smi` is absent (mock the subprocess), a real value when the CSV parses. |
| 4–5 | `hardware/calibration.py` — `calibrate()` + the bounded CPU/disk micro-bench + `HardwareProfile` + `persist`/`load`/`is_stale`. Unit: the bench completes < 300 ms; `persist` then `load` round-trips; `is_stale` on an old ts. |
| 6 | `hardware/monitor.py::LiveHardwareMonitor` (cached). Unit: two `sample()` calls within `min_interval_s` do one probe (spy on `read_telemetry`); after the interval, a second probe. |
| 7 | `budget/tracker.py::default_budget(profile=)` scaling + `routing/router.py` `hw_profile=` cloud bias. Unit: a slow-CPU profile lengthens `wall_clock_s`; a no-GPU profile shifts the static pick toward cloud; no profile → unchanged. |
| 8 | `app/services/hardware/calibrate.py` CLI + `TELEMETRY` event; `system_health` read-model includes live fields. Integration: `orch.hardware = LiveHardwareMonitor()` → a task logs a `HARDWARE` event with `source="live"` and real `ram_percent`. |
| 9 | Integration — a calibrated profile persisted to a `MemoryStore` is loaded by a fresh process and scales `default_budget`; the shell `/api/system` shows the live numbers. Edge: telemetry raising mid-run does not fail the task (monitor catches → static fallback). |
| 10 | Regression; `milestone_b/MILESTONE_R_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `read_telemetry()` on this host returns `ram_percent` / `cpu_percent` /
  `disk_free_percent` in `[0, 100]` and `source == "live"`; with `nvidia-smi` mocked absent,
  the GPU fields are `None` and nothing raises; with a mocked CSV they parse. `calibrate()`
  returns a `HardwareProfile` with a positive `cpu_count`, a finite `cpu_bench_score`, and a
  `gpu` block that is `None` or `{present: True, …}`; the micro-bench returns in < 300 ms.
  `persist` → `load` round-trips; `is_stale` true past the window. `LiveHardwareMonitor`
  coalesces calls within `min_interval_s`. `default_budget(profile=<slow>)` gives a larger
  `wall_clock_s` than `default_budget()`; `default_budget()` alone is byte-identical to
  before.
- **Integration** — `orch.hardware = LiveHardwareMonitor()`: a completed task has a
  `HARDWARE` event with `source == "live"` and a real `ram_percent`; the run still
  `COMPLETED`s (a live `NORMAL` machine does not trigger the pause). A profile persisted by
  one `MemoryStore` handle is `load()`-ed by another and changes `default_budget`. The shell
  `/api/system` includes the live fields when a `LiveHardwareMonitor` snapshot was logged.
- **Failure** — every probe forced to raise (`ctypes` unavailable, `nvidia-smi` returns
  garbage, `/proc/meminfo` missing) → a conservative `HardwareSnapshot` (`ram_percent=0`,
  GPU `None`, `source="live-degraded"`), never an exception out of `sample()`; a task with
  a degraded monitor still runs.
- **Security** — telemetry reads are local syscalls / a fixed `nvidia-smi` argv (no shell,
  no user input); no network; no write except the bounded temp file the disk bench deletes;
  the calibration profile is config data in system memory.
- **Recovery** — `reconcile()` + `resume()` unaffected; a stale profile is used (with the
  `is_stale` flag) rather than blocking; re-calibration is idempotent.
- **Benchmark** — the micro-bench numbers are informational; no pass/fail oracle. `calibrate.py`
  prints a profile on this host.

## 7. Tunable starting values

- CPU micro-bench window: **50 ms**; disk bench file: **4 MiB**; total `calibrate()` budget
  **≤ 300 ms**.
- `LiveHardwareMonitor.min_interval_s` = **2.0**.
- `LOW_VRAM_GB` = **6.0** (below this, local coder/reasoner models do not fit → cloud bias).
- Budget scale clamp: `wall_clock_s ×= clamp(REF_CPU_SCORE / profile.cpu_bench_score, 0.5, 3.0)`.
- `HardwareProfile` stale after **30 days**.
- `nvidia-smi` timeout **0.5 s**.

## 8. Risks

- **Platform coverage** — the RAM/CPU reads have a Windows / Linux / macOS branch each;
  an untested platform falls through to the conservative snapshot. Mitigate: the fallback is
  safe (mode stays `NORMAL`), and the branch set covers the three the product targets.
- **`nvidia-smi` only** — a non-NVIDIA GPU reports as "no GPU", so the router's low-VRAM bias
  fires on machines that actually have a capable AMD/Apple GPU. Documented; the bias is
  *small* and only at `NORMAL`; adding a vendor branch is additive.
- **Micro-bench noise** — a 50 ms CPU sample under load is rough. It is used only to *scale*
  a budget within a 0.5×–3× clamp, not to gate anything; a noisy read costs some budget
  slack, not correctness.
- **Calibration staleness** — hardware or thermal paste changes; `is_stale()` + a shown
  `calibrated_ts` are the signal, recalibration is one CLI call.
- **Determinism in tests** — live telemetry is non-deterministic by nature. Mitigated: the
  static monitor stays the default; live tests assert *ranges* and *shape*, and the
  micro-bench is bounded not exact.

## 9. Deliverables

- `app/services/hardware/` — `telemetry.py`, `calibration.py`, `calibrate.py`,
  `LiveHardwareMonitor`.
- `HardwareProfile` schema; extended `HardwareSnapshot`; `TELEMETRY` event.
- `default_budget(profile=)` scaling; `Router(hw_profile=)` bias; `system_health` live fields.
- Test suite: the current 423 green, plus unit (telemetry / calibration / budget scaling /
  live monitor) and integration (live monitor in the loop / profile persistence).
- `milestone_b/MILESTONE_R_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "full telemetry and target-machine calibration"
  moves off the "still requiring real implementation" list; the hardware-protection and
  VRAM-aware rows note a live monitor + calibration profile.
