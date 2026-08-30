"""A minimal, dependency-free PDF 1.4 writer — just enough for a themed report.

Text (standard-14 fonts, no embedding), filled rectangles, and lines. Origin is
top-left in this API (PDF's native bottom-left is hidden). Not a general PDF lib;
it exists so the `authoring` PDF path works with no `pip install`.
"""

from __future__ import annotations

# Helvetica advance widths (per 1000 units) for ASCII 32..126 — enough to wrap
# text without a font file. Bold uses the same table (close enough for layout).
_HELV_W = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278,
    278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584,
    584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556,
    833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
    278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222,
    500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500,
    500, 334, 260, 334, 584,
)


def _char_w(ch: str) -> int:
    o = ord(ch)
    return _HELV_W[o - 32] if 32 <= o <= 126 else 556


def text_width(s: str, size: float) -> float:
    return sum(_char_w(c) for c in s) * size / 1000.0


def wrap(s: str, size: float, max_w: float) -> list[str]:
    out: list[str] = []
    for para in s.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = (line + " " + word).strip()
            if text_width(trial, size) <= max_w or not line:
                line = trial
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


# the standard-14 fonts use WinAnsi (latin-1-ish); transliterate the handful of
# common non-latin-1 chars a model emits so they don't render as "?".
_TRANS = str.maketrans({
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "•": chr(149),
    " ": " ", "→": "->", "–": "-", "·": chr(183),
})


def _esc(s: str) -> str:
    s = s.translate(_TRANS)
    return (s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))


class PDF:
    def __init__(self, width: float = 612.0, height: float = 792.0) -> None:
        self.w, self.h = width, height
        self._pages: list[list[str]] = []
        self.new_page()

    # -- page ops ------------------------------------------------- #
    def new_page(self) -> None:
        self._pages.append([])

    @property
    def _cur(self) -> list[str]:
        return self._pages[-1]

    def _y(self, top_y: float) -> float:
        return self.h - top_y  # flip to PDF bottom-left origin

    # -- draw ops ------------------------------------------------- #
    def rect(self, x: float, y: float, w: float, h: float, color=(0, 0, 0)) -> None:
        r, g, b = (c / 255 for c in color)
        self._cur.append(f"{r:.3f} {g:.3f} {b:.3f} rg "
                         f"{x:.2f} {self._y(y + h):.2f} {w:.2f} {h:.2f} re f")

    def line(self, x1, y1, x2, y2, color=(0, 0, 0), width=1.0) -> None:
        r, g, b = (c / 255 for c in color)
        self._cur.append(f"{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w "
                         f"{x1:.2f} {self._y(y1):.2f} m {x2:.2f} {self._y(y2):.2f} l S")

    def text(self, x: float, y: float, s: str, *, size=11.0, bold=False,
             color=(0, 0, 0)) -> None:
        r, g, b = (c / 255 for c in color)
        font = "F2" if bold else "F1"
        self._cur.append(
            f"BT /{font} {size:.2f} Tf {r:.3f} {g:.3f} {b:.3f} rg "
            f"1 0 0 1 {x:.2f} {self._y(y + size):.2f} Tm ({_esc(s)}) Tj ET"
        )

    def paragraph(self, x: float, y: float, s: str, *, size=11.0, bold=False,
                  color=(0, 0, 0), max_w: float, leading: float | None = None) -> float:
        lead = leading or size * 1.4
        for ln in wrap(s, size, max_w):
            self.text(x, y, ln, size=size, bold=bold, color=color)
            y += lead
        return y

    # -- serialise --------------------------------------------- #
    def output(self) -> bytes:
        objs: list[bytes] = []

        def add(body: bytes) -> int:
            objs.append(body)
            return len(objs)

        font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        # build content + page objects
        content_nums: list[int] = []
        for ops in self._pages:
            stream = ("\n".join(ops)).encode("latin-1", "replace")
            content_nums.append(add(
                b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
            ))
        pages_num = len(objs) + len(self._pages) + 1
        page_nums: list[int] = []
        for cn in content_nums:
            page_nums.append(add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> "
                b"/Contents %d 0 R >>" % (pages_num, self.w, self.h, font1, font2, cn)
            ))
        kids_str = " ".join(f"{n} 0 R" for n in page_nums).encode()
        assert add(b"<< /Type /Pages /Kids [%s] /Count %d >>"
                   % (kids_str, len(page_nums))) == pages_num
        catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_num)

        # assemble file with xref
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref_pos = len(out)
        out += b"xref\n0 %d\n" % (len(objs) + 1)
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += b"%010d 00000 n \n" % off
        out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF"
                % (len(objs) + 1, catalog, xref_pos))
        return bytes(out)
