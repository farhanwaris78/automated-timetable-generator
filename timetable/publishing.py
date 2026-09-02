"""Publishing: printable PDF timetables and iCalendar (.ics) feeds.

Two deliberate design choices:

* **No third-party PDF library.**  ReportLab/WeasyPrint drag in C extensions
  and fonts that make the frozen executable fragile and much larger.  The
  writer below emits a valid PDF 1.4 file using only the standard library and
  the 14 built-in PDF fonts, so it behaves identically on Windows, macOS and
  Linux and adds nothing to the installer.
* **No third-party iCalendar library** - RFC 5545 for a weekly repeating
  lecture is a handful of lines, and hand-rolling it means the output stays
  readable and line-folded exactly as the spec requires.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Sequence

from .exporters import NON_CREDITED_LABEL, format_time_range
from .services import WEEKDAYS, format_12h, to_minutes

# Pastel day bands for the printed Class Schedule, matching the reference sheet.
SCHEDULE_DAY_FILLS = {
    1: (0.66, 0.77, 0.89),  # Monday   - blue
    2: (0.95, 0.72, 0.74),  # Tuesday  - rose
    3: (0.73, 0.67, 0.85),  # Wednesday- lavender
    4: (0.66, 0.84, 0.84),  # Thursday - teal
    5: (0.75, 0.71, 0.85),  # Friday   - lilac
    6: (0.84, 0.77, 0.88),  # Saturday - mauve
    7: (0.88, 0.82, 0.82),  # Sunday   - blush
}

# --------------------------------------------------------------------------- #
# tiny PDF writer
# --------------------------------------------------------------------------- #
# Advance widths (1/1000 em) of Helvetica for ASCII 32-126.  Used for real
# centring and for truncating text that will not fit a cell.
_HELVETICA_WIDTHS = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556,
    "8": 556, "9": 556, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556,
    "@": 1015, "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778,
    "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556,
    "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
    "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556,
    "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722,
    "x": 500, "y": 500, "z": 500, "{": 334, "|": 260, "}": 334, "~": 584,
}

# Advance widths (1/1000 em) of Times-Roman for ASCII 32-126 - the built-in
# PDF serif font that "Times New Roman" maps to.  This keeps the PDF free of
# embedded fonts (still fully offline and tiny) while giving the classic
# newspaper look the user asked for.
_TIMES_WIDTHS = {
    " ": 250, "!": 333, '"': 408, "#": 500, "$": 500, "%": 833, "&": 778, "'": 180,
    "(": 333, ")": 333, "*": 500, "+": 564, ",": 250, "-": 333, ".": 250, "/": 278,
    "0": 500, "1": 500, "2": 500, "3": 500, "4": 500, "5": 500, "6": 500, "7": 500,
    "8": 500, "9": 500, ":": 278, ";": 278, "<": 564, "=": 564, ">": 564, "?": 444,
    "@": 921, "A": 722, "B": 667, "C": 667, "D": 722, "E": 611, "F": 556, "G": 722,
    "H": 722, "I": 333, "J": 389, "K": 722, "L": 611, "M": 889, "N": 722, "O": 722,
    "P": 556, "Q": 722, "R": 667, "S": 556, "T": 611, "U": 722, "V": 722, "W": 944,
    "X": 722, "Y": 722, "Z": 611, "[": 333, "\\": 278, "]": 333, "^": 469, "_": 500,
    "`": 333, "a": 444, "b": 500, "c": 444, "d": 500, "e": 444, "f": 333, "g": 500,
    "h": 500, "i": 278, "j": 278, "k": 500, "l": 278, "m": 778, "n": 500, "o": 500,
    "p": 500, "q": 500, "r": 333, "s": 389, "t": 278, "u": 500, "v": 500, "w": 722,
    "x": 500, "y": 500, "z": 444, "{": 480, "|": 200, "}": 480, "~": 541,
}

# Courier is monospace: every glyph is the same width.
_COURIER_WIDTHS = {char: 600 for char in "".join(chr(i) for i in range(32, 127))}

_WIDTH_TABLES = {"helvetica": _HELVETICA_WIDTHS, "times": _TIMES_WIDTHS, "courier": _COURIER_WIDTHS}

# User-facing font name -> (PDF base font, PDF base bold font, width table key).
PDF_FONTS: dict[str, tuple[str, str, str]] = {
    "Times New Roman": ("/Times-Roman", "/Times-Bold", "times"),
    "Times": ("/Times-Roman", "/Times-Bold", "times"),
    "Georgia": ("/Times-Roman", "/Times-Bold", "times"),
    "Garamond": ("/Times-Roman", "/Times-Bold", "times"),
    "Arial": ("/Helvetica", "/Helvetica-Bold", "helvetica"),
    "Helvetica": ("/Helvetica", "/Helvetica-Bold", "helvetica"),
    "Calibri": ("/Helvetica", "/Helvetica-Bold", "helvetica"),
    "Courier New": ("/Courier", "/Courier-Bold", "courier"),
    "Courier": ("/Courier", "/Courier-Bold", "courier"),
}


def _font_key(name: str) -> str:
    """Normalise a user font name to a known key (default: serif Times)."""
    if not name:
        return "times"
    lowered = str(name).strip().lower()
    for font_name in PDF_FONTS:
        if font_name.lower() == lowered:
            return PDF_FONTS[font_name][2]
    return "times"


A4_LANDSCAPE = (841.89, 595.28)
A4_PORTRAIT = (595.28, 841.89)


def _ascii(text: Any) -> str:
    """PDF's built-in fonts are single byte - fold anything exotic to ASCII."""
    swaps = {"—": "-", "–": "-", "·": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "..."}
    out = []
    for char in str(text if text is not None else ""):
        char = swaps.get(char, char)
        out.append(char if 32 <= ord(char) < 127 else "?")
    return "".join(out)


