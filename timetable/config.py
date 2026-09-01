"""Runtime configuration.

Everything the application needs to run is resolved here, with sane
defaults so that a freshly installed executable works with **zero**
configuration.  Every value can still be overridden through environment
variables or a ``.env`` file placed next to the executable.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote_plus

APP_NAME = "Automated Timetable Generator"
APP_SLUG = "timetable-generator"


def is_frozen() -> bool:
    """True when running from a PyInstaller / cx_Freeze bundle."""
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path:
    """Directory that holds read-only bundled resources (templates, static)."""
    if is_frozen():
        # PyInstaller onefile extracts to sys._MEIPASS; onedir/cx_Freeze use exe dir.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    """Directory of the running executable / project root (writable-ish)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Per-user, always-writable directory for the database and logs.

    Windows: %LOCALAPPDATA%\\TimetableGenerator
    macOS:   ~/Library/Application Support/TimetableGenerator
    Linux:   ~/.local/share/timetable-generator  (respects XDG_DATA_HOME)
    """
    override = os.getenv("TTG_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    elif sys.platform.startswith("win"):
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or Path.home()
        path = Path(base) / "TimetableGenerator"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "TimetableGenerator"
    else:
        base = os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        path = Path(base) / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_dotenv() -> None:
    """Load a .env file if python-dotenv is available.

    Looked up next to the executable first, then in the current working
    directory.  Missing files are simply ignored - the app must never crash
    because an optional config file is absent.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:  # pragma: no cover - optional dependency
        return
    for candidate in (app_dir() / ".env", Path.cwd() / ".env"):
        try:
            if candidate.is_file():
                load_dotenv(candidate, override=False)
        except Exception:
            pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _sqlserver_url_from_parts() -> str | None:
    """Build an MSSQL SQLAlchemy URL from the legacy DB_* variables."""
    server = os.getenv("DB_SERVER")
    if not server:
        return None
    driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server").strip("{}")
    database = os.getenv("DB_NAME", "timetable")
    port = os.getenv("DB_PORT", "").strip()
    user = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "").strip()

    host = f"{server},{port}" if port else server
    parts = [f"DRIVER={{{driver}}}", f"SERVER={host}", f"DATABASE={database}"]
    if user:
        parts += [f"UID={user}", f"PWD={password}"]
    else:
        parts.append("Trusted_Connection=yes")
    parts.append("TrustServerCertificate=yes")
    odbc = ";".join(parts)
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc)


def resolve_database_url() -> str:
    """Decide which database to talk to.

    Priority:
      1. ``TTG_DATABASE_URL`` / ``DATABASE_URL`` - any SQLAlchemy URL.
      2. ``DB_CONNECTION_STRING`` - a raw ODBC string (legacy .env support).
      3. ``DB_SERVER`` + friends - the legacy per-part SQL Server settings.
      4. Bundled SQLite file in the user data directory (**default**).
    """
    for var in ("TTG_DATABASE_URL", "DATABASE_URL"):
        url = os.getenv(var)
        if url and url.strip():
            return url.strip()

    odbc = os.getenv("DB_CONNECTION_STRING")
    if odbc and odbc.strip():
        return "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc.strip())

    from_parts = _sqlserver_url_from_parts()
    if from_parts:
        return from_parts

    db_path = os.getenv("TTG_SQLITE_PATH")
    path = Path(db_path).expanduser() if db_path else user_data_dir() / "timetable.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the runtime configuration."""

    database_url: str
    host: str = "127.0.0.1"
    port: int = 0                      # 0 => pick a free port automatically
    debug: bool = False
    open_browser: bool = True
    seed_demo_data: bool = True
    secret_key: str = field(repr=False, default="")
    log_dir: Path = field(default_factory=user_data_dir)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def safe_database_url(self) -> str:
        """Database URL with any password removed - safe to log or display."""
        import re

        return re.sub(r"(?i)(pwd|password)=[^;&]*", r"\1=***", self.database_url)


def load_settings() -> Settings:
    _load_dotenv()
    return Settings(
        database_url=resolve_database_url(),
        host=os.getenv("TTG_HOST", "127.0.0.1"),
        port=_env_int("TTG_PORT", 0),
        debug=_env_bool("TTG_DEBUG", False),
        open_browser=_env_bool("TTG_OPEN_BROWSER", True),
        seed_demo_data=_env_bool("TTG_SEED_DEMO_DATA", True),
        secret_key=os.getenv("TTG_SECRET_KEY", os.urandom(24).hex()),
        log_dir=user_data_dir(),
    )
