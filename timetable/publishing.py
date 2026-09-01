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

from .services import WEEKDAYS, format_12h, to_minutes

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


def text_width(text: str, size: float, bold: bool = False) -> float:
    total = sum(_HELVETICA_WIDTHS.get(char, 556) for char in _ascii(text))
    return total / 1000.0 * size * (1.05 if bold else 1.0)


def _fit(text: str, size: float, max_width: float, bold: bool = False) -> str:
    text = _ascii(text)
    if text_width(text, size, bold) <= max_width:
        return text
    ellipsis = ".."
    while text and text_width(text + ellipsis, size, bold) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ""


def _wrap(text: str, size: float, max_width: float, bold: bool = False, max_lines: int = 2) -> list[str]:
    words = _ascii(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if text_width(candidate, size, bold) <= max_width or not current:
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
    lines[-1] = _fit(lines[-1], size, max_width, bold)
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
    """Minimal multi-page PDF writer (Helvetica / Helvetica-Bold only)."""

    def __init__(self, width: float = A4_LANDSCAPE[0], height: float = A4_LANDSCAPE[1]) -> None:
        self.width = width
        self.height = height
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
        self.text(cx - text_width(value, size, bold) / 2.0, y, value, size, bold, color)

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

        font_regular = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        font_bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

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
        pdf.text_centre(cx, top + 17, _fit(column, 8.5, column_width - 6, True), size=8.5, bold=True, color=(1, 1, 1))

    for row, label in enumerate(row_labels):
        y = top + header_height + row * row_height
        pdf.rect(margin, y, label_width, row_height, fill=BAND, stroke=GRID_LINE)
        pdf.text(margin + 6, y + (14 if row_sublabels else row_height / 2 + 3),
                 _fit(label, 9, label_width - 12, True), size=9, bold=True)
        if row_sublabels and row < len(row_sublabels) and row_sublabels[row]:
            pdf.text(margin + 6, y + 26, _fit(row_sublabels[row], 7.5, label_width - 12), size=7.5, color=GREY_TEXT)

        for column in range(len(columns)):
            x = margin + label_width + column * column_width
            entry = cell_for(row, column)
            fill = _rgb(entry.get("color")) if entry else None
            pdf.rect(x, y, column_width, row_height, fill=fill, stroke=GRID_LINE)
            if not entry:
                continue
            ink = _ink(fill or (1, 1, 1))
            lines = _wrap(entry["title"], 8.5, column_width - 8, True, max_lines=2)
            text_y = y + 13
            for line in lines:
                pdf.text(x + 4, text_y, line, size=8.5, bold=True, color=ink)
                text_y += 10
            for note in entry.get("notes", [])[:2]:
                if text_y > y + row_height - 3:
                    break
                pdf.text(x + 4, text_y, _fit(note, 7.5, column_width - 8), size=7.5, color=ink)
                text_y += 9

    baseline = top + header_height + len(row_labels) * row_height + 14
    pdf.text(margin, min(baseline, pdf.height - margin + 6), footer, size=7.5, color=GREY_TEXT)


def _entry_cell(entry: dict[str, Any], *, show_room: bool = True) -> dict[str, Any]:
    code = entry.get("code") or ""
    notes = [str(entry.get("instructor") or "Unassigned")]
    if show_room:
        notes.append(str(entry.get("room_label") or ""))
    return {
        "color": entry.get("color"),
        "title": f"{code + ' ' if code else ''}{entry['course_name']} ({entry['section']})",
        "notes": [note for note in notes if note],
    }


def build_pdf(
    entries: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    scope: str = "all",
    days: int = 5,
    slots: list[dict[str, str]] | None = None,
    title: str = "University Timetable",
) -> bytes:
    """Render a printable PDF.

    ``scope``
        ``all``           - one page per day, rooms down the side (master grid)
        ``teacher``       - one page per teacher, days down the side
        ``section``       - one page per course section
        ``room``          - one page per room
    Filter the ``entries`` before calling to publish a single teacher/section.
    """
    pdf = PdfCanvas(*A4_LANDSCAPE)
    slots = slots or _slots_from(entries)
    columns = [f"{format_12h(s['start'])} - {format_12h(s['end'])}" for s in slots]
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    days = max(1, min(7, days))

    if not entries:
        pdf.text(40, 60, title, size=16, bold=True)
        pdf.text(40, 82, "There is nothing scheduled yet.", size=10, color=GREY_TEXT)
        return pdf.build(title)

    def personal(group_name: str, group_entries: list[dict[str, Any]], subtitle: str) -> None:
        pdf.new_page()
        lookup = {(int(e["day"]), e["start_time"]): e for e in group_entries}
        _draw_table(
            pdf,
            title=f"{title} - {group_name}",
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
                title=f"{title} - {WEEKDAYS[day - 1]}",
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
    shift: str | None = None,
) -> list[dict[str, Any]]:
    """Narrow a timetable down to one teacher / section / room / shift."""
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
    if shift and shift != "all":
        result = [e for e in result if (e.get("shift") or "morning") == shift]
    return result
