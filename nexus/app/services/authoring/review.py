"""Review (MILESTONE_M_PLAN.md §2, §7.1).

Structural checks + one LLM pass over the section texts and their citation ids.
Advisory — issues are reported, never block. `authoring` gets this pass by design;
a high-stakes doc has the router escalate it to a cloud model.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.services.authoring.model import DocumentModel


class Issue(BaseModel):
    kind: str        # empty-section | heading-only | missing-citation | duplicate-title |
                     # unsupported-claim | overclaim | inconsistent | unsupported-section
    section: str = ""
    detail: str = ""
    severity: str = "minor"   # blocking | major | minor


_SYSTEM = """You review document sections for factual problems. For each section you get its
text and the ids of the claims it cites. Flag: an assertion with no citation
(unsupported-claim), a claim stated more strongly than a source would support (overclaim),
or a contradiction with another section (inconsistent). Reply with ONLY JSON:
{"issues": [{"kind": string, "section": string, "detail": string, "severity": "blocking|major|minor"}]}"""


def review(model: DocumentModel, llm: LLM) -> list[Issue]:
    issues: list[Issue] = []
    seen_titles: set[str] = set()

    for sec in model.walk():
        if sec.title.lower() in seen_titles:
            issues.append(Issue(kind="duplicate-title", section=sec.title,
                                detail="another section has the same title", severity="minor"))
        seen_titles.add(sec.title.lower())

        if "unsupported-section" in sec.flags:
            issues.append(Issue(kind="unsupported-section", section=sec.title,
                                detail="no supporting material was found", severity="major"))

        real = [b for b in sec.blocks if b.text.strip() and not b.text.strip().startswith("_(")]
        if not sec.children and not real:
            issues.append(Issue(kind="empty-section", section=sec.title,
                                detail="section has no body", severity="major"))
        elif not sec.children and all(b.kind == "heading" for b in sec.blocks):
            issues.append(Issue(kind="heading-only", section=sec.title,
                                detail="section is a heading with no prose", severity="minor"))

        if sec.is_factual() and not any(b.citation_ids for b in sec.blocks):
            issues.append(Issue(kind="missing-citation", section=sec.title,
                                detail="factual section with no citations", severity="major"))

    # one LLM pass over drafted sections
    drafted = [
        s for s in model.walk()
        if any(b.kind == "paragraph" and b.text and not b.text.startswith("_(") for b in s.blocks)
    ]
    if drafted:
        payload = "\n\n".join(
            f"### {s.title}\n{s.text_body()}\nCITES: "
            + ", ".join(sorted({c for b in s.blocks for c in b.citation_ids}))
            for s in drafted
        )
        try:
            parsed = parse_json_object(llm.complete(system=_SYSTEM, prompt=payload).text)
            for it in parsed.get("issues", []):
                k = str(it.get("kind", "")).strip()
                if k:
                    issues.append(Issue(
                        kind=k, section=str(it.get("section", "")),
                        detail=str(it.get("detail", "")),
                        severity=str(it.get("severity", "minor")),
                    ))
        except Exception:
            pass
    return issues
