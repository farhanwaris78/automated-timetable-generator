"""Desktop launcher.

Starts a production-grade local web server (waitress, falling back to the
Flask/Werkzeug server) and opens the user interface.

Two display modes:

* **native window** (default) - the UI is rendered inside its own desktop
  window through pywebview (WebView2 on Windows, WKWebView on macOS,
  WebKitGTK on Linux).  No browser tab, no URL bar - it behaves like any
  other installed application.
* **browser** - the classic mode: a console prints the address and the
  default browser opens it.  Used as an automatic fallback on systems
  where pywebview's webview runtime is missing, or with ``--browser``.

This module is the entry point that gets frozen into the .exe / .app /
Linux binary.
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
    """Run the WSGI app with the best server available (blocking)."""
    if debug:
        app.run(host=host, port=port, debug=True, use_reloader=False)
        return
    try:
        from waitress import serve as waitress_serve  # type: ignore

        waitress_serve(app, host=host, port=port, threads=8, ident=__app_name__, _quiet=True)
    except ImportError:  # pragma: no cover - waitress is a hard requirement
        log.warning("waitress not installed - falling back to the development server")
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


def start_server(app, host: str, port: int, *, debug: bool = False):
    """Start the local web server on a daemon thread.

    Returns ``(server, thread)`` where ``server`` may be None for the
    Werkzeug fallback.  Call :func:`stop_server` when done.
    """
    try:
        from waitress import create_server  # type: ignore

        server = create_server(app, host=host, port=port, threads=8, ident=__app_name__)
        thread = threading.Thread(target=server.run, name="waitress", daemon=True)
        thread.start()
        return server, thread
    except ImportError:
        from werkzeug.serving import make_server  # type: ignore

        server = make_server(host, port, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, name="werkzeug", daemon=True)
        thread.start()
        return server, thread


def stop_server(server, thread: threading.Thread | None) -> None:
    """Stop a server started by :func:`start_server`."""
    if server is not None:
        try:
            server.close()
        except Exception:  # pragma: no cover - server may already be gone
            pass
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


def serve_native(app, host: str, port: int, *, debug: bool = False) -> bool:
    """Open the app in its own native desktop window.

    Returns True when the window was shown (and closed by the user).
    Returns False when pywebview or the platform webview runtime is not
    available - the caller then falls back to opening the browser.
    """
    try:
        import webview  # type: ignore
    except Exception:  # pragma: no cover - optional runtime dependency
        log.info("pywebview is not installed - falling back to the browser")
        return False

    url = f"http://127.0.0.1:{port}/"
    server = thread = None
    try:
        server, thread = start_server(app, host, port, debug=debug)
        try:
            webview.create_window(
                __app_name__,
                url=url,
                width=1280,
                height=860,
                min_size=(980, 640),
                text_select=True,
            )
            webview.start(debug=debug)
        except Exception as exc:  # missing GTK/Qt runtime, headless shell, ...
            log.warning("Native window could not start (%s) - falling back to the browser", exc)
            stop_server(server, thread)
            return False
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(server, thread)
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="timetable-generator",
        description=f"{__app_name__} v{__version__} - clash-free university scheduling.",
    )
    parser.add_argument("--host", default=None, help="Interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: first free port)")
    display = parser.add_mutually_exclusive_group()
    display.add_argument(
        "--window",
        action="store_true",
        help="Open the app in its own native desktop window (default when available)",
    )
    display.add_argument(
        "--browser",
        action="store_true",
        help="Force the browser mode instead of the native window",
    )
    parser.add_argument("--no-browser", action="store_true", help="Start the server only; open nothing")
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

    want_window = args.window or settings.native_window
    headless = args.no_browser or not settings.open_browser

    print(f"  Data folder : {user_data_dir()}")
    print(f"  Database    : {settings.safe_database_url}")
    print(f"  Web address : {url}")
    if app.extensions.get("db_error"):
        print(f"  [!] Database problem: {app.extensions['db_error']}")
    print("\n  The app is running. Close the window (or press Ctrl+C) to stop it.\n")

    if headless:
        # Server only (e.g. scripts, headless machines, CI).
        try:
            serve(app, host, port, debug=settings.debug)
        except KeyboardInterrupt:
            print("\n  Shutting down. Bye!")
        return 0

    if not args.browser and want_window:
        print("  Display     : native desktop window")
        if serve_native(app, host, port, debug=settings.debug):
            print("\n  App window closed. Bye!")
            return 0
        # pywebview is missing or its runtime is broken on this machine.
        print("  Display     : browser (pywebview runtime unavailable)")

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
