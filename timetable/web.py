"""Flask application factory and JSON API.

Design rules applied here:
  * every route returns JSON errors (never an HTML traceback);
  * the database engine lives on ``app.extensions`` - no module-level
    connection that dies after the first network hiccup;
  * every SQL statement is parameterised (see :mod:`timetable.services`);
  * the UI degrades gracefully when the database is unavailable.
"""

from __future__ import annotations

import errno
import io
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from . import __version__
from .config import Settings, bundle_dir, load_settings
from .catalog import CatalogService
from .db import DatabaseError, init_database, reset_database
from .exporters import build_csv, build_workbook, openpyxl_available
from .reports import conflict_report, room_utilisation, teacher_workload
from .filesystem import (
    FileSystemError,
    default_export_dir,
    ensure_folder,
    is_writable,
    list_folder,
    list_roots,
    quick_places,
    require_writable,
    resolve_dir,
    resolve_target,
    sandbox_root,
    unique_path,
    validate_name,
)
from .importers import build_template, import_workbook
from .projects import (
    PROJECT_MIMETYPE,
    PROJECT_SUFFIX,
    ProjectError,
    autosave_project,
    list_recent_projects,
    new_project as create_new_project,
    open_project as open_project_file,
    push_recent_project,
    read_project,
    read_project_state,
    remove_recent_project,
    write_project,
    write_project_state,
)
from .publishing import build_ics, build_pdf, filter_entries
from .services import Assignment, TimetableService, ValidationError, WEEKDAYS

log = logging.getLogger("timetable")


def home_dir() -> Path:
    """The folder the project browser opens at by default.

    The browser is **not** limited to this folder any more - it is only the
    starting point.  Every drive is reachable from there (see
    :mod:`timetable.filesystem`), which is what a desktop app must allow.
    """
    from .filesystem import home_dir as _home

    return _home()


def _file_in_use_message(target: Path, exc: OSError) -> str:
    """A friendly, actionable message when a file cannot be overwritten."""
    if exc.errno in (errno.EACCES, errno.EPERM, errno.EBUSY):
        return (
            f"\u201c{target.name}\u201d is open in another program (probably Excel). "
            "Close it, then try the export again — nothing was changed."
        )
    return f"Could not write {target.name}: {exc.strerror or exc}"


def _resolve_user_dir(raw: str | Path | None) -> Path:
    """Validate a folder path sent by the UI (any drive, any location)."""
    return resolve_dir(raw)


def _resolve_user_file(raw: str | Path | None) -> Path:
    """Validate a file path sent by the UI (any drive, any location)."""
    return resolve_target(raw)


def configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.log_dir / "timetable.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s: %(message)s")
        )
        root.addHandler(file_handler)
    except OSError:  # read-only install dir, sandboxed store, ... - keep going
        pass


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    configure_logging(settings)

    root = bundle_dir()
    app = Flask(
        __name__,
        static_folder=str(root / "static"),
        template_folder=str(root / "templates"),
    )
    app.config.update(
        SECRET_KEY=settings.secret_key,
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,   # a timetable is small; block abuse
        TEMPLATES_AUTO_RELOAD=settings.debug,
        SEND_FILE_MAX_AGE_DEFAULT=0 if settings.debug else 3600,
    )
    app.extensions["settings"] = settings

    # ---- database -------------------------------------------------------- #
    engine = None
    db_error: str | None = None
    try:
        engine = init_database(settings.database_url, seed=settings.seed_demo_data)
        log.info("Database ready: %s", settings.safe_database_url)
    except DatabaseError as exc:
        db_error = str(exc)
        log.error("Database unavailable: %s", db_error)

    app.extensions["engine"] = engine
    app.extensions["db_error"] = db_error
    app.extensions["service"] = TimetableService(engine) if engine is not None else None
    app.extensions["catalog"] = CatalogService(engine) if engine is not None else None

    def service() -> TimetableService:
        svc = app.extensions.get("service")
        if svc is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        return svc

    def catalog() -> CatalogService:
        svc = app.extensions.get("catalog")
        if svc is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        return svc

    # ---- error handling --------------------------------------------------- #
    def wants_json() -> bool:
        return request.path.startswith("/api/") or request.is_json or request.method != "GET"

    @app.errorhandler(ValidationError)
    def _bad_request(exc: ValidationError):
        return jsonify({"error": "invalid_request", "message": str(exc)}), 400

    @app.errorhandler(ProjectError)
    def _project_error(exc: ProjectError):
        return jsonify({"error": "project_error", "message": str(exc)}), 400

    @app.errorhandler(FileSystemError)
    def _filesystem_error(exc: FileSystemError):
        return jsonify({"error": "filesystem_error", "message": str(exc)}), 400

    @app.errorhandler(DatabaseError)
    def _db_down(exc: DatabaseError):
        return (
            jsonify(
                {
                    "error": "database_unavailable",
                    "message": str(exc),
                    "hint": "Delete the data folder to rebuild the local database, "
                    "or check the DB settings in your .env file.",
                }
            ),
            503,
        )

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        if wants_json():
            return jsonify({"error": exc.name.lower().replace(" ", "_"), "message": exc.description}), exc.code
        return exc

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):  # pragma: no cover - safety net
        log.exception("Unhandled error on %s %s", request.method, request.path)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    # ---- pages ------------------------------------------------------------ #
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            app_version=__version__,
            db_error=app.extensions.get("db_error"),
            weekdays=WEEKDAYS,
        )

    @app.get("/api/health")
    def health():
        svc = app.extensions.get("service")
        payload: dict[str, Any] = {
            "status": "ok" if svc else "degraded",
            "version": __version__,
            "database": settings.safe_database_url,
            "backend": "sqlite" if settings.is_sqlite else "external",
        }
        if svc:
            payload["stats"] = svc.stats()
        else:
            payload["message"] = app.extensions.get("db_error")
        return jsonify(payload), (200 if svc else 503)

    # ---- reference data --------------------------------------------------- #
    @app.get("/api/courses")
    def api_courses():
        return jsonify(service().list_courses())

    @app.get("/api/course-details/<int:course_id>/<string:section>")
    def api_course_details(course_id: int, section: str):
        details = service().course_details(course_id, section)
        if details is None:
            return jsonify({"error": "not_found", "message": "Course section not found"}), 404
        return jsonify(details)

    @app.get("/api/rooms")
    def api_rooms():
        return jsonify(service().list_rooms())

    @app.get("/api/students")
    def api_students():
        return jsonify(service().list_students())

    @app.get("/api/student-enrollments")
    def api_enrollments():
        return jsonify(service().list_enrollments())

    # ---- timetable -------------------------------------------------------- #
    def _parse_assignments(payload: Any) -> list[Assignment]:
        if isinstance(payload, dict):
            raw = payload.get("assignments", payload.get("assigned_courses", []))
        else:
            raw = payload
        if not isinstance(raw, list):
            raise ValidationError("Expected a list of assignments")
        return [Assignment.from_payload(item) for item in raw]

    @app.get("/api/timetable")
    def api_get_timetable():
        return jsonify({"entries": service().load_timetable(), "weekdays": WEEKDAYS})

    @app.post("/api/timetable/validate")
    def api_validate():
        payload = request.get_json(silent=True)
        if payload is None:
            raise ValidationError("Request body must be JSON")
        if isinstance(payload, dict) and "candidate" in payload:
            candidate = Assignment.from_payload(payload["candidate"])
            others = _parse_assignments(payload.get("grid", []))
            grid = [
                {
                    "id": a.entry_id,
                    "day": a.day,
                    "start_time": a.start_time,
                    "end_time": a.end_time,
                    "room_id": a.room_id,
                    "course_id": a.course_id,
                    "section": a.section,
                    "kind": a.kind,
                }
                for a in others
            ]
            conflicts = service().check_assignment(candidate, others=grid)
            return jsonify(
                {
                    "ok": not any(c.severity == "error" for c in conflicts),
                    "conflicts": [c.as_dict() for c in conflicts],
                }
            )

        assignments = _parse_assignments(payload)
        reports = service().validate_timetable(assignments)
        blocking = any(c["severity"] == "error" for r in reports for c in r["conflicts"])
        return jsonify({"ok": not blocking, "reports": reports})

    @app.post("/api/timetable")
    def api_save_timetable():
        payload = request.get_json(silent=True)
        if payload is None:
            raise ValidationError("Request body must be JSON")
        assignments = _parse_assignments(payload)
        result = service().save_timetable(assignments)
        status = 200 if result["ok"] else 409
        message = (
            f"Saved {result['saved']} class(es) to the database."
            if result["ok"]
            else "Timetable was not saved because unresolved clashes were found."
        )
        return jsonify({**result, "message": message}), status

    @app.post("/api/timetable/unscheduled")
    def api_unscheduled():
        """Which required classes (lectures and labs) are still not placed?"""
        payload = request.get_json(silent=True) or {}
        raw = payload.get("assignments")
        assignments = _parse_assignments(raw) if raw is not None else None
        missing = service().unscheduled(assignments)
        by_semester: dict[str, int] = {}
        for item in missing:
            key = str(item["semester"] or "unassigned")
            by_semester[key] = by_semester.get(key, 0) + 1
        return jsonify(
            {
                "ok": not missing,
                "required": len(service().required_classes()),
                "missing": missing,
                "by_semester": by_semester,
            }
        )

    @app.post("/api/timetable/reset")
    def api_reset_timetable():
        removed = service().clear_timetable()
        return jsonify({"ok": True, "removed": removed, "message": f"Cleared {removed} scheduled class(es)."})

    @app.post("/api/database/reset")
    def api_reset_database():
        engine_ = app.extensions.get("engine")
        if engine_ is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        payload = request.get_json(silent=True) or {}
        blank = bool(payload.get("blank"))
        reset_database(engine_, seed=not blank)
        return jsonify(
            {
                "ok": True,
                "blank": blank,
                "message": "Database emptied." if blank else "Database restored to the bundled sample dataset.",
            }
        )

    # ---- settings --------------------------------------------------------- #
    @app.get("/api/settings")
    def api_get_settings():
        import json

        grid_raw = service().get_setting("grid", "")
        export_raw = service().get_setting("export", "")
        grid = json.loads(grid_raw) if grid_raw else {}
        if export_raw:
            grid["export"] = json.loads(export_raw)
        return jsonify(grid)

    @app.post("/api/settings")
    def api_set_settings():
        import json

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise ValidationError("Settings must be an object")
        # The grid settings and the export style are stored separately so
        # either can be edited without clobbering the other.
        export_opts = payload.get("export")
        if isinstance(export_opts, dict):
            service().set_setting("export", json.dumps(export_opts))
        grid_opts = {key: value for key, value in payload.items() if key != "export"}
        service().set_setting("grid", json.dumps(grid_opts))
        return jsonify({"ok": True})

    # ---- projects --------------------------------------------------------- #
    data_dir = settings.log_dir

    @app.get("/api/project")
    def api_project_info():
        svc = app.extensions.get("service")
        state = read_project_state(data_dir)
        return jsonify(
            {
                "name": state.get("name", "Untitled project"),
                "path": state.get("path"),
                "saved_at": state.get("saved_at"),
                "recent": list_recent_projects(data_dir),
                "home": str(home_dir()),
                "roots": list_roots(),
                "places": quick_places(),
                "sandboxed": sandbox_root() is not None,
                "export_dir": str(default_export_dir(state.get("path"))),
                "suffix": PROJECT_SUFFIX,
                "mimetype": PROJECT_MIMETYPE,
                "stats": svc.stats() if svc else {},
            }
        )

    @app.post("/api/project/new")
    def api_project_new():
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name") or "Untitled project").strip()[:120] or "Untitled project"
        engine_ = app.extensions.get("engine")
        if engine_ is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        # A new project is EMPTY by default: no courses, teachers, buildings,
        # rooms, students or scheduled classes.  Pass {"sample": true} to load
        # the demo university instead.
        blank = not bool(payload.get("sample"))
        result = create_new_project(engine_, data_dir, settings.database_url, name, blank=blank)
        write_project_state(data_dir, name=name, path=None)
        # The grid preferences belong to the old project - clear them too, or
        # the empty project would inherit the previous shift/room layout.
        if blank:
            service().set_setting("grid", "")
        result["stats"] = service().stats()
        result["message"] = (
            "Blank project created - add your teachers, buildings, rooms and courses."
            if blank
            else "New project created from the bundled sample dataset."
        )
        return jsonify(result)

    @app.post("/api/project/save")
    def api_project_save():
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("name") or "Untitled project").strip()[:120] or "Untitled project"
        raw_path = str(payload.get("path") or "").strip()
        if not raw_path:
            raise ValidationError("Choose a folder and a file name for the project.")
        engine_ = app.extensions.get("engine")
        if engine_ is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        target = _resolve_user_file(raw_path)
        require_writable(ensure_folder(target.parent))
        result = write_project(engine_, target, name)
        push_recent_project(data_dir, result["name"], result["path"], result.get("modified_at"))
        state = write_project_state(data_dir, name=result["name"], path=result["path"])
        result["saved_at"] = state["saved_at"]
        return jsonify(result)

    @app.post("/api/project/open")
    def api_project_open():
        payload = request.get_json(silent=True) or {}
        raw_path = str(payload.get("path") or "").strip()
        if not raw_path:
            raise ValidationError("Choose a project file to open.")
        target = _resolve_user_file(raw_path)
        if not target.is_file():
            raise ProjectError(f"Project file not found: {target.name}")
        engine_ = app.extensions.get("engine")
        if engine_ is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        result = open_project_file(engine_, target, data_dir, settings.database_url)
        push_recent_project(data_dir, result["name"], result["path"], result.get("modified_at"))
        write_project_state(data_dir, name=result["name"], path=result["path"])
        result.pop("data", None)
        result["stats"] = service().stats()
        return jsonify(result)

    def _project_meta(path: str | Path) -> dict[str, Any]:
        """Cheap metadata from a .ttproj file (no row data) for the UI."""
        project = read_project(path)
        project.pop("data", None)
        return project

    @app.get("/api/project/meta")
    def api_project_meta():
        path = _resolve_user_file(request.args.get("path"))
        if not path.is_file():
            raise ProjectError(f"Project file not found: {path.name}")
        return jsonify(_project_meta(path))

    @app.post("/api/project/autosave")
    def api_project_autosave():
        """Periodic backup of the current project into its own ``_backups`` folder."""
        payload = request.get_json(silent=True) or {}
        state = read_project_state(data_dir)
        raw_path = str(payload.get("path") or state.get("path") or "").strip()
        if not raw_path:
            return jsonify({"ok": False, "skipped": True})
        engine_ = app.extensions.get("engine")
        if engine_ is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        file_start = datetime.now()
        result = autosave_project(
            engine_,
            _resolve_user_file(raw_path),
            str(payload.get("name") or state.get("name") or "Untitled project"),
        )
        result["ok"] = True
        result["took_ms"] = int((datetime.now() - file_start).total_seconds() * 1000)
        return jsonify(result)

    @app.delete("/api/project/recent")
    def api_project_remove_recent():
        payload = request.get_json(silent=True) or {}
        raw_path = str(payload.get("path") or "").strip()
        if not raw_path:
            raise ValidationError("A recent-project path is required.")
        items = remove_recent_project(data_dir, raw_path)
        return jsonify({"ok": True, "recent": items})

    # ---- in-app file browser (whole computer, like a real Save-as) -------- #
    @app.get("/api/fs/list")
    def api_fs_list():
        """Contents of a folder anywhere the operating system allows.

        The old build confined this to the home directory, which made it
        impossible to save a project on another drive.  Now every drive is
        reachable; ``TTG_SANDBOX_HOME=1`` restores the strict behaviour for
        shared machines.
        """
        raw = request.args.get("path")
        folder = _resolve_user_dir(raw) if raw and raw.strip() else default_export_dir(
            read_project_state(data_dir).get("path")
        )
        suffix = request.args.get("suffix") or PROJECT_SUFFIX
        suffixes = [item.strip().lower() for item in suffix.split(",") if item.strip()]
        payload = list_folder(folder, suffixes or [PROJECT_SUFFIX])
        payload["roots"] = list_roots()
        payload["places"] = quick_places()
        return jsonify(payload)

    @app.get("/api/fs/roots")
    def api_fs_roots():
        """Drives / volumes plus the Desktop-Documents-Downloads shortcuts."""
        return jsonify(
            {
                "roots": list_roots(),
                "places": quick_places(),
                "home": str(home_dir()),
                "sandboxed": sandbox_root() is not None,
                "export_dir": str(default_export_dir(read_project_state(data_dir).get("path"))),
            }
        )

    @app.post("/api/fs/mkdir")
    def api_fs_mkdir():
        payload = request.get_json(silent=True) or {}
        folder = _resolve_user_dir(payload.get("path") or home_dir())
        name = validate_name(str(payload.get("name") or ""))
        require_writable(folder)
        target = folder / name
        try:
            target.mkdir()
        except FileExistsError:
            raise FileSystemError(f"A folder named \u201c{name}\u201d already exists here.") from None
        except OSError as exc:
            raise FileSystemError(f"Could not create the folder: {exc.strerror or exc}") from None
        return jsonify({"ok": True, "path": str(target), "name": name})

    @app.post("/api/fs/check")
    def api_fs_check():
        """Can the app write here?  Used to grey out the Save button early."""
        payload = request.get_json(silent=True) or {}
        folder = _resolve_user_dir(payload.get("path") or home_dir())
        return jsonify({"ok": True, "path": str(folder), "writable": is_writable(folder)})

    # ---- catalogue management (teachers / rooms / courses) ---------------- #
    @app.get("/api/instructors")
    def api_list_instructors():
        return jsonify(catalog().list_instructors())

    @app.post("/api/instructors")
    def api_create_instructor():
        payload = request.get_json(silent=True) or {}
        return jsonify(catalog().save_instructor(payload)), 201

    @app.put("/api/instructors/<int:instructor_id>")
    def api_update_instructor(instructor_id: int):
        payload = request.get_json(silent=True) or {}
        return jsonify(catalog().save_instructor(payload, instructor_id))

    @app.delete("/api/instructors/<int:instructor_id>")
    def api_delete_instructor(instructor_id: int):
        catalog().delete_instructor(instructor_id)
        return jsonify({"ok": True})

    @app.get("/api/buildings")
    def api_list_buildings():
        return jsonify(catalog().list_buildings())

    @app.post("/api/buildings")
    def api_create_building():
        return jsonify(catalog().save_building(request.get_json(silent=True) or {})), 201

    @app.put("/api/buildings/<int:building_id>")
    def api_update_building(building_id: int):
        return jsonify(catalog().save_building(request.get_json(silent=True) or {}, building_id))

    @app.delete("/api/buildings/<int:building_id>")
    def api_delete_building(building_id: int):
        catalog().delete_building(building_id)
        return jsonify({"ok": True})

    @app.post("/api/rooms")
    def api_create_room():
        return jsonify(catalog().save_room(request.get_json(silent=True) or {})), 201

    @app.put("/api/rooms/<int:room_id>")
    def api_update_room(room_id: int):
        return jsonify(catalog().save_room(request.get_json(silent=True) or {}, room_id))

    @app.delete("/api/rooms/<int:room_id>")
    def api_delete_room(room_id: int):
        catalog().delete_room(room_id)
        return jsonify({"ok": True})

    @app.get("/api/admin/courses")
    def api_admin_courses():
        return jsonify(catalog().list_courses_admin())

    @app.post("/api/courses")
    def api_create_course():
        return jsonify(catalog().save_course(request.get_json(silent=True) or {})), 201

    @app.put("/api/courses/<int:course_id>")
    def api_update_course(course_id: int):
        return jsonify(catalog().save_course(request.get_json(silent=True) or {}, course_id))

    @app.delete("/api/courses/<int:course_id>")
    def api_delete_course(course_id: int):
        catalog().delete_course(course_id)
        return jsonify({"ok": True})

    @app.post("/api/courses/<int:course_id>/sections")
    def api_create_section(course_id: int):
        return jsonify(catalog().save_section(course_id, request.get_json(silent=True) or {})), 201

    @app.delete("/api/courses/<int:course_id>/sections/<string:section>")
    def api_delete_section(course_id: int, section: str):
        catalog().delete_section(course_id, section)
        return jsonify({"ok": True})

    @app.post("/api/timetable/autofill")
    def api_autofill():
        payload = request.get_json(silent=True) or {}
        existing = _parse_assignments(payload.get("assignments", []))
        created = service().autofill(
            existing,
            days=int(payload.get("days") or 5),
            slots=payload.get("slots") or [],
            room_ids=[int(r) for r in (payload.get("room_ids") or [])],
            shift=str(payload.get("shift") or "morning"),
            limit=int(payload["limit"]) if payload.get("limit") else None,
            semester=int(payload["semester"]) if payload.get("semester") else None,
        )
        return jsonify(
            {
                "ok": True,
                "created": [
                    {
                        "day": a.day,
                        "start_time": a.start_time,
                        "end_time": a.end_time,
                        "room_id": a.room_id,
                        "course_id": a.course_id,
                        "section": a.section,
                        "shift": a.shift,
                        "kind": a.kind,
                    }
                    for a in created
                ],
            }
        )

    # ---- exports ---------------------------------------------------------- #
    def _delivery_folder(payload: dict[str, Any]) -> Path | None:
        """The folder the user asked exports to be written to, if any.

        When absent the file is streamed to the browser as before, so the
        download path keeps working everywhere.
        """
        raw = payload.get("folder") or payload.get("save_to")
        if raw is None or not str(raw).strip():
            return None
        if str(raw).strip().lower() == "auto":
            return default_export_dir(read_project_state(data_dir).get("path"))
        # must_exist=False: the folder is created on demand, so exporting into
        # a brand-new "Spring 2026" folder works without a separate mkdir.
        return resolve_dir(raw, must_exist=False)

    def _deliver(data: bytes, payload: dict[str, Any], *, filename: str, mimetype: str):
        """Write the export next to the project (or stream it as a download).

        Exports go **exactly where the user chose to save the project** - the
        same folder the .ttproj lives in - rather than the browser's download
        folder.  Existing files are never silently clobbered: the name gets a
        ``(2)`` suffix, just like Windows Explorer.
        """
        folder = _delivery_folder(payload)
        if folder is None:
            return send_file(
                io.BytesIO(data),
                mimetype=mimetype,
                as_attachment=True,
                download_name=filename,
                max_age=0,
            )

        ensure_folder(folder)
        require_writable(folder)
        name = validate_name(str(payload.get("filename") or filename))
        target = folder / name
        if not bool(payload.get("overwrite")):
            target = unique_path(target)
        tmp = target.with_name(target.name + ".part")
        try:
            tmp.write_bytes(data)
            tmp.replace(target)          # atomic: no half-written spreadsheets
        except OSError as exc:
            # A locked destination - almost always the file is still open in
            # Excel / LibreOffice.  Tell the user instead of failing silently.
            if target.exists():
                raise FileSystemError(_file_in_use_message(target, exc)) from None
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise FileSystemError(f"Could not write {target}: {exc.strerror or exc}") from None
        log.info("Export written: %s (%s bytes)", target, len(data))
        return jsonify(
            {
                "ok": True,
                "saved": True,
                "path": str(target),
                "folder": str(folder),
                "name": target.name,
                "size": len(data),
            }
        )

    def _export_entries(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Assignment]]:
        assignments = _parse_assignments(payload.get("assignments", []))
        svc = service()
        entries = svc.describe_assignments(assignments) if assignments else svc.load_timetable()
        if not entries:
            raise ValidationError("There is nothing to export yet.")
        return entries, assignments

    def _export_style(payload: dict[str, Any]) -> dict[str, Any]:
        """Merge the UI's export settings (saved on the server) with the ones
        sent for this particular export, so a font choice sticks between runs."""
        import json

        raw = service().get_setting("export", "")
        saved = json.loads(raw) if raw else {}

        def pick(key: str, default: Any = None) -> Any:
            return payload.get(key, saved.get(key, default))

        return {
            "font_name": str(pick("font_name", "Times New Roman") or "Times New Roman"),
            "font_size": int(pick("font_size", 10) or 10),
            "orientation": str(pick("orientation", "landscape") or "landscape"),
            "institution": str(pick("institution", "") or ""),
            "term": str(pick("term", "") or ""),
            "layout": str(pick("layout", "grid") or "grid"),
            "program": str(pick("program", "") or ""),
            "commencement": str(pick("commencement", "") or ""),
            "semester": str(pick("semester", "") or ""),
            "show_summary": bool(pick("show_summary", True)),
            "show_by_teacher": bool(pick("show_by_teacher", True)),
            "show_unscheduled": bool(pick("show_unscheduled", True)),
            "show_semesters": bool(pick("show_semesters", True)),
        }

    @app.post("/api/export/xlsx")
    def api_export_xlsx():
        if not openpyxl_available():
            return (
                jsonify({"error": "missing_dependency", "message": "openpyxl is not installed; use CSV export."}),
                501,
            )
        payload = request.get_json(silent=True) or {}
        entries, assignments = _export_entries(payload)
        svc = service()
        style = _export_style(payload)
        workbook = build_workbook(
            entries,
            svc.list_rooms(),
            days=int(payload.get("days") or max(int(e["day"]) for e in entries)),
            slots=payload.get("slots") or None,
            shift=str(payload.get("shift") or "all"),
            title=str(payload.get("title") or "University Timetable"),
            unscheduled=svc.unscheduled(assignments if assignments else None),
            font_name=style["font_name"],
            font_size=style["font_size"],
            orientation=style["orientation"],
            institution=style["institution"],
            term=style["term"],
            layout=style["layout"],
            program=style["program"],
            commencement=style["commencement"],
            semester=style["semester"],
            show_summary=style["show_summary"],
            show_by_teacher=style["show_by_teacher"],
            show_unscheduled=style["show_unscheduled"],
            show_semesters=style["show_semesters"],
        )
        return _deliver(
            workbook,
            payload,
            filename="timetable.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.post("/api/export/csv")
    def api_export_csv():
        """CSV of the timetable - the same delivery rules as the Excel export."""
        payload = request.get_json(silent=True) or {}
        entries, _ = _export_entries(payload)
        return _deliver(
            build_csv(entries),
            payload,
            filename="timetable.csv",
            mimetype="text/csv; charset=utf-8",
        )

    # ---- reporting (room utilisation / teacher workload / conflicts) ------ #
    @app.post("/api/report/<string:scope>")
    def api_report(scope: str):
        """Build one of the three reports as JSON so the UI can show it on
        screen and the same data powers the Excel sheet and PDF page."""
        payload = request.get_json(silent=True) or {}
        svc = service()
        raw = payload.get("assignments")
        entries = svc.describe_assignments(_parse_assignments(raw)) if raw else svc.load_timetable()
        rooms = svc.list_rooms()
        days = int(payload.get("days") or max((int(e["day"]) for e in entries), default=5))
        slots = payload.get("slots") or None
        shift = str(payload.get("shift") or "all")

        if scope == "utilisation":
            report = room_utilisation(entries, rooms, days=days, slots=slots, shift=shift)
        elif scope == "workload":
            report = teacher_workload(entries)
        elif scope == "conflict":
            report = conflict_report(entries)
        else:
            raise ValidationError("report scope must be utilisation, workload or conflict.")
        return jsonify({"ok": True, **report, "entries": len(entries)})

    # ---- bulk import (Excel) ---------------------------------------------- #
    @app.get("/api/import/template")
    def api_import_template():
        if not openpyxl_available():
            return (
                jsonify({"error": "missing_dependency", "message": "openpyxl is not installed."}),
                501,
            )
        return send_file(
            io.BytesIO(build_template()),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="timetable-import-template.xlsx",
            max_age=0,
        )

    @app.post("/api/import/xlsx")
    def api_import_xlsx():
        if not openpyxl_available():
            return (
                jsonify({"error": "missing_dependency", "message": "openpyxl is not installed."}),
                501,
            )
        upload = request.files.get("file")
        data = upload.read() if upload is not None else request.get_data()
        if not data:
            raise ValidationError("Choose an .xlsx file to import.")
        if len(data) > 8 * 1024 * 1024:
            raise ValidationError("That file is larger than 8 MB.")
        report = import_workbook(catalog(), data)
        log.info(
            "Import finished: %s added, %s updated, %s skipped",
            report["total_created"], report["total_updated"], report["skipped"],
        )
        return jsonify(report)

    # ---- publishing (PDF / iCalendar) ------------------------------------- #
    def _publish_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Entries to publish: the on-screen grid if supplied, else what is saved."""
        svc = service()
        raw = payload.get("assignments")
        entries = svc.describe_assignments(_parse_assignments(raw)) if raw else svc.load_timetable()
        return filter_entries(
            entries,
            teacher=payload.get("teacher") or None,
            course_id=int(payload["course_id"]) if payload.get("course_id") else None,
            section=payload.get("section") or None,
            room_id=int(payload["room_id"]) if payload.get("room_id") else None,
            semester=int(payload["semester"]) if payload.get("semester") else None,
            shift=str(payload.get("shift") or "all"),
        )

    @app.get("/api/publish/targets")
    def api_publish_targets():
        entries = service().load_timetable()
        teachers = sorted({str(e.get("instructor") or "Unassigned") for e in entries})
        sections = sorted(
            {
                (int(e["course_id"]), str(e.get("code") or ""), str(e["course_name"]), str(e["section"]))
                for e in entries
            },
            key=lambda item: (item[1], item[3]),
        )
        rooms_used = sorted({(int(e["room_id"]), str(e.get("room_label") or "")) for e in entries},
                            key=lambda item: item[1])
        semesters = sorted({int(e.get("semester") or 0) for e in entries if int(e.get("semester") or 0)})
        return jsonify(
            {
                "saved_classes": len(entries),
                "teachers": teachers,
                "sections": [
                    {"course_id": cid, "code": code, "name": name, "section": section}
                    for cid, code, name, section in sections
                ],
                "rooms": [{"id": rid, "label": label} for rid, label in rooms_used],
                "semesters": semesters,
                "unscheduled": len(service().unscheduled()),
            }
        )

    @app.post("/api/publish/pdf")
    def api_publish_pdf():
        payload = request.get_json(silent=True) or {}
        entries = _publish_entries(payload)
        if not entries:
            raise ValidationError("Nothing matches that selection, so there is no PDF to make.")
        scope = str(payload.get("scope") or "all")
        valid_scopes = (
            "all", "teacher", "section", "room", "semester",
            "schedule", "day", "utilisation", "workload", "conflict",
        )
        if scope not in valid_scopes:
            raise ValidationError(
                "scope must be one of: " + ", ".join(valid_scopes) + "."
            )
        style = _export_style(payload)
        pdf = build_pdf(
            entries,
            service().list_rooms(),
            scope=scope,
            days=int(payload.get("days") or max(int(e["day"]) for e in entries)),
            slots=payload.get("slots") or None,
            title=str(payload.get("title") or "University Timetable"),
            font_name=style["font_name"],
            institution=style["institution"],
            term=style["term"],
            layout=style["layout"],
            program=style["program"],
            commencement=style["commencement"],
            semester=style["semester"],
        )
        return _deliver(
            pdf,
            payload,
            filename=f"timetable-{scope}.pdf",
            mimetype="application/pdf",
        )

    def _ics_response(entries: list[dict[str, Any]], name: str, weeks: Any, start: Any, download: bool):
        from datetime import date

        try:
            first = date.fromisoformat(str(start)) if start else date.today()
        except ValueError:
            raise ValidationError("start must be a date in YYYY-MM-DD form.") from None
        text = build_ics(entries, start_date=first, weeks=int(weeks or 16), calendar_name=name)
        response = app.response_class(text, mimetype="text/calendar")
        disposition = "attachment" if download else "inline"
        safe = "".join(char for char in name if char.isalnum() or char in " -_").strip() or "timetable"
        response.headers["Content-Disposition"] = f'{disposition}; filename="{safe}.ics"'
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/calendar.ics")
    def api_calendar_feed():
        """Stable subscription URL - students/teachers can add it to any calendar app."""
        payload = {
            "teacher": request.args.get("teacher"),
            "course_id": request.args.get("course_id"),
            "section": request.args.get("section"),
            "room_id": request.args.get("room_id"),
            "semester": request.args.get("semester"),
            "shift": request.args.get("shift") or "all",
        }
        entries = _publish_entries(payload)
        name = payload["teacher"] or (
            f"Semester {payload['semester']} timetable" if payload.get("semester")
            else f"{payload['section']} timetable" if payload["section"]
            else "University Timetable"
        )
        return _ics_response(entries, name, request.args.get("weeks", 16), request.args.get("start"), False)

    @app.post("/api/publish/ics")
    def api_publish_ics():
        payload = request.get_json(silent=True) or {}
        entries = _publish_entries(payload)
        if not entries:
            raise ValidationError("Nothing matches that selection, so there is no calendar to make.")
        name = str(payload.get("title") or payload.get("teacher") or "University Timetable")
        if _delivery_folder(payload) is not None:
            from datetime import date

            try:
                first = date.fromisoformat(str(payload["start"])) if payload.get("start") else date.today()
            except ValueError:
                raise ValidationError("start must be a date in YYYY-MM-DD form.") from None
            text = build_ics(
                entries, start_date=first, weeks=int(payload.get("weeks") or 16), calendar_name=name
            )
            return _deliver(
                text.encode("utf-8"),
                payload,
                filename="timetable.ics",
                mimetype="text/calendar; charset=utf-8",
            )
        return _ics_response(entries, name, payload.get("weeks", 16), payload.get("start"), True)

    # ---- legacy routes (kept so old bookmarks/scripts keep working) -------- #
    @app.post("/save-timetable")
    def legacy_save():
        return api_save_timetable()

    @app.post("/reset-timetable")
    def legacy_reset():
        return api_reset_timetable()

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    return app


# Convenience for `flask --app timetable.web run` and WSGI servers.
def wsgi_app():  # pragma: no cover - thin wrapper
    return create_app()


if __name__ == "__main__":  # pragma: no cover
    _settings = load_settings()
    create_app(_settings).run(
        host=_settings.host,
        port=_settings.port or 5000,
        debug=_settings.debug,
    )
