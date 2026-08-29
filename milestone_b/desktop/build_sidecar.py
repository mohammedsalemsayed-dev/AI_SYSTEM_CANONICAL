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


def _pyinstaller_cmd() -> list[str] | None:
    """Prefer the console script; fall back to `python -m PyInstaller` (the pip
    wheel does not always drop a `pyinstaller` shim on PATH)."""
    exe = shutil.which("pyinstaller")
    if exe:
        return [exe]
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "PyInstaller"]


def main() -> int:
    pyi = _pyinstaller_cmd()
    if pyi is None:
        print("error: PyInstaller not found. `pip install pyinstaller`", file=sys.stderr)
        return 2
    if not ENTRY.is_file():
        print(f"error: entry not found: {ENTRY}", file=sys.stderr)
        return 2

    work = HERE / "_pyi"
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        *pyi, "--noconfirm", "--clean", "--onefile",
        "--name", "nexus-server",
        "--distpath", str(work / "dist"),
        "--workpath", str(work / "build"),
        "--specpath", str(work),
        "--add-data", f"{WEB}{sep}app/ui/web",
        "--collect-submodules", "app",
        "--hidden-import", "app.ui.server",
        "--hidden-import", "app.ui.runner",
        "--hidden-import", "app.llm.vision",
        "--hidden-import", "app.services.verify.verifier_godot",
        "--hidden-import", "app.services.authoring.pdf_writer",
        "--hidden-import", "app.services.tools.adapters.mcp_tool",
        str(ENTRY),
    ]
    # Optional integrations — bundle each if installed: the cloud-escalation
    # path (claude_agent_sdk) and the authoring renderers (docx/pptx).
    for opt in ("claude_agent_sdk", "anthropic", "docx", "pptx", "pypdf"):
        try:
            __import__(opt)
        except ImportError:
            continue
        cmd[-1:-1] = ["--collect-all", opt]
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
