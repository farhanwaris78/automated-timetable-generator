"""Desktop launcher.

Starts a production-grade local web server (waitress, falling back to the
Flask/Werkzeug server) and opens the default browser at the right address.
This is the entry point that gets frozen into the .exe / .app / Linux binary.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

from . import __app_name__, __version__
from .config import load_settings, user_data_dir

log = logging.getLogger("timetable.desktop")

BANNER = r"""
  ___ _           _        _    _    _
 |_ _| |_ ___ ___| |_ ___ | |__| |__| |___
  | ||  _|  _|  _|  _|  _||  _ \  _ \  -_|
 |___|\__|_| |_| |_| |_|  |_.__/_.__/\___|   {name}  v{version}
""".format(name=__app_name__, version=__version__)


def find_free_port(host: str, preferred: int = 0) -> int:
    """Return a usable TCP port, honouring a preferred one when free."""
    if preferred:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, preferred))
                return preferred
            except OSError:
                log.warning("Port %s is busy - picking a free one instead", preferred)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def wait_until_up(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((probe_host, port)) == 0:
                return True
        time.sleep(0.15)
    return False


def serve(app, host: str, port: int, *, debug: bool = False) -> None:
    """Run the WSGI app with the best server available."""
    if debug:
        app.run(host=host, port=port, debug=True, use_reloader=False)
        return
    try:
        from waitress import serve as waitress_serve  # type: ignore

        waitress_serve(app, host=host, port=port, threads=8, ident=__app_name__, _quiet=True)
    except ImportError:  # pragma: no cover - waitress is a hard requirement
        log.warning("waitress not installed - falling back to the development server")
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timetable-generator",
        description=f"{__app_name__} v{__version__} - clash-free university scheduling.",
    )
    parser.add_argument("--host", default=None, help="Interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: first free port)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging and the Flask debugger")
    parser.add_argument("--database-url", default=None, help="SQLAlchemy URL (overrides .env)")
    parser.add_argument("--reset-database", action="store_true", help="Recreate the local database, then exit")
    parser.add_argument("--data-dir", default=None, help="Where to keep the database and logs")
    parser.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.data_dir:
        os.environ["TTG_DATA_DIR"] = args.data_dir
    if args.database_url:
        os.environ["TTG_DATABASE_URL"] = args.database_url
    if args.debug:
        os.environ["TTG_DEBUG"] = "1"

    settings = load_settings()
    host = args.host or settings.host
    port = args.port if args.port is not None else settings.port

    # Imported late so that logging is configured by create_app() first.
    from .db import DatabaseError, init_database, reset_database
    from .web import configure_logging, create_app

    configure_logging(settings)
    print(BANNER)

    if args.reset_database:
        try:
            engine = init_database(settings.database_url, seed=False)
            reset_database(engine)
        except DatabaseError as exc:
            print(f"[!] Could not reset the database: {exc}", file=sys.stderr)
            return 2
        print("[ok] Database recreated from the bundled sample dataset.")
        return 0

    app = create_app(settings)
    port = find_free_port(host, port)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"

    print(f"  Data folder : {user_data_dir()}")
    print(f"  Database    : {settings.safe_database_url}")
    print(f"  Web address : {url}")
    if app.extensions.get("db_error"):
        print(f"  [!] Database problem: {app.extensions['db_error']}")
    print("\n  The app is running. Close this window (or press Ctrl+C) to stop it.\n")

    open_browser = (not args.no_browser) and settings.open_browser
    if open_browser:
        def _opener() -> None:
            if wait_until_up(host, port):
                try:
                    webbrowser.open(url, new=2)
                except Exception as exc:  # pragma: no cover - headless machines
                    log.warning("Could not open a browser automatically: %s", exc)

        threading.Thread(target=_opener, name="browser-opener", daemon=True).start()

    try:
        serve(app, host, port, debug=settings.debug)
    except KeyboardInterrupt:
        print("\n  Shutting down. Bye!")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
