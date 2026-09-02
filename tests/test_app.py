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
    assert len(courses) == 65          # 45 lectures + 20 labs
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
from timetable.exporters import build_workbook, format_time_range, openpyxl_available  # noqa: E402


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
    assert len(created) == 65                          # every lecture *and* every lab
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
    names = workbook.sheetnames
    assert names[:8] == [
        "Summary", "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday",
    ]
    # one sheet per semester that actually has classes, then the roll-ups
    assert [n for n in names if n.startswith("Semester ")] == ["Semester 1", "Semester 3"]
    assert "By Teacher" in names and "Unscheduled" in names

    summary = workbook["Summary"]
    assert [c.value for c in summary[1]][:6] == ["Day", "Shift", "Semester", "Type", "Start", "End"]
    assert summary.cell(row=2, column=1).value == "Monday"

    semester = workbook["Semester 1"]
    assert semester.cell(row=4, column=1).value == "Day / Section"
    assert semester.cell(row=5, column=1).value.startswith("Monday")

    gaps = workbook["Unscheduled"]
    assert gaps.cell(row=3, column=1).value == "Semester"
    assert gaps.cell(row=4, column=5).value in ("Theory", "Lab")


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


# --------------------- exports written to a chosen folder --------------------- #
def _one_class(client):
    client.post("/api/timetable", json={"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
         "course_id": 101, "section": "A", "shift": "morning"},
    ]})


@pytest.mark.skipif(not openpyxl_available(), reason="openpyxl not installed")
def test_export_is_written_into_the_requested_folder(client, tmp_path):
    """Exports land beside the project instead of in the Downloads folder."""
    _one_class(client)
    folder = tmp_path / "Spring 2026"

    response = client.post("/api/export/xlsx", json={"folder": str(folder)})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["saved"] is True
    written = Path(payload["path"])
    assert written.parent == folder.resolve()      # folder was created for us
    assert written.is_file() and written.stat().st_size > 0
    assert not list(folder.glob("*.part"))         # atomic write left no debris


@pytest.mark.skipif(not openpyxl_available(), reason="openpyxl not installed")
def test_repeated_exports_never_overwrite(client, tmp_path):
    _one_class(client)
    first = client.post("/api/export/xlsx", json={"folder": str(tmp_path)}).get_json()
    second = client.post("/api/export/xlsx", json={"folder": str(tmp_path)}).get_json()
    third = client.post("/api/export/xlsx", json={"folder": str(tmp_path)}).get_json()
    assert Path(first["path"]).name == "timetable.xlsx"
    assert Path(second["path"]).name == "timetable (2).xlsx"
    assert Path(third["path"]).name == "timetable (3).xlsx"

    # ...unless the caller explicitly asks for it.
    again = client.post("/api/export/xlsx", json={"folder": str(tmp_path), "overwrite": True}).get_json()
    assert Path(again["path"]).name == "timetable.xlsx"


def test_csv_export_matches_the_workbook_columns(client, tmp_path):
    _one_class(client)
    payload = client.post("/api/export/csv", json={"folder": str(tmp_path)}).get_json()
    text = Path(payload["path"]).read_text(encoding="utf-8")
    assert text.startswith("\ufeff")             # Excel-friendly BOM
    header = text.splitlines()[0]
    for column in ("Day", "Room", "Building", "Room type", "Capacity",
                   "Code", "Course", "Section", "Kind", "Teacher", "Semester", "Students"):
        assert f'"{column}"' in header
    row = text.splitlines()[1]
    assert '"Monday"' in row and '"Theory"' in row
    assert '"A-108"' in row or '"A-101"' in row   # a real room label, not an id


def test_csv_export_streams_when_no_folder_is_given(client):
    _one_class(client)
    response = client.post("/api/export/csv", json={})
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    assert response.data.startswith("\ufeff".encode("utf-8"))


def test_pdf_and_ics_also_honour_the_folder(client, tmp_path):
    _one_class(client)
    pdf = client.post("/api/publish/pdf", json={"folder": str(tmp_path), "scope": "all"}).get_json()
    assert Path(pdf["path"]).suffix == ".pdf"
    assert Path(pdf["path"]).read_bytes().startswith(b"%PDF")

    ics = client.post("/api/publish/ics", json={"folder": str(tmp_path)}).get_json()
    assert Path(ics["path"]).suffix == ".ics"
    assert "BEGIN:VCALENDAR" in Path(ics["path"]).read_text(encoding="utf-8")


@pytest.mark.skipif(
    sys.platform.startswith("win") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits: chmod does not restrict directories on Windows, and root ignores them",
)
def test_export_to_a_read_only_folder_explains_itself(client, tmp_path):
    _one_class(client)
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        response = client.post("/api/export/csv", json={"folder": str(locked)})
        assert response.status_code == 400
        assert "read-only" in response.get_json()["message"].lower()
    finally:
        locked.chmod(0o700)


def test_export_rejects_a_dangerous_filename(client, tmp_path):
    _one_class(client)
    response = client.post("/api/export/csv", json={"folder": str(tmp_path), "filename": "../escape.csv"})
    assert response.status_code == 400
    assert not (tmp_path.parent / "escape.csv").exists()


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


