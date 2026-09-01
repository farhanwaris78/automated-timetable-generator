"""Flask application factory and JSON API.

Design rules applied here:
  * every route returns JSON errors (never an HTML traceback);
  * the database engine lives on ``app.extensions`` - no module-level
    connection that dies after the first network hiccup;
  * every SQL statement is parameterised (see :mod:`timetable.services`);
  * the UI degrades gracefully when the database is unavailable.
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import os
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from . import __version__
from .config import Settings, bundle_dir, load_settings
from .catalog import CatalogService
from .db import DatabaseError, init_database, reset_database
from .exporters import build_workbook, openpyxl_available
from .services import Assignment, TimetableService, ValidationError, WEEKDAYS

log = logging.getLogger("timetable")


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

    @app.post("/api/timetable/reset")
    def api_reset_timetable():
        removed = service().clear_timetable()
        return jsonify({"ok": True, "removed": removed, "message": f"Cleared {removed} scheduled class(es)."})

    @app.post("/api/database/reset")
    def api_reset_database():
        engine_ = app.extensions.get("engine")
        if engine_ is None:
            raise DatabaseError(app.extensions.get("db_error") or "Database is not configured")
        reset_database(engine_)
        return jsonify({"ok": True, "message": "Database restored to the bundled sample dataset."})

    # ---- settings --------------------------------------------------------- #
    @app.get("/api/settings")
    def api_get_settings():
        import json

        raw = service().get_setting("grid", "")
        return jsonify(json.loads(raw) if raw else {})

    @app.post("/api/settings")
    def api_set_settings():
        import json

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise ValidationError("Settings must be an object")
        service().set_setting("grid", json.dumps(payload))
        return jsonify({"ok": True})


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
                    }
                    for a in created
                ],
            }
        )

    # ---- exports ---------------------------------------------------------- #
    @app.post("/api/export/xlsx")
    def api_export_xlsx():
        if not openpyxl_available():
            return (
                jsonify({"error": "missing_dependency", "message": "openpyxl is not installed; use CSV export."}),
                501,
            )
        payload = request.get_json(silent=True) or {}
        assignments = _parse_assignments(payload.get("assignments", []))
        svc = service()

        if assignments:
            entries = svc.describe_assignments(assignments)
        else:
            entries = svc.load_timetable()
        if not entries:
            raise ValidationError("There is nothing to export yet.")

        workbook = build_workbook(
            entries,
            svc.list_rooms(),
            days=int(payload.get("days") or max(int(e["day"]) for e in entries)),
            slots=payload.get("slots") or None,
            shift=str(payload.get("shift") or "all"),
            title=str(payload.get("title") or "University Timetable"),
        )
        return send_file(
            io.BytesIO(workbook),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=str(payload.get("filename") or "timetable.xlsx"),
            max_age=0,
        )

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
