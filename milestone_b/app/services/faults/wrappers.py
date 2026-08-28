"""Fault-injecting wrappers (MILESTONE_Q_PLAN.md §2).

Each wraps a real dependency and, on a matching scheduled fault, raises the
*actual* exception class the real backend raises (or returns the real failure
result shape) — otherwise it delegates untouched.
"""

from __future__ import annotations

from urllib.error import URLError

from app.llm.anthropic_client import RefusalError
from app.llm.base import LLMResponse
from app.services.build.base import BuildOutput
from app.services.faults.model import FaultPlan
from app.services.sandbox.runner import SandboxResult, SandboxSpec, SandboxUnavailable


class FlakyLLM:
    provider = "flaky"

    def __init__(self, inner, plan: FaultPlan, *, model: str = "flaky-1") -> None:
        self._inner = inner
        self._plan = plan
        self.model = getattr(inner, "model", model)

    def complete(self, *, system: str, prompt: str) -> LLMResponse:
        for kind, exc in (
            ("llm_refusal", lambda: RefusalError("model declined the request (injected)")),
            ("llm_timeout", lambda: TimeoutError("llm call timed out (injected)")),
        ):
            if self._plan.should_fire(kind):
                raise exc()
        if self._plan.should_fire("llm_garbage"):
            return LLMResponse(text="not json {{{ ", provider=self.provider, model=self.model)
        return self._inner.complete(system=system, prompt=prompt)


class FlakyRunner:
    name = "flaky"

    def __init__(self, inner, plan: FaultPlan) -> None:
        self._inner = inner
        self._plan = plan

    def run(self, spec: SandboxSpec) -> SandboxResult:
        if self._plan.should_fire("sandbox_unavailable"):
            raise SandboxUnavailable("no isolating backend (injected)")
        if self._plan.should_fire("sandbox_crash"):
            raise RuntimeError("sandbox backend crashed (injected)")
        if self._plan.should_fire("sandbox_timeout"):
            return SandboxResult(exit_code=124, timed_out=True, backend=self.name)
        if self._plan.should_fire("sandbox_error"):
            return SandboxResult(exit_code=1, error="injected sandbox error", backend=self.name)
        return self._inner.run(spec)


_BAD_HUNK = (
    "diff --git a/does_not_exist.py b/does_not_exist.py\n"
    "--- a/does_not_exist.py\n+++ b/does_not_exist.py\n"
    "@@ -1,3 +1,3 @@\n context that will not match\n-old\n+new\n"
)


class FlakyBuilder:
    name = "flaky"

    def __init__(self, inner, plan: FaultPlan) -> None:
        self._inner = inner
        self._plan = plan

    def execute(self, *, task_id, step, contract, workspace) -> BuildOutput:
        if self._plan.should_fire("builder_exception"):
            raise RuntimeError("builder blew up (injected)")
        if self._plan.should_fire("partial_diff"):
            return BuildOutput(changed_paths=["does_not_exist.py"], diff=_BAD_HUNK)
        if self._plan.should_fire("empty_diff"):
            return BuildOutput(changed_paths=[], diff="")
        return self._inner.execute(
            task_id=task_id, step=step, contract=contract, workspace=workspace
        )


def flaky_opener(inner, plan: FaultPlan):
    def _open(url: str, timeout: float) -> bytes:
        if plan.should_fire("egress_flap"):
            raise URLError("connection reset (injected)")
        return inner(url, timeout)

    return _open