# ============================================================================ #
# v2.2 - capacity warnings, Excel import, PDF / iCalendar publishing
# ============================================================================ #
from datetime import date  # noqa: E402

from timetable.importers import build_template, import_workbook  # noqa: E402
from timetable.importers import openpyxl_available as import_openpyxl  # noqa: E402
from timetable.publishing import (  # noqa: E402
    PdfCanvas,
    build_ics,
    build_pdf,
    filter_entries,
    text_width,
)


def _sample_entries():
    return [
        {
            "id": 1, "day": 1, "start_time": "08:30", "end_time": "09:50", "shift": "morning",
            "room_id": 1, "room_label": "A-101", "course_id": 101, "code": "CS3009",
            "course_name": "Artificial Intelligence", "section": "A", "color": "#a9d2e1",
            "instructor": "Mr. Saad Salman", "num_students": 42,
        },
        {
            "id": 2, "day": 3, "start_time": "13:30", "end_time": "14:50", "shift": "evening",
            "room_id": 2, "room_label": "B-201", "course_id": 102, "code": "CS4001",
            "course_name": "Machine Learning", "section": "B", "color": "#2b3465",
            "instructor": "Dr. Aftab Maroof", "num_students": 30,
        },
    ]


_SAMPLE_ROOMS = [
    {"id": 1, "room_number": "101", "label": "A-101", "capacity": 60, "room_type": "Classroom"},
    {"id": 2, "room_number": "201", "label": "B-201", "capacity": 30, "room_type": "Lab"},
]


# ------------------------------ capacity ------------------------------------ #
def test_capacity_warning_is_raised_but_not_blocking(service):
    """A too-small room must warn, never stop the user from saving."""
    from sqlalchemy import insert, select, text as sql_text
    from timetable.db import enrollments, rooms, students

    with service.engine.begin() as conn:
        room_id = conn.execute(select(rooms.c.id)).scalar()
        conn.execute(rooms.update().where(rooms.c.id == room_id).values(capacity=1))
        roll = conn.execute(select(students.c.roll_number)).scalar()
        already = conn.execute(
            select(enrollments.c.roll_number).where(
                enrollments.c.course_id == 101, enrollments.c.section == "A",
                enrollments.c.roll_number == roll,
            )
        ).first()
        if not already:
            conn.execute(insert(enrollments).values(roll_number=roll, course_id=101, section="A"))
        conn.execute(sql_text("SELECT 1"))

    candidate = Assignment(day=1, start_time="09:00", end_time="10:20", room_id=room_id,
                           course_id=101, section="A")
    conflicts = service.check_assignment(candidate)
    capacity = [c for c in conflicts if c.kind == "capacity"]
    assert capacity, "an over-full room must produce a capacity conflict"
    assert capacity[0].severity == "warning"
    assert not any(c.severity == "error" for c in conflicts)

    result = service.save_timetable([candidate])
    assert result["ok"] and result["saved"] == 1        # warnings never block a save


def test_capacity_warning_survives_the_http_layer(client):
    from sqlalchemy import select
    from timetable.db import rooms

    engine = client.application.extensions["engine"]
    with engine.begin() as conn:
        room_id = conn.execute(select(rooms.c.id)).scalar()
        conn.execute(rooms.update().where(rooms.c.id == room_id).values(capacity=1))

    response = client.post("/api/timetable/validate", json={
        "candidate": {"day": 1, "start_time": "09:00", "end_time": "10:20", "room_id": room_id,
                      "course_id": 101, "section": "A"},
        "grid": [],
    })
    payload = response.get_json()
    assert payload["ok"] is True                        # still placeable
    assert any(c["kind"] == "capacity" for c in payload["conflicts"])


# -------------------------------- import ------------------------------------ #
@pytest.mark.skipif(not import_openpyxl(), reason="openpyxl not installed")
def test_import_template_has_every_sheet(client):
    import io as _io
    from openpyxl import load_workbook

    response = client.get("/api/import/template")
    assert response.status_code == 200
    book = load_workbook(_io.BytesIO(response.data))
    assert {"Teachers", "Buildings", "Rooms", "Courses", "Sections"} <= set(book.sheetnames)


@pytest.mark.skipif(not import_openpyxl(), reason="openpyxl not installed")
def test_import_creates_updates_and_reports_bad_rows(app):
    import io as _io
    from openpyxl import load_workbook

    catalog = app.extensions["catalog"]
    book = load_workbook(_io.BytesIO(build_template()))
    for sheet in ("Teachers", "Buildings", "Rooms", "Courses", "Sections"):
        book[sheet].delete_rows(2, book[sheet].max_row)      # drop the examples
    book["Teachers"].append(["Prof. Test Import", "t.import@uni.edu", "Physics", "evening"])
    book["Buildings"].append(["Zeta"])
    book["Rooms"].append(["Z-1", "Zeta", 25, "Lab"])
    book["Rooms"].append(["", "Zeta", 25, "Lab"])            # invalid: no room number
    book["Courses"].append(["PH1001", "Quantum Mechanics", "Physics", 4, "#C7E1C0"])
    book["Sections"].append(["PH1001", "A", "t.import@uni.edu"])
    book["Sections"].append(["PH1001", "B", "Ghost Teacher"])  # invalid: unknown teacher
    buffer = _io.BytesIO()
    book.save(buffer)

    report = import_workbook(catalog, buffer.getvalue())
    assert report["created"] == {"Teachers": 1, "Buildings": 1, "Rooms": 1, "Courses": 1, "Sections": 1}
    assert report["skipped"] == 2
    assert {e["sheet"] for e in report["errors"]} == {"Rooms", "Sections"}
    assert report["ok"] is False

    # the good rows really landed
    names = {t["name"] for t in catalog.list_instructors()}
    assert "Prof. Test Import" in names
    codes = {c["code"] for c in catalog.list_courses_admin()}
    assert "PH1001" in codes

    # re-importing the same file updates instead of duplicating
    again = import_workbook(catalog, buffer.getvalue())
    assert again["total_created"] == 0
    assert again["total_updated"] >= 4
    assert len([t for t in catalog.list_instructors() if t["name"] == "Prof. Test Import"]) == 1


