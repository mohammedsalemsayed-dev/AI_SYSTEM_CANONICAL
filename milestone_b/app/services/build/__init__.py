"""Builder seam factory."""

from __future__ import annotations

from app.services.build.base import BuildOutput, Builder

__all__ = ["Builder", "BuildOutput", "get_builder"]


def get_builder(kind: str = "agent_sdk"):
    if kind == "agent_sdk":
        from app.services.build.agent_sdk import AgentSDKBuilder

        return AgentSDKBuilder()
    raise ValueError(
        f"get_builder({kind!r}): only 'agent_sdk' is constructible here; "
        "use app.services.build.fake.ScriptedBuilder for offline/test runs"
    )
