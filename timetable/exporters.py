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

# The default typewriter font for every exported workbook.  The user asked for
# "all text in Times New Roman", so this is the default; it can be changed in
# the Export & share dialog (and per request for the API).
DEFAULT_FONT_NAME = "Times New Roman"
DEFAULT_FONT_SIZE = 10


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


def format_time_range(start: str, end: str) -> str:
    """Compact 12-hour range used by the Class Schedule layout, e.g. \"2:30-4:00\"."""
    def compact(value: str) -> str:
        total = to_minutes(value)
        hour, minute = divmod(total, 60)
        display = hour % 12 or 12
        return f"{display}:{minute:02d}"

    return f"{compact(start)}-{compact(end)}"


# One pastel band per weekday, matching the reference Class Schedule sheet.
SCHEDULE_DAY_FILLS = {
    1: "FFA9C4E4",  # Monday   - blue
    2: "FFF2B8BC",  # Tuesday  - rose
    3: "FFB9ABD8",  # Wednesday- lavender
    4: "FFA9D6D6",  # Thursday - teal
    5: "FFC0B4DA",  # Friday   - lilac
    6: "FFD6C4E0",  # Saturday - mauve
    7: "FFE0D0D0",  # Sunday   - blush
}

# A course with zero credit hours is reported as a non-credited course.  This
# is a shared label between the Excel and PDF schedules (and the only place
# the wording lives), so changing it here updates every export.
NON_CREDITED_LABEL = "non-credited course"


