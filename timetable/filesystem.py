"""Filesystem services for the in-app file browser and the export writer.

The application is a **local desktop program**: the server listens on the
loopback interface only and is started by the person sitting at the machine.
Locking the file browser to the user's home folder therefore bought no real
security - it only stopped people from saving a project to ``D:\\Timetables``
or to a USB stick, which is exactly what a desktop app must be able to do.

This module replaces that restriction with something that behaves like a
normal *Save as* dialog:

* every drive / volume on the machine is listed (``C:\\``, ``D:\\`` … on
  Windows, ``/`` plus the mount points on macOS and Linux);
* handy shortcuts (Desktop, Documents, Downloads, home) are offered;
* you can walk *up* past your user folder all the way to the drive root;
* folders are checked for writability **before** anything is written, so the
  user gets a friendly message instead of a failed export;
* a strict mode (``TTG_SANDBOX_HOME=1``) is still available for shared or
  kiosk machines that really do want the old confinement.

Everything here is pure ``pathlib`` - no shell, no globbing of user input,
no string concatenation of paths.
"""

from __future__ import annotations

import os
import string
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "FileSystemError",
    "sandbox_root",
    "resolve_dir",
    "resolve_target",
    "list_folder",
    "list_roots",
    "quick_places",
    "is_writable",
    "unique_path",
    "default_export_dir",
    "ensure_folder",
    "describe",
]

# Names that are noise in a file picker.
_HIDDEN_NAMES = {
    "System Volume Information",
    "$RECYCLE.BIN",
    "$Recycle.Bin",
    "Recovery",
    "msdownld.tmp",
}

# Windows reserved device names - never valid as a file/folder name.
_RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_ILLEGAL_NAME_CHARS = set('<>:"/\\|?*') | {chr(index) for index in range(32)}


class FileSystemError(RuntimeError):
    """Raised when a path is unusable (missing, unreadable, not writable…)."""


# --------------------------------------------------------------------------- #
# strict mode
# --------------------------------------------------------------------------- #
def _truthy(raw: str | None) -> bool:
    return bool(raw) and str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def sandbox_root() -> Path | None:
    """The folder the browser is confined to, or ``None`` for the whole disk.

    Confinement is **opt-in** (``TTG_SANDBOX_HOME=1``); a custom root can be
    given with ``TTG_SANDBOX_ROOT=/some/folder`` for lab or kiosk machines.
    """
    custom = os.getenv("TTG_SANDBOX_ROOT")
    if custom and custom.strip():
        try:
            return Path(custom).expanduser().resolve()
        except OSError:  # pragma: no cover - defensive
            return None
    if _truthy(os.getenv("TTG_SANDBOX_HOME")):
        return home_dir()
    return None


def home_dir() -> Path:
    try:
        return Path.home().resolve()
    except (RuntimeError, OSError):  # pragma: no cover - exotic environments
        return Path.cwd().resolve()


# --------------------------------------------------------------------------- #
# path resolution
# --------------------------------------------------------------------------- #
def _expand(raw: str | Path) -> Path:
    """Expand ``~`` and environment variables, then make the path absolute."""
    text = os.path.expandvars(str(raw).strip())
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (home_dir() / path)
    try:
        return path.resolve()
    except OSError:  # pragma: no cover - broken symlink chains
        return path.absolute()


def _enforce_sandbox(path: Path) -> Path:
    root = sandbox_root()
    if root is None:
        return path
    try:
        path.relative_to(root)
    except ValueError:
        raise FileSystemError(
            f"This copy of the app is restricted to {root} and its sub-folders."
        ) from None
    return path


def resolve_dir(raw: str | Path | None, *, must_exist: bool = True) -> Path:
    """Validate a folder path coming from the user interface."""
    if raw is None or not str(raw).strip():
        raise FileSystemError("A folder path is required.")
    path = _enforce_sandbox(_expand(raw))
    if must_exist:
        if not path.exists():
            raise FileSystemError(f"That folder no longer exists: {path}")
        if not path.is_dir():
            raise FileSystemError(f"That is a file, not a folder: {path}")
    return path


