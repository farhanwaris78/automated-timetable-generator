"""Tests for the portable project system (.ttproj files) and the in-app
file browser.

Covered here:
  * save / open round-trip, including the timetable and grid settings;
  * validation of corrupt / foreign / version-incompatible project files;
  * NEW project (factory reset);
  * recent-projects list (bounded, deduplicated, removable);
  * automatic safety backups before destructive actions;
  * the sandboxed file-browser API (list, mkdir, home confinement);
  * the desktop launcher's native-window / browser CLI flags.

Run with:  python -m pytest -q
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from timetable import __version__  # noqa: E402
from timetable.config import Settings  # noqa: E402
from timetable.desktop import build_parser  # noqa: E402
from timetable.projects import (  # noqa: E402
    PROJECT_FORMAT,
    PROJECT_SUFFIX,
    ProjectError,
    ensure_project_suffix,
    list_recent_projects,
    new_project,
    open_project,
    push_recent_project,
    read_project,
    remove_recent_project,
    write_project,
)
from timetable.web import create_app  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    os.environ["TTG_DATA_DIR"] = str(tmp_path)
    return Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}", log_dir=tmp_path)


@pytest.fixture()
def app(settings: Settings, monkeypatch):
    # The API confines file operations to the home directory; point it at the
    # test folder so the tests can use real project files.
    import timetable.web as web

    monkeypatch.setattr(web, "home_dir", lambda: settings.log_dir)
    application = create_app(settings)
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def add_course(client, code: str, name: str) -> int:
    response = client.post(
        "/api/courses",
        json={
            "code": code,
            "name": name,
            "department": "Test Dept",
            "credit_hours": 3,
            "semester": 2,
            "color": "#cfe8f5",
            "sections": [{"section": "A"}],
            "teacher": None,
        },
    )
    assert response.status_code == 201
    return response.get_json()["id"]


def save_timetable(client, course_id: int) -> None:
    response = client.post(
        "/api/timetable",
        json={
            "assignments": [
                {
                    "day": 1,
                    "start_time": "09:00",
                    "end_time": "10:20",
                    "room_id": 1,
                    "course_id": course_id,
                    "section": "A",
                    "shift": "morning",
                    "kind": "theory",
                }
            ]
        },
    )
    assert response.status_code == 200, response.get_json()


# --------------------------------------------------------------------------- #
# file format
# --------------------------------------------------------------------------- #
def test_project_file_is_a_versioned_zip(settings: Settings):
    engine = __import__("timetable.db", fromlist=["init_database"]).init_database(settings.database_url)
    target = settings.log_dir / "college.ttproj"
    result = write_project(engine, target, "College 2026")
    assert result["ok"] and result["path"] == str(target.resolve())
    assert result["name"] == "College 2026"

    with zipfile.ZipFile(target) as zf:
        names = set(zf.namelist())
        assert "project.json" in names and "data.json" in names
        meta = json.loads(zf.read("project.json"))
        assert meta["format"] == PROJECT_FORMAT
        assert meta["app_version"] == __version__
        data = json.loads(zf.read("data.json"))
        assert data["courses"] and data["rooms"] and data["instructors"]
        # IDs must be preserved so foreign keys survive the round-trip.
        assert all("id" in row for row in data["courses"])


def test_ensure_project_suffix_appends_and_validates():
    assert ensure_project_suffix("holiday").name == f"holiday{PROJECT_SUFFIX}"
    assert ensure_project_suffix("holiday.ttproj").suffix == PROJECT_SUFFIX
    with pytest.raises(ProjectError):
        ensure_project_suffix("holiday.zip")


def test_read_project_rejects_missing_and_corrupt_files(tmp_path: Path):
    with pytest.raises(ProjectError):
        read_project(tmp_path / "nope.ttproj")
    bogus = tmp_path / "bogus.ttproj"
    bogus.write_text("this is not a zip", encoding="utf-8")
    with pytest.raises(ProjectError):
        read_project(bogus)
    wrong = tmp_path / "wrong.zip"
    wrong.write_text("x", encoding="utf-8")
    with pytest.raises(ProjectError):
        read_project(wrong)


def test_read_project_rejects_newer_formats(tmp_path: Path):
    filepath = tmp_path / "future.ttproj"
    with zipfile.ZipFile(filepath, "w") as zf:
        zf.writestr("project.json", json.dumps({"format": PROJECT_FORMAT + 1, "name": "Future"}))
        zf.writestr("data.json", json.dumps({}))
    with pytest.raises(ProjectError, match="newer version"):
        read_project(filepath)


# --------------------------------------------------------------------------- #
# round-trip through the API
# --------------------------------------------------------------------------- #
def test_save_then_open_roundtrip_through_api(client, settings: Settings):
    course_id = add_course(client, "TT-101", "Timetable Theory")
    save_timetable(client, course_id)

    info = client.get("/api/project").get_json()
    assert info["suffix"] == PROJECT_SUFFIX
    assert info["recent"] == []

    target = settings.log_dir / "sem-2.ttproj"
    saved = client.post("/api/project/save", json={"name": "Semester 2", "path": str(target)})
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()["path"] == str(target.resolve())
    assert target.is_file()

    recents = client.get("/api/project").get_json()["recent"]
    assert len(recents) == 1 and recents[0]["name"] == "Semester 2"

    # Now start fresh (a blank project) and verify the file restores everything.
    created = client.post("/api/project/new", json={"name": "Fresh"})
    assert created.status_code == 200
    assert created.get_json()["blank"] is True
    assert client.get("/api/courses").get_json() == []        # nothing left at all
    assert client.get("/api/rooms").get_json() == []

    opened = client.post("/api/project/open", json={"path": str(target)})
    assert opened.status_code == 200, opened.get_json()
    payload = opened.get_json()
    assert payload["name"] == "Semester 2"
    assert payload["stats"]["courses"] >= 19          # 18 sample + TT-101
    courses = client.get("/api/courses").get_json()
    assert any(c["code"] == "TT-101" for c in courses)
    entries = client.get("/api/timetable").get_json()["entries"]
    assert any(e["course_id"] == course_id for e in entries)


def test_open_project_suffix_and_validation_errors(client, settings: Settings):
    assert client.post("/api/project/open", json={"path": str(settings.log_dir / "missing.ttproj")}).status_code == 400
    assert client.post("/api/project/open", json={"path": "/etc/passwd"}).status_code == 400
    assert client.post("/api/project/save", json={"name": "X", "path": str(settings.log_dir / "no-suffix")}).status_code == 200
    assert (settings.log_dir / f"no-suffix{PROJECT_SUFFIX}").is_file()


def test_new_project_keeps_a_backup_and_resets(client, settings: Settings):
    add_course(client, "TT-999", "To Be Wiped")
    created = client.post("/api/project/new", json={"name": "Wipe"})
    assert created.status_code == 200
    assert not any(c["code"] == "TT-999" for c in client.get("/api/courses").get_json())
    backups = list((settings.log_dir / "backups").glob("timetable-*.db"))
    assert len(backups) == 1


def test_new_project_is_completely_blank(client, settings: Settings):
    """New project = an empty workspace, not somebody else's demo university."""
    add_course(client, "TT-500", "Will Vanish")
    save_timetable(client, add_course(client, "TT-501", "Also Vanishes"))

    created = client.post("/api/project/new", json={"name": "Empty"})
    assert created.status_code == 200
    payload = created.get_json()
    assert payload["blank"] is True
    assert "Blank project" in payload["message"]

    # Every single table must be empty - courses, staff, estate and schedule.
    stats = payload["stats"]
    for key in (
        "courses", "sections", "instructors", "rooms",
        "students", "enrollments", "scheduled_classes",
    ):
        assert stats[key] == 0, f"{key} should be empty in a new project, got {stats[key]}"

    assert client.get("/api/courses").get_json() == []
    assert client.get("/api/rooms").get_json() == []
    assert client.get("/api/instructors").get_json() == []
    assert client.get("/api/buildings").get_json() == []
    assert client.get("/api/students").get_json() == []
    assert client.get("/api/timetable").get_json()["entries"] == []
    # Stale grid preferences from the previous project must not leak through.
    assert client.get("/api/settings").get_json() == {}