def build_workbook(
    entries: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    days: int = 5,
    slots: list[dict[str, str]] | None = None,
    shift: str = "all",
    title: str = "University Timetable",
    unscheduled: list[dict[str, Any]] | None = None,
    font_name: str = DEFAULT_FONT_NAME,
    font_size: int = DEFAULT_FONT_SIZE,
    orientation: str = "landscape",
    institution: str = "",
    term: str = "",
    show_summary: bool = True,
    show_by_teacher: bool = True,
    show_unscheduled: bool = True,
    show_semesters: bool = True,
    layout: str = "grid",
    program: str = "",
    commencement: str = "",
    semester: str = "",
    non_credited_label: str = NON_CREDITED_LABEL,
) -> bytes:
    """Render the timetable into an .xlsx workbook and return the bytes.

    ``layout``
        ``grid`` (default)     - one sheet per day (room × time), plus semester,
                                 Summary, By Teacher and Unscheduled sheets.
        ``schedule``           - a single "Class Schedule" sheet that mirrors a
                                 printed classroom timetable: a metadata title
                                 block (institution, program, semester,
                                 commencement) and rows grouped by day with
                                 columns Days / Course Code / Course Title /
                                 C.Hrs / Students / Teacher / Time / Room No.
                                 Courses with ``credit_hours == 0`` are shown as
                                 **non-credited course**.

    ``font_name`` is applied to *every* cell in the workbook, so the export
    reads consistently in Excel, LibreOffice and Google Sheets (Times New
    Roman by default).
    """
    from openpyxl import Workbook

    if layout == "schedule":
        return build_class_schedule_workbook(
            entries,
            days=days,
            title=title,
            font_name=font_name,
            font_size=font_size,
            orientation=orientation,
            institution=institution,
            term=term,
            program=program,
            commencement=commencement,
            semester=semester,
            non_credited_label=non_credited_label,
        )
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    def font(*, size: int | None = None, bold: bool = False, color: str | None = None,
             italic: bool = False) -> Font:
        """One Font factory so a single ``font_name`` is used everywhere."""
        return Font(
            name=font_name,
            size=size if size is not None else font_size,
            bold=bold,
            italic=italic,
            color=color or "FF000000",
        )

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

    # Make the workbook's *default* cell font our chosen font too, so even
    # cells we forget to style explicitly (or that a user adds later) match.
    try:
        normal = workbook._named_styles["Normal"]
        normal.font = font(size=font_size)
    except Exception:
        pass
    # The sheet tab bar in Excel uses "Calibri" by default - set it to match.
    try:
        workbook._named_styles["Normal"].font = font(size=font_size)
    except Exception:
        pass

    def style_header(cell) -> None:
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.font = font(bold=True, color="FFFFFFFF", size=11)
        cell.alignment = centre
        cell.border = border

    # ---------------------------------------------------------------- days --
    for day in range(1, max(1, min(7, days)) + 1):
        sheet = workbook.create_sheet(WEEKDAYS[day - 1])
        day_entries = [e for e in entries if int(e["day"]) == day]

        sheet["A1"] = f"{title} — {WEEKDAYS[day - 1]}"
        sheet["A1"].font = font(bold=True, size=14, color="FF2B3465")
        span = max(2, len(slots) + 1)
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
        sheet["A1"].alignment = left
        label = "All shifts" if shift == "all" else f"{shift.capitalize()} shift"
        subrow = f"{label} · {len(day_entries)} class(es)"
        if institution or term:
            subrow = f"{institution} · {term} · {subrow}".strip(" ·")
        sheet.cell(row=2, column=1, value=subrow).font = font(
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
            room_cell.font = font(bold=True, size=10)
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
                cell.font = font(size=9, color=_ink_for(entry.get("color") or ""))

        sheet.column_dimensions["A"].width = 26
        for column in range(2, len(slots) + 2):
            sheet.column_dimensions[get_column_letter(column)].width = 24
        for offset in range(len(grid_rooms)):
            sheet.row_dimensions[header_row + 1 + offset].height = 34
        sheet.row_dimensions[header_row].height = 30
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=2)
        sheet.page_setup.orientation = orientation
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

    # ---------------------------------------------------------- semesters --
    # One sheet per semester: the view a batch of students actually needs.
    # Rows are (day, section) pairs so several parallel sections stay readable.
    semesters = sorted({int(e.get("semester") or 0) for e in entries if int(e.get("semester") or 0)})
    for semester in (semesters if show_semesters else []):
        sem_entries = [e for e in entries if int(e.get("semester") or 0) == semester]
        sections = sorted({str(e["section"]).upper() for e in sem_entries})
        sheet = workbook.create_sheet(f"Semester {semester}")

        sheet["A1"] = f"{title} — Semester {semester}"
        sheet["A1"].font = font(bold=True, size=14, color="FF2B3465")
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(2, len(slots) + 1))
        sheet["A1"].alignment = left
        teachers_here = len({e.get("instructor") for e in sem_entries})
        subrow = f"{len(sem_entries)} class(es) · {len(sections)} section(s) · {teachers_here} teacher(s)"
        if institution or term:
            subrow = f"{institution} · {term} · {subrow}".strip(" ·")
        sheet.cell(row=2, column=1, value=subrow).font = font(italic=True, size=10, color="FF5B6479")

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
                label.font = font(bold=True, size=10)
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
                    cell.font = font(size=9, color=_ink_for(entry.get("color") or ""))
                sheet.row_dimensions[row_index].height = 40

        sheet.column_dimensions["A"].width = 26
        for column in range(2, len(slots) + 2):
            sheet.column_dimensions[get_column_letter(column)].width = 26
        sheet.row_dimensions[header_row].height = 30
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=2)
        sheet.page_setup.orientation = orientation
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True

    # ------------------------------------------------------------- summary --
    ordered = sorted(entries, key=lambda e: (int(e["day"]), to_minutes(e["start_time"]), str(e.get("room_label", ""))))
    if show_summary:
        summary = workbook.create_sheet("Summary", 0)
        headers = ["Day", "Shift", "Semester", "Type", "Start", "End", "Code", "Course", "Section",
                   "Teacher", "Room", "Students"]
        for column, heading in enumerate(headers, start=1):
            style_header(summary.cell(row=1, column=column, value=heading))

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
        summary.cell(row=footer, column=1, value=f"Generated {datetime.now().strftime('%d %b %Y %H:%M')}").font = font(
            italic=True, size=9, color="FF5B6479"
        )

    # ----------------------------------------------------------- by teacher --
    if show_by_teacher:
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
    if unscheduled and show_unscheduled:
        sheet = workbook.create_sheet("Unscheduled")
        sheet["A1"] = f"{len(unscheduled)} class(es) are not on the timetable"
        sheet["A1"].font = font(bold=True, size=13, color="FFB4380F")
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

    # Finally, sweep every sheet and force our chosen font onto any cell that
    # is still carrying the workbook template default ("Calibri").  We style
    # the header / title / grid cells explicitly with ``font()``, but body
    # cells created by ``cell(value=...)`` inherit openpyxl's default font;
    # without this sweep those would leak the template font into the export
    # and break the "all text in Times New Roman" requirement.
    for worksheet in workbook.worksheets:
        for row_cells in worksheet.iter_rows():
            for cell in row_cells:
                if cell.value is not None and cell.font.name != font_name:
                    cell.font = font()

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