def resolve_target(raw: str | Path | None) -> Path:
    """Validate a *file* path (its folder must exist or be creatable)."""
    if raw is None or not str(raw).strip():
        raise FileSystemError("A file path is required.")
    path = _enforce_sandbox(_expand(raw))
    if path.is_dir():
        raise FileSystemError(f"{path} is a folder - please include a file name.")
    validate_name(path.name)
    return path


def validate_name(name: str) -> str:
    """Reject names the operating system cannot store."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise FileSystemError("Enter a name.")
    if len(cleaned) > 200:
        raise FileSystemError("That name is too long (200 characters maximum).")
    if cleaned in (".", ".."):
        raise FileSystemError("That name is not allowed.")
    bad = sorted({char for char in cleaned if char in _ILLEGAL_NAME_CHARS})
    if bad:
        shown = " ".join(char for char in bad if char.isprintable()) or "control characters"
        raise FileSystemError(f"A name cannot contain: {shown}")
    if cleaned.rstrip(". ").upper().split(".")[0] in _RESERVED_WINDOWS_NAMES:
        raise FileSystemError(f"“{cleaned}” is a reserved name on Windows.")
    return cleaned


def ensure_folder(path: Path) -> Path:
    """Create ``path`` (and parents) if needed, raising a friendly error."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileSystemError(f"Could not create the folder {path}: {exc.strerror or exc}") from None
    return path


# --------------------------------------------------------------------------- #
# writability
# --------------------------------------------------------------------------- #
def is_writable(folder: Path) -> bool:
    """True when a new file can actually be created in ``folder``.

    ``os.access`` lies on Windows (it ignores ACLs and read-only shares), so
    the check is done by creating and deleting a tiny probe file.
    """
    if not folder.is_dir():
        return False
    probe = folder / f".ttg-write-test-{os.getpid()}"
    try:
        with probe.open("wb") as handle:
            handle.write(b"0")
        probe.unlink()
        return True
    except OSError:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:  # pragma: no cover - best effort cleanup
            pass
        return False


def require_writable(folder: Path) -> Path:
    if not is_writable(folder):
        raise FileSystemError(
            f"{folder} is read-only (or you do not have permission to write there). "
            "Pick another folder."
        )
    return folder


def unique_path(target: Path) -> Path:
    """``report.xlsx`` → ``report (2).xlsx`` when the file already exists."""
    if not target.exists():
        return target
    stem, suffix, parent = target.stem, target.suffix, target.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return parent / f"{stem} {stamp}{suffix}"


# --------------------------------------------------------------------------- #
# roots, drives and quick places
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Place:
    name: str
    path: str
    kind: str  # "drive" | "place"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "kind": self.kind}


def _windows_drives() -> list[Place]:
    drives: list[Place] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if root.exists():
                drives.append(Place(f"{letter}: drive", str(root), "drive"))
        except OSError:  # pragma: no cover - disconnected network drive
            continue
    return drives


def _posix_roots() -> list[Place]:
    roots = [Place("Computer", "/", "drive")]
    for base in ("/Volumes", "/media", "/mnt", f"/media/{os.getenv('USER', '')}", "/run/media"):
        folder = Path(base)
        try:
            if not folder.is_dir():
                continue
            for child in sorted(folder.iterdir(), key=lambda item: item.name.lower()):
                if child.is_dir() and not child.name.startswith("."):
                    roots.append(Place(child.name, str(child), "drive"))
        except OSError:
            continue
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Place] = []
    for place in roots:
        if place.path in seen:
            continue
        seen.add(place.path)
        unique.append(place)
    return unique


def list_roots() -> list[dict[str, str]]:
    """Every drive / volume the user can browse."""
    root = sandbox_root()
    if root is not None:
        return [Place(root.name or str(root), str(root), "drive").as_dict()]
    places = _windows_drives() if sys.platform.startswith("win") else _posix_roots()
    return [place.as_dict() for place in places]


