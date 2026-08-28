"""LLM seam factory."""

from __future__ import annotations

from app.llm.base import LLM, LLMResponse

__all__ = ["LLM", "LLMResponse", "get_llm"]


def get_llm(kind: str = "agent_sdk"):
    """Return a real provider. `fake` is not built here — construct `ScriptedLLM`
    directly and inject it (tests do this).

    - `agent_sdk` (default): single-turn Claude Agent SDK query; uses the `claude`
      CLI's subscription auth, no API key, no per-token spend.
    - `anthropic`: raw Messages API; needs `ANTHROPIC_API_KEY`, billed per token.
    """
    if kind == "agent_sdk":
        from app.llm.agent_sdk_llm import AgentSDKLLM

        import os

        model = os.environ.get("SLICE_LLM_MODEL")
        return AgentSDKLLM(model=model)
    if kind == "anthropic":
        from app.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM()
    if kind in ("local", "ollama"):
        from app.llm.local_llm import OllamaLLM

        import os

        return OllamaLLM(model=os.environ.get("OLLAMA_MODEL"))
    raise ValueError(
        f"get_llm({kind!r}): use 'agent_sdk' (subscription), 'anthropic' (API key), "
        "or 'local'/'ollama' (Ollama server); app.llm.fake.ScriptedLLM for offline/test runs"
    )
