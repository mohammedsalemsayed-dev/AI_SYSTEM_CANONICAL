"""Build the `nexus-server` sidecar with PyInstaller (MILESTONE_H_TAURI_PLAN.md §2).

    python desktop/build_sidecar.py

Produces a one-file executable and copies it to
`desktop/src-tauri/binaries/nexus-server-<target-triple>[.exe]`, the name Tauri's
`externalBin` expects. Needs `pyinstaller` on PATH (`pip install pyinstaller`).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent  # milestone_b/
ENTRY = REPO / "app" / "ui" / "sidecar_main.py"
WEB = REPO / "app" / "ui" / "web"
BIN_DIR = HERE / "src-tauri" / "binaries"


def target_triple() -> str:
    """Best-effort rustc host triple so the artifact name matches Tauri's lookup."""
    try:
        out = subprocess.run(
            ["rustc", "-Vv"], capture_output=True, text=True, check=True
        ).stdout
        for line in out.splitlines():
            if line.startswith("host: "):
                return line.split(" ", 1)[1].strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    # fall back to a platform guess
    plat = sysconfig.get_platform()  # e.g. win-amd64, macosx-11.0-arm64, linux-x86_64
    if plat.startswith("win"):
        return "x86_64-pc-windows-msvc"
    if plat.startswith("macosx"):
        return "aarch64-apple-darwin" if "arm64" in plat else "x86_64-apple-darwin"
    return "aarch64-unknown-linux-gnu" if "aarch64" in plat else "x86_64-unknown-linux-gnu"


def main() -> int:
    if shutil.which("pyinstaller") is None:
        print("error: pyinstaller not found. `pip install pyinstaller`", file=sys.stderr)
        return 2
    if not ENTRY.is_file():
        print(f"error: entry not found: {ENTRY}", file=sys.stderr)
        return 2

    work = HERE / "_pyi"
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        "pyinstaller", "--noconfirm", "--clean", "--onefile",
        "--name", "nexus-server",
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "build"),
        "--specpath", str(work),
        "--add-data", f"{WEB}{sep}app/ui/web",
        "--collect-submodules", "app",
        "--hidden-import", "app.ui.server",
        str(ENTRY),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO)

    ext = ".exe" if sys.platform == "win32" else ""
    built = work / "dist" / f"nexus-server{ext}"
    if not built.is_file():
        print(f"error: expected artifact missing: {built}", file=sys.stderr)
        return 1

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = BIN_DIR / f"nexus-server-{target_triple()}{ext}"
    shutil.copy2(built, dest)
    print(f"sidecar -> {dest}  ({dest.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
