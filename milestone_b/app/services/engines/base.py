"""Engine adapter contract (MILESTONE_N_PLAN.md §2)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ExpertProfile(BaseModel):
    name: str
    prompt: str = ""
    do: list[str] = Field(default_factory=list)
    dont: list[str] = Field(default_factory=list)


class EngineInfo(BaseModel):
    engine: str = "generic"
    version_hint: str = ""
    source_globs: list[str] = Field(default_factory=list)
    asset_globs: list[str] = Field(default_factory=list)
    build_cmd: str = ""
    test_cmd: str = ""
    entrypoints: list[str] = Field(default_factory=list)
    conventions: dict[str, str] = Field(default_factory=dict)
    confidence: float = 0.0


@runtime_checkable
class EngineAdapter(Protocol):
    name: str

    def detect(self, root: str) -> float: ...

    def info(self, root: str) -> EngineInfo: ...

    def expert_profile(self) -> ExpertProfile: ...


def render_profile(profile: ExpertProfile, info: EngineInfo | None = None) -> str:
    lines = [f"EXPERT MODE — {profile.name}"]
    if profile.prompt:
        lines.append(profile.prompt.strip())
    for d in profile.do[:6]:
        lines.append(f"  do: {d}")
    for d in profile.dont[:6]:
        lines.append(f"  don't: {d}")
    if info and (info.engine != "generic" or info.test_cmd):
        lines.append(
            f"ENGINE: {info.engine}"
            + (f" {info.version_hint}" if info.version_hint else "")
            + (f" · verify: {info.test_cmd}" if info.test_cmd else "")
        )
    return "\n".join(lines[:12]) + "\n"