def test_new_project_can_still_load_the_sample_data(client):
    """Opt-in demo data for people who want to explore the app first."""
    created = client.post("/api/project/new", json={"name": "Demo", "sample": True})
    assert created.status_code == 200
    assert created.get_json()["blank"] is False
    assert created.get_json()["stats"]["courses"] > 0
    assert client.get("/api/rooms").get_json()


def test_blank_project_still_accepts_new_data(client):
    """The empty database is fully usable straight away."""
    client.post("/api/project/new", json={"name": "Fresh start"})

    building = client.post("/api/buildings", json={"name": "Main Block"})
    assert building.status_code == 201
    room = client.post(
        "/api/rooms",
        json={"building_id": building.get_json()["id"], "room_number": "101",
              "capacity": 40, "room_type": "Classroom"},
    )
    assert room.status_code == 201
    course_id = add_course(client, "NEW-1", "First Course")

    saved = client.post(
        "/api/timetable",
        json={"assignments": [{
            "day": 1, "start_time": "09:00", "end_time": "10:20",
            "room_id": room.get_json()["id"], "course_id": course_id,
            "section": "A", "shift": "morning", "kind": "theory",
        }]},
    )
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()["saved"] == 1


def test_database_reset_supports_blank_and_sample(client):
    assert client.post("/api/database/reset", json={"blank": True}).get_json()["blank"] is True
    assert client.get("/api/courses").get_json() == []
    assert client.post("/api/database/reset", json={}).get_json()["blank"] is False
    assert client.get("/api/courses").get_json()


