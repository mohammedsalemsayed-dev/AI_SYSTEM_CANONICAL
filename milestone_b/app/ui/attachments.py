"""Chat attachments for the desktop shell.

A message can carry files (docs, images, code). The composer base64-encodes them
and POSTs `/api/attachments`; they are written into the session folder so the
agent can read them, and — for document types — ingested into a throwaway
KnowledgeBase so an `authoring` task can ground its draft on them.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from pathlib import Path
from typing import Any

_MAX_BYTES = 12 * 1024 * 1024  # per request, total
_DOC_EXT = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".pdf", ".docx"}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
             ".c", ".h", ".cpp", ".cs", ".sh", ".sql", ".html", ".css", ".yaml", ".yml", ".toml"}


def _safe_name(name: str) -> str:
    base = os.path.basename(name or "file").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^\w.\- ]+", "_", base).strip() or "file"
    return base[:128]


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in _IMG_EXT:
        return "image"
    if ext in _DOC_EXT:
        return "document"
    if ext in _CODE_EXT:
        return "code"
    return "file"


def save_attachments(workspace: str, files: list[dict]) -> list[dict[str, Any]]:
    """`files` = [{"name": str, "b64": str}]. Writes each into `workspace`,
    returns [{"name", "path", "kind", "bytes"}]. Skips anything oversized/bad."""
    ws = Path(workspace)
    if not ws.is_dir():
        return []
    out: list[dict[str, Any]] = []
    total = 0
    for f in files or []:
        name = _safe_name(str(f.get("name", "")))
        try:
            raw = base64.b64decode(str(f.get("b64", "")), validate=True)
        except (binascii.Error, ValueError):
            continue
        total += len(raw)
        if not raw or total > _MAX_BYTES:
            continue
        dest = ws / name
        # don't clobber an existing repo file
        if dest.exists():
            stem, ext = dest.stem, dest.suffix
            dest = ws / f"{stem}_attached{ext}"
        try:
            dest.write_bytes(raw)
        except OSError:
            continue
        out.append({"name": dest.name, "path": str(dest),
                    "kind": kind_of(dest.name), "bytes": len(raw)})
    return out


def _extract_text(path: str) -> str:
    p = Path(path)
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(p))
            return "\n\n".join((pg.extract_text() or "") for pg in reader.pages)[:200_000]
        if ext == ".docx":
            import docx

            d = docx.Document(str(p))
            return "\n".join(par.text for par in d.paragraphs)[:200_000]
        return p.read_text("utf-8", errors="replace")[:200_000]
    except Exception:  # noqa: BLE001 — extraction is best-effort
        return ""


def build_kb(saved: list[dict]):
    """A throwaway in-memory KnowledgeBase over the document attachments, or None."""
    docs = [s for s in saved if s["kind"] in ("document", "code")]
    if not docs:
        return None
    from app.services.kb.store import KnowledgeBase

    kb = KnowledgeBase()
    ingested = ingest_attachments(kb, saved)
    return kb if ingested else None


def ingest_attachments(kb, saved: list[dict]) -> int:
    """Ingest the document/code attachments into an existing KnowledgeBase.
    Returns the count ingested. Used to feed both the throwaway authoring KB and
    the orchestrator's persistent `kb` (so a doc_analysis follow-up stays
    grounded on the attachment after the turn that supplied it)."""
    docs = [s for s in saved if s["kind"] in ("document", "code")]
    ingested = 0
    for s in docs:
        text = _extract_text(s["path"])
        if text.strip():
            kb.ingest_text(text, uri=s["name"], title=s["name"])
            ingested += 1
    return ingested


def describe_images(saved: list[dict]) -> dict[str, str]:
    """{name: description} for image attachments, via a local Ollama vision model
    if one is pulled. Empty when none available (callers just skip it)."""
    imgs = [s for s in saved if s["kind"] == "image"]
    if not imgs:
        return {}
    try:
        from app.llm.vision import OllamaVisionLLM

        vlm = OllamaVisionLLM()
        if not vlm.available():
            return {}
        out: dict[str, str] = {}
        for s in imgs:
            desc = vlm.describe(s["path"])
            if desc:
                out[s["name"]] = desc
        return out
    except Exception:  # noqa: BLE001 — vision is best-effort
        return {}


def prompt_note(saved: list[dict], image_descriptions: dict[str, str] | None = None) -> str:
    if not saved:
        return ""
    desc = image_descriptions or {}
    lines = ["[The user attached these files (now in the working folder):]"]
    for s in saved:
        tag = {"image": "", "document": " — use as source material",
               "code": " — reference code"}.get(s["kind"], "")
        if s["kind"] == "image":
            tag = " — description below" if s["name"] in desc else " — image (no vision model; not readable locally)"
        lines.append(f"  - {s['name']} ({s['kind']}, {s['bytes']} bytes){tag}")
    for name, d in desc.items():
        lines.append(f"\n[Contents of {name} (from a vision model):]\n{d[:1600]}")
    lines.append("")
    return "\n".join(lines)
