"""LLM seam factory."""

from __future__ import annotations

from app.llm.base import LLM, LLMResponse

__all__ = ["LLM", "LLMResponse", "get_llm"]


def get_llm(kind: str = "anthropic"):
    """Return a real provider. `fake` is not built here — construct `ScriptedLLM`
    directly and inject it (tests do this)."""
    if kind == "anthropic":
        from app.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM()
    raise ValueError(
        f"get_llm({kind!r}): only 'anthropic' is constructible here; "
        "use app.llm.fake.ScriptedLLM for offline/test runs"
    )