def quick_places() -> list[dict[str, str]]:
    """Desktop / Documents / Downloads style shortcuts that actually exist."""
    root = sandbox_root()
    home = home_dir()
    candidates: list[tuple[str, Path]] = [("Home", home)]
    for label in ("Desktop", "Documents", "Downloads"):
        candidates.append((label, home / label))
    # OneDrive-redirected folders are extremely common on Windows.
    onedrive = os.getenv("OneDrive") or os.getenv("OneDriveConsumer")
    if onedrive:
        base = Path(onedrive)
        candidates.append(("OneDrive", base))
        for label in ("Desktop", "Documents"):
            candidates.append((f"OneDrive {label}", base / label))

    places: list[dict[str, str]] = []
    seen: set[str] = set()
    for name, path in candidates:
        try:
            if not path.is_dir():
                continue
            resolved = path.resolve()
            if root is not None:
                try:
                    resolved.relative_to(root)
                except ValueError:
                    continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            places.append(Place(name, key, "place").as_dict())
        except OSError:
            continue
    return places


def default_export_dir(project_path: str | Path | None = None) -> Path:
    """Where exports land when the user has not chosen a folder.

    Next to the open project file when there is one, otherwise a tidy
    ``Documents/Timetable Generator`` folder (created on demand).
    """
    if project_path:
        try:
            parent = Path(str(project_path)).expanduser().resolve().parent
            if parent.is_dir():
                return parent
        except OSError:  # pragma: no cover - defensive
            pass
    home = home_dir()
    for base in (home / "Documents", home):
        if base.is_dir():
            target = base / "Timetable Generator"
            try:
                target.mkdir(parents=True, exist_ok=True)
                return target
            except OSError:
                continue
    return home


# --------------------------------------------------------------------------- #
# listing
# --------------------------------------------------------------------------- #
def _is_hidden(child: Path) -> bool:
    if child.name in _HIDDEN_NAMES:
        return True
    if child.name.startswith("."):
        return True
    if sys.platform.startswith("win"):
        try:  # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
            return bool(child.stat().st_file_attributes & 0x6)  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            return False
    return False


def _parent_of(folder: Path) -> Path | None:
    """The folder one level up, honouring strict mode and drive roots."""
    root = sandbox_root()
    if root is not None and folder == root:
        return None
    parent = folder.parent
    if parent == folder:  # already at "/" or "C:\"
        return None
    if root is not None:
        try:
            parent.relative_to(root)
        except ValueError:
            return None
    return parent


def describe(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def breadcrumbs(folder: Path) -> list[dict[str, str]]:
    """[{name, path}] from the drive root down to ``folder`` for the UI."""
    parts: list[dict[str, str]] = []
    current: Path | None = folder
    guard = 0
    while current is not None and guard < 64:
        guard += 1
        parts.append({"name": current.name or str(current), "path": str(current)})
        current = _parent_of(current)
    parts.reverse()
    return parts


def list_folder(folder: Path, suffixes: Iterable[str] = (".ttproj",)) -> dict[str, Any]:
    """Sub-folders plus the files whose suffix is in ``suffixes``."""
    wanted = {suffix.lower() for suffix in suffixes}
    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    truncated = False
    try:
        children = list(folder.iterdir())
    except PermissionError:
        raise FileSystemError(
            f"Windows/your OS will not let this app read {folder}. Try another folder."
        ) from None
    except OSError as exc:
        raise FileSystemError(f"Could not read {folder}: {exc.strerror or exc}") from None

    if len(children) > 5000:  # keep the picker responsive on huge folders
        children = children[:5000]
        truncated = True

    for child in children:
        try:
            if _is_hidden(child):
                continue
            if child.is_dir():
                dirs.append({"name": child.name, "path": str(child)})
            elif child.is_file() and child.suffix.lower() in wanted:
                files.append({**describe(child), "path": str(child)})
        except OSError:
            continue

    dirs.sort(key=lambda item: item["name"].lower())
    files.sort(key=lambda item: item["name"].lower())
    parent = _parent_of(folder)
    return {
        "path": str(folder),
        "name": folder.name or str(folder),
        "home": str(home_dir()),
        "parent": str(parent) if parent else None,
        "can_up": parent is not None,
        "writable": is_writable(folder),
        "sandboxed": sandbox_root() is not None,
        "breadcrumbs": breadcrumbs(folder),
        "dirs": dirs,
        "files": files,
        "truncated": truncated,
    }
