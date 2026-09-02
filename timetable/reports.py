"""Reporting helpers: room utilisation, teacher workload and clash report.

These are pure functions over already-described timetable rows (as produced by
``TimetableService.describe_assignments`` / ``load_timetable``), so the same
figures feed the Excel workbook, the PDF publisher and the web API without a
database round-trip.  Each returns a small dict with ``headers`` and ``rows``
so the caller decides whether to draw a worksheet or a page.
"""

from __future__ import annotations

from typing import Any, Iterable

from .services import WEEKDAYS, to_minutes

UNDER_USED_RATIO = 0.5        # a room under 50% of its weekly capacity is flagged
OVERLOADED_HOURS = 20.0       # a teacher with over 20 contact hours/week is flagged
UNDERLOADED_HOURS = 6.0       # a teacher with under 6 contact hours/week is flagged


def _slot_duration_hours(entries: Iterable[dict[str, Any]], slots: list[dict[str, str]] | None) -> float:
    """The typical length of one slot in hours, for estimating available time."""
    if slots:
        durations = [max(0, to_minutes(s["end"]) - to_minutes(s["start"])) / 60.0 for s in slots]
        if durations:
            return sum(durations) / len(durations)
    seen: dict[str, str] = {}
    for entry in entries:
        seen[str(entry.get("start_time"))] = str(entry.get("end_time"))
    durations = [max(0, to_minutes(end) - to_minutes(start)) / 60.0 for start, end in seen.items()]
    return sum(durations) / len(durations) if durations else 1.0


# --------------------------------------------------------------------------- #
# Room utilisation
# --------------------------------------------------------------------------- #
ROOM_HEADERS = [
    "Room",
    "Type",
    "Capacity",
    "Classes / week",
    "Used hours / week",
    "Free hours / week",
    "Utilisation",
    "Status",
]


def room_utilisation(
    entries: list[dict[str, Any]],
    rooms: list[dict[str, Any]],
    *,
    days: int = 5,
    slots: list[dict[str, str]] | None = None,
    shift: str = "all",
) -> dict[str, Any]:
    """Free vs. used hours per room per week, flagging rooms under 50% used."""
    if shift and shift != "all":
        entries = [e for e in entries if (e.get("shift") or "morning") == shift]

    # Per-room aggregates (rooms may appear in the grid without any class yet).
    used: dict[int, dict[str, Any]] = {}
    for room in rooms:
        used[int(room["id"])] = {
            "room": room,
            "classes": 0,
            "used_hours": 0.0,
        }

    for entry in entries:
        rid = int(entry.get("room_id") or 0)
        bucket = used.setdefault(
            rid,
            {"room": {"id": rid, "label": str(entry.get("room_label") or rid),
                      "type": "", "capacity": 0}, "classes": 0, "used_hours": 0.0},
        )
        bucket["classes"] += 1
        bucket["used_hours"] += max(0, to_minutes(str(entry.get("end_time"))) -
                                    to_minutes(str(entry.get("start_time")))) / 60.0

    weekdays = max(1, min(7, int(days)))
    slot_hours = _slot_duration_hours(entries, slots)
    available_hours = round(weekdays * slot_hours, 2)

    rows: list[list[Any]] = []
    for rid in sorted(used, key=lambda key: str(used[key]["room"].get("label") or key)):
        bucket = used[rid]
        room = bucket["room"]
        label = str(room.get("label") or room.get("room_number") or rid)
        used_hours = round(bucket["used_hours"], 2)
        free_hours = round(max(0.0, available_hours - used_hours), 2)
        utilisation = round((used_hours / available_hours) * 100, 1) if available_hours else 0.0
        status = (
            "Under-used"
            if utilisation < UNDER_USED_RATIO * 100
            else "Well used"
        )
        rows.append([
            label,
            str(room.get("room_type") or room.get("type") or ""),
            int(room.get("capacity") or 0),
            bucket["classes"],
            used_hours,
            free_hours,
            f"{utilisation:.0f}%",
            status,
        ])

    # Sort by utilisation so the most over-used rooms are at the top.
    def sort_key(row: list[Any]) -> str:
        pct = str(row[6]).replace("%", "")
        try:
            return -float(pct)
        except ValueError:
            return 999.0

    rows.sort(key=sort_key)
    return {
        "title": "Room Utilisation",
        "headers": ROOM_HEADERS,
        "rows": rows,
        "note": (
            f"Based on a {weekdays}-day week with ~{slot_hours:.1f} hour slots. "
            "Rooms under 50% utilisation are flagged under-used."
        ),
    }


# --------------------------------------------------------------------------- #
# Teacher workload
# --------------------------------------------------------------------------- #
WORKLOAD_HEADERS = [
    "Teacher",
    "Classes / week",
    "Contact hours / week",
    "Days / week",
    "Credit hours",
    "Load",
]


