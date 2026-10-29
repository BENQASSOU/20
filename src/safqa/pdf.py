"""Minimal, dependency-free PDF writer for Safqa reports.

Standard Helvetica fonts with WinAnsi encoding (covers French), wrapped
paragraphs, tables with repeated headers, filled rectangles and a page
footer with "Page x / y".  Coordinates in the API are top-down points.
"""

import unicodedata
import zlib
from datetime import date

A4 = (595.28, 841.89)

# Helvetica / Helvetica-Bold advance widths (1/1000 em) for ASCII 32..126.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
         556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
         1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
         667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
         333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
         556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HELV_B = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
           556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
           975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
           667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
           333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
           611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
_EXTRA = {"•": 350, "–": 556, "—": 1000, "’": 222, "‘": 222, "«": 556,
          "»": 556, "…": 1000, "€": 556, "‰": 1000, "°": 400, "œ": 944,
          "Œ": 1000, "²": 333, "³": 333, " ": 278}
_REPLACE = {" ": " ", " ": " ", "≤": "<=", "≥": ">=", "→": "->",
            "←": "<-", "✓": "v", "✖": "x", "−": "-"}
FONTS = {"R": ("F1", "Helvetica", _HELV), "B": ("F2", "Helvetica-Bold", _HELV_B),
         "I": ("F3", "Helvetica-Oblique", _HELV)}


def _clean(text):
    text = "" if text is None else str(text)
    for k, v in _REPLACE.items():
        text = text.replace(k, v)
    return text


def char_width(ch, style="R"):
    table = FONTS[style][2]
    o = ord(ch)
    if 32 <= o <= 126:
        return table[o - 32]
    if ch in _EXTRA:
        return _EXTRA[ch]
    base = unicodedata.normalize("NFD", ch)[0]
    if base != ch and 32 <= ord(base) <= 126:
        return table[ord(base) - 32]
    return 556


def text_width(text, size, style="R"):
    return sum(char_width(c, style) for c in _clean(text)) * size / 1000.0


def _escape(text):
    raw = _clean(text).encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(color):
    if isinstance(color, str):
        c = color.lstrip("#")
        return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return color


def wrap(text, width, size, style="R"):
    lines = []
    for para in _clean(text).split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            cand = (cur + " " + w) if cur else w
            if text_width(cand, size, style) <= width or not cur:
                # hard-break words longer than the line
                while text_width(cand, size, style) > width and len(cand) > 1:
                    cut = len(cand)
                    while cut > 1 and text_width(cand[:cut], size, style) > width:
                        cut -= 1
                    lines.append(cand[:cut])
                    cand = cand[cut:]
                cur = cand
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