def text_width(text: str, size: float, bold: bool = False, font: str = "helvetica") -> float:
    table = _WIDTH_TABLES.get(font, _HELVETICA_WIDTHS)
    total = sum(table.get(char, 556) for char in _ascii(text))
    return total / 1000.0 * size * (1.05 if bold else 1.0)


def _fit(text: str, size: float, max_width: float, bold: bool = False, font: str = "helvetica") -> str:
    text = _ascii(text)
    if text_width(text, size, bold, font) <= max_width:
        return text
    ellipsis = ".."
    while text and text_width(text + ellipsis, size, bold, font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ""


def _wrap(text: str, size: float, max_width: float, bold: bool = False, font: str = "helvetica",
          max_lines: int = 2) -> list[str]:
    words = _ascii(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if text_width(candidate, size, bold, font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return []
    lines[-1] = _fit(lines[-1], size, max_width, bold, font)
    return lines


def _rgb(hex_color: str, fallback: tuple[float, float, float] = (0.87, 0.89, 0.94)):
    value = str(hex_color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(char * 2 for char in value)
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return fallback


def _ink(rgb: Sequence[float]) -> tuple[float, float, float]:
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    return (0.09, 0.13, 0.24) if luminance > 0.6 else (1.0, 1.0, 1.0)


class PdfCanvas:
    """Minimal multi-page PDF writer using the 14 built-in PDF fonts.

    ``font`` is a width-table key (``times``, ``helvetica``, ``courier``) and
    selects the matching built-in base fonts, so a PDF can read as Times New
    Roman / Arial / Courier without embedding a single font file.
    """

    def __init__(self, width: float = A4_LANDSCAPE[0], height: float = A4_LANDSCAPE[1],
                 font: str = "times") -> None:
        self.width = width
        self.height = height
        self.font = _font_key(font) if font not in _WIDTH_TABLES else font
        self._pages: list[list[str]] = []
        self._ops: list[str] = []

    # ------------------------------------------------------------------ #
    def new_page(self) -> None:
        if self._ops:
            self._pages.append(self._ops)
        self._ops = []

    def _y(self, y: float) -> float:
        """Flip to PDF's bottom-left origin so callers can think top-down."""
        return self.height - y

    def rect(self, x, y, w, h, fill=None, stroke=None, line_width: float = 0.6) -> None:
        if fill is None and stroke is None:
            return
        ops = []
        if fill is not None:
            ops.append(f"{fill[0]:.3f} {fill[1]:.3f} {fill[2]:.3f} rg")
        if stroke is not None:
            ops.append(f"{stroke[0]:.3f} {stroke[1]:.3f} {stroke[2]:.3f} RG")
            ops.append(f"{line_width:.2f} w")
        ops.append(f"{x:.2f} {self._y(y) - h:.2f} {w:.2f} {h:.2f} re")
        ops.append("B" if (fill is not None and stroke is not None) else ("f" if fill is not None else "S"))
        self._ops.append(" ".join(ops))

    def text(self, x, y, value, size=9, bold=False, color=(0.09, 0.13, 0.24)) -> None:
        value = _ascii(value)
        if not value:
            return
        escaped = value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        font = "/F2" if bold else "/F1"
        self._ops.append(
            f"BT {font} {size:.2f} Tf {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
            f"{x:.2f} {self._y(y):.2f} Td ({escaped}) Tj ET"
        )

    def text_centre(self, cx, y, value, size=9, bold=False, color=(0.09, 0.13, 0.24)) -> None:
        self.text(cx - text_width(value, size, bold, self.font) / 2.0, y, value, size, bold, color)

    # ------------------------------------------------------------------ #
    def build(self, title: str = "Timetable") -> bytes:
        if self._ops:
            self._pages.append(self._ops)
            self._ops = []
        if not self._pages:
            self._pages = [[]]

        objects: list[bytes] = []

        def add(payload: bytes) -> int:
            objects.append(payload)
            return len(objects)          # 1-based object number

        base, base_bold, _ = PDF_FONTS.get(
            next((name for name, (_, _, key) in PDF_FONTS.items() if key == self.font), "."),
            ("/Times-Roman", "/Times-Bold", self.font),
        )
        font_regular = add(
            (f"<< /Type /Font /Subtype /Type1 /BaseFont {base} /Encoding /WinAnsiEncoding >>").encode("latin-1")
        )
        font_bold = add(
            (f"<< /Type /Font /Subtype /Type1 /BaseFont {base_bold} /Encoding /WinAnsiEncoding >>").encode("latin-1")
        )

        pages_id = len(objects) + 1 + 2 * len(self._pages)   # reserved below
        page_ids: list[int] = []
        for ops in self._pages:
            stream = "\n".join(ops).encode("latin-1", "replace")
            content_id = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            page_ids.append(
                add(
                    (
                        f"<< /Type /Page /Parent {pages_id} 0 R "
                        f"/MediaBox [0 0 {self.width:.2f} {self.height:.2f}] "
                        f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> "
                        f"/Contents {content_id} 0 R >>"
                    ).encode("latin-1")
                )
            )
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        real_pages_id = add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("latin-1"))
        assert real_pages_id == pages_id, "page-tree id calculation drifted"

        stamp = datetime.now().strftime("D:%Y%m%d%H%M%S")
        info_id = add(
            (
                f"<< /Title ({_ascii(title)}) /Producer (Automated Timetable Generator) "
                f"/CreationDate ({stamp}) >>"
            ).encode("latin-1")
        )
        catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin-1"))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, payload in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("latin-1") + payload + b"\nendobj\n"

        xref_at = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode("latin-1")
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("latin-1")
        return bytes(out)


# --------------------------------------------------------------------------- #
# timetable -> PDF
# --------------------------------------------------------------------------- #
HEADER_BLUE = (0.30, 0.36, 0.69)
GREY_TEXT = (0.36, 0.39, 0.47)
GRID_LINE = (0.75, 0.77, 0.85)
BAND = (0.95, 0.96, 0.98)


def _slots_from(entries: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    seen: dict[str, str] = {}
    for entry in entries:
        seen[entry["start_time"]] = entry["end_time"]
    return [{"start": start, "end": seen[start]} for start in sorted(seen, key=to_minutes)]


def _draw_table(
    pdf: PdfCanvas,
    *,
    title: str,
    subtitle: str,
    row_labels: list[str],
    row_sublabels: list[str],
    columns: list[str],
    cell_for: Callable[[int, int], dict[str, Any] | None],
    footer: str,
) -> None:
    """Shared renderer: rows down the left, time columns across the top."""
    margin = 28.0
    top = margin + 46
    pdf.text(margin, margin + 14, title, size=15, bold=True, color=(0.17, 0.20, 0.40))
    pdf.text(margin, margin + 29, subtitle, size=9, color=GREY_TEXT)

    usable = pdf.width - 2 * margin
    label_width = min(150.0, max(96.0, usable * 0.17))
    column_width = (usable - label_width) / max(1, len(columns))
    available = pdf.height - top - margin - 18
    row_height = min(58.0, max(26.0, available / max(1, len(row_labels))))
    header_height = 26.0

    pdf.rect(margin, top, usable, header_height, fill=HEADER_BLUE)
    pdf.text(margin + 8, top + 17, "Room / Time" if row_sublabels else "Day / Time",
             size=9, bold=True, color=(1, 1, 1))
    for index, column in enumerate(columns):
        cx = margin + label_width + column_width * (index + 0.5)
        pdf.text_centre(cx, top + 17, _fit(column, 8.5, column_width - 6, True, pdf.font), size=8.5, bold=True, color=(1, 1, 1))

    for row, label in enumerate(row_labels):
        y = top + header_height + row * row_height
        pdf.rect(margin, y, label_width, row_height, fill=BAND, stroke=GRID_LINE)
        pdf.text(margin + 6, y + (14 if row_sublabels else row_height / 2 + 3),
                 _fit(label, 9, label_width - 12, True, pdf.font), size=9, bold=True)
        if row_sublabels and row < len(row_sublabels) and row_sublabels[row]:
            pdf.text(margin + 6, y + 26, _fit(row_sublabels[row], 7.5, label_width - 12, False, pdf.font), size=7.5, color=GREY_TEXT)

        for column in range(len(columns)):
            x = margin + label_width + column * column_width
            entry = cell_for(row, column)
            fill = _rgb(entry.get("color")) if entry else None
            pdf.rect(x, y, column_width, row_height, fill=fill, stroke=GRID_LINE)
            if not entry:
                continue
            ink = _ink(fill or (1, 1, 1))
            lines = _wrap(entry["title"], 8.5, column_width - 8, True, pdf.font, max_lines=2)
            text_y = y + 13
            for line in lines:
                pdf.text(x + 4, text_y, line, size=8.5, bold=True, color=ink)
                text_y += 10
            for note in entry.get("notes", [])[:2]:
                if text_y > y + row_height - 3:
                    break
                pdf.text(x + 4, text_y, _fit(note, 7.5, column_width - 8, False, pdf.font), size=7.5, color=ink)
                text_y += 9

    baseline = top + header_height + len(row_labels) * row_height + 14
    pdf.text(margin, min(baseline, pdf.height - margin + 6), footer, size=7.5, color=GREY_TEXT)


def _draw_schedule_table(
    pdf: PdfCanvas,
    *,
    title: str,
    subtitle: str,
    rows: list[dict[str, Any]],
    footer: str,
) -> None:
    """Printed class schedule: a metadata block then day-grouped vertical rows.

    ``rows`` is a list of ``{"day": int, "cells": [8 strings]}`` already sorted
    by day/time; the Day cell is painted the pastel band for that weekday.
    """
    margin = 28.0
    top = margin + 46
    pdf.text(margin, margin + 14, _fit(title, 15, pdf.width - 2 * margin, True, pdf.font),
             size=15, bold=True, color=(0.17, 0.20, 0.40))
    if subtitle:
        pdf.text(margin, margin + 29, _fit(subtitle, 9, pdf.width - 2 * margin, False, pdf.font),
                 size=9, color=GREY_TEXT)

    headers = ["Days", "Course Code", "Course Title", "C.Hrs", "Students", "Teacher's Name", "Time", "Room No"]
    usable = pdf.width - 2 * margin
    widths = [0.08, 0.12, 0.23, 0.12, 0.07, 0.16, 0.16, 0.06]
    scaled = [w * usable for w in widths]
    x0 = margin
    header_height = 22.0
    row_height = 24.0
    header_y = top

    # title block band
    pdf.rect(margin, top - header_height, usable, row_height * max(1, len(rows)) + header_height,
             fill=(0.93, 0.95, 0.98), stroke=None)

    # header
    pdf.rect(margin, top, usable, header_height, fill=HEADER_BLUE)
    cx = x0
    for index, heading in enumerate(headers):
        w = scaled[index]
        pdf.text_centre(cx + w / 2, top + 14, _fit(heading, 8.5, w - 6, True, pdf.font),
                        size=8.5, bold=True, color=(1, 1, 1))
        cx += w

    current_day = None
    band = (1, 1, 1)
    y = top + header_height
    for entry in rows:
        if entry["day"] != current_day:
            current_day = entry["day"]
            band = SCHEDULE_DAY_FILLS.get(current_day, BAND)
        pdf.rect(margin, y, usable, row_height, fill=band, stroke=GRID_LINE)
        cx = x0
        cells = entry["cells"]
        for index, value in enumerate(cells):
            w = scaled[index]
            pdf.text(cx + 4, y + row_height / 2 + 3, _fit(value, 8.5, w - 8, index == 0, pdf.font),
                     size=8.5, bold=False, color=(0.09, 0.13, 0.24))
            cx += w
        y += row_height

    baseline = y + 14
    pdf.text(margin, min(baseline, pdf.height - margin + 6), footer, size=7.5, color=GREY_TEXT)


def _entry_cell(entry: dict[str, Any], *, show_room: bool = True, show_section: bool = True) -> dict[str, Any]:
    code = entry.get("code") or ""
    lab = " [LAB]" if entry.get("kind") == "lab" else ""
    notes = [str(entry.get("instructor") or "Unassigned")]
    if show_room:
        notes.append(str(entry.get("room_label") or ""))
    section = f" ({entry['section']})" if show_section else ""
    return {
        "color": entry.get("color"),
        "title": f"{code + ' ' if code else ''}{entry['course_name']}{section}{lab}",
        "notes": [note for note in notes if note],
    }


def _build_schedule_pdf(
    entries: list[dict[str, Any]],
    *,
    days: int = 5,
    title: str = "Class Schedule",
    font_name: str = "Times New Roman",
    institution: str = "",
    term: str = "",
    program: str = "",
    commencement: str = "",
    semester: str = "",
) -> bytes:
    """Render the printed Class Schedule as a single-page PDF."""
    pdf = PdfCanvas(*A4_LANDSCAPE, font=_font_key(font_name))
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    heading = str(title or "Class Schedule")
    if term:
        heading = f"{heading} {term}"
    meta_parts = [part for part in [institution, program, commencement, semester] if part]
    subtitle = " · ".join(meta_parts)

    ordered = sorted(entries, key=lambda e: (int(e["day"]), to_minutes(e["start_time"]), str(e.get("code", ""))))
    rows = []
    for entry in ordered:
        credits = int(entry.get("credit_hours") or 0)
        rows.append(
            {
                "day": int(entry["day"]),
                "cells": [
                    WEEKDAYS[int(entry["day"]) - 1],
                    str(entry.get("code") or ""),
                    str(entry.get("course_name") or ""),
                    NON_CREDITED_LABEL if credits == 0 else str(credits),
                    str(entry.get("num_students") or ""),
                    str(entry.get("instructor") or "Unassigned"),
                    format_time_range(str(entry.get("start_time", "")), str(entry.get("end_time", ""))),
                    str(entry.get("room_number") or entry.get("room_label") or ""),
                ],
            }
        )
    if not rows:
        pdf.text(40, 60, heading, size=16, bold=True)
        pdf.text(40, 82, "There is nothing scheduled yet.", size=10, color=GREY_TEXT)
        return pdf.build(heading)

    _draw_schedule_table(
        pdf,
        title=heading,
        subtitle=f"{subtitle} · {len(rows)} class(es)" if subtitle else f"{len(rows)} class(es)",
        rows=rows,
        footer=f"Generated {stamp} by Automated Timetable Generator",
    )
    return pdf.build(heading)


def _draw_report_page(
    pdf: PdfCanvas,
    *,
    title: str,
    subtitle: str,
    report: dict[str, Any],
    footer: str,
) -> None:
    """A single-page table for a report dict (headers + rows + a note)."""
    margin = 28.0
    top = margin + 46
    pdf.text(margin, margin + 14, _fit(title, 15, pdf.width - 2 * margin, True, pdf.font),
             size=15, bold=True, color=(0.17, 0.20, 0.40))
    if subtitle:
        pdf.text(margin, margin + 29, _fit(subtitle, 9, pdf.width - 2 * margin, False, pdf.font),
                 size=9, color=GREY_TEXT)

    headers = [str(h) for h in report.get("headers") or []]
    rows = report.get("rows") or []
    usable = pdf.width - 2 * margin
    ncols = max(1, len(headers))
    # Give the last column (usually the free-text "Issue"/"Load"/"Status") more room.
    if len(headers) >= 6:
        widths = [ust * usable for ust in (0.10, 0.09, 0.10, 0.15, 0.14, 0.22)]
        if len(headers) == 7:
            widths = [ust * usable for ust in (0.10, 0.10, 0.11, 0.13, 0.13, 0.13, 0.20)]
        elif len(headers) >= 8:
            widths = [ust * usable for ust in (0.09, 0.09, 0.11, 0.12, 0.10, 0.11, 0.12, 0.26)]
        widths = widths[:ncols]
        while len(widths) < ncols:
            widths.append(usable * 0.12)
        widths = [w * (usable / sum(widths)) for w in widths]
    else:
        widths = [usable / ncols] * ncols
    x0 = margin
    header_height = 22.0
    row_height_limit = pdf.height - top - margin - 18
    row_height = row_height_limit / max(1, len(rows)) if rows else 18.0
    row_height = min(20.0, max(14.0, row_height))

    # Background band behind the whole table.
    table_height = header_height + row_height * max(1, len(rows))
    pdf.rect(margin, top - header_height, usable, table_height + header_height,
             fill=(0.93, 0.95, 0.98), stroke=None)

    # header
    pdf.rect(margin, top, usable, header_height, fill=HEADER_BLUE)
    cx = x0
    for index, heading in enumerate(headers):
        w = widths[index]
        pdf.text_centre(cx + w / 2, top + 14, _fit(heading, 8.5, w - 6, True, pdf.font),
                        size=8.5, bold=True, color=(1, 1, 1))
        cx += w

    y = top + header_height
    for row_index, row in enumerate(rows):
        pdf.rect(margin, y, usable, row_height, fill=BAND if row_index % 2 else (1, 1, 1), stroke=GRID_LINE)
        cx = x0
        for index, value in enumerate(row[:ncols]):
            w = widths[index]
            pdf.text(cx + 4, y + row_height / 2 + 3,
                     _fit(value, 8.5, w - 8, index == 0, pdf.font),
                     size=8.5, bold=index == 0, color=(0.09, 0.13, 0.24))
            cx += w
        y += row_height

    baseline = y + 14
    pdf.text(margin, min(baseline, pdf.height - margin + 6), footer, size=7.5, color=GREY_TEXT)
    note = report.get("note")
    if note:
        pdf.text(margin, pdf.height - margin - 8, _fit(note, 8, usable, False, pdf.font),
                 size=8, color=GREY_TEXT)


def _build_report_pdf(
    entries: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    scope: str = "utilisation",
    days: int = 5,
    slots: list[dict[str, str]] | None = None,
    title: str = "University Timetable",
    font_name: str = "Times New Roman",
    institution: str = "",
    term: str = "",
) -> bytes:
    """Render one of the analytic reports (utilisation / workload / conflict)."""
    from .reports import conflict_report, room_utilisation, teacher_workload

    pdf = PdfCanvas(*A4_LANDSCAPE, font=_font_key(font_name))
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    heading = str(title or "University Timetable")
    if institution or term:
        heading = f"{heading} · {institution} · {term}".strip(" ·")

    if scope == "utilisation":
        report = room_utilisation(entries, rooms, days=days, slots=slots)
    elif scope == "workload":
        report = teacher_workload(entries)
    elif scope == "conflict":
        report = conflict_report(entries)
    else:
        raise ValueError(f"Unknown report scope {scope!r}")

    _draw_report_page(
        pdf,
        title=report.get("title", scope.title()),
        subtitle=f"{len(report.get('rows') or [])} row(s) · {heading}",
        report=report,
        footer=f"Generated {stamp} by Automated Timetable Generator",
    )
    return pdf.build(heading)


def _build_day_pdf(
    entries: list[dict[str, Any]],
    *,
    days: int = 5,
    title: str = "Class Schedule",
    font_name: str = "Times New Roman",
    institution: str = "",
    term: str = "",
    program: str = "",
    commencement: str = "",
    semester: str = "",
) -> bytes:
    """One landscape page per day, with a large day header."""
    pdf = PdfCanvas(*A4_LANDSCAPE, font=_font_key(font_name))
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    heading = str(title or "Class Schedule")
    if term:
        heading = f"{heading} {term}"
    meta_parts = [part for part in [institution, program, commencement, semester] if part]
    meta = " · ".join(meta_parts)

    ordered = sorted(entries, key=lambda e: (int(e["day"]), to_minutes(e["start_time"]), str(e.get("code", ""))))
    days_present = sorted({int(e["day"]) for e in ordered if 1 <= int(e["day"]) <= 7})
    if not days_present:
        pdf.text(40, 60, heading, size=16, bold=True)
        pdf.text(40, 82, "There is nothing scheduled yet.", size=10, color=GREY_TEXT)
        return pdf.build(heading)

    for position, day in enumerate(days_present[:7]):
        day_entries = [e for e in ordered if int(e["day"]) == day]
        rows = []
        for entry in day_entries:
            credits = int(entry.get("credit_hours") or 0)
            rows.append({
                "day": day,
                "cells": [
                    WEEKDAYS[day - 1],
                    str(entry.get("code") or ""),
                    str(entry.get("course_name") or ""),
                    NON_CREDITED_LABEL if credits == 0 else str(credits),
                    str(entry.get("num_students") or ""),
                    str(entry.get("instructor") or "Unassigned"),
                    format_time_range(str(entry.get("start_time", "")), str(entry.get("end_time", ""))),
                    str(entry.get("room_number") or entry.get("room_label") or ""),
                ],
            })
        if position:
            pdf.new_page()
        day_title = f"{heading} — {WEEKDAYS[day - 1]}"
        subtitle = f"Page {position + 1} of {len(days_present)} · {len(day_entries)} class(es)"
        if meta:
            subtitle = f"{meta} · {subtitle}"
        _draw_schedule_table(
            pdf,
            title=day_title,
            subtitle=subtitle,
            rows=rows,
            footer=f"Generated {stamp} by Automated Timetable Generator",
        )
    return pdf.build(heading)


def build_pdf(
    entries: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    scope: str = "all",
    days: int = 5,
    slots: list[dict[str, str]] | None = None,
    title: str = "University Timetable",
    font_name: str = "Times New Roman",
    institution: str = "",
    term: str = "",
    layout: str = "grid",
    program: str = "",
    commencement: str = "",
    semester: str = "",
) -> bytes:
    """Render a printable PDF.

    ``scope``
        ``all``           - one page per day, rooms down the side (master grid)
        ``teacher``       - one page per teacher, days down the side
        ``section``       - one page per course section
        ``room``          - one page per room
        ``semester``      - one page per semester, day x section rows
        ``schedule``      - the printed Class Schedule (day-grouped vertical rows)
    Filter the ``entries`` before calling to publish a single teacher/section.

    ``layout`` is ``schedule`` to use the printed Class Schedule look (a
    metadata title block plus rows grouped by day, with ``credit_hours == 0``
    courses shown as **non-credited course**); otherwise the grid scopes above
    apply.

    ``font_name`` is mapped to one of the PDF built-in fonts (Times New Roman
    / Georgia -> Times, Arial / Calibri -> Helvetica, Courier New -> Courier),
    so no font is embedded and the file stays tiny and fully offline.
    """
    if scope in ("utilisation", "workload", "conflict"):
        return _build_report_pdf(
            entries,
            rooms,
            scope=scope,
            days=days,
            slots=slots,
            title=title,
            font_name=font_name,
            institution=institution,
            term=term,
        )
    if scope == "day":
        return _build_day_pdf(
            entries,
            days=days,
            title=title,
            font_name=font_name,
            institution=institution,
            term=term,
            program=program,
            commencement=commencement,
            semester=semester,
        )
    if layout == "schedule":
        return _build_schedule_pdf(
            entries,
            days=days,
            title=title,
            font_name=font_name,
            institution=institution,
            term=term,
            program=program,
            commencement=commencement,
            semester=semester,
        )
    pdf = PdfCanvas(*A4_LANDSCAPE, font=_font_key(font_name))
    slots = slots or _slots_from(entries)
    columns = [f"{format_12h(s['start'])} - {format_12h(s['end'])}" for s in slots]
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    days = max(1, min(7, days))
    heading = title
    if institution or term:
        heading = f"{title} · {institution} · {term}".strip(" ·")

    if not entries:
        pdf.text(40, 60, title, size=16, bold=True)
        pdf.text(40, 82, "There is nothing scheduled yet.", size=10, color=GREY_TEXT)
        return pdf.build(title)

    def personal(group_name: str, group_entries: list[dict[str, Any]], subtitle: str) -> None:
        pdf.new_page()
        lookup = {(int(e["day"]), e["start_time"]): e for e in group_entries}
        _draw_table(
            pdf,
            title=f"{heading} - {group_name}",
            subtitle=subtitle,
            row_labels=[WEEKDAYS[day] for day in range(days)],
            row_sublabels=[],
            columns=columns,
            cell_for=lambda row, column: (
                _entry_cell(lookup[(row + 1, slots[column]["start"])])
                if (row + 1, slots[column]["start"]) in lookup
                else None
            ),
            footer=f"Generated {stamp} by Automated Timetable Generator",
        )

    if scope == "all":
        used = {e["room_id"] for e in entries}
        grid_rooms = [r for r in rooms if r["id"] in used] or rooms[:14]
        for day in range(1, days + 1):
            day_entries = [e for e in entries if int(e["day"]) == day]
            pdf.new_page()
            lookup = {(e["room_id"], e["start_time"]): e for e in day_entries}
            _draw_table(
                pdf,
                title=f"{heading} - {WEEKDAYS[day - 1]}",
                subtitle=f"{len(day_entries)} class(es) - page {day} of {days}",
                row_labels=[str(r.get("label") or r["room_number"]) for r in grid_rooms],
                row_sublabels=[f"{r.get('room_type', '')} - {r.get('capacity', '')} seats" for r in grid_rooms],
                columns=columns,
                cell_for=lambda row, column: (
                    _entry_cell(lookup[(grid_rooms[row]["id"], slots[column]["start"])], show_room=False)
                    if (grid_rooms[row]["id"], slots[column]["start"]) in lookup
                    else None
                ),
                footer=f"Generated {stamp} by Automated Timetable Generator",
            )
        return pdf.build(title)

    if scope == "teacher":
        groups: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            groups.setdefault(str(entry.get("instructor") or "Unassigned"), []).append(entry)
        for name in sorted(groups):
            hours = sum(
                (to_minutes(e["end_time"]) - to_minutes(e["start_time"])) for e in groups[name]
            ) / 60.0
            personal(name, groups[name], f"{len(groups[name])} class(es) - {hours:.1f} contact hours per week")
        return pdf.build(title)

    if scope == "section":
        groups = {}
        for entry in entries:
            key = f"{entry.get('code') or ''} {entry['course_name']} - {entry['section']}".strip()
            groups.setdefault(key, []).append(entry)
        for name in sorted(groups):
            teacher = groups[name][0].get("instructor") or "Unassigned"
            personal(name, groups[name], f"Teacher: {teacher} - {len(groups[name])} class(es) per week")
        return pdf.build(title)

    if scope == "room":
        groups = {}
        for entry in entries:
            groups.setdefault(str(entry.get("room_label") or entry["room_id"]), []).append(entry)
        for name in sorted(groups):
            personal(name, groups[name], f"{len(groups[name])} booking(s) per week")
        return pdf.build(title)

    if scope == "semester":
        # The batch view: rows are (day, section) so parallel sections of the
        # same semester are visible side by side and clashes jump out.
        groups = {}
        for entry in entries:
            groups.setdefault(int(entry.get("semester") or 0), []).append(entry)
        for semester in sorted(groups):
            group_entries = groups[semester]
            sections = sorted({str(e["section"]).upper() for e in group_entries})
            pairs = [(day, section) for day in range(1, days + 1) for section in sections]
            lookup = {
                (int(e["day"]), str(e["section"]).upper(), e["start_time"]): e for e in group_entries
            }
            pdf.new_page()
            _draw_table(
                pdf,
                title=f"{heading} - Semester {semester}" if semester else f"{heading} - Unassigned semester",
                subtitle=(
                    f"{len(group_entries)} class(es) - section(s) {', '.join(sections)} - "
                    f"{len({e.get('instructor') for e in group_entries})} teacher(s)"
                ),
                row_labels=[WEEKDAYS[day - 1] for day, _ in pairs],
                row_sublabels=[f"Section {section}" for _, section in pairs],
                columns=columns,
                cell_for=lambda row, column: (
                    _entry_cell(
                        lookup[(pairs[row][0], pairs[row][1], slots[column]["start"])],
                        show_section=False,
                    )
                    if (pairs[row][0], pairs[row][1], slots[column]["start"]) in lookup
                    else None
                ),
                footer=f"Generated {stamp} by Automated Timetable Generator",
            )
        return pdf.build(title)

    raise ValueError(f"Unknown publish scope {scope!r}")


# --------------------------------------------------------------------------- #
# timetable -> iCalendar
# --------------------------------------------------------------------------- #
def _fold(line: str) -> str:
    """RFC 5545 - no content line may exceed 75 octets."""
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    chunks, start = [], 0
    while start < len(raw):
        end = min(start + 73, len(raw))
        while end < len(raw) and (raw[end] & 0xC0) == 0x80:   # never split a UTF-8 sequence
            end -= 1
        chunks.append(raw[start:end].decode("utf-8"))
        start = end
    return "\r\n ".join(chunks)


def _escape_ics(value: Any) -> str:
    return (
        str(value if value is not None else "")
        .replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\n", r"\n")
    )


def build_ics(
    entries: list[dict[str, Any]],
    *,
    start_date: date | None = None,
    weeks: int = 16,
    calendar_name: str = "University Timetable",
) -> str:
    """One weekly-recurring VEVENT per scheduled class.

    Times are written as floating local time, which is what every calendar
    client shows in the user's own timezone - correct for a campus timetable
    that is always read on campus.
    """
    weeks = max(1, min(52, int(weeks)))
    start_date = start_date or date.today()
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Automated Timetable Generator//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics(calendar_name)}",
        "X-PUBLISHED-TTL:PT12H",
    ]

    for entry in sorted(entries, key=lambda e: (int(e["day"]), to_minutes(e["start_time"]))):
        weekday = int(entry["day"]) - 1                       # 0 = Monday
        offset = (weekday - start_date.weekday()) % 7
        first = start_date + timedelta(days=offset)
        start_h, start_m = divmod(to_minutes(entry["start_time"]), 60)
        end_h, end_m = divmod(to_minutes(entry["end_time"]), 60)

        code = entry.get("code") or ""
        summary = f"{code + ' ' if code else ''}{entry['course_name']} ({entry['section']})"
        seed = f"{entry.get('id') or ''}{entry['course_id']}{entry['section']}{entry['day']}{entry['start_time']}"
        uid = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]

        description = "; ".join(
            part
            for part in [
                f"Teacher: {entry.get('instructor') or 'Unassigned'}",
                f"Section: {entry['section']}",
                f"Shift: {str(entry.get('shift') or 'morning').capitalize()}",
                f"Students: {entry.get('num_students')}" if entry.get("num_students") else "",
            ]
            if part
        )

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@timetable-generator",
            f"DTSTAMP:{stamp}Z",
            f"DTSTART:{first.strftime('%Y%m%d')}T{start_h:02d}{start_m:02d}00",
            f"DTEND:{first.strftime('%Y%m%d')}T{end_h:02d}{end_m:02d}00",
            f"RRULE:FREQ=WEEKLY;COUNT={weeks}",
            _fold(f"SUMMARY:{_escape_ics(summary)}"),
            _fold(f"LOCATION:{_escape_ics(entry.get('room_label') or '')}"),
            _fold(f"DESCRIPTION:{_escape_ics(description)}"),
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    teacher: str | None = None,
    course_id: int | None = None,
    section: str | None = None,
    room_id: int | None = None,
    semester: int | None = None,
    shift: str | None = None,
) -> list[dict[str, Any]]:
    """Narrow a timetable down to one teacher / section / room / semester."""
    result = entries
    if teacher:
        needle = teacher.strip().lower()
        result = [e for e in result if str(e.get("instructor") or "").strip().lower() == needle]
    if course_id is not None:
        result = [e for e in result if int(e["course_id"]) == int(course_id)]
    if section:
        result = [e for e in result if str(e["section"]).upper() == str(section).upper()]
    if room_id is not None:
        result = [e for e in result if int(e["room_id"]) == int(room_id)]
    if semester:
        result = [e for e in result if int(e.get("semester") or 0) == int(semester)]
    if shift and shift != "all":
        result = [e for e in result if (e.get("shift") or "morning") == shift]
    return result