# --------------------------------------------------------------------------- #
# Class Schedule (the printed-classroom-timetable layout)
# --------------------------------------------------------------------------- #
SCHEDULE_HEADERS = [
    "Days",
    "Course Code",
    "Course Title",
    "C.Hrs",
    "Total No.of Students",
    "Teacher's Name",
    "Time",
    "Room No",
]
TITLE_FILL = "FFD9E2F3"


def build_class_schedule_workbook(
    entries: list[dict[str, Any]],
    *,
    days: int = 5,
    title: str = "Class Schedule",
    font_name: str = DEFAULT_FONT_NAME,
    font_size: int = DEFAULT_FONT_SIZE,
    orientation: str = "landscape",
    institution: str = "",
    term: str = "",
    program: str = "",
    commencement: str = "",
    semester: str = "",
    non_credited_label: str = NON_CREDITED_LABEL,
) -> bytes:
    """Render the timetable as one printed-style "Class Schedule" sheet.

    Mirrors the reference spreadsheet: a merged metadata block up top
    (institution, program, semester, commencement) followed by a header row and
    rows grouped by day, where the Day cell is merged vertically over that
    day's classes and painted a pastel band.  A course whose credit hours are
    zero is written as ``non_credited_label`` (default **non-credited course**).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    def font(*, size: int | None = None, bold: bool = False, color: str | None = None,
             italic: bool = False) -> Font:
        return Font(
            name=font_name,
            size=size if size is not None else font_size,
            bold=bold,
            italic=italic,
            color=color or "FF000000",
        )

    thin = Side(style="thin", color="FFBFC5D8")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    centre = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Class Schedule"

    ncols = len(SCHEDULE_HEADERS)
    for cell in sheet[1]:
        cell.font = font(size=font_size)
    try:
        workbook._named_styles["Normal"].font = font(size=font_size)
    except Exception:
        pass

    def merge_row(row: int, value: str, *, fill: str = "", bold: bool = True,
                  size: int = 12, color: str = "FF16223D", align: Alignment | None = None) -> None:
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        cell = sheet.cell(row=row, column=1, value=value)
        cell.font = font(bold=bold, size=size, color=color)
        cell.alignment = align or centre
        if fill:
            for column in range(1, ncols + 1):
                sheet.cell(row=row, column=column).fill = PatternFill("solid", fgColor=fill)
        return cell

    # ---- metadata title block (matches the reference layout) -------------- #
    row = 1
    heading = str(title or "Class Schedule")
    if term:
        heading = f"{heading} {term}"
    merge_row(row, heading, fill=TITLE_FILL, bold=True, size=14, color="FF1F3864")
    sheet.row_dimensions[row].height = 22
    row += 1
    if institution:
        merge_row(row, institution, bold=True, size=12, color="FF1F3864")
        sheet.row_dimensions[row].height = 18
        row += 1

    # Row: "Name of program: X" (left)  |  "Semester: Y" (right)
    left_label = f"Name of program: {program}" if program else ""
    right_label = f"Semester: {semester}" if semester else ""
    if left_label or right_label:
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(2, ncols // 2))
        lc = sheet.cell(row=row, column=1, value=left_label)
        lc.font = font(bold=False, size=11, color="FF16223D")
        lc.alignment = left
        if right_label:
            half = ncols // 2
            sheet.merge_cells(start_row=row, start_column=half + 1, end_row=row, end_column=ncols)
            rc = sheet.cell(row=row, column=half + 1, value=right_label)
            rc.font = font(bold=False, size=11, color="FF16223D")
            rc.alignment = left
        sheet.row_dimensions[row].height = 18
        row += 1

    if commencement:
        merge_row(row, f"Commencement of Classes: {commencement}", bold=False, size=11)
        sheet.row_dimensions[row].height = 18
        row += 1

    # ---- header row ------------------------------------------------------- #
    header_row = row + 1
    for column, heading in enumerate(SCHEDULE_HEADERS, start=1):
        cell = sheet.cell(row=header_row, column=column, value=heading)
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.font = font(bold=True, color="FFFFFFFF", size=11)
        cell.alignment = centre
        cell.border = border
    sheet.row_dimensions[header_row].height = 30

    # ---- rows grouped by day ---------------------------------------------- #
    ordered = sorted(entries, key=lambda e: (int(e["day"]), to_minutes(e["start_time"]), str(e.get("code", ""))))
    days_present = sorted({int(e["day"]) for e in entries if 1 <= int(e["day"]) <= 7})
    if not days_present:
        days_present = list(range(1, min(7, max(1, days)) + 1))

    data_row = header_row + 1
    blank_rows = 0
    for day in days_present[:7]:
        day_entries = [e for e in ordered if int(e["day"]) == day]
        if not day_entries:
            continue
        start_row = data_row
        band = SCHEDULE_DAY_FILLS.get(day, "FFDDDDE8")

        for entry in day_entries:
            credits = int(entry.get("credit_hours") or 0)
            creditors = non_credited_label if credits == 0 else str(credits)
            values = [
                WEEKDAYS[day - 1],
                entry.get("code", ""),
                entry.get("course_name", ""),
                creditors,
                entry.get("num_students", ""),
                entry.get("instructor", "Unassigned"),
                format_time_range(str(entry.get("start_time", "")), str(entry.get("end_time", ""))),
                entry.get("room_number") or entry.get("room_label", ""),
            ]
            for column, value in enumerate(values, start=1):
                cell = sheet.cell(row=data_row, column=column, value=value)
                cell.border = border
                cell.alignment = left if column in (3, 6) else centre
                if column == 4 and credits == 0:
                    cell.font = font(bold=True, italic=True, color="FF9C4330", size=int(max(8, font_size - 1)))
                elif column == 3:
                    cell.font = font(bold=False, size=font_size)
                else:
                    cell.font = font(size=font_size)
            # Band fill across the whole row (Day cell is merged below).
            for column in range(1, ncols + 1):
                sheet.cell(row=data_row, column=column).fill = PatternFill("solid", fgColor=band)
            sheet.row_dimensions[data_row].height = 26
            data_row += 1

        # Merge the day cell over its block and re-centre.
        if data_row - 1 > start_row:
            sheet.merge_cells(start_row=start_row, start_column=1, end_row=data_row - 1, end_column=1)
        day_cell = sheet.cell(row=start_row, column=1)
        day_cell.font = font(bold=True, size=12, color="FF16223D")
        day_cell.alignment = centre

        # A blank spacer row keeps the day blocks visibly separated.
        data_row += 1
        blank_rows += 1

    # ---- column widths ---------------------------------------------------- #
    widths = [12, 14, 32, 18, 16, 24, 15, 10]
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=2)
    sheet.page_setup.orientation = orientation
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"{header_row}:{header_row}"

    # Norm the font on any cell we might have skipped.
    for row_cells in sheet.iter_rows():
        for cell in row_cells:
            if cell.value is not None and cell.font.name != font_name:
                cell.font = font()

    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
CSV_HEADERS = [
    "Day",
    "Shift",
    "Start",
    "End",
    "Room",
    "Building",
    "Room type",
    "Capacity",
    "Code",
    "Course",
    "Section",
    "Kind",
    "Teacher",
    "Semester",
    "Students",
]


def build_csv(entries: list[dict[str, Any]]) -> bytes:
    """Render the timetable as UTF-8 CSV bytes.

    Written server-side (rather than stitched together in JavaScript) so the
    CSV can be saved straight into the project folder, contains exactly the
    same columns as the workbook, and is correctly quoted for Excel.  A UTF-8
    BOM is included so Excel opens accented names correctly on Windows.
    """
    import csv

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(CSV_HEADERS)

    def sort_key(entry: dict[str, Any]) -> tuple[int, int]:
        return int(entry.get("day") or 0), to_minutes(str(entry.get("start_time") or "00:00"))

    for entry in sorted(entries, key=sort_key):
        day = int(entry.get("day") or 0)
        writer.writerow(
            [
                WEEKDAYS[day - 1] if 1 <= day <= len(WEEKDAYS) else day,
                str(entry.get("shift") or "morning").title(),
                format_12h(str(entry.get("start_time") or "")),
                format_12h(str(entry.get("end_time") or "")),
                entry.get("room_label") or entry.get("room_id") or "",
                entry.get("building_name") or entry.get("building") or "",
                entry.get("room_type") or "",
                entry.get("capacity") or "",
                entry.get("code") or "",
                entry.get("course_name") or "",
                entry.get("section") or "",
                "Lab" if entry.get("kind") == "lab" else "Theory",
                entry.get("instructor") or "Unassigned",
                entry.get("semester") or "",
                entry.get("num_students") or 0,
            ]
        )
    return "\ufeff".encode("utf-8") + buffer.getvalue().encode("utf-8")