def test_blank_project_saves_and_reopens(client, tmp_path: Path):
    """An empty project round-trips through a .ttproj file without errors."""
    client.post("/api/project/new", json={"name": "Nothing yet"})
    target = tmp_path / "blank.ttproj"
    assert client.post("/api/project/save", json={"name": "Nothing yet", "path": str(target)}).status_code == 200

    client.post("/api/project/new", json={"name": "Other", "sample": True})
    assert client.get("/api/courses").get_json()

    opened = client.post("/api/project/open", json={"path": str(target)})
    assert opened.status_code == 200
    assert client.get("/api/courses").get_json() == []
    assert client.get("/api/rooms").get_json() == []


def test_recent_projects_are_deduplicated_and_removable(client, settings: Settings):
    target = settings.log_dir / "a.ttproj"
    client.post("/api/project/save", json={"name": "A", "path": str(target)})
    client.post("/api/project/save", json={"name": "A again", "path": str(target)})
    recents = client.get("/api/project").get_json()["recent"]
    assert len(recents) == 1 and recents[0]["name"] == "A again"

    removed = client.delete("/api/project/recent", json={"path": str(target)})
    assert removed.status_code == 200
    assert client.get("/api/project").get_json()["recent"] == []


def test_recent_list_is_bounded(settings: Settings):
    for index in range(15):
        push_recent_project(settings.log_dir, f"P{index}", settings.log_dir / f"p-{index}{PROJECT_SUFFIX}")
    recents = list_recent_projects(settings.log_dir)
    assert len(recents) == 10 and recents[0]["name"] == "P14"


