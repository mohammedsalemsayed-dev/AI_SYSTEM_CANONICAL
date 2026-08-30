"""Unit: the Ollama local-LLM seam degrades cleanly when no server is up
(MILESTONE §15.2 local tier). A live server is NOT required for these."""

from __future__ import annotations

import pytest

from app.llm import get_llm
from app.llm.local_llm import OllamaLLM
from app.services.routing.registry import ProviderRegistry

_DEAD = "http://127.0.0.1:9"  # nothing listens on port 9


def test_get_llm_local_returns_ollama_provider() -> None:
    llm = get_llm("local")
    assert llm.provider == "local" and isinstance(llm, OllamaLLM)
    assert get_llm("ollama").provider == "local"


def test_available_is_false_when_server_down() -> None:
    assert OllamaLLM(model="whatever:7b", host=_DEAD).available() is False


def test_complete_raises_clean_runtimeerror_when_server_down() -> None:
    with pytest.raises(RuntimeError) as ei:
        OllamaLLM(model="whatever:7b", host=_DEAD, timeout_s=2).complete(
            system="s", prompt="p"
        )
    assert "Ollama request failed" in str(ei.value)


def test_probe_local_is_a_noop_when_server_down() -> None:
    reg = ProviderRegistry()
    enabled = reg.probe_local(host=_DEAD)
    assert enabled == []
    assert all(not s.available for s in reg.all() if s.local)  # seam stays a seam
    assert {s.id for s in reg.available()} == {"agent_sdk"}


def test_seed_local_coder_names_a_real_model_but_stays_unavailable() -> None:
    reg = ProviderRegistry()
    lc = reg.require("local-coder")
    assert lc.model and lc.local and not lc.available
