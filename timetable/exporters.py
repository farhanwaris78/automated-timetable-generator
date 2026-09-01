"""Excel (.xlsx) export - one worksheet per day, plus summary sheets.

Uses openpyxl, which is pure Python and therefore bundles cleanly into the
frozen executable.  If openpyxl is somehow unavailable the caller falls back
to CSV so the feature degrades instead of crashing.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from .services import WEEKDAYS, format_12h, to_minutes

HEADER_FILL = "FF4C5CAF"
BAND_FILL = "FFF2F4F9"


def openpyxl_available() -> bool:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return False
    return True


def _ink_for(hex_color: str) -> str:
    """Black or white text, whichever is readable on the given background."""
    value = (hex_color or "").lstrip("#")
    if len(value) != 6:
        return "FF000000"
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return "FF16223D" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "FFFFFFFF"


def _argb(hex_color: str, fallback: str = "FFDDDDDD") -> str:
    value = (hex_color or "").lstrip("#").upper()
    return f"FF{value}" if len(value) == 6 else fallback


def _class_label(entry: dict[str, Any]) -> str:
    code = entry.get("code") or ""
    lab = " [LAB]" if (entry.get("kind") == "lab") else ""
    return f"{code + ' · ' if code else ''}{entry['course_name']} ({entry['section']}){lab}"


def build_workbook(
    entries: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    days: int = 5,
    slots: list[dict[str, str]] | None = None,
    shift: str = "all",
    title: str = "University Timetable",
    unscheduled: list[dict[str, Any]] | None = None,
) -> bytes:
    """Render the timetable into an .xlsx workbook and return the bytes.

    * one sheet per day (Monday … Sunday, as many as ``days``)
    * **one sheet per semester** - the batch view, day × section rows
    * a "Summary" sheet listing every class
    * a "By Teacher" sheet - each teacher's personal week
    * an "Unscheduled" sheet when something has not been placed
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin = Side(style="thin", color="FFBFC5D8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    centre = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    if shift and shift != "all":
        entries = [e for e in entries if (e.get("shift") or "morning") == shift]

    # Derive the slot list from the data when the caller did not supply one.
    if not slots:
        seen: dict[str, str] = {}
        for entry in entries:
            seen[entry["start_time"]] = entry["end_time"]
        slots = [{"start": s, "end": seen[s]} for s in sorted(seen, key=to_minutes)]

    used_rooms = {e["room_id"] for e in entries}
    grid_rooms = [r for r in rooms if r["id"] in used_rooms] or rooms[:12]

    workbook = Workbook()
    workbook.remove(workbook.active)

    def style_header(cell) -> None:
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.font = Font(bold=True, color="FFFFFFFF", size=11)
        cell.alignment = centre
        cell.border = border

    # ---------------------------------------------------------------- days --
    for day in range(1, max(1, min(7, days)) + 1):
        sheet = workbook.create_sheet(WEEKDAYS[day - 1])
        day_entries = [e for e in entries if int(e["day"]) == day]

        sheet["A1"] = f"{title} — {WEEKDAYS[day - 1]}"
        sheet["A1"].font = Font(bold=True, size=14, color="FF2B3465")
        span = max(2, len(slots) + 1)
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
        sheet["A1"].alignment = left
        label = "All shifts" if shift == "all" else f"{shift.capitalize()} shift"
        sheet.cell(row=2, column=1, value=f"{label} · {len(day_entries)} class(es)").font = Font(
            italic=True, size=10, color="FF5B6479"
        )

        header_row = 4
        head = sheet.cell(row=header_row, column=1, value="Room / Time")
        style_header(head)
        for index, slot in enumerate(slots, start=2):
            style_header(
                sheet.cell(
                    row=header_row,
                    column=index,
                    value=f"{format_12h(slot['start'])}\n{format_12h(slot['end'])}",
                )
            )

        lookup = {(e["start_time"], e["room_id"]): e for e in day_entries}
        for offset, room in enumerate(grid_rooms):
            row_index = header_row + 1 + offset
            room_cell = sheet.cell(
                row=row_index,
                column=1,
                value=f"{room.get('label') or room['room_number']}  ({room.get('capacity', '')} seats)",
            )
            room_cell.font = Font(bold=True, size=10)
            room_cell.alignment = left
            room_cell.border = border
            room_cell.fill = PatternFill("solid", fgColor=BAND_FILL)

            for column, slot in enumerate(slots, start=2):
                cell = sheet.cell(row=row_index, column=column)
                cell.border = border
                cell.alignment = centre
                entry = lookup.get((slot["start"], room["id"]))
                if not entry:
                    continue
                cell.value = f"{_class_label(entry)}\n{entry.get('instructor') or ''}"
                cell.fill = PatternFill("solid", fgColor=_argb(entry.get("color")))
                cell.font = Font(size=9, color=_ink_for(entry.get("color") or ""))

        sheet.column_dimensions["A"].width = 26
        for column in range(2, len(slots) + 2):
            sheet.column_dimensions[get_column_letter(column)].width = 24
        for offset in range(len(grid_rooms)):
            sheet.row_dimensions[header_row + 1 + offset].height = 34
        sheet.row_dimensions[header_row].height = 30
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=2)
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

    # ---------------------------------------------------------- semesters --
    # One sheet per semester: the view a batch of students actually needs.
    # Rows are (day, section) pairs so several parallel sections stay readable.
    semesters = sorted({int(e.get("semester") or 0) for e in entries if int(e.get("semester") or 0)})
    for semester in semesters:
        sem_entries = [e for e in entries if int(e.get("semester") or 0) == semester]
        sections = sorted({str(e["section"]).upper() for e in sem_entries})
        sheet = workbook.create_sheet(f"Semester {semester}")

        sheet["A1"] = f"{title} — Semester {semester}"
        sheet["A1"].font = Font(bold=True, size=14, color="FF2B3465")
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(2, len(slots) + 1))
        sheet["A1"].alignment = left
        teachers_here = len({e.get("instructor") for e in sem_entries})
        sheet.cell(
            row=2,
            column=1,
            value=f"{len(sem_entries)} class(es) · {len(sections)} section(s) · {teachers_here} teacher(s)",
        ).font = Font(italic=True, size=10, color="FF5B6479")

        header_row = 4
        style_header(sheet.cell(row=header_row, column=1, value="Day / Section"))
        for index, slot in enumerate(slots, start=2):
            style_header(
                sheet.cell(
                    row=header_row,
                    column=index,
                    value=f"{format_12h(slot['start'])}\n{format_12h(slot['end'])}",
                )
            )

        lookup = {
            (int(e["day"]), str(e["section"]).upper(), e["start_time"]): e for e in sem_entries
        }
        row_index = header_row
        for day in range(1, max(1, min(7, days)) + 1):
            for section in sections:
                row_index += 1
                label = sheet.cell(row=row_index, column=1, value=f"{WEEKDAYS[day - 1]} · Section {section}")
                label.font = Font(bold=True, size=10)
                label.alignment = left
                label.border = border
                label.fill = PatternFill("solid", fgColor=BAND_FILL)
                for column, slot in enumerate(slots, start=2):
                    cell = sheet.cell(row=row_index, column=column)
                    cell.border = border
                    cell.alignment = centre
                    entry = lookup.get((day, section, slot["start"]))
                    if not entry:
                        continue
                    cell.value = (
                        f"{_class_label(entry)}\n{entry.get('instructor') or ''}\n"
                        f"{entry.get('room_label') or ''}"
                    )
                    cell.fill = PatternFill("solid", fgColor=_argb(entry.get("color")))
                    cell.font = Font(size=9, color=_ink_for(entry.get("color") or ""))
                sheet.row_dimensions[row_index].height = 40

        sheet.column_dimensions["A"].width = 26
        for column in range(2, len(slots) + 2):
            sheet.column_dimensions[get_column_letter(column)].width = 26
        sheet.row_dimensions[header_row].height = 30
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=2)
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

    # ------------------------------------------------------------- summary --
    summary = workbook.create_sheet("Summary", 0)
    headers = ["Day", "Shift", "Semester", "Type", "Start", "End", "Code", "Course", "Section",
               "Teacher", "Room", "Students"]
    for column, heading in enumerate(headers, start=1):
        style_header(summary.cell(row=1, column=column, value=heading))

    ordered = sorted(entries, key=lambda e: (int(e["day"]), to_minutes(e["start_time"]), str(e.get("room_label", ""))))
    for row_index, entry in enumerate(ordered, start=2):
        values = [
            WEEKDAYS[int(entry["day"]) - 1],
            (entry.get("shift") or "morning").capitalize(),
            int(entry.get("semester") or 0) or "-",
            "Lab" if entry.get("kind") == "lab" else "Theory",
            format_12h(entry["start_time"]),
            format_12h(entry["end_time"]),
            entry.get("code", ""),
            entry["course_name"],
            entry["section"],
            entry.get("instructor", ""),
            entry.get("room_label", entry["room_id"]),
            entry.get("num_students", ""),
        ]
        for column, value in enumerate(values, start=1):
            cell = summary.cell(row=row_index, column=column, value=value)
            cell.border = border
            cell.alignment = left if column in (8, 10, 11) else centre
            if row_index % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=BAND_FILL)

    widths = [12, 10, 10, 9, 11, 11, 12, 30, 9, 26, 14, 10]
    for column, width in enumerate(widths, start=1):
        summary.column_dimensions[get_column_letter(column)].width = width
    summary.freeze_panes = "A2"
    summary.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(ordered) + 1)}"

    footer = len(ordered) + 3
    summary.cell(row=footer, column=1, value=f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}").font = Font(
        italic=True, size=9, color="FF5B6479"
    )

    # ----------------------------------------------------------- by teacher --
    teachers = workbook.create_sheet("By Teacher")
    for column, heading in enumerate(["Teacher", "Day", "Start", "End", "Course", "Section", "Room"], start=1):
        style_header(teachers.cell(row=1, column=column, value=heading))
    by_teacher = sorted(
        ordered, key=lambda e: (str(e.get("instructor") or "~"), int(e["day"]), to_minutes(e["start_time"]))
    )
    for row_index, entry in enumerate(by_teacher, start=2):
        values = [
            entry.get("instructor") or "Unassigned",
            WEEKDAYS[int(entry["day"]) - 1],
            format_12h(entry["start_time"]),
            format_12h(entry["end_time"]),
            f"{entry.get('code', '')} {entry['course_name']}".strip()
            + (" [LAB]" if entry.get("kind") == "lab" else ""),
            entry["section"],
            entry.get("room_label", ""),
        ]
        for column, value in enumerate(values, start=1):
            cell = teachers.cell(row=row_index, column=column, value=value)
            cell.border = border
            cell.alignment = left if column in (1, 5, 7) else centre
    for column, width in enumerate([26, 12, 11, 11, 34, 9, 14], start=1):
        teachers.column_dimensions[get_column_letter(column)].width = width
    teachers.freeze_panes = "A2"

    # ---------------------------------------------------------- gaps ------
    if unscheduled:
        sheet = workbook.create_sheet("Unscheduled")
        sheet["A1"] = f"{len(unscheduled)} class(es) are not on the timetable"
        sheet["A1"].font = Font(bold=True, size=13, color="FFB4380F")
        sheet.merge_cells("A1:F1")
        for column, heading in enumerate(
            ["Semester", "Code", "Course", "Section", "Type", "Teacher"], start=1
        ):
            style_header(sheet.cell(row=3, column=column, value=heading))
        for row_index, item in enumerate(unscheduled, start=4):
            values = [
                int(item.get("semester") or 0) or "-",
                item.get("code", ""),
                item.get("course_name", ""),
                item.get("section", ""),
                "Lab" if item.get("kind") == "lab" else "Theory",
                item.get("instructor", ""),
            ]
            for column, value in enumerate(values, start=1):
                cell = sheet.cell(row=row_index, column=column, value=value)
                cell.border = border
                cell.alignment = left if column in (3, 6) else centre
        for column, width in enumerate([11, 12, 32, 9, 9, 26], start=1):
            sheet.column_dimensions[get_column_letter(column)].width = width
        sheet.freeze_panes = "A4"

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()
