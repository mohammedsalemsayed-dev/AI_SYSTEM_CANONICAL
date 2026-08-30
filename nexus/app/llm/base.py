"""The `LLM` seam. One synchronous `complete()` call; concrete providers behind it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    provider: str = ""
    model: str = ""


@runtime_checkable
class LLM(Protocol):
    provider: str
    model: str

    def complete(self, *, system: str, prompt: str) -> LLMResponse: ...