class PDF:
    def __init__(self, title="", subtitle="", company="", accent="#0B4F6C"):
        self.W, self.H = A4
        self.L, self.R, self.T, self.B = 40, 40, 46, 54
        self.title, self.subtitle, self.company = title, subtitle, company
        self.accent = accent
        self.pages = []
        self.y = 0
        self.new_page(first=True)

    @property
    def content_width(self):
        return self.W - self.L - self.R

    # ------------------------------------------------------------ primitives
    def _op(self, s):
        self.pages[-1].append(s)

    def new_page(self, first=False):
        self.pages.append([])
        self.y = self.T
        if first:
            self._banner()
        else:
            self.text(self.L, self.y, self.title, 8, "B", "#667085")
            self.line(self.L, self.y + 4, self.W - self.R, self.y + 4, "#E4E7EC", 0.6)
            self.y += 16

    def _banner(self):
        self.rect(0, 0, self.W, 96, self.accent)
        self.text(self.L, 32, self.company or "Safqa ERP", 10, "B", "#FFFFFF")
        self.text(self.L, 58, self.title, 18, "B", "#FFFFFF")
        if self.subtitle:
            self.text(self.L, 78, self.subtitle, 9.5, "R", "#D8E7EE")
        self.y = 118

    def ensure(self, h):
        if self.y + h > self.H - self.B:
            self.new_page()
            return True
        return False

    def text(self, x, y, s, size=10, style="R", color="#101828"):
        r, g, b = _rgb(color)
        self._op(b"BT /%s %.1f Tf %.3f %.3f %.3f rg %.2f %.2f Td (" % (
            FONTS[style][0].encode(), size, r, g, b, x, self.H - y) + _escape(s) + b") Tj ET")

    def text_right(self, x_right, y, s, size=10, style="R", color="#101828"):
        self.text(x_right - text_width(s, size, style), y, s, size, style, color)

    def text_center(self, x_center, y, s, size=10, style="R", color="#101828"):
        self.text(x_center - text_width(s, size, style) / 2, y, s, size, style, color)

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=0.6):
        ops = []
        if fill:
            ops.append(b"%.3f %.3f %.3f rg" % _rgb(fill))
        if stroke:
            ops.append(b"%.3f %.3f %.3f RG %.2f w" % (_rgb(stroke) + (lw,)))
        paint = b"B" if fill and stroke else (b"f" if fill else b"S")
        ops.append(b"%.2f %.2f %.2f %.2f re %s" % (x, self.H - y - h, w, h, paint))
        self._op(b" ".join(ops))

    def line(self, x1, y1, x2, y2, color="#D0D5DD", lw=0.6):
        self._op(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (
            _rgb(color) + (lw, x1, self.H - y1, x2, self.H - y2)))

    # ------------------------------------------------------------ flow
    def spacer(self, h=8):
        self.y += h

    def heading(self, s, size=13, color=None):
        self.ensure(size + 26)
        self.y += 8
        self.text(self.L, self.y + size, s, size, "B", color or self.accent)
        self.y += size + 5
        self.line(self.L, self.y, self.W - self.R, self.y, "#D0D5DD", 0.8)
        self.y += 8

    def para(self, s, size=9.5, style="R", color="#101828", indent=0, leading=1.35):
        width = self.content_width - indent
        for ln in wrap(s, width, size, style):
            self.ensure(size * leading)
            self.text(self.L + indent, self.y + size, ln, size, style, color)
            self.y += size * leading
        self.y += 2

    def kv(self, pairs, size=9.5, key_ratio=0.45, zebra=True):
        """Two-column key/value block."""
        kw = self.content_width * key_ratio
        vw = self.content_width - kw - 12
        for i, (k, v) in enumerate(pairs):
            klines = wrap(k, kw - 8, size, "R")
            vlines = wrap(v, vw, size, "B")
            h = max(len(klines), len(vlines)) * size * 1.3 + 6
            self.ensure(h)
            if zebra and i % 2 == 0:
                self.rect(self.L, self.y, self.content_width, h, "#F6F8FA")
            yy = self.y + 3 + size
            for ln in klines:
                self.text(self.L + 6, yy, ln, size, "R", "#475467")
                yy += size * 1.3
            yy = self.y + 3 + size
            for ln in vlines:
                self.text_right(self.W - self.R - 6, yy, ln, size, "B")
                yy += size * 1.3
            self.y += h
        self.y += 6

    def table(self, columns, rows, size=8.5, header_bg=None, zebra=True, totals=None):
        """columns: [(title, weight, align)], align in 'l','r','c'.
        rows: list of lists of str. totals: optional last row in bold."""
        total_w = sum(c[1] for c in columns)
        widths = [self.content_width * c[1] / total_w for c in columns]
        pad = 4
        header_bg = header_bg or self.accent

        def draw_header():
            hl = [wrap(c[0], w - 2 * pad, size, "B") for c, w in zip(columns, widths)]
            h = max(len(x) for x in hl) * size * 1.25 + 8
            self.ensure(h + size * 4 + 12)   # never leave a header alone at the page bottom
            self.rect(self.L, self.y, self.content_width, h, header_bg)
            x = self.L
            for (title, _w, align), w, lines in zip(columns, widths, hl):
                yy = self.y + 4 + size
                for ln in lines:
                    self._cell_text(x, w, yy, ln, size, "B", "#FFFFFF", align, pad)
                    yy += size * 1.25
                x += w
            self.y += h

        draw_header()
        all_rows = list(rows) + ([totals] if totals else [])
        for i, row in enumerate(all_rows):
            is_total = totals is not None and i == len(all_rows) - 1
            style = "B" if is_total else "R"
            cl = [wrap(str(v if v is not None else ""), w - 2 * pad, size, style) for v, w in zip(row, widths)]
            h = max(len(x) for x in cl) * size * 1.25 + 6
            if self.ensure(h):
                draw_header()
            if is_total:
                self.rect(self.L, self.y, self.content_width, h, "#E6F1F5")
            elif zebra and i % 2 == 1:
                self.rect(self.L, self.y, self.content_width, h, "#F6F8FA")
            x = self.L
            for (title, _w, align), w, lines in zip(columns, widths, cl):
                yy = self.y + 3 + size
                for ln in lines:
                    self._cell_text(x, w, yy, ln, size, style, "#101828", align, pad)
                    yy += size * 1.25
                x += w
            self.y += h
            self.line(self.L, self.y, self.W - self.R, self.y, "#EAECF0", 0.4)
        self.y += 8

    def _cell_text(self, x, w, y, s, size, style, color, align, pad):
        if align == "r":
            self.text_right(x + w - pad, y, s, size, style, color)
        elif align == "c":
            self.text_center(x + w / 2, y, s, size, style, color)
        else:
            self.text(x + pad, y, s, size, style, color)

    def kpis(self, items, size=9):
        """Row of KPI boxes: [(label, value, color)]."""
        n = len(items)
        gap = 8
        w = (self.content_width - gap * (n - 1)) / n
        h = 46
        self.ensure(h + 6)
        for i, (lbl, val, color) in enumerate(items):
            x = self.L + i * (w + gap)
            self.rect(x, self.y, w, h, "#F6F8FA", "#E4E7EC")
            self.rect(x, self.y, 3, h, color or self.accent)
            self.text(x + 9, self.y + 15, lbl, 7.5, "R", "#667085")
            self.text(x + 9, self.y + 34, val, 11.5 if text_width(val, 11.5, "B") < w - 14 else 9, "B")
        self.y += h + 10

    def bars(self, series, colors, legend, height=120):
        """Grouped vertical bar chart. series: [(label, v1, v2, ...)]."""
        self.ensure(height + 44)
        top = self.y
        vmax = max([max(s[1:]) for s in series] + [1])
        n = len(series)
        k = len(series[0]) - 1 if series else 1
        slot = self.content_width / max(n, 1)
        bw = min(14, (slot - 6) / k)
        base = top + height
        self.line(self.L, base, self.W - self.R, base, "#98A2B3", 0.6)
        for i, s in enumerate(series):
            x0 = self.L + i * slot + (slot - bw * k) / 2
            for j, v in enumerate(s[1:]):
                h = height * (v / vmax) if v > 0 else 0
                if h:
                    self.rect(x0 + j * bw, base - h, bw - 1, h, colors[j])
            self.text_center(self.L + i * slot + slot / 2, base + 10, s[0], 6.5, "R", "#475467")
        lx = self.L
        for c, name in zip(colors, legend):
            self.rect(lx, base + 18, 8, 8, c)
            self.text(lx + 11, base + 25, name, 7.5, "R", "#475467")
            lx += text_width(name, 7.5) + 30
        self.y = base + 36

    # ------------------------------------------------------------ output
    def output(self):
        n = len(self.pages)
        footer = "Safqa ERP - %s - édité le %s" % (self.company or "", date.today().strftime("%d/%m/%Y"))
        for i, ops in enumerate(self.pages):
            self.pages[i] = ops
            ops.append(b"0.80 0.82 0.85 RG 0.5 w %.2f %.2f m %.2f %.2f l S" % (
                self.L, self.B - 18, self.W - self.R, self.B - 18))
            for s, x, right in ((footer, self.L, False), ("Page %d / %d" % (i + 1, n), self.W - self.R, True)):
                xx = x - text_width(s, 7.5) if right else x
                ops.append(b"BT /F1 7.5 Tf 0.4 0.44 0.52 rg %.2f %.2f Td (" % (xx, self.B - 30) + _escape(s) + b") Tj ET")

        objects = []

        def add(obj):
            objects.append(obj)
            return len(objects)

        catalog = add(None)
        pages_obj = add(None)
        font_ids = {}
        for key, (name, base, _w) in FONTS.items():
            font_ids[name] = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>"
                                 % base.encode())
        res = b"<< /Font << " + b" ".join(b"/%s %d 0 R" % (k.encode(), v) for k, v in font_ids.items()) + b" >> >>"
        page_ids = []
        for ops in self.pages:
            stream = zlib.compress(b"\n".join(ops))
            cid = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
            page_ids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources %s /Contents %d 0 R >>"
                                % (pages_obj, self.W, self.H, res, cid)))
        objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
        objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % p for p in page_ids), len(page_ids))
        info = add(b"<< /Title (" + _escape(self.title) + b") /Producer (Safqa ERP) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, obj in enumerate(objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1, catalog, info, xref)
        return bytes(out)