@pytest.mark.skipif(not import_openpyxl(), reason="openpyxl not installed")
def test_import_rejects_a_workbook_without_known_sheets(app):
    import io as _io
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Random"
    buffer = _io.BytesIO()
    book.save(buffer)
    with pytest.raises(ValidationError):
        import_workbook(app.extensions["catalog"], buffer.getvalue())


def test_import_rejects_a_non_excel_file(client):
    response = client.post("/api/import/xlsx", data=b"this is not a spreadsheet",
                           content_type="application/octet-stream")
    assert response.status_code == 400
    assert "Excel" in response.get_json()["message"]


def test_import_without_a_file_is_a_clean_400(client):
    assert client.post("/api/import/xlsx", data=b"").status_code == 400


# ------------------------------- publishing ---------------------------------- #
def test_pdf_writer_produces_a_valid_document():
    pdf = PdfCanvas()
    pdf.text(20, 20, "Hello")
    pdf.new_page()
    pdf.rect(10, 10, 50, 20, fill=(1, 0, 0))
    data = pdf.build("Test")
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/Type /Page ") == 2
    assert b"startxref" in data


def test_text_width_is_font_aware():
    assert text_width("iii", 10) < text_width("WWW", 10)
    assert text_width("Hello", 20) == pytest.approx(2 * text_width("Hello", 10))


@pytest.mark.parametrize("scope,pages", [("all", 5), ("teacher", 2), ("section", 2), ("room", 2)])
def test_pdf_scopes_produce_one_page_per_group(scope, pages):
    data = build_pdf(_sample_entries(), _SAMPLE_ROOMS, scope=scope, days=5)
    assert data.count(b"/Type /Page ") == pages


def test_pdf_handles_an_empty_timetable():
    assert build_pdf([], _SAMPLE_ROOMS, scope="all").startswith(b"%PDF")


def test_pdf_rejects_an_unknown_scope():
    with pytest.raises(ValueError):
        build_pdf(_sample_entries(), _SAMPLE_ROOMS, scope="galaxy")


def test_ics_is_well_formed_and_repeats_weekly():
    text = build_ics(_sample_entries(), start_date=date(2026, 1, 5), weeks=12)
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.rstrip().endswith("END:VCALENDAR")
    assert text.count("BEGIN:VEVENT") == 2 == text.count("END:VEVENT")
    assert "RRULE:FREQ=WEEKLY;COUNT=12" in text
    # Monday class must start on the Monday of that week, Wednesday two days later
    assert "DTSTART:20260105T083000" in text
    assert "DTSTART:20260107T133000" in text
    assert "\r\n" in text and all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_ics_escapes_special_characters():
    entries = _sample_entries()
    entries[0]["course_name"] = "Maths; Stats, Advanced"
    assert r"Maths\; Stats\, Advanced" in build_ics(entries)


def test_filter_entries_narrows_by_teacher_section_and_room():
    entries = _sample_entries()
    assert len(filter_entries(entries, teacher="mr. saad salman")) == 1
    assert len(filter_entries(entries, course_id=102, section="b")) == 1
    assert len(filter_entries(entries, room_id=1)) == 1
    assert len(filter_entries(entries, shift="evening")) == 1
    assert len(filter_entries(entries)) == 2


def test_publish_endpoints_round_trip(client):
    assignments = [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
         "course_id": 101, "section": "A", "shift": "morning"},
        {"day": 3, "start_time": "10:00", "end_time": "11:20", "room_id": 2,
         "course_id": 102, "section": "A", "shift": "morning"},
    ]
    assert client.post("/api/timetable", json={"assignments": assignments}).status_code == 200

    targets = client.get("/api/publish/targets").get_json()
    assert targets["saved_classes"] == 2
    assert targets["teachers"] and targets["sections"] and targets["rooms"]

    pdf = client.post("/api/publish/pdf", json={"scope": "teacher", "days": 5})
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF")
    assert pdf.mimetype == "application/pdf"

    ics = client.get("/calendar.ics?weeks=8")
    assert ics.status_code == 200
    assert ics.mimetype == "text/calendar"
    assert ics.data.count(b"BEGIN:VEVENT") == 2
    assert b"COUNT=8" in ics.data

    only_one = client.get(f"/calendar.ics?teacher={targets['teachers'][0]}")
    assert 1 <= only_one.data.count(b"BEGIN:VEVENT") < 3


