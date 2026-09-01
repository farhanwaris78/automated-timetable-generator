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

        entry_id = raw.get("entry_id")
        return cls(
            day=day,
            start_time=start,
            end_time=end,
            room_id=room_id,
            course_id=course_id,
            section=section,
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
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


@dataclass
class Conflict:
    kind: str                       # room | instructor | student | duplicate | capacity | unknown
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
                courses.c.name,
                courses.c.color,
                courses.c.department,
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
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "color": r.color or "#4c5caf",
                    "department": r.department,
                    "section": r.section,
                    "instructor": r.instructor or "Unassigned",
                    "instructor_id": r.instructor_id,
                    "num_students": int(r.num_students or 0),
                    "label": f"{r.name} - {r.section}",
                    "key": f"{r.id}:{r.section}",
                }
                for r in conn.execute(stmt)
            ]

    def course_details(self, course_id: int, section: str) -> dict[str, Any] | None:
        stmt = (
            select(
                courses.c.id,
                courses.c.name,
                courses.c.color,
                courses.c.department,
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
                courses.c.name.label("course_name"),
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
                select(rooms.c.id, rooms.c.room_number, rooms.c.capacity, buildings.c.name.label("building"))
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
            missing_names = {e["course_id"] for e in existing if not e.get("course_name")}
            if missing_names:
                lookup = {
                    row.id: row.name
                    for row in conn.execute(select(courses.c.id, courses.c.name).where(courses.c.id.in_(missing_names)))
                }
                for entry in existing:
                    if not entry.get("course_name"):
                        entry["course_name"] = lookup.get(entry["course_id"], str(entry["course_id"]))

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
                other_label = f"{other.get('course_name', other['course_id'])} - {other['section']}"

                # 1. same course-section twice at the same time
                if other["course_id"] == candidate.course_id and other["section"] == candidate.section:
                    conflicts.append(
                        Conflict(
                            "duplicate",
                            "error",
                            f"{other_label} is already scheduled at {when} on "
                            f"{WEEKDAYS[candidate.day - 1]}.",
                            {"entry_id": other.get("id")},
                        )
                    )
                    continue

                # 2. room double booking
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

                # 3. instructor double booking
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

                # 4. student clash
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
            names = {c.id: c.name for c in conn.execute(select(courses.c.id, courses.c.name))}

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
                    "course_name": names.get(item.course_id, str(item.course_id)),
                }
            )
        return reports

    # ------------------------------ persistence ---------------------------- #
    def load_timetable(self) -> list[dict[str, Any]]:
        stmt = (
            select(
                timetable_entries.c.id,
                timetable_entries.c.day,
                timetable_entries.c.start_time,
                timetable_entries.c.end_time,
                timetable_entries.c.room_id,
                timetable_entries.c.course_id,
                timetable_entries.c.section,
                courses.c.name.label("course_name"),
                courses.c.color,
                rooms.c.room_number,
                buildings.c.name.label("building_name"),
            )
            .select_from(
                timetable_entries.join(courses, timetable_entries.c.course_id == courses.c.id)
                .join(rooms, timetable_entries.c.room_id == rooms.c.id)
                .join(buildings, rooms.c.building_id == buildings.c.id)
            )
            .order_by(timetable_entries.c.day, timetable_entries.c.start_time, rooms.c.room_number)
        )
        with self.engine.connect() as conn:
            return [
                {
                    **dict(r),
                    "day_name": WEEKDAYS[int(r.day) - 1],
                    "room_label": f"{r.building_name}-{r.room_number}",
                }
                for r in conn.execute(stmt).mappings()
            ]

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