# --------------------------------------------------------------------------- #
# low-level engine operations
# --------------------------------------------------------------------------- #
def test_projects_module_roundtrip_preserves_settings_and_timetable(settings: Settings):
    from timetable.services import TimetableService

    engine = __import__("timetable.db", fromlist=["init_database"]).init_database(settings.database_url)
    svc = TimetableService(engine)
    svc.set_setting("grid", '{"days": 6}')
    svc.save_timetable(
        [
            __import__("timetable.services", fromlist=["Assignment"]).Assignment(
                day=2, start_time="10:00", end_time="11:20", room_id=2, course_id=101, section="A"
            )
        ]
    )
    target = settings.log_dir / "full.ttproj"
    write_project(engine, target, "Full")

    fresh = settings.log_dir / "fresh.db"
    fresh_engine = __import__("timetable.db", fromlist=["init_database"]).init_database(f"sqlite:///{fresh.as_posix()}")
    open_project(fresh_engine, target, settings.log_dir, f"sqlite:///{fresh.as_posix()}")
    fresh_svc = TimetableService(fresh_engine)

    assert fresh_svc.get_setting("grid") == '{"days": 6}'
    entries = fresh_svc.load_timetable()
    assert len(entries) == 1 and entries[0]["room_id"] == 2


def test_new_project_marks_working_database_fresh(settings: Settings):
    engine = __import__("timetable.db", fromlist=["init_database"]).init_database(settings.database_url)
    result = new_project(engine, settings.log_dir, settings.database_url, "Empty start")
    assert result["name"] == "Empty start" and result["path"] is None
    assert list_recent_projects(settings.log_dir) == []
    # A backup of the old working DB survives in the backups folder.
    assert list((settings.log_dir / "backups").glob("*.db"))


def test_remove_recent_ignores_unknown_paths(settings: Settings):
    assert remove_recent_project(settings.log_dir, "/nonexistent/x.ttproj") == []


# --------------------------------------------------------------------------- #
# sandboxed file browser
# --------------------------------------------------------------------------- #
def test_fs_list_and_mkdir(client, settings: Settings):
    (settings.log_dir / "Projects").mkdir()
    (settings.log_dir / "Projects" / "demo.ttproj").write_text("x", encoding="utf-8")

    data = client.get("/api/fs/list?path=" + str(settings.log_dir)).get_json()
    assert data["path"] == str(settings.log_dir)
    assert any(item["name"] == "Projects" for item in data["dirs"])
    assert [f["name"] for f in data["files"]] == []
    assert data["writable"] is True
    assert data["sandboxed"] is False

    deep = client.get("/api/fs/list?path=" + str(settings.log_dir / "Projects")).get_json()
    assert deep["can_up"] is True
    assert deep["files"][0]["name"] == "demo.ttproj"
    assert deep["parent"] == str(settings.log_dir)

    made = client.post("/api/fs/mkdir", json={"path": str(settings.log_dir / "Projects"), "name": "New Folder"})
    assert made.status_code == 200
    assert (settings.log_dir / "Projects" / "New Folder").is_dir()

    assert client.post("/api/fs/mkdir", json={"path": str(settings.log_dir), "name": "a/b"}).status_code == 400
    assert client.post("/api/fs/mkdir", json={"path": str(settings.log_dir), "name": ".."}).status_code == 400
    assert client.post("/api/fs/mkdir", json={"path": str(settings.log_dir), "name": "CON"}).status_code == 400


def test_browser_can_leave_the_home_folder(client, settings: Settings):
    r"""The whole point of 2.0.2: users are no longer locked under C:\Users\name."""
    listing = client.get("/api/fs/list?path=" + str(settings.log_dir))
    assert listing.status_code == 200

    # Walking up past the home folder is allowed, all the way to the root.
    current = listing.get_json()
    hops = 0
    while current["can_up"] and hops < 40:
        hops += 1
        current = client.get("/api/fs/list?path=" + current["parent"]).get_json()
    assert current["can_up"] is False
    assert current["parent"] is None
    assert str(Path(current["path"])) == Path(current["path"]).anchor and hops > 0

    # And an absolute path outside the home folder resolves normally.
    import tempfile

    outside = Path(tempfile.gettempdir()).resolve()
    assert client.get("/api/fs/list?path=" + str(outside)).status_code == 200