def test_publish_uses_the_unsaved_grid_when_given_one(client):
    response = client.post("/api/publish/pdf", json={
        "scope": "all", "days": 1,
        "assignments": [{"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
                         "course_id": 101, "section": "A", "shift": "morning"}],
    })
    assert response.status_code == 200
    assert client.get("/api/timetable").get_json()["entries"] == []      # nothing was saved


def test_publish_rejects_an_empty_selection(client):
    assert client.post("/api/publish/pdf", json={"teacher": "Nobody At All"}).status_code == 400
    assert client.post("/api/publish/pdf", json={"scope": "moon"}).status_code == 400


# ------------------------------ building CRUD -------------------------------- #
def test_building_can_be_created_renamed_and_deleted(client):
    created = client.post("/api/buildings", json={"name": "Zeta Wing"})
    assert created.status_code == 201
    building_id = created.get_json()["id"]

    renamed = client.put(f"/api/buildings/{building_id}", json={"name": "Omega Wing"})
    assert renamed.status_code == 200 and renamed.get_json()["name"] == "Omega Wing"

    assert client.post("/api/buildings", json={"name": "omega wing"}).status_code == 400   # duplicate
    assert client.delete(f"/api/buildings/{building_id}").status_code == 200


def test_building_with_rooms_cannot_be_deleted(client):
    building_id = client.post("/api/buildings", json={"name": "Delta"}).get_json()["id"]
    client.post("/api/rooms", json={"room_number": "D-1", "building_name": "Delta", "capacity": 30})
    response = client.delete(f"/api/buildings/{building_id}")
    assert response.status_code == 400
    assert "room" in response.get_json()["message"].lower()


# --------------------------- front-end integrity ----------------------------- #
def _read(*parts) -> str:
    return (Path(__file__).resolve().parent.parent.joinpath(*parts)).read_text(encoding="utf-8")


def test_every_button_action_exists_in_the_controller():
    """A typo in a data-action would silently produce a dead button."""
    html = _read("timetable", "templates", "index.html")
    js = _read("timetable", "static", "app.js")
    actions = set(re.findall(r'data-action="([A-Za-z]+)"', html))
    declared = set(re.findall(r"^\s{4}([A-Za-z]+): ", js, re.M))
    assert actions, "the template should define some actions"
    assert actions <= declared, f"buttons with no handler: {sorted(actions - declared)}"


def test_every_shortcut_action_exists_in_the_controller():
    js = _read("timetable", "static", "app.js")
    used = set(re.findall(r'action: "([A-Za-z]+)"', js))
    declared = set(re.findall(r"^\s{4}([A-Za-z]+): ", js, re.M))
    assert used <= declared, f"shortcuts with no handler: {sorted(used - declared)}"


def test_every_dialog_referenced_by_the_controller_exists():
    html = _read("timetable", "templates", "index.html")
    js = _read("timetable", "static", "app.js")
    opened = set(re.findall(r'openDialog\("#([A-Za-z]+)"\)', js))
    present = set(re.findall(r'<div id="([A-Za-z]+)" class="dialog', html))
    assert opened <= present, f"missing dialogs: {sorted(opened - present)}"


def test_the_ui_no_longer_uses_blocking_browser_prompts():
    """Desktop webviews may ignore window.confirm/prompt - we ship our own."""
    js = "\n".join(
        line for line in _read("timetable", "static", "app.js").splitlines()
        if not line.lstrip().startswith(("//", "/*", "*"))
    )
    assert "window.confirm(" not in js
    assert js.count("window.prompt(") <= 1        # only the clipboard fallback


# ======================= v2.3: labs, semesters, gaps ========================= #
def test_catalogue_lists_a_separate_card_for_every_lab(client):
    catalogue = client.get("/api/courses").get_json()
    labs = [c for c in catalogue if c["kind"] == "lab"]
    assert labs, "the sample data should contain lab courses"
    for lab in labs:
        assert lab["has_lab"] is True
        assert lab["hours"] == lab["lab_credit_hours"] >= 1
        assert lab["key"].endswith(":lab")
        assert lab["label"].endswith("(Lab)")
        # the matching lecture exists too
        assert any(
            c["id"] == lab["id"] and c["section"] == lab["section"] and c["kind"] == "theory"
            for c in catalogue
        )


def test_a_lab_cannot_be_scheduled_for_a_course_without_one(client):
    theory = next(c for c in client.get("/api/courses").get_json() if not c["has_lab"])
    verdict = client.post("/api/timetable/validate", json={
        "candidate": {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
                      "course_id": theory["id"], "section": theory["section"], "kind": "lab"},
        "grid": [],
    }).get_json()
    assert verdict["ok"] is False
    assert "no lab component" in verdict["conflicts"][0]["message"]


def test_a_lab_outside_a_lab_room_is_only_a_warning(client):
    lab = next(c for c in client.get("/api/courses").get_json() if c["kind"] == "lab")
    classroom = next(r for r in client.get("/api/rooms").get_json() if r["room_type"] != "Lab")
    verdict = client.post("/api/timetable/validate", json={
        "candidate": {"day": 2, "start_time": "08:30", "end_time": "09:50", "room_id": classroom["id"],
                      "course_id": lab["id"], "section": lab["section"], "kind": "lab"},
        "grid": [],
    }).get_json()
    assert verdict["ok"] is True                       # a warning never blocks
    assert [c["kind"] for c in verdict["conflicts"]] == ["roomtype"]
    assert verdict["conflicts"][0]["severity"] == "warning"


