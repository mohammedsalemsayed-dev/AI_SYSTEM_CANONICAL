"""ArtifactRef + kinds (MILESTONE_P_PLAN.md §2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.contracts import new_id, now_ts

ArtifactKind = Literal[
    "diff", "research_answer", "kb_answer", "document", "file_snapshot"
]


class ArtifactRef(BaseModel):
    id: str = Field(default_factory=lambda: new_id("art"))
    sha: str = ""
    kind: str = "diff"
    bytes: int = 0
    task_id: str = ""
    logical_key: str = ""
    parent_id: str | None = None
    trust: str = "workspace"          # workspace | user | retrieved_web | doc_input
    truncated: bool = False
    archived: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)
    ts: float = Field(default_factory=now_ts)
