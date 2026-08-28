# NEXUS desktop shell (Tauri v2)

Native window around the Milestone H shell. The Rust side is **process
supervision only**: it spawns the Python control-plane server (`nexus-server`) as
a managed sidecar, waits for its loopback port, points the WebView at
`http://127.0.0.1:8770`, and kills the sidecar on exit. All logic stays in
Python (`app/ui/`, `app/services/`, `app/orchestration/`).

```
desktop/
  package.json          @tauri-apps/cli
  gen_icons.py           Pillow -> app-icon.png + src-tauri/icons/*
  build_sidecar.py       PyInstaller -> src-tauri/binaries/nexus-server-<triple>
  build.py               one command: sidecar + npm + tauri build
  dist/splash.html        shown until the sidecar is ready (frontendDist)
  src-tauri/
    Cargo.toml  build.rs  tauri.conf.json
    capabilities/default.json   shell-execute scoped to the sidecar only
    icons/                       committed PNGs + .ico
    src/main.rs                  spawn / poll / navigate / kill
```

## Prerequisites (to actually produce a binary)

Not present in the CI/dev container this was written in — install these on a real
build host:

| Tool | All platforms |
|---|---|
| Rust (stable) | https://rustup.rs |
| Node.js 18+ | https://nodejs.org |
| PyInstaller | `pip install pyinstaller` |

Plus the platform toolchain:

- **Windows** — "Desktop development with C++" (MSVC) + WebView2 runtime (ships
  with Windows 11 / Edge; installer otherwise).
- **macOS** — Xcode Command Line Tools (`xcode-select --install`).
- **Linux** — `webkit2gtk-4.1`, `libappindicator3`, `librsvg2`, `patchelf`
  (see the Tauri prerequisites page for the exact package names per distro).

## Build

```
python desktop/gen_icons.py        # once, or after changing the icon
python desktop/build.py            # sidecar + CLI install + bundle
```

`build.py` fails fast with a named missing prerequisite if `cargo` / `npm` /
`pyinstaller` is absent. On success the installers are under
`desktop/src-tauri/target/release/bundle/` (`.msi` + NSIS on Windows, `.dmg` on
macOS, `.deb` + AppImage on Linux).

`.icns` for macOS: run `npm run tauri icon desktop/app-icon.png` on a Mac (adds
`src-tauri/icons/icon.icns`).

## Develop

```
python desktop/build_sidecar.py    # the shell spawns this artifact
cd desktop && npm install && npm run tauri dev
```

## Runtime behaviour

- Event-log DB: `<per-user data dir>/nexus/events.db`
  (`%LOCALAPPDATA%` / `~/Library/Application Support` / `~/.local/share`).
- Port: `8770` (sidecar honours `NEXUS_PORT`).
- Task submission (`POST /api/tasks`) is **off**; set `NEXUS_ALLOW_SUBMIT=1` in
  the sidecar environment to enable it. A submitted task still passes every
  policy / capability / approval / budget gate.
- Readiness: the shell TCP-polls the port ~18 s, then falls back to
  `splash.html`; it is not a crash.

## Build status (2026-08-29)

- **Sidecar: verified.** `pip install pyinstaller` + `python desktop/build_sidecar.py`
  produces `src-tauri/binaries/nexus-server-x86_64-pc-windows-msvc.exe` (~31 MB,
  one-file). Launched standalone (no Python on PATH), it serves `/api/health`,
  `/api/tasks` (full read-model shape), and the shell HTML on `:8791`. The
  Python half of the desktop app is packaged and working.
- **Tauri native window: still needs a build host.** `cargo` is not installed
  and Tauri's Windows link step needs the MSVC "Desktop development with C++"
  toolchain. `node` is present. Install Rust (`rustup`) + VS Build Tools, then
  `python desktop/build.py`.

## Not done here / caveats

- **The Rust side is written to the Tauri v2 API but not `cargo build`-verified
  in this environment** (no Rust toolchain / MSVC). The Python side — sidecar
  (now built + run-verified), path resolution, config parsing — is covered by
  `tests/` and the manual run above.
- The exact `shell:allow-execute` scope shape has shifted across
  `tauri-plugin-shell` point releases; verify `capabilities/default.json`
  against the version `npm install` resolves.
- Bundles are **unsigned** — SmartScreen / Gatekeeper will warn. Code signing
  (certs + `tauri.conf.json > bundle > {windows,macOS}`) is a separate ops step.
- No auto-update, tray, or single-instance guard yet — additive Tauri plugins.