def test_lecture_and_lab_of_one_section_cannot_overlap(client):
    lab = next(c for c in client.get("/api/courses").get_json() if c["kind"] == "lab")
    slot = {"day": 3, "start_time": "10:00", "end_time": "11:20",
            "course_id": lab["id"], "section": lab["section"]}
    verdict = client.post("/api/timetable/validate", json={
        "candidate": dict(slot, room_id=2, kind="lab"),
        "grid": [dict(slot, room_id=1, kind="theory")],
    }).get_json()
    assert verdict["ok"] is False
    duplicate = next(c for c in verdict["conflicts"] if c["kind"] == "duplicate")
    assert "same students attend both" in duplicate["message"]


def test_two_courses_of_the_same_semester_and_section_clash(client):
    catalogue = client.get("/api/courses").get_json()
    first = next(c for c in catalogue if c["semester"] and c["kind"] == "theory")
    second = next(
        c for c in catalogue
        if c["kind"] == "theory" and c["semester"] == first["semester"]
        and c["section"] == first["section"] and c["id"] != first["id"]
    )
    verdict = client.post("/api/timetable/validate", json={
        "candidate": {"day": 4, "start_time": "08:30", "end_time": "09:50", "room_id": 2,
                      "course_id": second["id"], "section": second["section"]},
        "grid": [{"day": 4, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
                  "course_id": first["id"], "section": first["section"]}],
    }).get_json()
    assert verdict["ok"] is False
    kinds = [c["kind"] for c in verdict["conflicts"]]
    assert "semester" in kinds
    message = next(c for c in verdict["conflicts"] if c["kind"] == "semester")["message"]
    assert f"Semester {first['semester']} section {first['section']}" in message


def test_unscheduled_report_lists_missing_lectures_and_labs(client):
    everything = client.post("/api/timetable/unscheduled", json={"assignments": []}).get_json()
    assert everything["ok"] is False
    assert everything["required"] == 65 == len(everything["missing"])
    assert sum(everything["by_semester"].values()) == 65
    assert {item["kind"] for item in everything["missing"]} == {"theory", "lab"}

    created = client.post("/api/timetable/autofill", json={
        "assignments": [], "days": 5,
        "slots": [{"start": f"{8 + i * 2:02d}:30", "end": f"{9 + i * 2:02d}:50"} for i in range(4)],
        "room_ids": [r["id"] for r in client.get("/api/rooms").get_json()][:14],
    }).get_json()["created"]
    filled = client.post("/api/timetable/unscheduled", json={"assignments": created}).get_json()
    assert filled == {"ok": True, "required": 65, "missing": [], "by_semester": {}}

    # ... and the saved timetable is used when no grid is supplied
    client.post("/api/timetable", json={"assignments": created[:-2]})
    saved = client.post("/api/timetable/unscheduled", json={}).get_json()
    assert len(saved["missing"]) == 2


def test_autofill_can_be_limited_to_one_semester(client):
    created = client.post("/api/timetable/autofill", json={
        "assignments": [], "days": 5, "semester": 3,
        "slots": [{"start": "08:30", "end": "09:50"}, {"start": "10:00", "end": "11:20"}],
        "room_ids": [1, 2, 3, 4, 5, 6],
    }).get_json()["created"]
    assert created
    semesters = {
        c["semester"] for c in client.get("/api/courses").get_json()
        if any(c["id"] == entry["course_id"] for entry in created)
    }
    assert semesters == {3}


def test_publish_pdf_accepts_a_semester_scope(client):
    client.post("/api/timetable", json={"assignments": [
        {"day": 1, "start_time": "08:30", "end_time": "09:50", "room_id": 1,
         "course_id": 101, "section": "A"},
    ]})
    targets = client.get("/api/publish/targets").get_json()
    assert targets["semesters"]
    assert targets["unscheduled"] == 64

    response = client.post("/api/publish/pdf", json={"scope": "semester", "days": 5})
    assert response.status_code == 200
    assert response.data.startswith(b"%PDF-1.4")

    bad = client.post("/api/publish/pdf", json={"scope": "nonsense"})
    assert bad.status_code == 400


def test_course_editor_round_trips_the_lab_and_semester_fields(client):
    created = client.post("/api/courses", json={
        "code": "SE4001", "name": "Compiler Construction", "credit_hours": 3,
        "semester": 6, "has_lab": "yes", "lab_credit_hours": 2,
        "sections": [{"section": "A"}],
    }).get_json()
    assert created["semester"] == 6 and created["has_lab"] == 1 and created["lab_credit_hours"] == 2

    catalogue = client.get("/api/courses").get_json()
    mine = [c for c in catalogue if c["id"] == created["id"]]
    assert sorted(c["kind"] for c in mine) == ["lab", "theory"]

    # turning the lab off clears its credit hours and removes the lab card
    updated = client.put(f"/api/courses/{created['id']}", json={
        "code": "SE4001", "name": "Compiler Construction", "semester": 6, "has_lab": "",
        "sections": [{"section": "A"}],
    }).get_json()
    assert updated["has_lab"] == 0 and updated["lab_credit_hours"] == 0
    assert [c["kind"] for c in client.get("/api/courses").get_json() if c["id"] == created["id"]] == ["theory"]


