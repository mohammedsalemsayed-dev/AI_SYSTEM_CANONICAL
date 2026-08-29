"""Chat attachments: base64 files land in the workspace (name-sanitised),
document types feed a throwaway KB, images are flagged cloud-only."""

from __future__ import annotations

import base64
from pathlib import Path

from app.ui.attachments import (
    build_kb,
    describe_images,
    kind_of,
    prompt_note,
    save_attachments,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_save_sanitises_names_and_skips_bad(tmp_path: Path) -> None:
    saved = save_attachments(str(tmp_path), [
        {"name": "../../etc/passwd", "b64": _b64(b"root:x:0:0")},
        {"name": "notes.md", "b64": _b64(b"# hi\nbody")},
        {"name": "broken.txt", "b64": "not base64!!!"},
    ])
    names = {s["name"] for s in saved}
    assert "notes.md" in names
    assert not any("/" in n or "\\" in n or ".." in n for n in names)
    assert "broken.txt" not in names          # undecodable -> skipped
    assert (tmp_path / "notes.md").read_text() == "# hi\nbody"


def test_existing_file_not_clobbered(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("keep me")
    saved = save_attachments(str(tmp_path), [{"name": "data.csv", "b64": _b64(b"new")}])
    assert saved and saved[0]["name"] == "data_attached.csv"
    assert (tmp_path / "data.csv").read_text() == "keep me"


def test_kind_and_prompt_note(tmp_path: Path) -> None:
    saved = save_attachments(str(tmp_path), [
        {"name": "report.md", "b64": _b64(b"# Report\nRevenue up 12 percent.")},
        {"name": "chart.png", "b64": _b64(b"\x89PNG\r\n" + b"x" * 30)},
    ])
    assert kind_of("chart.png") == "image" and kind_of("report.md") == "document"
    note = prompt_note(saved)
    assert "report.md" in note and "chart.png" in note
    # no vision model in the test env -> images marked "not readable locally"
    assert "not readable locally" in note
    assert describe_images(saved) == {}  # inert without a pulled vision model
    # a supplied description is embedded verbatim
    note2 = prompt_note(saved, {"chart.png": "A bar chart: Q1 40, Q2 55, Q3 70."})
    assert "from a vision model" in note2 and "Q3 70" in note2


def test_build_kb_from_documents(tmp_path: Path) -> None:
    saved = save_attachments(str(tmp_path), [
        {"name": "a.md", "b64": _b64(b"# A\nThe API allows 100 requests per minute.")},
        {"name": "pic.jpg", "b64": _b64(b"\xff\xd8\xff" + b"x" * 20)},
    ])
    kb = build_kb(saved)
    assert kb is not None and len(kb.documents()) == 1   # only the .md, not the image
    assert build_kb([s for s in saved if s["kind"] == "image"]) is None
