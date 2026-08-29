"""Local image understanding via an Ollama vision model (llava / llama3.2-vision /
qwen2.5vl). Text models can't see attachments; when a vision model is present we
turn each attached image into a text description that the rest of the pipeline —
interpreter, authoring, qa_explain — can reason over.

No new dependency (stdlib `urllib`). Inert when no vision model is pulled:
`available()` returns False and callers skip it.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
# any of these, first one present wins
_CANDIDATES = ("llava", "llava:13b", "llama3.2-vision", "qwen2.5vl", "bakllava", "moondream")

_DESCRIBE = (
    "Describe this image for someone who cannot see it. Cover: what it shows, any "
    "text or numbers visible (quote them), chart/diagram structure and the trend "
    "or point it makes, and colours/layout only if they carry meaning. Be concrete "
    "and compact — no preamble."
)


class OllamaVisionLLM:
    def __init__(self, model: str | None = None, *, host: str = _HOST,
                 timeout_s: float = 180.0) -> None:
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.model = model or os.environ.get("OLLAMA_VISION_MODEL") or self._detect()

    # -- discovery ---------------------------------------------- #
    def _tags(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=4) as r:
                return [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return []

    def _detect(self) -> str:
        tags = self._tags()
        names = {t.split(":")[0]: t for t in tags} | {t: t for t in tags}
        for cand in _CANDIDATES:
            if cand in names:
                return names[cand]
        return ""

    def available(self) -> bool:
        if not self.model:
            return False
        tags = self._tags()
        return self.model in tags or self.model.split(":")[0] in {t.split(":")[0] for t in tags}

    # -- use --------------------------------------------------- #
    def describe(self, image_path: str, *, prompt: str = _DESCRIBE) -> str:
        try:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except OSError:
            return ""
        body = json.dumps({
            "model": self.model, "prompt": prompt, "images": [b64],
            "stream": False, "options": {"temperature": 0.0},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                return (json.loads(r.read()).get("response") or "").strip()
        except (urllib.error.URLError, OSError, ValueError) as exc:  # noqa: BLE001
            return f"(image description unavailable: {exc})"