def test_import_template_carries_the_lab_and_semester_columns(client):
    response = client.get("/api/import/template")
    if response.status_code == 501:
        pytest.skip("openpyxl is not installed")
    import io as _io

    import openpyxl

    workbook = openpyxl.load_workbook(_io.BytesIO(response.data))
    headers = [cell.value for cell in workbook["Courses"][1]]
    assert "Semester (1-12, blank = none)" in headers
    assert "Has lab? (yes/no)" in headers
    assert "Lab credit hours" in headers


def test_the_shortcut_hints_are_no_longer_printed_on_the_controls():
    """Alt+1 and friends belong in the F1 reference, not on every button."""
    html = _read("timetable", "templates", "index.html")
    controls = re.findall(r"<button[^>]*>.*?</button>", html, re.S)
    assert controls
    assert not [button for button in controls if "<kbd>" in button]
    # but the reference itself still lists them
    assert html.count("<kbd>") > 10
    assert 'title="Morning shift (Alt+1)"' in html


# ======================= v2.4: Class Schedule printed list ===================== #


@pytest.mark.parametrize("start,end,expected", [
    ("14:30", "16:00", "2:30 PM - 4:00 PM"),
    ("08:30", "09:50", "8:30 AM - 9:50 AM"),
    ("00:00", "12:00", "12:00 AM - 12:00 PM"),
    ("23:00", "23:30", "11:00 PM - 11:30 PM"),
])
def test_format_time_range_uses_am_pm(start, end, expected):
    assert format_time_range(start, end) == expected


def _schedule_entries():
    """A tiny timetable including a zero-credit (Non-credited) course."""
    return [
        {
            "id": 1, "day": 1, "start_time": "14:30", "end_time": "16:00", "shift": "morning",
            "room_id": 1, "room_number": "105", "room_label": "A-105", "course_id": 101,
            "code": "CHEM4134", "course_name": "Special Paper - I", "section": "A",
            "color": "#a9d2e1", "instructor": "Miss Fozia", "num_students": 42,
            "semester": 4, "kind": "theory", "credit_hours": 3,
        },
        {
            "id": 2, "day": 1, "start_time": "16:00", "end_time": "17:30", "shift": "morning",
            "room_id": 1, "room_number": "105", "room_label": "A-105", "course_id": 102,
            "code": "CHEM4130", "course_name": "Food and Drug Analysis", "section": "A",
            "color": "#a9d2e1", "instructor": "Mr Umar Faraz", "num_students": 40,
            "semester": 4, "kind": "theory", "credit_hours": 3,
        },
        {
            "id": 3, "day": 4, "start_time": "17:30", "end_time": "18:30", "shift": "morning",
            "room_id": 9, "room_number": "mosque", "room_label": "mosque", "course_id": 120,
            "code": "", "course_name": "Tajuma Quran course", "section": "A",
            "color": "#a9d2e1", "instructor": "Dr. Bilal", "num_students": 0,
            "semester": 4, "kind": "theory", "credit_hours": 0,
        },
    ]


_SCHEDULE_ROOMS = [
    {"id": 1, "room_number": "105", "label": "A-105", "capacity": 60, "room_type": "Classroom"},
    {"id": 9, "room_number": "mosque", "label": "mosque", "capacity": 0, "room_type": "Classroom"},
]


@pytest.mark.skipif(not openpyxl_available(), reason="openpyxl not installed")
def test_class_schedule_layout_matches_the_reference():
    import io as _io

    from openpyxl import load_workbook

    data = build_workbook(
        _schedule_entries(), _SCHEDULE_ROOMS, days=5, layout="schedule",
        title="Class Schedule", term="Spring 2024",
        institution="University of Education Jauharabad Campus",
        program="BS Chemistry (Post ADP)", semester="4", commencement="January 2024",
    )
    book = load_workbook(_io.BytesIO(data))
    assert book.sheetnames == ["Class Schedule"]
    sheet = book["Class Schedule"]

    # metadata title block
    assert sheet.cell(row=1, column=1).value == "Class Schedule Spring 2024"
    assert sheet.cell(row=2, column=1).value == "University of Education Jauharabad Campus"
    assert "Name of program: BS Chemistry (Post ADP)" in str(sheet.cell(row=3, column=1).value)
    assert "Semester: 4" in str(sheet.cell(row=3, column=5).value)
    assert sheet.cell(row=4, column=1).value == "Commencement of Classes: January 2024"

    # header row (find it after the metadata block)
    header = None
    for r in range(1, 8):
        if sheet.cell(row=r, column=1).value == "Days":
            header = r
            break
    assert header is not None, "header row not found"
    expected = ["Days", "Course Code", "Course Title", "C.Hrs", "Total No.of Students",
                "Teacher's Name", "Time", "Room No"]
    assert [sheet.cell(row=header, column=c).value for c in range(1, 9)] == expected

    # Monday block
    mon = header + 1
    assert sheet.cell(row=mon, column=1).value == "Monday"
    assert sheet.cell(row=mon, column=2).value == "CHEM4134"
    assert sheet.cell(row=mon, column=4).value == "3"           # credit hours
    assert sheet.cell(row=mon, column=7).value == "2:30 PM - 4:00 PM"   # AM/PM 12h range
    assert sheet.cell(row=mon, column=8).value == "105"

    # Non-credited course (credit hours == 0)
    thu = next(r for r in range(header + 1, sheet.max_row + 1)
               if sheet.cell(row=r, column=3).value == "Tajuma Quran course")
    assert sheet.cell(row=thu, column=1).value == "Thursday"
    assert sheet.cell(row=thu, column=4).value == "non-credited course"


