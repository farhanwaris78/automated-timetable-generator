"""Database schema, engine management and first-run seeding.

The application is portable across SQLite (default, zero-config) and
Microsoft SQL Server (optional, for institutional deployments).  All access
goes through SQLAlchemy Core with **bound parameters** - never string
interpolation - so the app is immune to SQL injection.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    event,
    insert,
    inspect,
    select,
)
from sqlalchemy.engine import Engine

from .config import bundle_dir

log = logging.getLogger(__name__)

metadata = MetaData()

courses = Table(
    "courses",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", String(255), nullable=False),
    Column("color", String(20), nullable=False, server_default="#4c5caf"),
    Column("department", String(100), nullable=False, server_default="General"),
)

course_sections = Table(
    "course_sections",
    metadata,
    Column("course_id", Integer, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
    Column("section", String(8), primary_key=True),
)

instructors = Table(
    "instructors",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", String(255), nullable=False),
)

courses_taught_by = Table(
    "courses_taught_by",
    metadata,
    Column("instructor_id", Integer, ForeignKey("instructors.id", ondelete="CASCADE"), primary_key=True),
    Column("course_id", Integer, primary_key=True),
    Column("section", String(8), primary_key=True),
    ForeignKeyConstraint(
        ["course_id", "section"],
        ["course_sections.course_id", "course_sections.section"],
        ondelete="CASCADE",
    ),
)

buildings = Table(
    "buildings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", String(255), nullable=False),
)

rooms = Table(
    "rooms",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("room_number", String(20), nullable=False),
    Column("building_id", Integer, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False),
    Column("capacity", Integer, nullable=False, server_default="60"),
    UniqueConstraint("building_id", "room_number", name="uq_room_per_building"),
)

students = Table(
    "students",
    metadata,
    Column("roll_number", String(16), primary_key=True),
    Column("name", String(100)),
    Column("parent_section", String(50)),
    Column("degree", String(50)),
    Column("batch", Integer),
    Column("gender", String(10)),
    Column("email", String(100)),
    Column("date_of_birth", Date),
    Column("cnic", String(15)),
    Column("mobile_number", String(20)),
    Column("blood_group", String(5)),
    Column("nationality", String(50)),
)

enrollments = Table(
    "enrollments",
    metadata,
    Column("roll_number", String(16), ForeignKey("students.roll_number", ondelete="CASCADE"), primary_key=True),
    Column("course_id", Integer, primary_key=True),
    Column("section", String(8), primary_key=True),
    Column("enrollment_date", Date),
    ForeignKeyConstraint(
        ["course_id", "section"],
        ["course_sections.course_id", "course_sections.section"],
        ondelete="CASCADE",
    ),
)

# One scheduled class = one row.  ``day`` is 1..7 (Monday == 1).
timetable_entries = Table(
    "timetable_entries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("day", Integer, nullable=False),
    Column("start_time", String(5), nullable=False),   # "HH:MM", 24h
    Column("end_time", String(5), nullable=False),     # "HH:MM", 24h
    Column("room_id", Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("course_id", Integer, nullable=False),
    Column("section", String(8), nullable=False),
    Column("created_at", String(32), nullable=False, server_default=""),
    CheckConstraint("day >= 1 AND day <= 7", name="ck_day_range"),
    UniqueConstraint("day", "start_time", "room_id", name="uq_room_slot"),
    ForeignKeyConstraint(
        ["course_id", "section"],
        ["course_sections.course_id", "course_sections.section"],
        ondelete="CASCADE",
    ),
)

settings_table = Table(
    "app_settings",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("value", String(2000), nullable=False),
)

ALL_TABLES = [
    courses,
    course_sections,
    instructors,
    courses_taught_by,
    buildings,
    rooms,
    students,
    enrollments,
    timetable_entries,
    settings_table,
]


class DatabaseError(RuntimeError):
    """Raised when the database cannot be reached or prepared."""


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def seed_payload() -> dict[str, list[dict[str, Any]]]:
    """Load the bundled demo dataset (FAST-NUCES sample)."""
    for candidate in (
        bundle_dir() / "seed_data.json",
        bundle_dir() / "timetable" / "seed_data.json",
        Path(__file__).resolve().parent / "seed_data.json",
    ):
        if candidate.is_file():
            with candidate.open("r", encoding="utf-8") as fh:
                return json.load(fh)
    log.warning("seed_data.json not found - starting with an empty database")
    return {}


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine with settings tuned for desktop usage."""
    kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        # check_same_thread=False: the Flask dev/waitress server is threaded.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    engine = create_engine(database_url, **kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


def _insert_rows(conn, table: Table, rows: Iterable[dict[str, Any]]) -> int:
    rows = [r for r in rows if r]
    if not rows:
        return 0
    conn.execute(insert(table), rows)
    return len(rows)


def seed_if_empty(engine: Engine, *, force: bool = False) -> bool:
    """Populate reference data on first run.  Returns True when seeded."""
    payload = seed_payload()
    if not payload:
        return False

    with engine.begin() as conn:
        if not force:
            existing = conn.execute(select(courses.c.id).limit(1)).first()
            if existing is not None:
                return False

        _insert_rows(conn, courses, payload.get("courses", []))
        _insert_rows(conn, course_sections, payload.get("course_sections", []))
        _insert_rows(conn, instructors, payload.get("instructors", []))
        _insert_rows(conn, courses_taught_by, payload.get("courses_taught_by", []))
        _insert_rows(conn, buildings, payload.get("buildings", []))
        _insert_rows(conn, rooms, payload.get("rooms", []))
        _insert_rows(
            conn,
            students,
            [{**s, "date_of_birth": _parse_date(s.get("date_of_birth"))} for s in payload.get("students", [])],
        )
        _insert_rows(
            conn,
            enrollments,
            [
                {**e, "enrollment_date": _parse_date(e.get("enrollment_date"))}
                for e in payload.get("enrollments", [])
            ],
        )
    log.info("Seeded database with the bundled sample dataset")
    return True


def init_database(database_url: str, *, seed: bool = True) -> Engine:
    """Create the engine, ensure the schema exists and seed on first run."""
    try:
        engine = create_db_engine(database_url)
        with engine.connect() as conn:  # fail fast with a clear message
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
        raise DatabaseError(str(exc)) from exc

    metadata.create_all(engine, checkfirst=True)

    if seed:
        try:
            seed_if_empty(engine)
        except Exception as exc:  # noqa: BLE001 - seeding must never be fatal
            log.warning("Could not seed sample data: %s", exc)

    missing = [t.name for t in ALL_TABLES if not inspect(engine).has_table(t.name)]
    if missing:
        raise DatabaseError(f"Tables could not be created: {', '.join(missing)}")
    return engine


def reset_database(engine: Engine) -> None:
    """Drop everything and re-seed - the 'factory reset' action."""
    metadata.drop_all(engine, checkfirst=True)
    metadata.create_all(engine)
    seed_if_empty(engine, force=True)
