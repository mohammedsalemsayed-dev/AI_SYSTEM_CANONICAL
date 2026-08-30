"""Deterministic `LLM` for tests and offline runs.

`ScriptedLLM` is constructed with either:
  - a list of reply strings, consumed in order; or
  - a callable `(system, prompt) -> str`.
Every call is recorded in `.calls` for assertions.
"""

from __future__ import annotations

from typing import Callable

from app.llm.base import LLMResponse


class ScriptedLLM:
    provider = "fake"

    def __init__(
        self,
        responses: list[str] | tuple[str, ...] | Callable[[str, str], str],
        model: str = "scripted-1",
    ) -> None:
        self.model = model
        self._callable = responses if callable(responses) else None
        self._queue = list(responses) if not callable(responses) else []
        self._i = 0
        self.calls: list[dict[str, str]] = []

    def complete(self, *, system: str, prompt: str) -> LLMResponse:
        self.calls.append({"system": system, "prompt": prompt})
        if self._callable is not None:
            text = self._callable(system, prompt)
        else:
            if self._i >= len(self._queue):
                raise IndexError(
                    f"ScriptedLLM ran out of responses after {self._i} call(s)"
                )
            text = self._queue[self._i]
            self._i += 1
        return LLMResponse(
            text=text,
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            latency_s=0.0,
            provider=self.provider,
            model=self.model,
        )
