"""End-to-end tests for the API and the clash-detection engine.

Run with:  python -m pytest -q
"""

from __future__ import annotations

import os
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
