"""Builder seam factory."""

from __future__ import annotations

from app.services.build.base import BuildOutput, Builder

__all__ = ["Builder", "BuildOutput", "get_builder"]


def get_builder(kind: str = "agent_sdk"):
    """`kind` may carry a model after a colon: `local:qwen3:8b`,
    `local:qwen2.5-coder:7b`. Bare `local` uses LocalBuilder's default model."""
    kind, _, model = kind.partition(":")
    if kind == "agent_sdk":
        from app.services.build.agent_sdk import AgentSDKBuilder

        return AgentSDKBuilder(model=model or None)
    if kind in ("local", "ollama"):
        from app.services.build.local_builder import LocalBuilder

        return LocalBuilder(model=model) if model else LocalBuilder()
    raise ValueError(
        f"get_builder({kind!r}): 'agent_sdk' or 'local[:<model>]'; "
        "use app.services.build.fake.ScriptedBuilder for offline/test runs"
    )