@pytest.mark.skipif(not openpyxl_available(), reason="openpyxl not installed")
def test_grid_layout_is_still_the_default_when_layout_is_omitted():
    import io as _io

    from openpyxl import load_workbook

    data = build_workbook(_schedule_entries(), _SCHEDULE_ROOMS, days=1)
    book = load_workbook(_io.BytesIO(data))
    assert "Class Schedule" not in book.sheetnames
    assert "Summary" in book.sheetnames and "Monday" in book.sheetnames


def test_credit_hours_are_carried_into_export_entries(service):
    """describe_assignments must expose credit_hours so exports can spot non-credited courses."""
    from timetable.services import Assignment

    entry = service.describe_assignments([
        Assignment(day=1, start_time="08:30", end_time="09:50", room_id=1,
                   course_id=101, section="A")
    ])[0]
    assert "credit_hours" in entry
    assert entry["credit_hours"] >= 1


def test_schedule_pdf_renders_a_single_landscape_page():
    """layout='schedule' on build_pdf must produce a valid single-page document."""
    from timetable.publishing import build_pdf

    data = build_pdf(
        _schedule_entries(), _SCHEDULE_ROOMS, days=5, layout="schedule",
        title="Class Schedule", term="Spring 2024",
        institution="University of Education Jauharabad Campus",
        program="BS Chemistry (Post ADP)", semester="4", commencement="January 2024",
    )
    assert data.startswith(b"%PDF-1.4")
    assert data.count(b"/Type /Page ") == 1


# =================== v2.5: standalone desktop (no server) ==================== #
def test_standalone_html_is_self_contained(app):
    """The native window must not depend on a Flask static server at all."""
    from timetable.desktop import _build_standalone_html

    html = _build_standalone_html(app)
    # assets are inlined, not referenced from /static
    assert "rel=\"stylesheet\" href=\"/static" not in html
    assert "<script defer src=\"/static" not in html
    assert html.count("<style>") >= 1
    assert "front-end controller" in html            # app.js is embedded
    # the in-process fetch shim is injected before the controller
    assert "window.__NATIVE__" in html
    assert "window.pywebview.api" in html
    # renders the title/version without error
    assert "Automated Timetable Generator" in html


def test_native_bridge_routes_requests_in_process(app):
    """The desktop bridge must answer the same endpoints as the HTTP server."""
    from timetable.desktop import _NativeBridge

    bridge = _NativeBridge(app)

    health = bridge.request({"method": "GET", "path": "/api/health", "query": ""})
    assert health["status"] == 200
    assert '"status":"ok"' in health["text"]

    validate = bridge.request({
        "method": "POST", "path": "/api/timetable/validate", "query": "", "raw": False,
        "body": '{"candidate":{"day":1,"start_time":"08:30","end_time":"09:50",'
                '"room_id":1,"course_id":101,"section":"A"},"grid":[]}',
    })
    assert validate["status"] == 200
    assert '"ok":true' in validate["text"]

    wrong = bridge.request({"method": "GET", "path": "/api/does-not-exist", "query": ""})
    assert wrong["status"] == 404


def test_native_bridge_streams_binary_exports(app):
    """Raw (binary) exports come back as base64 so the window can save them."""
    import base64

    from timetable.desktop import _NativeBridge

    bridge = _NativeBridge(app)
    body = '{"assignments":[{"day":1,"start_time":"08:30","end_time":"09:50",' \
           '"room_id":1,"course_id":101,"section":"A","shift":"morning"}],' \
           '"days":2,"shift":"all"}'
    result = bridge.request({
        "method": "POST", "path": "/api/export/csv", "query": "", "raw": True, "body": body,
    })
    assert result["status"] == 200
    raw = base64.b64decode(result["base64"])
    assert raw.startswith("\ufeff".encode("utf-8"))     # Excel-friendly BOM
    assert b"Monday" in raw


# ======================= v2.6: reports, day scope, autosave ==================== #
from timetable.reports import conflict_report, room_utilisation, teacher_workload  # noqa: E402
from timetable.exporters import build_workbook  # noqa: E402


