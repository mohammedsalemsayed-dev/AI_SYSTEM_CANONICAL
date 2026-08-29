"""Dev-only fallback: run the command as a host subprocess.

**This is not isolation** — no namespace, no network cut, no resource cap, and
(because Python on Windows needs %APPDATA% etc. to find site-packages) not even a
real env scrub. It exists only so the suite runs before Docker is installed, and
it refuses any spec marked `allow_non_isolated=False` (MILESTONE_C_PLAN.md 4).
Real isolation and env scrubbing are the Docker backend's job.
"""

from __future__ import annotations

import os
import subprocess
import sys

from app.services.sandbox.runner import SandboxRefused, SandboxResult, SandboxSpec
from app.services.secrets.store import SecretStore, scrub_env


class SubprocessSandbox:
    name = "subprocess-fallback"
    isolation = "none"

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self._store = secret_store or SecretStore()

    def available(self) -> bool:
        return True

    def run(self, spec: SandboxSpec) -> SandboxResult:
        if not spec.allow_non_isolated:
            raise SandboxRefused(
                "subprocess fallback is not isolation; refused for untrusted / real runs"
            )
        argv = [sys.executable if tok == "python" else tok for tok in spec.command]
        # inherit the host env so Python can find site-packages, then strip
        # anything secret-shaped before the child sees it.
        merged = dict(os.environ)
        merged["PYTHONDONTWRITEBYTECODE"] = "1"
        merged.update(spec.env)
        env = scrub_env(merged, self._store)
        try:
            p = subprocess.run(
                argv,
                cwd=spec.workdir,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=spec.timeout_s,
            )
            return SandboxResult(
                exit_code=p.returncode,
                stdout=p.stdout,
                stderr=p.stderr,
                backend=self.name,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                exit_code=124, timed_out=True, backend=self.name,
                error=f"timed out after {spec.timeout_s}s",
            )
