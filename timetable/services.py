"""Domain logic: queries, clash detection and timetable persistence.

This module is deliberately framework-free (no Flask imports) so it can be
unit-tested and reused by a CLI or a future desktop UI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from .db import (
    buildings,
    course_sections,
    courses,
    courses_taught_by,
    enrollments,
    instructors,
    rooms,
    settings_table,
    students,
    timetable_entries,
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ValidationError(ValueError):
    """Raised when client-supplied data is malformed."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def to_minutes(value: str) -> int:
    """'08:30' -> 510.  Raises ValidationError on anything else."""
    if not isinstance(value, str) or not TIME_RE.match(value.strip()):
        raise ValidationError(f"Invalid time {value!r}; expected 24-hour HH:MM")
    hours, minutes = value.strip().split(":")
    return int(hours) * 60 + int(minutes)


def normalise_time(value: str) -> str:
    return f"{to_minutes(value) // 60:02d}:{to_minutes(value) % 60:02d}"


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open interval overlap: [start, end)."""
    return a_start < b_end and b_start < a_end


def format_12h(value: str) -> str:
    total = to_minutes(value)
    hour, minute = divmod(total, 60)
    suffix = "AM" if hour < 12 else "PM"
    display = hour % 12 or 12
    return f"{display:02d}:{minute:02d} {suffix}"


@dataclass
class Assignment:
    """One class the user wants to place on the grid."""

    day: int
    start_time: str
    end_time: str
    room_id: int
    course_id: int
    section: str
    shift: str = "morning"
    kind: str = "theory"                # theory | lab
    entry_id: int | None = None

    @property
    def start_min(self) -> int:
        return to_minutes(self.start_time)

    @property
    def end_min(self) -> int:
        return to_minutes(self.end_time)

    @classmethod
    def from_payload(cls, raw: Any) -> "Assignment":
        if not isinstance(raw, dict):
            raise ValidationError("Each assignment must be an object")
        try:
            day = int(raw["day"])
            room_id = int(raw["room_id"])
            course_id = int(raw["course_id"])
            section = str(raw["section"]).strip()
            start = normalise_time(str(raw["start_time"]))
            end = normalise_time(str(raw["end_time"]))
        except KeyError as exc:
            raise ValidationError(f"Missing field: {exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValidationError):
                raise
            raise ValidationError(f"Malformed assignment: {exc}") from exc

        if not 1 <= day <= 7:
            raise ValidationError("day must be between 1 (Monday) and 7 (Sunday)")
        if not section:
            raise ValidationError("section must not be empty")
        if to_minutes(end) <= to_minutes(start):
            raise ValidationError("end_time must be after start_time")

        shift = str(raw.get("shift") or "morning").strip().lower()
        if shift not in ("morning", "evening"):
            shift = "morning"

        kind = str(raw.get("kind") or "theory").strip().lower()
        if kind not in ("theory", "lab"):
            raise ValidationError("kind must be either 'theory' or 'lab'")

        entry_id = raw.get("entry_id")
        return cls(
            day=day,
            start_time=start,
            end_time=end,
            room_id=room_id,
            course_id=course_id,
            section=section,
            shift=shift,
            kind=kind,
            entry_id=int(entry_id) if entry_id not in (None, "") else None,
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "room_id": self.room_id,
            "course_id": self.course_id,
            "section": self.section,
            "shift": self.shift,
            "kind": self.kind,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


@dataclass
class Conflict:
    kind: str                       # room | instructor | student | semester |
                                    # duplicate | capacity | roomtype | unknown
    severity: str                   # error | warning
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
        }


# --------------------------------------------------------------------------- #
# service
# --------------------------------------------------------------------------- #
class TimetableService:
    """All read/write operations the web layer needs."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---------------------------- reference data --------------------------- #
    def list_courses(self) -> list[dict[str, Any]]:
        enrolled = (
            select(
                enrollments.c.course_id.label("cid"),
                enrollments.c.section.label("sec"),
                func.count().label("num_students"),
            )
            .group_by(enrollments.c.course_id, enrollments.c.section)
            .subquery()
        )
        teacher = (
            select(
                courses_taught_by.c.course_id.label("cid"),
                courses_taught_by.c.section.label("sec"),
                instructors.c.id.label("instructor_id"),
                instructors.c.name.label("instructor"),
            )
            .select_from(courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id))
            .subquery()
        )
        stmt = (
            select(
                courses.c.id,
                courses.c.code,
                courses.c.name,
                courses.c.color,
                courses.c.department,
                courses.c.credit_hours,
                courses.c.has_lab,
                courses.c.lab_credit_hours,
                courses.c.semester,
                course_sections.c.section,
                teacher.c.instructor,
                teacher.c.instructor_id,
                func.coalesce(enrolled.c.num_students, 0).label("num_students"),
            )
            .select_from(
                courses.join(course_sections, courses.c.id == course_sections.c.course_id)
                .outerjoin(
                    teacher,
                    (teacher.c.cid == course_sections.c.course_id) & (teacher.c.sec == course_sections.c.section),
                )
                .outerjoin(
                    enrolled,
                    (enrolled.c.cid == course_sections.c.course_id) & (enrolled.c.sec == course_sections.c.section),
                )
            )
            .order_by(courses.c.name, course_sections.c.section)
        )
        with self.engine.connect() as conn:
            rows = list(conn.execute(stmt))

        items: list[dict[str, Any]] = []
        for r in rows:
            base = {
                "id": r.id,
                "code": r.code or "",
                "name": r.name,
                "color": r.color or "#4c5caf",
                "department": r.department,
                "credit_hours": r.credit_hours,
                "has_lab": bool(r.has_lab),
                "lab_credit_hours": int(r.lab_credit_hours or 0),
                "semester": int(r.semester or 0),
                "section": r.section,
                "instructor": r.instructor or "Unassigned",
                "instructor_id": r.instructor_id,
                "num_students": int(r.num_students or 0),
            }
            # One catalogue entry per class that has to be scheduled: the
            # lecture, plus the lab when the course has one.
            items.append({
                **base,
                "kind": "theory",
                "hours": r.credit_hours,
                "label": f"{r.name} - {r.section}",
                "key": f"{r.id}:{r.section}:theory",
            })
            if r.has_lab:
                items.append({
                    **base,
                    "kind": "lab",
                    "hours": int(r.lab_credit_hours or 1),
                    "label": f"{r.name} - {r.section} (Lab)",
                    "key": f"{r.id}:{r.section}:lab",
                })
        return items

    def course_details(self, course_id: int, section: str) -> dict[str, Any] | None:
        stmt = (
            select(
                courses.c.id,
                courses.c.code,
                courses.c.name,
                courses.c.color,
                courses.c.department,
                courses.c.credit_hours,
                course_sections.c.section,
            )
            .select_from(courses.join(course_sections, courses.c.id == course_sections.c.course_id))
            .where(courses.c.id == course_id, course_sections.c.section == section)
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
            if row is None:
                return None

            teacher = conn.execute(
                select(instructors.c.id, instructors.c.name)
                .select_from(courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id))
                .where(courses_taught_by.c.course_id == course_id, courses_taught_by.c.section == section)
            ).first()

            roster = conn.execute(
                select(students.c.roll_number, students.c.name)
                .select_from(enrollments.join(students, enrollments.c.roll_number == students.c.roll_number))
                .where(enrollments.c.course_id == course_id, enrollments.c.section == section)
                .order_by(students.c.roll_number)
            ).all()

            scheduled = conn.execute(
                select(
                    timetable_entries.c.day,
                    timetable_entries.c.start_time,
                    timetable_entries.c.end_time,
                    rooms.c.room_number,
                    buildings.c.name.label("building"),
                )
                .select_from(
                    timetable_entries.join(rooms, timetable_entries.c.room_id == rooms.c.id).join(
                        buildings, rooms.c.building_id == buildings.c.id
                    )
                )
                .where(timetable_entries.c.course_id == course_id, timetable_entries.c.section == section)
                .order_by(timetable_entries.c.day, timetable_entries.c.start_time)
            ).all()

        return {
            "id": row.id,
            "code": row.code or "",
            "credit_hours": row.credit_hours,
            "name": f"{row.name} - {row.section}",
            "course_name": row.name,
            "section": row.section,
            "color": row.color,
            "department": row.department,
            "instructor": teacher.name if teacher else "Unassigned",
            "instructor_id": teacher.id if teacher else None,
            "num_students": len(roster),
            "students": [{"roll_number": s.roll_number, "name": s.name} for s in roster],
            "scheduled": [
                {
                    "day": s.day,
                    "day_name": WEEKDAYS[s.day - 1],
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "room": f"{s.building}-{s.room_number}",
                }
                for s in scheduled
            ],
        }

    def list_rooms(self) -> list[dict[str, Any]]:
        stmt = (
            select(
                rooms.c.id,
                rooms.c.room_number,
                rooms.c.capacity,
                rooms.c.room_type,
                buildings.c.name.label("building_name"),
                buildings.c.id.label("building_id"),
            )
            .select_from(rooms.join(buildings, rooms.c.building_id == buildings.c.id))
            .order_by(buildings.c.name, rooms.c.room_number)
        )
        with self.engine.connect() as conn:
            return [
                {
                    "id": r.id,
                    "room_number": str(r.room_number),
                    "building_id": r.building_id,
                    "building_name": r.building_name,
                    "capacity": r.capacity,
                    "room_type": r.room_type,
                    "label": f"{r.building_name}-{r.room_number}",
                }
                for r in conn.execute(stmt)
            ]

    def list_students(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(students).order_by(students.c.roll_number)).mappings().all()
        out = []
        for row in rows:
            item = dict(row)
            dob = item.get("date_of_birth")
            item["date_of_birth"] = dob.isoformat() if hasattr(dob, "isoformat") else dob
            out.append(item)
        return out

    def list_enrollments(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(enrollments).order_by(enrollments.c.roll_number, enrollments.c.course_id)
            ).mappings().all()
        out = []
        for row in rows:
            item = dict(row)
            enrolled_on = item.get("enrollment_date")
            item["enrollment_date"] = enrolled_on.isoformat() if hasattr(enrolled_on, "isoformat") else enrolled_on
            out.append(item)
        return out

    def instructor_for(self, conn, course_id: int, section: str):
        return conn.execute(
            select(instructors.c.id, instructors.c.name)
            .select_from(courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id))
            .where(courses_taught_by.c.course_id == course_id, courses_taught_by.c.section == section)
        ).first()

    def section_exists(self, conn, course_id: int, section: str) -> bool:
        return conn.execute(
            select(course_sections.c.section).where(
                course_sections.c.course_id == course_id, course_sections.c.section == section
            )
        ).first() is not None

    # ---------------------------- clash detection -------------------------- #
    def _placed_classes(self, conn, day: int) -> list[dict[str, Any]]:
        stmt = (
            select(
                timetable_entries.c.id,
                timetable_entries.c.day,
                timetable_entries.c.start_time,
                timetable_entries.c.end_time,
                timetable_entries.c.room_id,
                timetable_entries.c.course_id,
                timetable_entries.c.section,
                timetable_entries.c.kind,
                courses.c.name.label("course_name"),
                courses.c.semester,
                rooms.c.room_number,
                buildings.c.name.label("building"),
            )
            .select_from(
                timetable_entries.join(courses, timetable_entries.c.course_id == courses.c.id)
                .join(rooms, timetable_entries.c.room_id == rooms.c.id)
                .join(buildings, rooms.c.building_id == buildings.c.id)
            )
            .where(timetable_entries.c.day == day)
        )
        return [dict(r) for r in conn.execute(stmt).mappings()]

    def check_assignment(
        self,
        candidate: Assignment,
        *,
        others: Iterable[dict[str, Any]] | None = None,
    ) -> list[Conflict]:
        """Validate one placement against everything already scheduled.

        ``others`` lets the caller supply an in-memory grid (used when the
        whole timetable is validated before saving); otherwise the currently
        persisted timetable is used.
        """
        conflicts: list[Conflict] = []
        with self.engine.connect() as conn:
            if not self.section_exists(conn, candidate.course_id, candidate.section):
                return [
                    Conflict(
                        "unknown",
                        "error",
                        f"Course {candidate.course_id} section {candidate.section} does not exist.",
                    )
                ]
            room = conn.execute(
                select(
                    rooms.c.id,
                    rooms.c.room_number,
                    rooms.c.capacity,
                    rooms.c.room_type,
                    buildings.c.name.label("building"),
                )
                .select_from(rooms.join(buildings, rooms.c.building_id == buildings.c.id))
                .where(rooms.c.id == candidate.room_id)
            ).first()
            if room is None:
                return [Conflict("unknown", "error", f"Room {candidate.room_id} does not exist.")]

            source = list(others) if others is not None else self._placed_classes(conn, candidate.day)
            existing = [
                dict(e)
                for e in source
                if int(e["day"]) == candidate.day
                and not (candidate.entry_id is not None and e.get("id") == candidate.entry_id)
            ]

            # Client-supplied grids only carry ids - resolve names so that the
            # conflict messages read like "Machine Learning - B", not "103 - B".
            missing_names = {
                e["course_id"] for e in existing
                if not e.get("course_name") or e.get("semester") is None
            }
            if missing_names:
                lookup = {
                    row.id: row
                    for row in conn.execute(
                        select(courses.c.id, courses.c.name, courses.c.semester).where(
                            courses.c.id.in_(missing_names)
                        )
                    )
                }
                for entry in existing:
                    found = lookup.get(entry["course_id"])
                    if not entry.get("course_name"):
                        entry["course_name"] = found.name if found else str(entry["course_id"])
                    if entry.get("semester") is None:
                        entry["semester"] = int(found.semester or 0) if found else 0

            course_row = conn.execute(
                select(courses.c.semester, courses.c.has_lab, courses.c.name).where(
                    courses.c.id == candidate.course_id
                )
            ).first()
            semester = int(course_row.semester or 0) if course_row else 0

            if candidate.kind == "lab":
                if course_row is not None and not course_row.has_lab:
                    return [
                        Conflict(
                            "unknown",
                            "error",
                            f"{course_row.name} has no lab component. Turn on “This course has a lab” "
                            "in the course editor first.",
                        )
                    ]
                if (room.room_type or "") != "Lab":
                    conflicts.append(
                        Conflict(
                            "roomtype",
                            "warning",
                            f"This is a lab but {room.building}-{room.room_number} is a "
                            f"{room.room_type or 'Classroom'}, not a Lab.",
                            {"room_type": room.room_type},
                        )
                    )

            teacher = self.instructor_for(conn, candidate.course_id, candidate.section)
            roster = {
                r.roll_number
                for r in conn.execute(
                    select(enrollments.c.roll_number).where(
                        enrollments.c.course_id == candidate.course_id,
                        enrollments.c.section == candidate.section,
                    )
                )
            }
            if len(roster) > (room.capacity or 0):
                conflicts.append(
                    Conflict(
                        "capacity",
                        "warning",
                        f"{len(roster)} students enrolled but room {room.building}-{room.room_number} "
                        f"seats {room.capacity}.",
                        {"enrolled": len(roster), "capacity": room.capacity},
                    )
                )

            for other in existing:
                if not overlaps(
                    candidate.start_min,
                    candidate.end_min,
                    to_minutes(other["start_time"]),
                    to_minutes(other["end_time"]),
                ):
                    continue

                when = f"{format_12h(other['start_time'])}-{format_12h(other['end_time'])}"
                other_kind = str(other.get("kind") or "theory")
                suffix = " (Lab)" if other_kind == "lab" else ""
                other_label = f"{other.get('course_name', other['course_id'])} - {other['section']}{suffix}"

                # 1. the same course-section cannot run twice at once - not even
                #    its lecture and its lab, which the same students attend.
                if other["course_id"] == candidate.course_id and other["section"] == candidate.section:
                    same_class = other_kind == candidate.kind
                    conflicts.append(
                        Conflict(
                            "duplicate",
                            "error",
                            (
                                f"{other_label} is already scheduled at {when} on "
                                f"{WEEKDAYS[candidate.day - 1]}."
                            )
                            if same_class
                            else (
                                f"The {other_kind} of this course-section is already at {when} on "
                                f"{WEEKDAYS[candidate.day - 1]}; the same students attend both."
                            ),
                            {"entry_id": other.get("id")},
                        )
                    )
                    continue

                # 2. semester clash - one batch-section can only be in one place.
                if (
                    semester
                    and int(other.get("semester") or 0) == semester
                    and str(other["section"]).upper() == candidate.section.upper()
                ):
                    conflicts.append(
                        Conflict(
                            "semester",
                            "error",
                            f"Semester {semester} section {candidate.section.upper()} is already in "
                            f"{other_label} at {when} on {WEEKDAYS[candidate.day - 1]}.",
                            {"semester": semester, "entry_id": other.get("id")},
                        )
                    )

                # 3. room double booking
                if int(other["room_id"]) == candidate.room_id:
                    conflicts.append(
                        Conflict(
                            "room",
                            "error",
                            f"Room {room.building}-{room.room_number} is already taken by "
                            f"{other_label} at {when}.",
                            {"entry_id": other.get("id"), "room": f"{room.building}-{room.room_number}"},
                        )
                    )

                # 4. instructor double booking
                if teacher is not None:
                    other_teacher = self.instructor_for(conn, other["course_id"], other["section"])
                    if other_teacher is not None and other_teacher.id == teacher.id:
                        conflicts.append(
                            Conflict(
                                "instructor",
                                "error",
                                f"{teacher.name} already teaches {other_label} at {when}.",
                                {"instructor": teacher.name, "entry_id": other.get("id")},
                            )
                        )

                # 5. student clash
                if roster:
                    other_roster = {
                        r.roll_number
                        for r in conn.execute(
                            select(enrollments.c.roll_number).where(
                                enrollments.c.course_id == other["course_id"],
                                enrollments.c.section == other["section"],
                            )
                        )
                    }
                    shared = sorted(roster & other_roster)
                    if shared:
                        preview = ", ".join(shared[:8]) + (" ..." if len(shared) > 8 else "")
                        conflicts.append(
                            Conflict(
                                "student",
                                "error",
                                f"{len(shared)} student(s) are enrolled in both this class and "
                                f"{other_label} at {when}: {preview}",
                                {"roll_numbers": shared, "entry_id": other.get("id")},
                            )
                        )
        return conflicts

    def validate_timetable(self, assignments: list[Assignment]) -> list[dict[str, Any]]:
        """Validate a whole grid; returns one report per conflicting class."""
        reports: list[dict[str, Any]] = []
        grid: list[dict[str, Any]] = []
        with self.engine.connect() as conn:
            rows = conn.execute(select(courses.c.id, courses.c.name, courses.c.semester)).all()
        names = {row.id: row.name for row in rows}
        semesters = {row.id: int(row.semester or 0) for row in rows}

        for index, item in enumerate(assignments):
            others = [g for g in grid]
            conflicts = self.check_assignment(item, others=others)
            if conflicts:
                reports.append(
                    {
                        "index": index,
                        "course_id": item.course_id,
                        "section": item.section,
                        "course_name": names.get(item.course_id, str(item.course_id)),
                        "kind": item.kind,
                        "day": item.day,
                        "start_time": item.start_time,
                        "end_time": item.end_time,
                        "conflicts": [c.as_dict() for c in conflicts],
                    }
                )
            grid.append(
                {
                    "id": None,
                    "day": item.day,
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "room_id": item.room_id,
                    "course_id": item.course_id,
                    "section": item.section,
                    "shift": item.shift,
                    "kind": item.kind,
                    "semester": semesters.get(item.course_id, 0),
                    "course_name": names.get(item.course_id, str(item.course_id)),
                }
            )
        return reports

    # ------------------------------ auto-fill ------------------------------ #
    def required_classes(self) -> list[dict[str, Any]]:
        """Every class that has to appear on the timetable.

        One entry per course-section lecture, plus one per lab when the course
        has a lab component.
        """
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    course_sections.c.course_id,
                    course_sections.c.section,
                    courses.c.code,
                    courses.c.name,
                    courses.c.semester,
                    courses.c.has_lab,
                    courses.c.credit_hours,
                    courses.c.lab_credit_hours,
                )
                .select_from(course_sections.join(courses, courses.c.id == course_sections.c.course_id))
                .order_by(courses.c.semester, courses.c.code, course_sections.c.section)
            ).all()
            teachers = {
                (r.course_id, r.section): r.name
                for r in conn.execute(
                    select(courses_taught_by.c.course_id, courses_taught_by.c.section, instructors.c.name)
                    .select_from(
                        courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id)
                    )
                )
            }

        required: list[dict[str, Any]] = []
        for row in rows:
            for kind in ("theory", "lab") if row.has_lab else ("theory",):
                required.append(
                    {
                        "course_id": row.course_id,
                        "code": row.code or "",
                        "course_name": row.name,
                        "section": row.section,
                        "kind": kind,
                        "semester": int(row.semester or 0),
                        "hours": int(row.lab_credit_hours if kind == "lab" else row.credit_hours),
                        "instructor": teachers.get((row.course_id, row.section), "Unassigned"),
                    }
                )
        return required

    def unscheduled(self, assignments: list[Assignment] | None = None) -> list[dict[str, Any]]:
        """Which required classes are missing from the given (or saved) grid."""
        if assignments is None:
            placed = {
                (int(e["course_id"]), str(e["section"]).upper(), str(e.get("kind") or "theory"))
                for e in self.load_timetable()
            }
        else:
            placed = {(a.course_id, a.section.upper(), a.kind) for a in assignments}
        return [
            item for item in self.required_classes()
            if (item["course_id"], str(item["section"]).upper(), item["kind"]) not in placed
        ]

    # ------------------------------ auto-fill ------------------------------ #
    def autofill(
        self,
        existing: list[Assignment],
        *,
        days: int,
        slots: list[dict[str, str]],
        room_ids: list[int],
        shift: str = "morning",
        limit: int | None = None,
        semester: int | None = None,
    ) -> list[Assignment]:
        """Greedily place every not-yet-scheduled class into a free slot.

        Everything is resolved in memory first (rosters, teachers, capacities,
        semesters, room types), so the search is pure computation - a full week
        fills in milliseconds.  Labs are steered towards Lab rooms and the
        hardest classes (largest enrolment) are placed first.
        """
        if not slots or not room_ids or days < 1:
            raise ValidationError("Generate a grid before using auto-fill.")

        with self.engine.connect() as conn:
            teacher_of = {
                (r.course_id, r.section): r.instructor_id
                for r in conn.execute(
                    select(courses_taught_by.c.course_id, courses_taught_by.c.section, courses_taught_by.c.instructor_id)
                )
            }
            roster_of: dict[tuple[int, str], set[str]] = {}
            for row in conn.execute(select(enrollments.c.course_id, enrollments.c.section, enrollments.c.roll_number)):
                roster_of.setdefault((row.course_id, row.section), set()).add(row.roll_number)
            room_rows = {
                r.id: {"capacity": r.capacity, "room_type": r.room_type}
                for r in conn.execute(select(rooms.c.id, rooms.c.capacity, rooms.c.room_type))
            }
            semester_of = {
                r.id: int(r.semester or 0) for r in conn.execute(select(courses.c.id, courses.c.semester))
            }

        def group_of(course_id: int, section: str) -> tuple[int, str] | None:
            """The student cohort: (semester, section).  None when unassigned."""
            sem = semester_of.get(course_id, 0)
            return (sem, str(section).upper()) if sem else None

        placed = [
            {
                "day": a.day,
                "start": a.start_min,
                "end": a.end_min,
                "room_id": a.room_id,
                "key": (a.course_id, a.section),
                "group": group_of(a.course_id, a.section),
            }
            for a in existing
        ]
        already = {(a.course_id, a.section.upper(), a.kind) for a in existing}

        todo = [
            item for item in self.required_classes()
            if (item["course_id"], str(item["section"]).upper(), item["kind"]) not in already
            and (semester is None or item["semester"] == semester)
        ]
        todo.sort(key=lambda item: -len(roster_of.get((item["course_id"], item["section"]), ())))
        if limit:
            todo = todo[:limit]

        normalised_slots = []
        for slot in slots:
            start = normalise_time(str(slot.get("start") or slot.get("start_time")))
            end = normalise_time(str(slot.get("end") or slot.get("end_time")))
            if to_minutes(end) <= to_minutes(start):
                raise ValidationError("Slot end must be after its start.")
            normalised_slots.append((start, end))

        created: list[Assignment] = []
        for item in todo:
            course_id, section, kind = item["course_id"], item["section"], item["kind"]
            roster = roster_of.get((course_id, section), set())
            teacher = teacher_of.get((course_id, section))
            group = group_of(course_id, section)
            # Labs go to Lab rooms when any exist; lectures avoid them so the
            # labs stay free.
            preferred = [rid for rid in room_ids if room_rows.get(rid, {}).get("room_type") == "Lab"]
            others = [rid for rid in room_ids if rid not in preferred]
            candidates = (preferred + others) if kind == "lab" else (others + preferred)
            done = False

            for day in range(1, days + 1):
                if done:
                    break
                for start, end in normalised_slots:
                    if done:
                        break
                    start_min, end_min = to_minutes(start), to_minutes(end)
                    overlapping = [
                        p for p in placed
                        if p["day"] == day and overlaps(start_min, end_min, p["start"], p["end"])
                    ]
                    busy_rooms = {p["room_id"] for p in overlapping}
                    blocked = any(
                        p["key"] == (course_id, section)
                        or (group is not None and p["group"] == group)
                        or (teacher is not None and teacher_of.get(p["key"]) == teacher)
                        or (roster and roster & roster_of.get(p["key"], set()))
                        for p in overlapping
                    )
                    if blocked:
                        continue
                    for room_id in candidates:
                        if room_id in busy_rooms:
                            continue
                        if roster and len(roster) > room_rows.get(room_id, {}).get("capacity", 0):
                            continue
                        assignment = Assignment(
                            day=day, start_time=start, end_time=end, room_id=room_id,
                            course_id=course_id, section=section, shift=shift, kind=kind,
                        )
                        created.append(assignment)
                        placed.append(
                            {"day": day, "start": start_min, "end": end_min, "room_id": room_id,
                             "key": (course_id, section), "group": group}
                        )
                        done = True
                        break
        return created

    # ------------------------------ persistence ---------------------------- #
    def load_timetable(self) -> list[dict[str, Any]]:
        enrolled = (
            select(
                enrollments.c.course_id.label("cid"),
                enrollments.c.section.label("sec"),
                func.count().label("num_students"),
            )
            .group_by(enrollments.c.course_id, enrollments.c.section)
            .subquery()
        )
        teacher = (
            select(
                courses_taught_by.c.course_id.label("cid"),
                courses_taught_by.c.section.label("sec"),
                instructors.c.name.label("instructor"),
            )
            .select_from(courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id))
            .subquery()
        )
        stmt = (
            select(
                timetable_entries.c.id,
                timetable_entries.c.day,
                timetable_entries.c.start_time,
                timetable_entries.c.end_time,
                timetable_entries.c.room_id,
                timetable_entries.c.course_id,
                timetable_entries.c.section,
                timetable_entries.c.shift,
                timetable_entries.c.kind,
                courses.c.name.label("course_name"),
                courses.c.code,
                courses.c.color,
                courses.c.semester,
                courses.c.credit_hours,
                courses.c.lab_credit_hours,
                rooms.c.room_number,
                rooms.c.capacity,
                rooms.c.room_type,
                buildings.c.name.label("building_name"),
                teacher.c.instructor,
                func.coalesce(enrolled.c.num_students, 0).label("num_students"),
            )
            .select_from(
                timetable_entries.join(courses, timetable_entries.c.course_id == courses.c.id)
                .join(rooms, timetable_entries.c.room_id == rooms.c.id)
                .join(buildings, rooms.c.building_id == buildings.c.id)
                .outerjoin(
                    teacher,
                    (teacher.c.cid == timetable_entries.c.course_id)
                    & (teacher.c.sec == timetable_entries.c.section),
                )
                .outerjoin(
                    enrolled,
                    (enrolled.c.cid == timetable_entries.c.course_id)
                    & (enrolled.c.sec == timetable_entries.c.section),
                )
            )
            .order_by(timetable_entries.c.day, timetable_entries.c.start_time, rooms.c.room_number)
        )
        with self.engine.connect() as conn:
            return [
                {
                    **dict(r),
                    "instructor": r.instructor or "Unassigned",
                    "kind": r.kind or "theory",
                    "semester": int(r.semester or 0),
                    "day_name": WEEKDAYS[int(r.day) - 1],
                    "room_label": f"{r.building_name}-{r.room_number}",
                }
                for r in conn.execute(stmt).mappings()
            ]

    def describe_assignments(self, assignments: list[Assignment]) -> list[dict[str, Any]]:
        """Turn raw assignments into export-ready rows (names, teacher, room…).

        Used by the Excel export so the user can export what is currently on
        screen without having to save it first.
        """
        if not assignments:
            return []
        with self.engine.connect() as conn:
            course_rows = {
                r.id: r
                for r in conn.execute(
                    select(
                        courses.c.id,
                        courses.c.code,
                        courses.c.name,
                        courses.c.color,
                        courses.c.department,
                        courses.c.semester,
                        courses.c.credit_hours,
                        courses.c.lab_credit_hours,
                    )
                )
            }
            room_rows = {
                r.id: r
                for r in conn.execute(
                    select(
                        rooms.c.id,
                        rooms.c.room_number,
                        rooms.c.capacity,
                        buildings.c.name.label("building_name"),
                    ).select_from(rooms.join(buildings, rooms.c.building_id == buildings.c.id))
                )
            }
            teachers = {
                (r.course_id, r.section): r.name
                for r in conn.execute(
                    select(
                        courses_taught_by.c.course_id,
                        courses_taught_by.c.section,
                        instructors.c.name,
                    ).select_from(
                        courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id)
                    )
                )
            }
            headcount = {
                (r.course_id, r.section): r.total
                for r in conn.execute(
                    select(
                        enrollments.c.course_id,
                        enrollments.c.section,
                        func.count().label("total"),
                    ).group_by(enrollments.c.course_id, enrollments.c.section)
                )
            }

        rows: list[dict[str, Any]] = []
        for item in assignments:
            course = course_rows.get(item.course_id)
            room = room_rows.get(item.room_id)
            rows.append(
                {
                    "id": item.entry_id,
                    "day": item.day,
                    "day_name": WEEKDAYS[item.day - 1],
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "shift": item.shift,
                    "room_id": item.room_id,
                    "room_number": room.room_number if room else item.room_id,
                    "capacity": room.capacity if room else 0,
                    "kind": item.kind,
                    "semester": int(course.semester or 0) if course else 0,
                    "building_name": room.building_name if room else "",
                    "room_label": f"{room.building_name}-{room.room_number}" if room else str(item.room_id),
                    "course_id": item.course_id,
                    "code": course.code if course else "",
                    "course_name": course.name if course else str(item.course_id),
                    "color": course.color if course else "#dddddd",
                    "department": course.department if course else "",
                    "credit_hours": int(course.credit_hours or 0) if course else 0,
                    "lab_credit_hours": int(course.lab_credit_hours or 0) if course else 0,
                    "section": item.section,
                    "instructor": teachers.get((item.course_id, item.section), "Unassigned"),
                    "num_students": headcount.get((item.course_id, item.section), 0),
                }
            )
        return rows

    def save_timetable(self, assignments: list[Assignment], *, replace: bool = True) -> dict[str, Any]:
        """Persist the grid atomically after a full validation pass."""
        reports = self.validate_timetable(assignments)
        blocking = [
            r for r in reports if any(c["severity"] == "error" for c in r["conflicts"])
        ]
        if blocking:
            return {"saved": 0, "ok": False, "conflicts": reports}

        with self.engine.begin() as conn:
            if replace:
                conn.execute(delete(timetable_entries))
            if assignments:
                conn.execute(insert(timetable_entries), [a.as_row() for a in assignments])
        return {"saved": len(assignments), "ok": True, "conflicts": reports}

    def clear_timetable(self) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(delete(timetable_entries))
        return result.rowcount or 0

    # ------------------------------- settings ------------------------------ #
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(settings_table.c.value).where(settings_table.c.key == key)).first()
        return row.value if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            existing = conn.execute(select(settings_table.c.key).where(settings_table.c.key == key)).first()
            if existing:
                conn.execute(
                    settings_table.update().where(settings_table.c.key == key).values(value=value)
                )
            else:
                conn.execute(insert(settings_table).values(key=key, value=value))

    # -------------------------------- stats -------------------------------- #
    def stats(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            def count(table) -> int:
                return int(conn.execute(select(func.count()).select_from(table)).scalar() or 0)

            return {
                "courses": count(courses),
                "sections": count(course_sections),
                "instructors": count(instructors),
                "rooms": count(rooms),
                "students": count(students),
                "enrollments": count(enrollments),
                "scheduled_classes": count(timetable_entries),
            }