def test_fs_roots_lists_drives_and_places(client):
    payload = client.get("/api/fs/roots").get_json()
    assert payload["roots"], "at least one drive/volume must be offered"
    assert all("path" in item and "name" in item for item in payload["roots"])
    assert any(place["name"] == "Home" for place in payload["places"])
    assert payload["sandboxed"] is False
    assert payload["export_dir"]


def test_fs_check_reports_writability(client, settings: Settings):
    ok = client.post("/api/fs/check", json={"path": str(settings.log_dir)}).get_json()
    assert ok["writable"] is True
    # A folder that does not exist is reported clearly rather than as writable.
    assert client.post("/api/fs/check", json={"path": str(settings.log_dir / "ghost")}).status_code == 400


@pytest.mark.skipif(
    sys.platform.startswith("win") or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits: chmod does not restrict directories on Windows, and root ignores them",
)
def test_fs_check_detects_a_read_only_folder(client, settings: Settings):
    readonly = settings.log_dir / "locked"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        result = client.post("/api/fs/check", json={"path": str(readonly)}).get_json()
        assert result["writable"] is False
    finally:
        readonly.chmod(0o700)


def test_fs_rejects_missing_folders_with_a_clear_message(client, settings: Settings):
    response = client.get("/api/fs/list?path=" + str(settings.log_dir / "nope"))
    assert response.status_code == 400
    assert "no longer exists" in response.get_json()["message"]


def test_strict_sandbox_mode_still_available(settings: Settings, monkeypatch, tmp_path: Path):
    """Shared/kiosk machines can opt back in to the old confinement."""
    from timetable import filesystem as fs

    monkeypatch.setenv("TTG_SANDBOX_ROOT", str(tmp_path))
    assert fs.sandbox_root() == tmp_path.resolve()
    inside = tmp_path / "inside"
    inside.mkdir()
    assert fs.resolve_dir(inside) == inside.resolve()
    with pytest.raises(fs.FileSystemError):
        fs.resolve_dir("/etc")
    assert fs.list_folder(tmp_path)["can_up"] is False
    assert fs.list_folder(tmp_path)["sandboxed"] is True


def test_unique_path_never_overwrites(tmp_path: Path):
    from timetable.filesystem import unique_path

    target = tmp_path / "timetable.xlsx"
    assert unique_path(target) == target
    target.write_bytes(b"1")
    assert unique_path(target).name == "timetable (2).xlsx"
    (tmp_path / "timetable (2).xlsx").write_bytes(b"2")
    assert unique_path(target).name == "timetable (3).xlsx"


def test_project_can_be_saved_outside_the_home_folder(client, tmp_path: Path):
    """A project saves to any drive/folder the OS allows."""
    target = tmp_path / "elsewhere" / "away.ttproj"
    saved = client.post("/api/project/save", json={"name": "Away", "path": str(target)})
    assert saved.status_code == 200, saved.get_json()
    assert Path(saved.get_json()["path"]) == target.resolve()
    assert target.is_file()  # parent folder was created for the user

    opened = client.post("/api/project/open", json={"path": str(target)})
    assert opened.status_code == 200
    assert opened.get_json()["name"] == "Away"


# --------------------------------------------------------------------------- #
# desktop launcher flags
# --------------------------------------------------------------------------- #
def test_desktop_parser_exposes_window_and_browser_flags():
    parser = build_parser()
    args = parser.parse_args(["--window"])
    assert args.window is True
    args = parser.parse_args(["--browser"])
    assert args.browser is True
    args = parser.parse_args(["--no-browser"])
    assert args.no_browser is True
    args = parser.parse_args([])
    assert args.window is False and args.browser is False


def test_native_window_default_setting():
    from timetable.config import load_settings

    assert load_settings().native_window is True
    os.environ["TTG_WINDOW_NATIVE"] = "0"
    try:
        assert load_settings().native_window is False
    finally:
        os.environ.pop("TTG_WINDOW_NATIVE", None)
