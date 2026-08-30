"""`LLM` provider backed by a local Ollama server (design-notes §15.2 —
the local-model tier: "Ollama / llama.cpp, invoked by the router as one route
among cloud routes").

Talks to the Ollama HTTP API with the standard library only — no new dependency.
Unlike the `agent_sdk` path, Ollama returns real token counts
(`prompt_eval_count` / `eval_count`), so `MODEL_RUN` accounting works here.

Not exercised by the test suite (that runs on `ScriptedLLM`). This is the concrete
route the Router's `local-*` `ProviderSpec`s point at.

Config (env):
  OLLAMA_HOST   default http://localhost:11434
  OLLAMA_MODEL  default qwen2.5-coder:7b
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from app.llm.base import LLMResponse

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")


class OllamaLLM:
    provider = "local"

    def __init__(
        self,
        model: str | None = None,
        *,
        host: str | None = None,
        timeout_s: float = 300.0,
        num_ctx: int | None = None,
        temperature: float = 0.0,
        keep_alive: str | None = None,
        think: bool = False,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.timeout_s = timeout_s
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.think = think
        # how long Ollama keeps the model in VRAM after a call — a longer value
        # avoids a cold reload between the Interpreter and Planner calls.
        self.keep_alive = keep_alive or os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

    # -- health -------------------------------------------------------- #
    def available(self) -> bool:
        """True if the Ollama server answers and has this model pulled."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as resp:
                tags = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return False
        names = {m.get("name", "") for m in tags.get("models", [])}
        return self.model in names or f"{self.model}:latest" in names or any(
            n.split(":", 1)[0] == self.model.split(":", 1)[0] for n in names
        )

    # -- inference --------------------------------------------------- #
    def complete(self, *, system: str, prompt: str) -> LLMResponse:
        options: dict = {"temperature": self.temperature}
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        body = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": options,
            "keep_alive": self.keep_alive,
            # Interpreter/Planner want a single JSON object, not a chain-of-thought
            # preamble. Qwen3 thinks by default and buries the JSON after a large
            # <think> block that breaks tolerant parsing; other models ignore this.
            "think": self.think,
        }
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Ollama request failed (host {self.host}, model {self.model!r}): {exc}"
            ) from exc

        return LLMResponse(
            text=payload.get("response", ""),
            input_tokens=int(payload.get("prompt_eval_count", 0) or 0),
            output_tokens=int(payload.get("eval_count", 0) or 0),
            latency_s=time.time() - t0,
            provider=self.provider,
            model=self.model,
        )
