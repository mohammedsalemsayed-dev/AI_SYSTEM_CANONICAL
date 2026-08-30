"""Sandbox seam (MILESTONE_C_PLAN.md sections 2, 4; design-notes 14.6).

`select_runner` returns the strongest available backend. A run that carries
untrusted content, or a real (non-test) run, must pass `require_isolation=True`
so the non-isolating fallback is refused rather than silently used.
"""

from __future__ import annotations

from app.services.sandbox.runner import (
    SandboxRefused,
    SandboxResult,
    SandboxRunner,
    SandboxSpec,
    SandboxUnavailable,
)

__all__ = [
    "SandboxRunner",
    "SandboxSpec",
    "SandboxResult",
    "SandboxUnavailable",
    "SandboxRefused",
    "select_runner",
]


def select_runner(*, require_isolation: bool) -> SandboxRunner:
    from app.services.sandbox.docker_backend import DockerSandbox
    from app.services.sandbox.subprocess_backend import SubprocessSandbox

    docker = DockerSandbox()
    if docker.available():
        return docker
    if require_isolation:
        raise SandboxUnavailable(
            "no isolating sandbox backend available (install Docker Desktop and "
            "build the runner image) and this run requires isolation"
        )
    return SubprocessSandbox()
