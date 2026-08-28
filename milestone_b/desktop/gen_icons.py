"""Generate the app icon and the Tauri icon set (MILESTONE_H_TAURI_PLAN.md §2).

    python desktop/gen_icons.py

Writes `desktop/app-icon.png` (1024x1024, the source) and the sizes Tauri needs
into `desktop/src-tauri/icons/`. `.icns` (macOS) is produced by
`npm run tauri icon desktop/app-icon.png` on a Mac; this script also writes a
Windows `.ico`. Needs Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
ICONS = HERE / "src-tauri" / "icons"
BG = (11, 15, 20, 255)      # --bg from style.css
ACCENT = (79, 209, 197, 255)  # --accent
INK = (214, 224, 234, 255)


def _base(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 8
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)
    # a stylised "N": two verticals + a diagonal
    m = size // 5
    w = max(2, size // 12)
    d.line([(m, size - m), (m, m)], fill=ACCENT, width=w)
    d.line([(size - m, size - m), (size - m, m)], fill=ACCENT, width=w)
    d.line([(m, m), (size - m, size - m)], fill=INK, width=w)
    # a node dot at each terminal
    dot = max(2, size // 22)
    for x, y in [(m, m), (m, size - m), (size - m, m), (size - m, size - m)]:
        d.ellipse([x - dot, y - dot, x + dot, y + dot], fill=ACCENT)
    return img


def main() -> int:
    ICONS.mkdir(parents=True, exist_ok=True)
    src = _base(1024)
    src.save(HERE / "app-icon.png")

    for name, size in [
        ("32x32.png", 32),
        ("128x128.png", 128),
        ("128x128@2x.png", 256),
        ("icon.png", 512),
        ("Square150x150Logo.png", 150),
        ("Square44x44Logo.png", 44),
        ("StoreLogo.png", 50),
    ]:
        _base(size).save(ICONS / name)

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    _base(256).save(ICONS / "icon.ico", sizes=ico_sizes)

    print(f"wrote {HERE / 'app-icon.png'} and {len(list(ICONS.glob('*')))} files in {ICONS}")
    print("macOS: run `npm run tauri icon desktop/app-icon.png` to add icon.icns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
