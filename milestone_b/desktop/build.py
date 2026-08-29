"""One-command native build (MILESTONE_H_TAURI_PLAN.md §2, §5).

    python desktop/build.py

Steps:
  1. build the `nexus-server` sidecar (PyInstaller)          -> build_sidecar.py
  2. install the Tauri CLI                                    -> npm ci  (or npm install)
  3. bundle the native app                                    -> npm run tauri build

Exits non-zero with a named missing prerequisite if `pyinstaller`, `npm`, or
`cargo` is absent. The bundle lands under
`desktop/src-tauri/target/release/bundle/`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def _resolve(tool: str) -> str | None:
    """Full path to `tool` — on Windows this also finds npm.cmd / cargo.exe,
    which bare `subprocess.run(["npm", ...])` cannot."""
    return shutil.which(tool)


def _need(tool: str, hint: str) -> str | None:
    if _resolve(tool) is None:
        return f"missing prerequisite: {tool!r} not on PATH — {hint}"
    return None


def _need_pyinstaller() -> str | None:
    """Accept either the `pyinstaller` shim or the importable module — the pip
    wheel does not always install a console script."""
    if _resolve("pyinstaller"):
        return None
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        return "missing prerequisite: PyInstaller not installed — pip install pyinstaller"
    return None


def main() -> int:
    problems = [
        p for p in (
            _need("python", "install Python 3.12+"),
            _need_pyinstaller(),
            _need("npm", "install Node.js 18+ (https://nodejs.org)"),
            _need("cargo", "install Rust (https://rustup.rs) + platform build tools"),
        ) if p
    ]
    if problems:
        for p in problems:
            print("error:", p, file=sys.stderr)
        print(
            "\nThis environment is missing the toolchain, so the binary cannot be "
            "produced here. Install the above and re-run.",
            file=sys.stderr,
        )
        return 2

    npm = _resolve("npm")

    print("== 1/3  building the nexus-server sidecar ==")
    subprocess.run([sys.executable, str(HERE / "build_sidecar.py")], check=True)

    print("== 2/3  installing the Tauri CLI ==")
    lock = HERE / "package-lock.json"
    subprocess.run([npm, "ci" if lock.is_file() else "install"], check=True, cwd=HERE)

    print("== 3/3  bundling the native app ==")
    subprocess.run([npm, "run", "tauri", "build"], check=True, cwd=HERE)

    bundle = HERE / "src-tauri" / "target" / "release" / "bundle"
    print(f"\ndone — bundles under {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