def _report_entries():
    """Three classes with one room conflict and a 0-credit course."""
    return [
        {
            "id": 1, "day": 1, "start_time": "08:30", "end_time": "09:50", "shift": "morning",
            "room_id": 1, "room_number": "101", "room_label": "A-101", "course_id": 101,
            "code": "CS3009", "course_name": "Artificial Intelligence", "section": "A",
            "kind": "theory", "semester": 1, "instructor": "Dr A", "num_students": 40,
            "credit_hours": 3, "capacity": 60,
        },
        {
            "id": 2, "day": 1, "start_time": "08:30", "end_time": "09:50", "shift": "morning",
            "room_id": 1, "room_number": "101", "room_label": "A-101", "course_id": 102,
            "code": "CS4001", "course_name": "Machine Learning", "section": "B",
            "kind": "theory", "semester": 2, "instructor": "Dr B", "num_students": 30,
            "credit_hours": 3, "capacity": 60,
        },
        {
            "id": 3, "day": 2, "start_time": "17:30", "end_time": "18:30", "shift": "morning",
            "room_id": 9, "room_number": "mosque", "room_label": "mosque", "course_id": 120,
            "code": "", "course_name": "Tajuma Quran course", "section": "A",
            "kind": "theory", "semester": 4, "instructor": "Dr Bilal", "num_students": 0,
            "credit_hours": 0, "capacity": 0,
        },
    ]


_REPORT_ROOMS = [
    {"id": 1, "room_number": "101", "label": "A-101", "capacity": 60, "room_type": "Classroom"},
    {"id": 9, "room_number": "mosque", "label": "mosque", "capacity": 0, "room_type": "Classroom"},
]


def test_room_utilisation_report_flags_under_used_rooms():
    slots = [{"start": "08:30", "end": "09:50"}, {"start": "10:00", "end": "11:20"}]
    report = room_utilisation(_report_entries(), _REPORT_ROOMS, days=5, slots=slots)
    assert report["headers"][0] == "Room"
    assert "Utilisation" in report["headers"]

    a101 = next(r for r in report["rows"] if r[0] == "A-101")
    assert a101[3] == 2                       # two classes per week
    assert a101[6].endswith("%")
    # the 0-credit course is in the "mosque" room of capacity 0 -> under-used
    mosque = next(r for r in report["rows"] if r[0] == "mosque")
    assert mosque[6].endswith("%")


def test_teacher_workload_report_orders_by_hours():
    report = teacher_workload(_report_entries())
    assert "Contact hours / week" in report["headers"]
    hours = [row[2] for row in report["rows"]]
    assert hours == sorted(hours, reverse=True)
    dr_a = next(r for r in report["rows"] if r[0] == "Dr A")
    assert dr_a[1] == 1                       # one theory class


def test_conflict_report_sorts_errors_before_warnings():
    report = conflict_report(_report_entries())
    assert report["rows"]
    severities = [row[0] for row in report["rows"]]
    # All "Error" rows come before any "Warning" row.
    try:
        first_warning = severities.index("Warning")
    except ValueError:
        first_warning = len(severities)
    assert all(severity == "Error" for severity in severities[:first_warning])
    assert any("Same room booked twice" in row[7] for row in report["rows"])


@pytest.mark.parametrize("scope,pages", [
    ("day", 2),          # two days with classes -> two pages
])
def test_publish_day_scope_is_one_page_per_day(scope, pages):
    from timetable.publishing import build_pdf
    data = build_pdf(_report_entries(), _REPORT_ROOMS, days=5, scope=scope, layout="grid")
    assert data.startswith(b"%PDF-1.4")
    assert data.count(b"/Type /Page ") == pages


@pytest.mark.parametrize("scope", ["utilisation", "workload", "conflict"])
def test_publish_report_scopes_produce_valid_pdfs(scope):
    from timetable.publishing import build_pdf
    data = build_pdf(_report_entries(), _REPORT_ROOMS, days=5, scope=scope, layout="grid")
    assert data.startswith(b"%PDF-1.4")
    assert data.count(b"/Type /Page ") == 1


def test_workbook_contains_the_report_sheets():
    import io as _io
    from openpyxl import load_workbook

    data = build_workbook(_report_entries(), _REPORT_ROOMS, days=5, layout="grid")
    book = load_workbook(_io.BytesIO(data))
    assert "Room Utilisation" in book.sheetnames
    assert "Teacher Workload" in book.sheetnames
    assert "Conflict Report" in book.sheetnames
    sheet = book["Conflict Report"]
    assert sheet.cell(row=3, column=1).value == "Severity"


def test_project_autosave_writes_a_backup_next_to_the_project(app, tmp_path):
    from timetable.projects import autosave_project

    client = app.test_client()
    project = client.post("/api/project/save", json={
        "name": "Autosave Test", "path": str(tmp_path / "proj")
    }).get_json()
    assert project["ok"] is True

    engine = app.extensions["engine"]
    backup = autosave_project(engine, project["path"], "Autosave Test")
    assert backup["ok"] is True
    backup_path = backup["path"]
    assert backup_path.endswith(".ttproj")
    parent = Path(backup_path).parent
    assert parent.name == "_backups"
    assert Path(backup_path).is_file()
    assert len(list(parent.glob("proj-*.ttproj"))) >= 1


def test_project_autosave_via_api(app, tmp_path):
    client = app.test_client()
    project = client.post("/api/project/save", json={
        "name": "API Autosave", "path": str(tmp_path / "api-proj")
    }).get_json()
    assert project["ok"] is True

    result = client.post("/api/project/autosave", json={"path": project["path"]}).get_json()
    assert result["ok"] is True
    assert Path(result["path"]).is_file()
