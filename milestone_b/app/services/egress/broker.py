"""Egress broker (MILESTONE_C_PLAN.md section 2, DESIGN_TIGHTENING.md 14.3).

The only path to the network during a task. Enforces a per-task allowlist
(default deny), returns raw bytes tagged `retrieved_web`, and records every block.
Nothing inside the sandbox has network; research fetches go through here on the
control-plane side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

_DEFAULT_TIMEOUT_S = 15


class EgressDenied(RuntimeError):
    pass


@dataclass
class EgressResult:
    url: str
    content: bytes
    trust: str = "retrieved_web"
    status: int = 200


Opener = Callable[[str, float], bytes]


def _urllib_opener(url: str, timeout: float) -> bytes:
    from urllib.request import urlopen  # lazy; keeps import-time clean

    with urlopen(url, timeout=timeout) as resp:  # noqa: S310 - allowlist enforced above
        return resp.read()


@dataclass
class EgressBroker:
    allowlist: list[str] = field(default_factory=list)
    opener: Opener = _urllib_opener
    timeout_s: float = _DEFAULT_TIMEOUT_S
    blocked: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)

    def _norm(self) -> list[str]:
        return [a.strip().lower() for a in self.allowlist if a.strip()]

    def allows(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        return any(host == a or host.endswith("." + a) for a in self._norm())

    def fetch(self, url: str) -> EgressResult:
        if not self.allows(url):
            self.blocked.append(url)
            raise EgressDenied(
                f"egress to {url!r} denied: host not in allowlist {self._norm()}"
            )
        content = self.opener(url, self.timeout_s)
        self.fetched.append(url)
        return EgressResult(url=url, content=content, trust="retrieved_web")
