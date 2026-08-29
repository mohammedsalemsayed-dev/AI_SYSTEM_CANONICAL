"""Render docs/demo.gif — an animated terminal replay of a real `run_task --full`.

The script below is a faithful condensation of an actual run (captured
2026-08-29): local `qwen3:8b` interprets + plans + edits, its diff fails T0
verification, the orchestrator auto-escalates to cloud Claude, that diff passes
in the Docker sandbox, the task completes verified, and the fix is written back.

    python docs/make_demo.py        # -> docs/demo.gif   (Pillow + Consolas only)
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).with_name("demo.gif")
COLS, ROWS = 92, 20
FS = 20

BG = (13, 17, 23)          # #0d1117
FG = (201, 209, 217)       # #c9d1d9
DIM = (139, 148, 158)      # #8b949e
GREEN = (63, 185, 80)      # #3fb950
BLUE = (88, 166, 255)      # #58a6ff
RED = (248, 81, 73)        # #f85149
AMBER = (210, 153, 34)     # #d29922
BAR = (22, 27, 34)

# (text, color).  A line is a list of spans.
S = "  "
STORY: list[list[tuple[str, tuple]]] = [
    [("$ ", GREEN), ('run_task "Fix slugify(): strip punctuation, collapse separators" \\', FG)],
    [("      --workspace ./repo --full --apply", FG)],
    [("", FG)],
    [("  full stack  ", DIM), ("brainstorm . router . local-first builder + cloud fallback", DIM)],
    [("              ", DIM), (". critic . T2(cloud) . tool registry . per-file policy", DIM)],
    [("", FG)],
    [(S + "> ", DIM), ("INTERPRETING   ", BLUE), ("local:qwen3:8b", DIM)],
    [(S + "> ", DIM), ("PLANNING       ", BLUE), ("ROUTE builder -> local-coder", DIM),
     ("   BRAINSTORM 3 approaches", DIM)],
    [(S + "> ", DIM), ("EXECUTING      ", BLUE), ("qwen3:8b edits strutil.py", DIM),
     ("   POLICY ok fs.write", DIM)],
    [(S + "> ", DIM), ("VERIFYING      ", BLUE), ("T0 ", DIM), ("FAIL", RED),
     ("   local diff rejected", DIM)],
    [(S + "> ", DIM), ("ESCALATION     ", AMBER), ("verification failed  ->  agent_sdk (cloud)", AMBER)],
    [(S + "> ", DIM), ("EXECUTING      ", BLUE), ("cloud Claude edits strutil.py", DIM)],
    [(S + "> ", DIM), ("VERIFYING      ", BLUE), ("T0 ", DIM), ("PASS", GREEN),
     ("   Docker sandbox     CRITIC accept", DIM)],
    [(S + "> ", DIM), ("COMPLETED      ", GREEN), ("verified = true", GREEN)],
    [("", FG)],
    [(S + "=== apply ===  ", DIM), ("applied  (strutil.py)", GREEN)],
    [("", FG)],
    [("$ ", GREEN), ("pytest -q", FG)],
    [(S, FG), ("3 passed", GREEN), (" in 0.01s", DIM)],
]

# ms to linger after a line appears (draw attention to the beats)
HOLD = {9: 950, 10: 1100, 12: 950, 13: 1200, 15: 950, 18: 1400}
STEP_MS = 260      # ordinary line reveal
TYPE_MS = 45       # per typing frame
END_MS = 1800      # final hold before the loop restarts


def _font(bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (("consolab.ttf",) if bold else ("consola.ttf",)):
        for base in (r"C:\Windows\Fonts", "/usr/share/fonts", "/Library/Fonts"):
            p = Path(base) / name
            if p.is_file():
                return ImageFont.truetype(str(p), FS)
    return ImageFont.load_default()


def main() -> None:
    font = _font()
    bold = _font(bold=True)
    cw = font.getbbox("M")[2]
    lh = FS + 8
    pad = 18
    bar_h = 30
    W = pad * 2 + cw * COLS
    H = bar_h + pad + lh * ROWS

    def blank() -> Image.Image:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, bar_h], fill=BAR)
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([pad + i * 22, bar_h // 2 - 6, pad + i * 22 + 12, bar_h // 2 + 6], fill=c)
        d.text((W // 2 - 90, bar_h // 2 - FS // 2 - 1), "run_task  —  nexus", font=font, fill=DIM)
        return img

    def render(n_lines: int, typed: int | None) -> Image.Image:
        img = blank()
        d = ImageDraw.Draw(img)
        y = bar_h + pad
        for li in range(min(n_lines, len(STORY))):
            spans = STORY[li]
            x = pad
            last = li == n_lines - 1
            for si, (txt, col) in enumerate(spans):
                t = txt
                if last and typed is not None and li in (0, 17):
                    # type-on effect for the two command lines
                    budget = typed - sum(len(s[0]) for s in spans[:si])
                    if budget <= 0:
                        break
                    t = txt[:budget]
                f = bold if (col in (GREEN, RED, AMBER, BLUE) and txt.strip()) else font
                d.text((x, y), t, font=f, fill=col)
                x += cw * len(txt)
            if last and typed is not None and li in (0, 17):
                d.text((x, y), "_", font=font, fill=FG)
            y += lh
        return img

    frames: list[Image.Image] = []
    durs: list[int] = []

    def add(img: Image.Image, ms: int) -> None:
        frames.append(img)
        durs.append(ms)

    # type line 0
    cmd0 = sum(len(s[0]) for s in STORY[0])
    for k in range(0, cmd0 + 1, 3):
        add(render(1, k), TYPE_MS)
    add(render(2, None), 400)
    # reveal the rest, one line per frame, lingering on the beats
    for li in range(3, len(STORY)):
        if li == 17:  # the "$ pytest -q" line types on
            c17 = sum(len(s[0]) for s in STORY[17])
            for k in range(0, c17 + 1, 3):
                add(render(18, k), TYPE_MS)
            continue
        add(render(li + 1, None), HOLD.get(li, STEP_MS))
    add(render(len(STORY), None), END_MS)

    frames[0].save(
        OUT, save_all=True, append_images=frames[1:], loop=0,
        duration=durs, disposal=2,
    )
    kb = OUT.stat().st_size // 1024
    print(f"wrote {OUT}  ({W}x{H}, {len(frames)} frames, {sum(durs)/1000:.1f}s loop, {kb} KiB)")


if __name__ == "__main__":
    main()