def teacher_workload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Contact hours per teacher per week, flagging over/under-loaded teachers."""
    by_teacher: dict[str, dict[str, Any]] = {}
    for entry in entries:
        name = str(entry.get("instructor") or "Unassigned")
        bucket = by_teacher.setdefault(
            name,
            {"classes": 0, "hours": 0.0, "days": set(), "credits": 0},
        )
        bucket["classes"] += 1
        bucket["hours"] += max(0, to_minutes(str(entry.get("end_time"))) -
                               to_minutes(str(entry.get("start_time")))) / 60.0
        bucket["days"].add(int(entry.get("day") or 0))
        bucket["credits"] += int(entry.get("credit_hours") or 0)

    rows: list[list[Any]] = []
    for name in sorted(by_teacher):
        bucket = by_teacher[name]
        hours = round(bucket["hours"], 2)
        if hours > OVERLOADED_HOURS:
            load = "Over-loaded"
        elif hours < UNDERLOADED_HOURS and bucket["classes"]:
            load = "Under-loaded"
        else:
            load = "Balanced"
        rows.append([
            name,
            bucket["classes"],
            hours,
            len(bucket["days"]),
            bucket["credits"],
            load,
        ])

    # Most-loaded teachers first.
    rows.sort(key=lambda row: -float(row[2]))
    return {
        "title": "Teacher Workload",
        "headers": WORKLOAD_HEADERS,
        "rows": rows,
        "note": (
            f"Contact hours per week. Teachers above {OVERLOADED_HOURS:.0f} hours are "
            f"over-loaded; below {UNDERLOADED_HOURS:.0f} hours (and with classes) are under-loaded."
        ),
    }


# --------------------------------------------------------------------------- #
# Conflict report
# --------------------------------------------------------------------------- #
CONFLICT_HEADERS = ["Severity", "Day", "Time", "Course", "Section", "Room", "Teacher", "Issue"]


def _label(entry: dict[str, Any]) -> str:
    code = str(entry.get("code") or "")
    name = str(entry.get("course_name") or "")
    lab = " (Lab)" if entry.get("kind") == "lab" else ""
    return f"{code + ' ' if code else ''}{name}{lab}".strip()


def _when(entry: dict[str, Any]) -> str:
    start = str(entry.get("start_time"))
    end = str(entry.get("end_time"))
    try:
        s, e = to_minutes(start), to_minutes(end)
        def fmt(total: int) -> str:
            h, m = divmod(total, 60)
            suffix = "AM" if h < 12 else "PM"
            return f"{h % 12 or 12}:{m:02d} {suffix}"
        return f"{fmt(s)} - {fmt(e)}"
    except Exception:
        return f"{start}-{end}"


def conflict_report(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """A printable list of the clashes in the given grid.

    Detects the clash kinds that can be inferred from the described rows alone
    (same room, same teacher, same course-section / lecture-vs-lab, and same
    semester + section).  Student-level clashes need the roster and are left to
    the live validator.  Results are ordered errors first, then warnings.
    """
    rows: list[list[Any]] = []
    ordered = sorted(entries, key=lambda e: (int(e.get("day") or 0), to_minutes(str(e.get("start_time") or "00:00"))))

    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if int(a.get("day")) != int(b.get("day")):
                continue
            if not _overlap(a, b):
                continue
            day = WEEKDAYS[int(a["day"]) - 1]

            same_section = int(a.get("course_id") or 0) == int(b.get("course_id") or 0) and \
                str(a.get("section") or "").upper() == str(b.get("section") or "").upper()
            if same_section:
                if str(a.get("kind") or "theory") != str(b.get("kind") or "theory"):
                    issue = "Lecture and lab of the same section overlap"
                else:
                    issue = "Duplicate class at the same time"
                rows.append(_conflict_row("error", day, a, b, issue))
                continue

            if int(a.get("room_id") or 0) == int(b.get("room_id") or 0):
                rows.append(_conflict_row("error", day, a, b, "Same room booked twice"))

            if a.get("instructor") and a.get("instructor") == b.get("instructor"):
                rows.append(_conflict_row("error", day, a, b, "Teacher double-booked"))

            if int(a.get("semester") or 0) and int(a.get("semester") or 0) == int(b.get("semester") or 0) and \
                    str(a.get("section") or "").upper() == str(b.get("section") or "").upper():
                rows.append(_conflict_row("error", day, a, b, "Same semester + section at once"))

            capacity_a = int(a.get("num_students") or 0)
            capacity_b = int(b.get("num_students") or 0)
            room_a = int(a.get("room_id") or 0)
            room_b = int(b.get("room_id") or 0)
            if capacity_a > int(a.get("capacity") or 0) and capacity_a:
                rows.append(_conflict_row("warning", day, a, b,
                                          f"Room seats fewer than {capacity_a} enrolled students"))
            if capacity_b > int(b.get("capacity") or 0) and capacity_b:
                rows.append(_conflict_row("warning", day, b, a,
                                          f"Room seats fewer than {capacity_b} enrolled students"))

    # Deduplicate identical (day, severity, course, issue) reports.
    seen: set[tuple[Any, ...]] = set()
    unique: list[list[Any]] = []
    for row in rows:
        key = (row[0], row[1], row[2], row[3], row[4], row[6], row[7])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    order = {"error": 0, "warning": 1}
    unique.sort(key=lambda row: (order.get(row[0], 2), row[1], row[2]))
    errors = sum(1 for row in unique if row[0] == "error")
    warnings = sum(1 for row in unique if row[0] == "warning")
    return {
        "title": "Conflict Report",
        "headers": CONFLICT_HEADERS,
        "rows": unique,
        "note": f"{errors} error(s) and {warnings} warning(s). Student-level clashes need the saved grid.",
    }


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    try:
        return to_minutes(str(a["start_time"])) < to_minutes(str(b["end_time"])) and \
            to_minutes(str(b["start_time"])) < to_minutes(str(a["end_time"]))
    except Exception:
        return False


def _conflict_row(severity: str, day: str, a: dict[str, Any], b: dict[str, Any], issue: str) -> list[Any]:
    return [
        severity.capitalize(),
        day,
        _when(a),
        _label(a),
        str(a.get("section") or ""),
        str(a.get("room_label") or a.get("room_number") or ""),
        str(a.get("instructor") or ""),
        issue,
    ]
