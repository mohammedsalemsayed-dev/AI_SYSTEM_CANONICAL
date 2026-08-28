"""LLM seam factory."""

from __future__ import annotations

import os

from app.llm.base import LLM, LLMResponse

__all__ = ["LLM", "LLMResponse", "get_llm"]


def get_llm(kind: str = "agent_sdk"):
    """Return a real provider. `fake` is not built here — construct `ScriptedLLM`
    directly and inject it (tests do this).

    `kind` may carry an explicit model after a colon, e.g. `local:llama3.1:8b`,
    `agent_sdk:claude-opus-5`, `anthropic:claude-sonnet-5`. Without one, each
    provider falls back to its own env var / default. The colon form is what lets
    different agent roles run on different models (see `app/cli/run_task.py`).

    - `agent_sdk` (default): single-turn Claude Agent SDK query; uses the `claude`
      CLI's subscription auth, no API key, no per-token spend.
    - `anthropic`: raw Messages API; needs `ANTHROPIC_API_KEY`, billed per token.
    - `local` / `ollama`: a local Ollama server (no key, no spend).
    """
    kind, _, model = kind.partition(":")
    model = model or None

    if kind == "agent_sdk":
        from app.llm.agent_sdk_llm import AgentSDKLLM

        return AgentSDKLLM(model=model or os.environ.get("SLICE_LLM_MODEL"))
    if kind == "anthropic":
        from app.llm.anthropic_client import AnthropicLLM

        return AnthropicLLM(model=model) if model else AnthropicLLM()
    if kind in ("local", "ollama"):
        from app.llm.local_llm import OllamaLLM

        return OllamaLLM(model=model or os.environ.get("OLLAMA_MODEL"))
    raise ValueError(
        f"get_llm({kind!r}): use 'agent_sdk' (subscription), 'anthropic' (API key), "
        "or 'local'/'ollama' (Ollama server) — optionally '<kind>:<model>'; "
        "app.llm.fake.ScriptedLLM for offline/test runs"
    )
