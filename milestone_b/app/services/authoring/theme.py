"""Presentation / document themes for the DOCX + PPTX renderers.

A small set of hand-tuned palettes + font pairings so `authoring` output looks
deliberate, not python-pptx default. Pick by name (keyword in the brief) or take
the default. Pure data — the renderers apply it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    # colors as (r, g, b)
    bg: tuple[int, int, int]
    ink: tuple[int, int, int]          # body text
    heading: tuple[int, int, int]      # heading / title text
    accent: tuple[int, int, int]       # bars, rules, bullets
    dim: tuple[int, int, int]          # captions, footers, page numbers
    band: tuple[int, int, int]         # title-slide / cover band fill
    band_ink: tuple[int, int, int]     # text on the band
    heading_font: str
    body_font: str
    mono_font: str = "Consolas"
    title_pt: int = 40                 # title-slide title size
    slide_title_pt: int = 30
    body_pt: int = 18
    dark: bool = False


_THEMES: dict[str, Theme] = {
    # calm corporate — the default
    "slate": Theme(
        name="slate",
        bg=(255, 255, 255), ink=(30, 34, 44), heading=(20, 24, 33),
        accent=(84, 87, 247), dim=(120, 128, 143),
        band=(20, 24, 33), band_ink=(255, 255, 255),
        heading_font="Calibri Light", body_font="Calibri",
    ),
    # dark keynote
    "midnight": Theme(
        name="midnight",
        bg=(13, 17, 28), ink=(214, 222, 235), heading=(255, 255, 255),
        accent=(109, 124, 255), dim=(120, 132, 156),
        band=(9, 12, 20), band_ink=(255, 255, 255),
        heading_font="Segoe UI Semibold", body_font="Segoe UI", dark=True,
    ),
    # warm editorial
    "editorial": Theme(
        name="editorial",
        bg=(250, 247, 240), ink=(40, 34, 28), heading=(28, 24, 20),
        accent=(191, 87, 60), dim=(122, 110, 96),
        band=(40, 34, 28), band_ink=(250, 247, 240),
        heading_font="Georgia", body_font="Georgia",
    ),
    # stark minimal
    "mono": Theme(
        name="mono",
        bg=(255, 255, 255), ink=(17, 17, 17), heading=(0, 0, 0),
        accent=(0, 0, 0), dim=(130, 130, 130),
        band=(0, 0, 0), band_ink=(255, 255, 255),
        heading_font="Consolas", body_font="Consolas",
    ),
}

DEFAULT = "slate"

_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("midnight", ("dark", "keynote", "midnight", "neon", "tech")),
    ("editorial", ("editorial", "warm", "magazine", "elegant", "classic", "serif")),
    ("mono", ("minimal", "mono", "monochrome", "stark", "black and white", "black-and-white")),
    ("slate", ("corporate", "clean", "professional", "business", "slate", "blue")),
)


def theme_names() -> list[str]:
    return list(_THEMES)


def get_theme(name: str | None) -> Theme:
    return _THEMES.get((name or DEFAULT).lower().strip(), _THEMES[DEFAULT])


def theme_for_brief(brief: str) -> Theme:
    low = f" {brief.lower()} "
    for tname, needles in _KEYWORDS:
        if any(n in low for n in needles):
            return _THEMES[tname]
    return _THEMES[DEFAULT]
