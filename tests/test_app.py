"""End-to-end tests for the API and the clash-detection engine.

Run with:  python -m pytest -q
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from timetable.config import Settings  # noqa: E402
from timetable.db import init_database  # noqa: E402
from timetable.services import Assignment, TimetableService, ValidationError, to_minutes  # noqa: E402
from timetable.web import create_app  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    os.environ["TTG_DATA_DIR"] = str(tmp_path)
    return Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}", log_dir=tmp_path)


@pytest.fixture()
def app(settings: Settings):
    application = create_app(settings)
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def service(settings: Settings) -> TimetableService:
    return TimetableService(init_database(settings.database_url))


# --------------------------------------------------------------------------- #
# smoke
# --------------------------------------------------------------------------- #
def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Automated Timetable Generator" in response.data


def test_health_reports_seeded_stats(client):
    payload = client.get("/api/health").get_json()
    assert payload["status"] == "ok"
    assert payload["stats"]["courses"] == 18
    assert payload["stats"]["rooms"] == 36
    assert payload["stats"]["sections"] == 45


def test_courses_include_instructor_and_headcount(client):
    courses = client.get("/api/courses").get_json()
    assert len(courses) == 45          # one row per course-section
    sample = courses[0]
    for key in ("id", "name", "color", "section", "instructor", "num_students"):
        assert key in sample


def test_course_details_and_404(client):
    details = client.get("/api/course-details/101/A").get_json()
    assert details["section"] == "A"
    assert isinstance(details["students"], list)
    assert client.get("/api/course-details/101/Z").status_code == 404
    assert client.get("/api/course-details/9999/A").status_code == 404


def test_rooms_are_labelled(client):
    rooms = client.get("/api/rooms").get_json()
    assert rooms[0]["label"].startswith("A-")
    assert rooms[0]["capacity"] > 0


# --------------------------------------------------------------------------- #
# validation helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", ["8:30", "08:30", "23:59", "00:00"])
def test_valid_times(value):
    assert to_minutes(value) >= 0


@pytest.mark.parametrize("value", ["24:00", "8:70", "half past 8", "", "0830", None])
def test_invalid_times_rejected(value):
    with pytest.raises(ValidationError):
        to_minutes(value)


def test_assignment_rejects_backwards_slot():
    with pytest.raises(ValidationError):
        Assignment.from_payload(
            {"day": 1, "start_time": "10:00", "end_time": "09:00", "room_id": 1, "course_id": 101, "section": "A"}
        )


def test_assignment_rejects_bad_day():
    with pytest.raises(ValidationError):
        Assignment.from_payload(
            {"day": 9, "start_time": "09:00", "end_time": "10:00", "room_id": 1, "course_id": 101, "section": "A"}
        )


# --------------------------------------------------------------------------- #
# clash detection
# --------------------------------------------------------------------------- #
def make(day=1, start="09:00", end="10:20", room=1, course=101, section="A"):
    return Assignment(day=day, start_time=start, end_time=end, room_id=room, course_id=course, section=section)


def test_no_conflict_on_empty_grid(service):
    assert service.check_assignment(make(), others=[]) == []


def grid_from(*assignments):
    return [
        {
            "id": None,
            "day": a.day,
            "start_time": a.start_time,
            "end_time": a.end_time,
            "room_id": a.room_id,
            "course_id": a.course_id,
            "section": a.section,
            "course_name": f"Course {a.course_id}",
        }
        for a in assignments
    ]


def test_room_double_booking_detected(service):
    placed = make(course=101, section="A", room=5)
    conflicts = service.check_assignment(make(course=103, section="A", room=5), others=grid_from(placed))
    assert any(c.kind == "room" for c in conflicts)


def test_partial_overlap_detected(service):
    placed = make(course=101, section="A", room=5, start="09:00", end="10:20")
    candidate = make(course=103, section="A", room=5, start="10:00", end="11:20")
    assert any(c.kind == "room" for c in service.check_assignment(candidate, others=grid_from(placed)))


def test_back_to_back_is_allowed(service):
    placed = make(course=101, section="A", room=5, start="09:00", end="10:20")
    candidate = make(course=103, section="A", room=5, start="10:20", end="11:40")
    assert service.check_assignment(candidate, others=grid_from(placed)) == []


def test_different_day_is_allowed(service):
    placed = make(day=1, room=5)
    candidate = make(day=2, room=5, course=103)
    assert service.check_assignment(candidate, others=grid_from(placed)) == []


def test_instructor_double_booking_detected(service):
    # Dr. Hammad Majeed (111) teaches MLOps A and MLOps B.
    placed = make(course=101, section="A", room=1)
    candidate = make(course=101, section="B", room=2)
    conflicts = service.check_assignment(candidate, others=grid_from(placed))
    assert any(c.kind == "instructor" for c in conflicts)


def test_student_clash_lists_roll_numbers(service):
    # 20I-0546 is enrolled in MLOps A (101) and Network Security A (102).
    placed = make(course=101, section="A", room=1)
    candidate = make(course=102, section="A", room=2)
    conflicts = service.check_assignment(candidate, others=grid_from(placed))
    student = [c for c in conflicts if c.kind == "student"]
    assert student, "expected a student clash"
    assert "20I-0546" in student[0].details["roll_numbers"]


def test_duplicate_section_detected(service):
    placed = make(course=101, section="A", room=1)
    candidate = make(course=101, section="A", room=2)
    assert any(c.kind == "duplicate" for c in service.check_assignment(candidate, others=grid_from(placed)))


def test_unknown_course_or_room_rejected(service):
    assert service.check_assignment(make(course=999), others=[])[0].kind == "unknown"
    assert service.check_assignment(make(room=9999), others=[])[0].kind == "unknown"


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def test_save_load_and_reset_roundtrip(client):
    payload = {
        "assignments": [
            {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1, "course_id": 101, "section": "A"},
            {"day": 1, "start_time": "10:00", "end_time": "11:20", "room_id": 2, "course_id": 103, "section": "B"},
        ]
    }
    saved = client.post("/api/timetable", json=payload)
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()["saved"] == 2

    entries = client.get("/api/timetable").get_json()["entries"]
    assert len(entries) == 2
    assert entries[0]["room_label"].startswith("A-")

    # saving again must replace, not duplicate
    client.post("/api/timetable", json=payload)
    assert len(client.get("/api/timetable").get_json()["entries"]) == 2

    reset = client.post("/api/timetable/reset").get_json()
    assert reset["removed"] == 2
    assert client.get("/api/timetable").get_json()["entries"] == []


def test_save_is_rejected_when_the_grid_clashes(client):
    payload = {
        "assignments": [
            {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1, "course_id": 101, "section": "A"},
            {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1, "course_id": 103, "section": "A"},
        ]
    }
    response = client.post("/api/timetable", json=payload)
    assert response.status_code == 409
    assert response.get_json()["saved"] == 0
    assert client.get("/api/timetable").get_json()["entries"] == []   # nothing partially written


def test_validate_endpoint_reports_candidate_conflicts(client):
    body = {
        "candidate": {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1, "course_id": 101, "section": "B"},
        "grid": [
            {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 2, "course_id": 101, "section": "A"}
        ],
    }
    result = client.post("/api/timetable/validate", json=body).get_json()
    assert result["ok"] is False
    assert any(c["kind"] == "instructor" for c in result["conflicts"])


def test_malformed_payloads_return_400_not_500(client):
    assert client.post("/api/timetable", data="not json", content_type="application/json").status_code == 400
    assert client.post("/api/timetable", json={"assignments": [{"day": 1}]}).status_code == 400
    assert client.post("/api/timetable", json={"assignments": "nope"}).status_code == 400


def test_sql_injection_attempt_is_harmless(client):
    payload = {
        "assignments": [
            {
                "day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
                "course_id": 101, "section": "A'); DROP TABLE courses;--",
            }
        ]
    }
    response = client.post("/api/timetable", json=payload)
    assert response.status_code == 409          # rejected as an unknown section
    assert client.get("/api/health").get_json()["stats"]["courses"] == 18   # table intact


def test_settings_roundtrip(client):
    client.post("/api/settings", json={"days": 6, "start": "09:00"})
    assert client.get("/api/settings").get_json()["days"] == 6


def test_legacy_routes_still_answer(client):
    assert client.post("/save-timetable", json={"assigned_courses": []}).status_code == 200
    assert client.post("/reset-timetable", json={}).status_code == 200


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.is_json


def test_database_failure_is_reported_gracefully(tmp_path):
    broken = Settings(database_url="postgresql+psycopg2://nobody@127.0.0.1:1/none", log_dir=tmp_path)
    application = create_app(broken)
    test_client = application.test_client()
    assert test_client.get("/").status_code == 200          # UI still loads
    assert test_client.get("/api/health").status_code == 503
    assert test_client.get("/api/courses").status_code == 503


# =========================================================================== #
# v2.1 - catalogue management, shifts, auto-fill, Excel export
# =========================================================================== #
from timetable.catalog import CatalogService  # noqa: E402
from timetable.exporters import build_workbook, openpyxl_available  # noqa: E402


@pytest.fixture()
def catalog(settings: Settings) -> CatalogService:
    return CatalogService(init_database(settings.database_url))


# ------------------------------- teachers ---------------------------------- #
def test_add_edit_delete_teacher(client):
    created = client.post("/api/instructors", json={
        "name": "Dr. New Person", "email": "new@uni.edu", "department": "CS", "shift": "evening"
    })
    assert created.status_code == 201
    teacher_id = created.get_json()["id"]

    listing = client.get("/api/instructors").get_json()
    assert any(t["id"] == teacher_id and t["shift"] == "evening" for t in listing)

    updated = client.put(f"/api/instructors/{teacher_id}", json={"name": "Dr. Renamed", "department": "SE"})
    assert updated.get_json()["name"] == "Dr. Renamed"

    assert client.delete(f"/api/instructors/{teacher_id}").status_code == 200
    assert not any(t["id"] == teacher_id for t in client.get("/api/instructors").get_json())


def test_teacher_validation(client):
    assert client.post("/api/instructors", json={"name": "  "}).status_code == 400
    assert client.post("/api/instructors", json={"name": "X", "email": "not-an-email"}).status_code == 400
    client.post("/api/instructors", json={"name": "Unique Person"})
    assert client.post("/api/instructors", json={"name": "unique person"}).status_code == 400  # case-insensitive


def test_busy_teacher_cannot_be_deleted(client):
    teachers = client.get("/api/instructors").get_json()
    busy = next(t for t in teachers if t["sections"] > 0)
    response = client.delete(f"/api/instructors/{busy['id']}")
    assert response.status_code == 400
    assert "section" in response.get_json()["message"].lower()


# --------------------------------- rooms ----------------------------------- #
def test_add_room_creating_its_building_on_the_fly(client):
    response = client.post("/api/rooms", json={
        "room_number": "Z-9", "building_name": "New Block", "capacity": 35, "room_type": "Lab"
    })
    assert response.status_code == 201
    room_id = response.get_json()["id"]

    rooms = client.get("/api/rooms").get_json()
    room = next(r for r in rooms if r["id"] == room_id)
    assert room["room_type"] == "Lab" and room["capacity"] == 35
    assert any(b["name"] == "New Block" for b in client.get("/api/buildings").get_json())

    assert client.delete(f"/api/rooms/{room_id}").status_code == 200


def test_duplicate_room_in_same_building_rejected(client):
    first = client.post("/api/rooms", json={"room_number": "777", "building_name": "A"})
    assert first.status_code == 201
    assert client.post("/api/rooms", json={"room_number": "777", "building_name": "A"}).status_code == 400
    # ... but the same number in another building is fine
    assert client.post("/api/rooms", json={"room_number": "777", "building_name": "B"}).status_code == 201


def test_room_used_by_saved_timetable_cannot_be_deleted(client):
    client.post("/api/timetable", json={"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1, "course_id": 101, "section": "A"}
    ]})
    assert client.delete("/api/rooms/1").status_code == 400


def test_invalid_room_payloads(client):
    assert client.post("/api/rooms", json={"room_number": "", "building_name": "A"}).status_code == 400
    assert client.post("/api/rooms", json={"room_number": "1", "building_name": "A", "capacity": 0}).status_code == 400
    assert client.post("/api/rooms", json={"room_number": "1", "building_name": "A", "room_type": "Cave"}).status_code == 400


# ----------------------------- courses & codes ------------------------------ #
def test_add_course_with_code_and_sections(client):
    teacher_id = client.get("/api/instructors").get_json()[0]["id"]
    response = client.post("/api/courses", json={
        "code": "cs5099", "name": "Advanced Topics", "department": "Computer Science",
        "credit_hours": 4, "color": "#123456",
        "sections": [{"section": "a", "instructor_id": teacher_id}, {"section": "b"}],
    })
    assert response.status_code == 201
    body = response.get_json()
    assert body["code"] == "CS5099"          # normalised to upper case

    admin = next(c for c in client.get("/api/admin/courses").get_json() if c["id"] == body["id"])
    assert {s["section"] for s in admin["sections"]} == {"A", "B"}
    assert admin["sections"][0]["instructor_id"] == teacher_id

    catalogue = client.get("/api/courses").get_json()
    assert any(c["code"] == "CS5099" and c["credit_hours"] == 4 for c in catalogue)


def test_course_code_must_be_unique_and_valid(client):
    client.post("/api/courses", json={"code": "CS7000", "name": "One"})
    assert client.post("/api/courses", json={"code": "cs7000", "name": "Two"}).status_code == 400
    assert client.post("/api/courses", json={"code": "", "name": "Three"}).status_code == 400
    assert client.post("/api/courses", json={"code": "BAD/CODE", "name": "Four"}).status_code == 400
    assert client.post("/api/courses", json={"code": "OK1", "name": "", }).status_code == 400
    assert client.post("/api/courses", json={"code": "OK2", "name": "Five", "color": "red"}).status_code == 400


def test_course_gets_an_automatic_colour(client):
    body = client.post("/api/courses", json={"code": "CS7100", "name": "Auto Colour"}).get_json()
    assert re.match(r"^#[0-9A-Fa-f]{6}$", body["color"])


def test_sections_can_be_added_and_removed(client):
    course_id = client.post("/api/courses", json={"code": "CS7200", "name": "Sectioned"}).get_json()["id"]
    assert client.post(f"/api/courses/{course_id}/sections", json={"section": "z"}).status_code == 201
    admin = next(c for c in client.get("/api/admin/courses").get_json() if c["id"] == course_id)
    assert [s["section"] for s in admin["sections"]] == ["Z"]
    assert client.delete(f"/api/courses/{course_id}/sections/Z").status_code == 200
    assert client.delete(f"/api/courses/{course_id}/sections/Z").status_code == 400   # already gone


def test_course_in_saved_timetable_cannot_be_deleted(client):
    client.post("/api/timetable", json={"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1, "course_id": 101, "section": "A"}
    ]})
    assert client.delete("/api/courses/101").status_code == 400
    client.post("/api/timetable/reset")
    assert client.delete("/api/courses/101").status_code == 200


# --------------------------------- shifts ----------------------------------- #
def test_shift_is_persisted_with_each_class(client):
    payload = {"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
         "course_id": 101, "section": "A", "shift": "morning"},
        {"day": 7, "start_time": "18:00", "end_time": "19:20", "room_id": 2,
         "course_id": 103, "section": "A", "shift": "evening"},
    ]}
    assert client.post("/api/timetable", json=payload).status_code == 200
    entries = client.get("/api/timetable").get_json()["entries"]
    assert {e["shift"] for e in entries} == {"morning", "evening"}
    assert max(e["day"] for e in entries) == 7          # full 7-day week supported


def test_unknown_shift_falls_back_to_morning(client):
    client.post("/api/timetable", json={"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
         "course_id": 101, "section": "A", "shift": "nonsense"}
    ]})
    assert client.get("/api/timetable").get_json()["entries"][0]["shift"] == "morning"


# -------------------------------- auto-fill ---------------------------------- #
def test_autofill_places_sections_without_any_clash(client):
    slots = [{"start": "08:30", "end": "09:50"}, {"start": "10:00", "end": "11:20"},
             {"start": "11:30", "end": "12:50"}]
    response = client.post("/api/timetable/autofill", json={
        "assignments": [], "days": 5, "slots": slots,
        "room_ids": [1, 2, 3, 4, 5, 6], "shift": "morning",
    })
    created = response.get_json()["created"]
    assert len(created) == 45                                    # every section placed
    assert all(c["shift"] == "morning" for c in created)

    verdict = client.post("/api/timetable/validate", json={"assignments": created}).get_json()
    assert verdict["ok"] is True, verdict.get("reports")


def test_autofill_respects_what_is_already_placed(client):
    existing = [{"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
                 "course_id": 101, "section": "A", "shift": "morning"}]
    created = client.post("/api/timetable/autofill", json={
        "assignments": existing, "days": 5,
        "slots": [{"start": "08:30", "end": "09:50"}, {"start": "10:00", "end": "11:20"}],
        "room_ids": [1, 2, 3, 4],
    }).get_json()["created"]
    assert not any(c["course_id"] == 101 and c["section"] == "A" for c in created)
    combined = client.post("/api/timetable/validate", json={"assignments": existing + created}).get_json()
    assert combined["ok"] is True


def test_autofill_needs_a_grid(client):
    assert client.post("/api/timetable/autofill", json={"days": 5, "slots": [], "room_ids": []}).status_code == 400


# ------------------------------ Excel export --------------------------------- #
@pytest.mark.skipif(not openpyxl_available(), reason="openpyxl not installed")
def test_excel_export_has_one_sheet_per_day(client):
    client.post("/api/timetable", json={"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
         "course_id": 101, "section": "A", "shift": "morning"},
        {"day": 6, "start_time": "18:00", "end_time": "19:20", "room_id": 2,
         "course_id": 103, "section": "A", "shift": "evening"},
    ]})
    response = client.post("/api/export/xlsx", json={"days": 7, "shift": "all"})
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )

    import io as _io
    import openpyxl

    workbook = openpyxl.load_workbook(_io.BytesIO(response.data))
    assert workbook.sheetnames == [
        "Summary", "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday", "By Teacher",
    ]
    summary = workbook["Summary"]
    assert [c.value for c in summary[1]][:4] == ["Day", "Shift", "Start", "End"]
    assert summary.cell(row=2, column=1).value == "Monday"


@pytest.mark.skipif(not openpyxl_available(), reason="openpyxl not installed")
def test_excel_export_works_on_an_unsaved_grid(client):
    response = client.post("/api/export/xlsx", json={
        "days": 2,
        "assignments": [{"day": 2, "start_time": "09:00", "end_time": "10:00", "room_id": 5,
                         "course_id": 104, "section": "A", "shift": "morning"}],
    })
    assert response.status_code == 200
    assert client.get("/api/timetable").get_json()["entries"] == []      # nothing was saved


def test_excel_export_rejects_an_empty_timetable(client):
    assert client.post("/api/export/xlsx", json={}).status_code == 400


# ------------------------------- migrations ---------------------------------- #
def test_migration_adds_columns_to_an_old_database(tmp_path):
    """Simulate a v2.0 database and prove it upgrades in place."""
    from sqlalchemy import create_engine, inspect, text

    db_file = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE courses (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL, "
            "color VARCHAR(20) NOT NULL DEFAULT '#4c5caf', department VARCHAR(100) NOT NULL DEFAULT 'General')"
        ))
        conn.execute(text("INSERT INTO courses (id, name, department) VALUES (501, 'Legacy Course', 'Computer Science')"))
    engine.dispose()

    upgraded = init_database(f"sqlite:///{db_file.as_posix()}", seed=False)
    columns = {c["name"] for c in inspect(upgraded).get_columns("courses")}
    assert {"code", "credit_hours"} <= columns

    with upgraded.connect() as conn:
        code = conn.execute(text("SELECT code FROM courses WHERE id = 501")).scalar()
    assert code                     # a code was back-filled, not left blank
