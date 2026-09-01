"""Catalogue management: create / update / delete teachers, rooms and courses.

Everything the "Manage data" screens need.  Kept separate from
:mod:`timetable.services` (which owns scheduling) so each module stays small
and testable.  All input is validated here - the web layer only translates
exceptions into HTTP status codes.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine

from .db import (
    buildings,
    course_sections,
    courses,
    courses_taught_by,
    enrollments,
    instructors,
    rooms,
    timetable_entries,
)
from .services import ValidationError

SHIFTS = ("morning", "evening", "both")
ROOM_TYPES = ("Classroom", "Lab", "Hall")
SECTION_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,23}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PALETTE = [
    "#A9D2E1", "#C1D8E7", "#8C9FB2", "#ADC4D6", "#9CA8B9", "#F2C6A0",
    "#EBD9A5", "#C7E1C0", "#E3C2D8", "#B7B5E4", "#F1B9B9", "#A8DAD5",
]


def _text(value: Any, field: str, *, max_length: int, required: bool = True, default: str = "") -> str:
    if value is None:
        value = default
    text = str(value).strip()
    if required and not text:
        raise ValidationError(f"{field} is required.")
    if len(text) > max_length:
        raise ValidationError(f"{field} must be {max_length} characters or fewer.")
    return text


def _int(value: Any, field: str, *, minimum: int, maximum: int, default: int | None = None) -> int:
    if value in (None, "") and default is not None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a whole number.") from None
    if not minimum <= number <= maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum}.")
    return number


def _choice(value: Any, field: str, options: Iterable[str], default: str) -> str:
    text = str(value or default).strip()
    lowered = {o.lower(): o for o in options}
    if text.lower() not in lowered:
        raise ValidationError(f"{field} must be one of: {', '.join(options)}.")
    return lowered[text.lower()]


class CatalogService:
    """CRUD for the reference data behind the timetable."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ #
    # instructors / teachers
    # ------------------------------------------------------------------ #
    def list_instructors(self) -> list[dict[str, Any]]:
        load = (
            select(
                courses_taught_by.c.instructor_id.label("iid"),
                func.count().label("sections"),
            )
            .group_by(courses_taught_by.c.instructor_id)
            .subquery()
        )
        stmt = (
            select(
                instructors.c.id,
                instructors.c.name,
                instructors.c.email,
                instructors.c.department,
                instructors.c.shift,
                func.coalesce(load.c.sections, 0).label("sections"),
            )
            .select_from(instructors.outerjoin(load, load.c.iid == instructors.c.id))
            .order_by(instructors.c.name)
        )
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(stmt).mappings()]

    def save_instructor(self, payload: dict[str, Any], instructor_id: int | None = None) -> dict[str, Any]:
        name = _text(payload.get("name"), "Teacher name", max_length=255)
        email = _text(payload.get("email"), "Email", max_length=150, required=False)
        if email and not EMAIL_RE.match(email):
            raise ValidationError("Email does not look like a valid address.")
        department = _text(payload.get("department"), "Department", max_length=100, required=False, default="General") or "General"
        shift = _choice(payload.get("shift"), "Shift", SHIFTS, "both")
        values = {"name": name, "email": email, "department": department, "shift": shift}

        with self.engine.begin() as conn:
            clash = conn.execute(
                select(instructors.c.id).where(func.lower(instructors.c.name) == name.lower())
            ).first()
            if clash and clash.id != instructor_id:
                raise ValidationError(f"A teacher called “{name}” already exists.")

            if instructor_id is None:
                new_id = conn.execute(insert(instructors).values(**values)).inserted_primary_key[0]
            else:
                updated = conn.execute(
                    update(instructors).where(instructors.c.id == instructor_id).values(**values)
                )
                if not updated.rowcount:
                    raise ValidationError("That teacher no longer exists.")
                new_id = instructor_id
        return {"id": new_id, **values}

    def delete_instructor(self, instructor_id: int) -> None:
        with self.engine.begin() as conn:
            teaching = conn.execute(
                select(func.count()).select_from(courses_taught_by).where(
                    courses_taught_by.c.instructor_id == instructor_id
                )
            ).scalar()
            if teaching:
                raise ValidationError(
                    f"This teacher is assigned to {teaching} section(s). "
                    "Reassign those sections first."
                )
            if not conn.execute(delete(instructors).where(instructors.c.id == instructor_id)).rowcount:
                raise ValidationError("That teacher no longer exists.")

    # ------------------------------------------------------------------ #
    # buildings & rooms
    # ------------------------------------------------------------------ #
    def list_buildings(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(select(buildings).order_by(buildings.c.name)).mappings()]

    def save_building(self, payload: dict[str, Any], building_id: int | None = None) -> dict[str, Any]:
        name = _text(payload.get("name"), "Building name", max_length=255)
        with self.engine.begin() as conn:
            clash = conn.execute(
                select(buildings.c.id).where(func.lower(buildings.c.name) == name.lower())
            ).first()
            if clash and clash.id != building_id:
                raise ValidationError(f"Building “{name}” already exists.")
            if building_id is None:
                building_id = conn.execute(insert(buildings).values(name=name)).inserted_primary_key[0]
            else:
                conn.execute(update(buildings).where(buildings.c.id == building_id).values(name=name))
        return {"id": building_id, "name": name}

    def delete_building(self, building_id: int) -> None:
        with self.engine.begin() as conn:
            used = conn.execute(
                select(func.count()).select_from(rooms).where(rooms.c.building_id == building_id)
            ).scalar()
            if used:
                raise ValidationError(f"This building still holds {used} room(s). Delete them first.")
            conn.execute(delete(buildings).where(buildings.c.id == building_id))

    def save_room(self, payload: dict[str, Any], room_id: int | None = None) -> dict[str, Any]:
        number = _text(payload.get("room_number"), "Room number", max_length=20)
        capacity = _int(payload.get("capacity"), "Capacity", minimum=1, maximum=2000, default=60)
        room_type = _choice(payload.get("room_type"), "Room type", ROOM_TYPES, "Classroom")

        building_id = payload.get("building_id")
        building_name = str(payload.get("building_name") or "").strip()
        with self.engine.begin() as conn:
            if not building_id and building_name:
                found = conn.execute(
                    select(buildings.c.id).where(func.lower(buildings.c.name) == building_name.lower())
                ).first()
                building_id = found.id if found else conn.execute(
                    insert(buildings).values(name=building_name)
                ).inserted_primary_key[0]
            building_id = _int(building_id, "Building", minimum=1, maximum=10**9)
            if not conn.execute(select(buildings.c.id).where(buildings.c.id == building_id)).first():
                raise ValidationError("Pick an existing building (or type a new name).")

            clash = conn.execute(
                select(rooms.c.id).where(
                    rooms.c.building_id == building_id, func.lower(rooms.c.room_number) == number.lower()
                )
            ).first()
            if clash and clash.id != room_id:
                raise ValidationError(f"Room {number} already exists in that building.")

            values = {
                "room_number": number,
                "building_id": building_id,
                "capacity": capacity,
                "room_type": room_type,
            }
            if room_id is None:
                room_id = conn.execute(insert(rooms).values(**values)).inserted_primary_key[0]
            else:
                if not conn.execute(update(rooms).where(rooms.c.id == room_id).values(**values)).rowcount:
                    raise ValidationError("That room no longer exists.")
        return {"id": room_id, **values}

    def delete_room(self, room_id: int) -> None:
        with self.engine.begin() as conn:
            scheduled = conn.execute(
                select(func.count()).select_from(timetable_entries).where(timetable_entries.c.room_id == room_id)
            ).scalar()
            if scheduled:
                raise ValidationError(
                    f"{scheduled} saved class(es) use this room. Remove them from the saved timetable first."
                )
            if not conn.execute(delete(rooms).where(rooms.c.id == room_id)).rowcount:
                raise ValidationError("That room no longer exists.")

    # ------------------------------------------------------------------ #
    # courses & sections
    # ------------------------------------------------------------------ #
    def list_courses_admin(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(courses).order_by(courses.c.code, courses.c.name)).mappings().all()
            section_rows = conn.execute(
                select(course_sections.c.course_id, course_sections.c.section).order_by(course_sections.c.section)
            ).all()
            teaching = conn.execute(
                select(
                    courses_taught_by.c.course_id,
                    courses_taught_by.c.section,
                    instructors.c.id.label("instructor_id"),
                    instructors.c.name.label("instructor"),
                ).select_from(
                    courses_taught_by.join(instructors, courses_taught_by.c.instructor_id == instructors.c.id)
                )
            ).all()

        by_course: dict[int, list[dict[str, Any]]] = {}
        teacher_map = {(t.course_id, t.section): (t.instructor_id, t.instructor) for t in teaching}
        for row in section_rows:
            instructor_id, instructor = teacher_map.get((row.course_id, row.section), (None, None))
            by_course.setdefault(row.course_id, []).append(
                {"section": row.section, "instructor_id": instructor_id, "instructor": instructor or "Unassigned"}
            )

        return [{**dict(course), "sections": by_course.get(course["id"], [])} for course in rows]

    def save_course(self, payload: dict[str, Any], course_id: int | None = None) -> dict[str, Any]:
        code = _text(payload.get("code"), "Course code", max_length=24)
        if not CODE_RE.match(code):
            raise ValidationError("Course code may contain letters, digits, spaces, dots, dashes and underscores.")
        name = _text(payload.get("name"), "Course name", max_length=255)
        department = _text(payload.get("department"), "Department", max_length=100, required=False, default="General") or "General"
        credit_hours = _int(payload.get("credit_hours"), "Credit hours", minimum=0, maximum=12, default=3)
        color = str(payload.get("color") or "").strip()
        if not color:
            color = PALETTE[abs(hash(code.upper())) % len(PALETTE)]
        if not COLOR_RE.match(color):
            raise ValidationError("Colour must look like #RRGGBB.")

        values = {
            "code": code.upper(),
            "name": name,
            "department": department,
            "credit_hours": credit_hours,
            "color": color,
        }
        with self.engine.begin() as conn:
            clash = conn.execute(
                select(courses.c.id).where(func.upper(courses.c.code) == code.upper())
            ).first()
            if clash and clash.id != course_id:
                raise ValidationError(f"Course code “{code.upper()}” is already used.")

            if course_id is None:
                course_id = conn.execute(insert(courses).values(**values)).inserted_primary_key[0]
            else:
                if not conn.execute(update(courses).where(courses.c.id == course_id).values(**values)).rowcount:
                    raise ValidationError("That course no longer exists.")

        for section in payload.get("sections") or []:
            self.save_section(course_id, section)
        return {"id": course_id, **values}

    def delete_course(self, course_id: int) -> None:
        with self.engine.begin() as conn:
            scheduled = conn.execute(
                select(func.count()).select_from(timetable_entries).where(timetable_entries.c.course_id == course_id)
            ).scalar()
            if scheduled:
                raise ValidationError(
                    f"{scheduled} saved class(es) use this course. Clear them from the saved timetable first."
                )
            conn.execute(delete(enrollments).where(enrollments.c.course_id == course_id))
            conn.execute(delete(courses_taught_by).where(courses_taught_by.c.course_id == course_id))
            conn.execute(delete(course_sections).where(course_sections.c.course_id == course_id))
            if not conn.execute(delete(courses).where(courses.c.id == course_id)).rowcount:
                raise ValidationError("That course no longer exists.")

    def save_section(self, course_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        section = _text(payload.get("section"), "Section", max_length=8).upper()
        if not SECTION_RE.match(section):
            raise ValidationError("Section may only contain letters and digits (max 8).")
        instructor_id = payload.get("instructor_id")
        instructor_id = None if instructor_id in (None, "", "null") else _int(
            instructor_id, "Instructor", minimum=1, maximum=10**9
        )

        with self.engine.begin() as conn:
            if not conn.execute(select(courses.c.id).where(courses.c.id == course_id)).first():
                raise ValidationError("That course no longer exists.")
            exists = conn.execute(
                select(course_sections.c.section).where(
                    course_sections.c.course_id == course_id, course_sections.c.section == section
                )
            ).first()
            if not exists:
                conn.execute(insert(course_sections).values(course_id=course_id, section=section))

            conn.execute(
                delete(courses_taught_by).where(
                    courses_taught_by.c.course_id == course_id, courses_taught_by.c.section == section
                )
            )
            if instructor_id is not None:
                if not conn.execute(select(instructors.c.id).where(instructors.c.id == instructor_id)).first():
                    raise ValidationError("That teacher no longer exists.")
                conn.execute(
                    insert(courses_taught_by).values(
                        instructor_id=instructor_id, course_id=course_id, section=section
                    )
                )
        return {"course_id": course_id, "section": section, "instructor_id": instructor_id}

    def delete_section(self, course_id: int, section: str) -> None:
        section = str(section).strip().upper()
        with self.engine.begin() as conn:
            scheduled = conn.execute(
                select(func.count()).select_from(timetable_entries).where(
                    timetable_entries.c.course_id == course_id, timetable_entries.c.section == section
                )
            ).scalar()
            if scheduled:
                raise ValidationError("This section appears in the saved timetable. Remove it there first.")
            conn.execute(
                delete(enrollments).where(
                    enrollments.c.course_id == course_id, enrollments.c.section == section
                )
            )
            conn.execute(
                delete(courses_taught_by).where(
                    courses_taught_by.c.course_id == course_id, courses_taught_by.c.section == section
                )
            )
            removed = conn.execute(
                delete(course_sections).where(
                    course_sections.c.course_id == course_id, course_sections.c.section == section
                )
            )
            if not removed.rowcount:
                raise ValidationError("That section no longer exists.")
