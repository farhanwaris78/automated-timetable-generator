"""Portable project files: the whole database in one file.

A *project* is everything a user has worked on - teachers, buildings, rooms,
courses, sections, students, enrolments, the saved timetable and the grid
preferences - bundled into a single ``.ttproj`` file that can be saved,
opened, archived, e-mailed or copied to another machine.

File format (a ZIP archive, versioned so future releases can migrate it):

    project.json      metadata: name, app version, timestamps, row counts
    data.json         every table as a list of rows (portable across backends)

The data is exported as JSON rather than a raw SQLite copy so that a project
created while the app is pointed at SQL Server, PostgreSQL or MySQL still
opens on any other machine - and the file stays inspectable in any text
editor.

Design rules:
  * all writes are atomic (temp file + rename) - a crash never corrupts a
    project or the working database;
  * ``NEW`` and ``OPEN`` run inside one database transaction, so a failure
    rolls back and never leaves the user with half a project;
  * a safety backup of the working database is taken before either action,
    and the most recent 10 are kept;
  * project paths are confined to the user's home directory (the in-app
    browser never advertises anything else) and are validated server-side -
    a web page talking to the local server cannot read arbitrary files.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Date, DateTime, delete, insert, select

from . import __version__
from .db import ALL_TABLES

log = logging.getLogger(__name__)

PROJECT_SUFFIX = ".ttproj"
PROJECT_FORMAT = 1
PROJECT_MIMETYPE = "application/x-timetable-project"
MAX_RECENT = 10
MAX_BACKUPS = 10

# Insert order (parents before children, FK-safe).  Restore deletes in the
# exact reverse order so foreign keys are never violated.
TABLE_ORDER = [
    "courses",
    "course_sections",
    "instructors",
    "courses_taught_by",
    "buildings",
    "rooms",
    "students",
    "enrollments",
    "timetable_entries",
    "app_settings",
]

_TABLES_BY_NAME = {table.name: table for table in ALL_TABLES}


class ProjectError(RuntimeError):
    """Raised when a project file is missing, corrupt or incompatible."""


# --------------------------------------------------------------------------- #
# paths / state
# --------------------------------------------------------------------------- #
def project_state_path(data_dir: Path) -> Path:
    return data_dir / "project-state.json"


def recent_path(data_dir: Path) -> Path:
    return data_dir / "recent-projects.json"


def backups_dir(data_dir: Path) -> Path:
    path = data_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic JSON write: temp file in the same directory, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        log.warning("Could not read %s - ignoring it", path)
    return default


def read_project_state(data_dir: Path) -> dict[str, Any]:  # noqa: F811 - kept public
    """Name/path of the project currently loaded in the working database."""
    return _read_json(project_state_path(data_dir), {"name": "Untitled project", "path": None, "saved_at": None})


def write_project_state(data_dir: Path, *, name: str, path: str | None) -> dict[str, Any]:
    state = {
        "name": (name or "Untitled project").strip() or "Untitled project",
        "path": path,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_json(project_state_path(data_dir), state)
    return state


# --------------------------------------------------------------------------- #
# recent projects
# --------------------------------------------------------------------------- #
def list_recent_projects(data_dir: Path) -> list[dict[str, Any]]:
    """Most recently used projects, newest first, with a max length."""
    items = _read_json(recent_path(data_dir), {"recent": []}).get("recent", [])
    if not isinstance(items, list):
        return []
    valid: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("path"):
            valid.append(
                {
                    "name": str(item.get("name") or Path(item["path"]).stem),
                    "path": str(item["path"]),
                    "modified": str(item.get("modified") or ""),
                }
            )
    return valid[:MAX_RECENT]


def push_recent_project(data_dir: Path, name: str, path: str | Path, modified: str | None = None) -> list[dict[str, Any]]:
    target = str(Path(path).resolve())
    if not modified:
        try:
            modified = datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(timespec="seconds")
        except OSError:
            modified = datetime.now().isoformat(timespec="seconds")
    items = [item for item in list_recent_projects(data_dir) if item["path"] != target]
    items.insert(0, {"name": name, "path": target, "modified": modified})
    _write_json(recent_path(data_dir), {"recent": items[:MAX_RECENT]})
    return items[:MAX_RECENT]


def remove_recent_project(data_dir: Path, path: str) -> list[dict[str, Any]]:
    target = str(Path(path).expanduser().resolve())
    items = [item for item in list_recent_projects(data_dir) if item["path"] != target]
    _write_json(recent_path(data_dir), {"recent": items})
    return items


# --------------------------------------------------------------------------- #
# safety backup of the working database
# --------------------------------------------------------------------------- #
def backup_working_database(database_url: str, data_dir: Path) -> Path | None:
    """Consistent copy of the working SQLite database before a destructive op.

    Only SQLite databases can be backed up this way; external servers are
    protected by the transaction around the restore itself.
    """
    if not database_url.startswith("sqlite"):
        return None
    raw = database_url.split("sqlite:///", 1)[-1]
    source = Path(raw)
    if not source.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir(data_dir) / f"timetable-{stamp}.db"
    try:
        with sqlite3.connect(str(source)) as src:
            with sqlite3.connect(str(target)) as dst:
                src.backup(dst)
        _prune_backups(data_dir)
        log.info("Safety backup written: %s", target)
        return target
    except (OSError, sqlite3.Error) as exc:  # pragma: no cover - defensive
        log.warning("Could not back up the working database: %s", exc)
        return None


def _prune_backups(data_dir: Path) -> None:
    backups = sorted(backups_dir(data_dir).glob("timetable-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[MAX_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# dump / restore (row-level, backend-agnostic)
# --------------------------------------------------------------------------- #
def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):  # date / datetime
        return value.isoformat()
    return str(value)


def dump_database(engine) -> dict[str, list[dict[str, Any]]]:
    """Export every table, in FK-safe order, as JSON-serialisable rows."""
    payload: dict[str, list[dict[str, Any]]] = {}
    with engine.connect() as conn:
        for name in TABLE_ORDER:
            table = _TABLES_BY_NAME[name]
            rows = [
                {key: _json_safe(value) for key, value in row._mapping.items()}
                for row in conn.execute(select(table))
            ]
            payload[name] = rows
    return payload


def _row_counts(payload: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {name: len(rows) for name, rows in payload.items()}


def _coerce(column, value: Any) -> Any:
    """Turn ISO strings back into the typed values SQLAlchemy expects."""
    if value is None:
        return None
    if isinstance(column.type, (Date, DateTime)) and isinstance(value, str):
        try:
            if "T" in value or " " in value:
                return DateTime().python_type.fromisoformat(value)
            return Date().python_type.fromisoformat(value)
        except ValueError:
            return value
    return value


def restore_database(engine, payload: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    """Replace the working database with the rows from a project file.

    Runs inside a single transaction: on any error nothing is changed.
    """
    missing = [name for name in TABLE_ORDER if name not in payload]
    if missing:
        raise ProjectError(f"Project data is missing table(s): {', '.join(missing)}")

    with engine.begin() as conn:
        # Delete existing rows children-first (reverse of the insert order).
        for name in reversed(TABLE_ORDER):
            conn.execute(delete(_TABLES_BY_NAME[name]))
        # Restore parents first, preserving every id so foreign keys survive.
        for name in TABLE_ORDER:
            table = _TABLES_BY_NAME[name]
            rows = [
                {key: _coerce(table.c[key], value) for key, value in row.items() if key in table.c}
                for row in payload[name]
                if isinstance(row, dict) and row
            ]
            if rows:
                conn.execute(insert(table), rows)
    return _row_counts(payload)


# --------------------------------------------------------------------------- #
# project file I/O
# --------------------------------------------------------------------------- #
def ensure_project_suffix(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.suffix == "":
        candidate = candidate.with_suffix(PROJECT_SUFFIX)
    if candidate.suffix.lower() != PROJECT_SUFFIX:
        raise ProjectError(f"Project files must end with {PROJECT_SUFFIX}.")
    return candidate


def autosave_project(engine, project_path: str | Path, name: str, *, keep: int = MAX_BACKUPS) -> dict[str, Any]:
    """Write a timestamped backup of the current project into ``_backups``.

    Called periodically by the UI so a crash never loses more than a few
    minutes of work.  The backups live **next to the project file** (in a
    ``_backups`` folder) so they travel with the project and are easy to find,
    and the newest ``keep`` are kept (older ones are pruned automatically).
    """
    source = Path(project_path).expanduser()
    if not source.is_file():
        raise ProjectError("There is no saved project to back up yet.")
    backups = source.parent / "_backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "".join(char for char in source.stem if char.isalnum() or char in " -_").strip() or "timetable"
    target = backups / f"{base}-{stamp}{PROJECT_SUFFIX}"
    result = write_project(engine, target, name or source.stem)

    # Prune the oldest backups, keeping the newest `keep`.
    rolling = sorted(
        backups.glob(f"{base}-*{PROJECT_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in rolling[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return result


def write_project(engine, path: str | Path, name: str) -> dict[str, Any]:
    """Save the working database to ``path`` as a portable .ttproj file."""
    target = ensure_project_suffix(path).resolve()
    payload = dump_database(engine)
    counts = _row_counts(payload)
    now = datetime.now().isoformat(timespec="seconds")
    project = {
        "format": PROJECT_FORMAT,
        "name": (name or target.stem).strip() or target.stem,
        "app_version": __version__,
        "created_at": now,
        "modified_at": now,
        "counts": counts,
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    existed = target.exists()
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            zf.writestr("project.json", json.dumps(project, indent=2, ensure_ascii=False))
            zf.writestr("data.json", json.dumps(payload, ensure_ascii=False))
        tmp.replace(target)  # atomic
    finally:
        if tmp.exists():
            tmp.unlink()

    log.info("Project saved: %s (%s rows)", target, sum(counts.values()))
    return {
        "ok": True,
        "name": project["name"],
        "path": str(target),
        "modified_at": project["modified_at"],
        "counts": counts,
        "existing": existed,
    }


def read_project(path: str | Path) -> dict[str, Any]:
    """Open and validate a .ttproj file; returns metadata + data payload."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise ProjectError(f"Project file not found: {source}")
    if source.suffix.lower() != PROJECT_SUFFIX:
        raise ProjectError(f"Not a project file (expected {PROJECT_SUFFIX}): {source.name}")
    try:
        with zipfile.ZipFile(source, "r") as zf:
            names = set(zf.namelist())
            if "project.json" not in names or "data.json" not in names:
                raise ProjectError(f"{source.name} is not a valid Automatd Timetable Generator project.")
            meta = json.loads(zf.read("project.json").decode("utf-8"))
            data = json.loads(zf.read("data.json").decode("utf-8"))
    except (zipfile.BadZipFile, ValueError, KeyError) as exc:
        raise ProjectError(f"Could not read project file {source.name}: {exc}") from exc

    if not isinstance(meta, dict) or not isinstance(data, dict):
        raise ProjectError(f"{source.name} is corrupt - it cannot be opened.")
    fmt = int(meta.get("format", 0))
    if fmt != PROJECT_FORMAT:
        raise ProjectError(
            f"{source.name} was saved by a newer version of the app (format {fmt}); "
            f"this build supports format {PROJECT_FORMAT}. Please update the app."
        )
    return {
        "name": str(meta.get("name") or source.stem),
        "path": str(source.resolve()),
        "app_version": str(meta.get("app_version") or "unknown"),
        "created_at": str(meta.get("created_at") or ""),
        "modified_at": str(meta.get("modified_at") or ""),
        "counts": meta.get("counts") or {},
        "data": data,
        "size": source.stat().st_size,
    }


def open_project(engine, path: str | Path, data_dir: Path, database_url: str) -> dict[str, Any]:
    """Load a project file into the working database (with a safety backup)."""
    project = read_project(path)
    backup_working_database(database_url, data_dir)
    counts = restore_database(engine, project["data"])
    project["counts"] = counts
    log.info("Project opened: %s", project["path"])
    return project


def new_project(
    engine,
    data_dir: Path,
    database_url: str,
    name: str,
    *,
    blank: bool = True,
) -> dict[str, Any]:
    """Start a brand-new project.

    ``blank=True`` (the default) gives a **completely empty** workspace - no
    courses, teachers, buildings, rooms, students, enrolments or scheduled
    classes - which is what people actually want when they start their own
    institute's timetable.  ``blank=False`` loads the bundled sample
    university instead, for anyone who wants to explore the app first.

    A safety backup of the current working database is always taken first, so
    "New" is never destructive in practice.
    """
    from .db import reset_database

    backup_working_database(database_url, data_dir)
    reset_database(engine, seed=not blank)
    return {
        "ok": True,
        "name": (name or "Untitled project").strip() or "Untitled project",
        "path": None,
        "blank": bool(blank),
    }
