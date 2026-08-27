"""SandboxRunner protocol + value types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class SandboxUnavailable(RuntimeError):
    """No backend that meets the required isolation level is available."""


class SandboxRefused(RuntimeError):
    """The chosen backend cannot safely run this spec (e.g. fallback + untrusted)."""


@dataclass
class SandboxSpec:
    workdir: str  # host directory bind-mounted as the working dir
    command: list[str]  # logical argv; "python" is resolved per backend
    network: bool = False
    cpu: float = 2.0
    memory_mb: int = 2048
    pids: int = 512
    timeout_s: int = 300
    env: dict[str, str] = field(default_factory=dict)
    # False => this run involves untrusted content or is a real run; a
    # non-isolating backend must refuse it.
    allow_non_isolated: bool = True


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    backend: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None


@runtime_checkable
class SandboxRunner(Protocol):
    name: str
    isolation: str  # "container" | "none"

    def available(self) -> bool: ...

    def run(self, spec: SandboxSpec) -> SandboxResult: ...
