"""Tier-A sandbox: an ephemeral Docker container (design-notes 14.6).

`--network none`, read-only root + tmpfs, cgroup cpu/memory/pid limits, all caps
dropped, no-new-privileges. The workdir is bind-mounted rw; task code runs there.

The Docker CLI call is built by `build_args` so it can be asserted in a unit test
with an injected command runner — no Docker needed to verify the flags. Real
execution needs Docker Desktop running and the runner image built:

    docker build -t slice-sandbox:pytest app/services/sandbox/images/pytest-runner
    python -m app.services.sandbox.docker_backend --selftest
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from app.services.sandbox.runner import SandboxResult, SandboxSpec
from app.services.secrets.store import SecretStore, scrub_env

IMAGE = os.environ.get("SLICE_SANDBOX_IMAGE", "slice-sandbox:pytest")


@dataclass
class _Cmd:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


CmdRunner = Callable[[list[str], int], _Cmd]


def _real_cmd(argv: list[str], timeout_s: int) -> _Cmd:
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s
        )
        return _Cmd(p.returncode, p.stdout, p.stderr)
    except subprocess.TimeoutExpired as exc:
        return _Cmd(124, exc.stdout or "", exc.stderr or "", timed_out=True)
    except FileNotFoundError:
        return _Cmd(127, "", "docker not found")


class DockerSandbox:
    name = "docker"
    isolation = "container"

    def __init__(
        self,
        image: str = IMAGE,
        cmd_runner: CmdRunner | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.image = image
        self._cmd = cmd_runner or _real_cmd
        self._store = secret_store or SecretStore()

    # ------------------------------------------------------------------ #
    def available(self) -> bool:
        try:
            res = self._cmd(
                ["docker", "version", "--format", "{{.Server.Version}}"], 10
            )
        except Exception:
            return False
        return res.exit_code == 0

    def image_present(self) -> bool:
        res = self._cmd(["docker", "image", "inspect", self.image], 10)
        return res.exit_code == 0

    def build_args(self, spec: SandboxSpec) -> list[str]:
        argv = [
            "docker", "run", "--rm",
            "--network", "bridge" if spec.network else "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=256m",
            "--tmpfs", "/run:rw,size=16m",
            "--mount", f"type=bind,src={os.path.abspath(spec.workdir)},dst=/work",
            "--workdir", "/work",
            "--cpus", str(spec.cpu),
            "--memory", f"{spec.memory_mb}m",
            "--pids-limit", str(spec.pids),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
        ]
        for key, val in scrub_env(spec.env, self._store).items():
            argv += ["--env", f"{key}={val}"]
        argv.append(self.image)
        argv += [("python" if tok == "python" else tok) for tok in spec.command]
        return argv

    def run(self, spec: SandboxSpec) -> SandboxResult:
        argv = self.build_args(spec)
        res = self._cmd(argv, spec.timeout_s + 15)
        return SandboxResult(
            exit_code=res.exit_code,
            stdout=res.stdout,
            stderr=res.stderr,
            timed_out=res.timed_out,
            backend=self.name,
            error=None if res.exit_code != 127 else res.stderr or "docker unavailable",
        )


def _selftest() -> int:
    box = DockerSandbox()
    if not box.available():
        print("docker not available")
        return 1
    if not box.image_present():
        print(f"image {box.image!r} not built — run: "
              f"docker build -t {box.image} app/services/sandbox/images/pytest-runner")
        return 1
    result = box.run(
        SandboxSpec(workdir=".", command=["python", "-c", "print('sandbox ok')"])
    )
    print(result)
    return 0 if result.ok and "sandbox ok" in result.stdout else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_selftest() if "--selftest" in sys.argv else 0)
