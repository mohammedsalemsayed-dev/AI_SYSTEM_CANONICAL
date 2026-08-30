"""Engine registry (MILESTONE_N_PLAN.md §2).

Resolve the highest-confidence adapter for a workspace. The generic adapter
always matches at a low floor, so `detect()` never returns nothing.
"""

from __future__ import annotations

from app.services.engines.android import AndroidAdapter
from app.services.engines.base import EngineAdapter, EngineInfo
from app.services.engines.generic import GenericAdapter

# order = tie-break preference (most specific first); generic is always last
_DEFAULT = [AndroidAdapter(), GenericAdapter()]


class EngineRegistry:
    def __init__(self, adapters: list[EngineAdapter] | None = None) -> None:
        self.adapters = adapters if adapters is not None else list(_DEFAULT)

    def detect(self, root: str) -> tuple[EngineAdapter, EngineInfo]:
        best: tuple[float, int, EngineAdapter] | None = None
        for i, ad in enumerate(self.adapters):
            try:
                conf = ad.detect(root)
            except Exception:  # noqa: BLE001 — a broken adapter must not sink detection
                conf = 0.0
            if best is None or conf > best[0] or (conf == best[0] and i < best[1]):
                best = (conf, i, ad)
        adapter = best[2] if best else GenericAdapter()
        info = adapter.info(root)
        info.confidence = best[0] if best else 0.0
        return adapter, info

    def for_name(self, name: str) -> EngineAdapter | None:
        return next((a for a in self.adapters if a.name == name.lower()), None)
