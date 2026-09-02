"""Desktop launcher.

``python -m timetable`` (or the frozen .exe / .app / Linux binary) opens the
app as a **standalone desktop program**.  In the default native-window mode the
UI is a single self-contained HTML document and every data call is bridged
straight into the running Python process - no backend (waitress/Werkzeug)
server, no port, no browser tab are involved.

Two display modes:

* **native window** (default) - rendered inside its own desktop window through
  pywebview (WebView2 on Windows, WKWebView on macOS, WebKitGTK on Linux).
  It behaves like any other installed application and needs no server.
* **browser** - the classic mode: a console prints the address and the
  default browser opens it.  Used as an automatic fallback on systems where
  pywebview's webview runtime is missing, with ``--browser``, or for headless /
  server-only use (``--no-browser``).

This module is the entry point that gets frozen into the .exe / .app /
Linux binary.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from . import __app_name__, __version__
from .config import bundle_dir, load_settings, user_data_dir

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


# --------------------------------------------------------------------------- #
# Serverless (no-HTTP) desktop mode
# --------------------------------------------------------------------------- #
# The desktop window is the whole point: the user asked for a standalone
# program that does NOT spin up a Flask/waitress backend and route every call
# through a local socket.  We therefore deliver the UI as one self-contained
# HTML page and bridge every API call straight into the running Python process
# through pywebview's JS<->Python API.  There is no port to find, no waitress
# worker, and no browser tab - it really is software, not a server.
# --------------------------------------------------------------------------- #

# A tiny transport that, inside the packaged window, routes every same-app
# ``fetch`` through ``window.pywebview.api`` instead of the network.
_NATIVE_FETCH_SHIM = r"""
/* Native (no HTTP server) transport: when the app is shown in its own
   pywebview window, every same-app fetch() is routed in-process through
   window.pywebview.api so nothing talks to a Flask / waitress server. */
(function () {
  "use strict";
  if (!window.__NATIVE__) return;

  var pending = [];
  var bridge = null;
  var originalFetch = window.fetch;

  function ready() {
    return !!(window.pywebview && window.pywebview.api && window.pywebview.api.request);
  }
  function start() {
    if (bridge || !ready()) return false;
    bridge = window.pywebview.api;
    var q = pending.splice(0, pending.length);
    q.forEach(function (fn) { try { fn(); } catch (e) {} });
    return true;
  }
  function fileToBase64(file) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result).split(",")[1] || ""); };
      r.onerror = function () { reject(r.error || new Error("Could not read the file.")); };
      r.readAsDataURL(file);
    });
  }
  function firstFile(form) {
    var file = null;
    try {
      form.forEach(function (value, key) { if (!file && value instanceof File) file = value; });
    } catch (e) {}
    return file;
  }
  function fromBridge(result) {
    if (result && result.error) throw new Error(result.error);
    return result || {};
  }
  function makeResponse(result, raw) {
    var status = (result && typeof result.status === "number") ? result.status : 200;
    var headers = new Headers((result && result.headers) || {});
    if (raw) {
      var b64 = (result && result.base64) || "";
      var bin = atob(b64);
      var bytes = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      var blob = new Blob([bytes], { type: headers.get("Content-Type") || "application/octet-stream" });
      return new Response(blob, { status: status, headers: headers });
    }
    return new Response((result && result.text) || "", { status: status, headers: headers });
  }
  function route(url, init) {
    var method = (init && init.method) || "GET";
    var target = new URL(url, "http://ttg.local");
    var body = init && init.body;

    if (typeof FormData !== "undefined" && body instanceof FormData) {
      var file = firstFile(body);
      if (file) {
        return fileToBase64(file).then(function (b64) {
          return bridge.import_xlsx(file.name, b64).then(function (result) {
            return makeResponse(fromBridge(result), false);
          });
        });
      }
      body = null;
    }

    var payload = {
      method: method,
      path: target.pathname,
      query: target.search.replace(/^\?/, ""),
      raw: !!((init && init.headers) && String(init.headers.Accept || "") === "*/*")
    };
    if (body) payload.body = body;
    return bridge.request(payload).then(function (result) {
      return makeResponse(fromBridge(result), payload.raw);
    });
  }

  window.fetch = function (url, init) {
    var s = String(url);
    var isAppCall = s.indexOf("/") === 0 || s.indexOf("http://ttg.local") === 0;
    if (!isAppCall) return originalFetch.apply(window, arguments);
    if (!bridge) {
      return new Promise(function (resolve, reject) {
        var go = function () { try { route(url, init).then(resolve, reject); } catch (e) { reject(e); } };
        if (start()) go(); else pending.push(go);
      });
    }
    try { return route(url, init); } catch (err) { return Promise.reject(err); }
  };
})();
"""


class _NativeBridge:
    """The in-process bridge that stands in for the Flask HTTP server.

    Every JS ``fetch('/api/...')`` becomes a call to :meth:`request`, which
    runs the very same Flask WSGI app through its test client - so every
    endpoint, export, clash check and persistence rule is identical, without
    a socket or a separate server process.  Uploads (Excel import) go through
    :meth:`import_xlsx`.
    """

    def __init__(self, app) -> None:
        self._app = app

    def request(self, payload):
        method = str(payload.get("method") or "GET").upper()
        path = str(payload.get("path") or "/")
        query = payload.get("query") or ""
        body = payload.get("body")
        raw = bool(payload.get("raw"))
        try:
            client = self._app.test_client()
            kwargs = {"query_string": query}
            if body:
                if isinstance(body, str):
                    try:
                        kwargs["json"] = json.loads(body)
                    except (ValueError, TypeError):
                        kwargs["data"] = body
                else:
                    kwargs["json"] = body
            response = client.open(path, method=method, **kwargs)
            data = response.get_data()
            content_type = response.content_type or "application/json"
            if raw or "json" not in content_type:
                return {
                    "status": response.status_code,
                    "headers": {"Content-Type": content_type},
                    "base64": base64.b64encode(data).decode("ascii"),
                    "text": data.decode("utf-8", "replace"),
                }
            return {
                "status": response.status_code,
                "headers": {"Content-Type": content_type},
                "text": data.decode("utf-8", "replace"),
            }
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Native bridge request failed: %s", exc)
            return {
                "status": 500,
                "headers": {"Content-Type": "application/json"},
                "text": json.dumps({"error": "internal_error", "message": str(exc)}),
            }

    def import_xlsx(self, name, data_base64):
        """Import an .xlsx the user picked in the desktop window.

        Returns the same ``{status, headers, text}`` envelope as :meth:`request`
        so the JS transport can build a real Response (the frontend parses the
        body as JSON, exactly as it does over HTTP).
        """
        try:
            data = base64.b64decode(data_base64)
            from .importers import import_workbook

            catalog = self._app.extensions.get("catalog")
            if catalog is None:
                return self._json(503, {"error": "database_unavailable", "message": "Database is not configured"})
            report = import_workbook(catalog, data)
            return self._json(200, report)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Native import failed: %s", exc)
            return self._json(500, {"error": "internal_error", "message": str(exc)})

    @staticmethod
    def _json(status: int, payload) -> dict:
        return {
            "status": int(status),
            "headers": {"Content-Type": "application/json"},
            "text": json.dumps(payload),
        }


def _inline_stylesheet(href: str, static_dir: Path) -> str:
    path = static_dir / Path(href).name
    if path.is_file():
        return "<style>\n" + path.read_text(encoding="utf-8") + "\n</style>"
    return f'<link rel="stylesheet" href="{href}">'


def _inline_script(src: str, static_dir: Path) -> str:
    path = static_dir / Path(src).name
    if path.is_file():
        content = path.read_text(encoding="utf-8")
        return (
            "<script>\n"
            "window.__NATIVE__ = true;\n"
            + _NATIVE_FETCH_SHIM
            + "\n"
            + content
            + "\n</script>"
        )
    return f'<script defer src="{src}"></script>'


def _build_standalone_html(app) -> str:
    """Render the UI as one self-contained HTML document.

    The Jinja template is rendered and every CSS/JS asset is inlined, and the
    fetch shim above is injected ahead of the controller so the window never
    needs an HTTP server to reach itself.
    """
    from flask import render_template

    from .services import WEEKDAYS

    with app.test_request_context("/"):
        html = render_template(
            "index.html",
            app_version=__version__,
            db_error=app.extensions.get("db_error"),
            weekdays=WEEKDAYS,
        )

    static_dir = bundle_dir() / "static"
    html = re.sub(
        r'<link\s+rel=["\']stylesheet["\']\s+href=["\']([^"\']+)["\']\s*/?>',
        lambda m: _inline_stylesheet(m.group(1), static_dir),
        html,
    )
    html = re.sub(
        r'<script\s+defer\s+src=["\']([^"\']+)["\']>\s*</script>',
        lambda m: _inline_script(m.group(1), static_dir),
        html,
    )
    return html


def serve_native(app, *, debug: bool = False) -> bool:
    """Open the app in its own native desktop window WITHOUT an HTTP server.

    Returns True when the window was shown (and closed by the user).
    Returns False when pywebview or the platform webview runtime is not
    available - the caller then falls back to opening the browser.

    Unlike the old mode this never starts waitress/Werkzeug: the UI is a
    self-contained document and all data goes through :class:`_NativeBridge`.
    """
    try:
        import webview  # type: ignore
    except Exception:  # pragma: no cover - optional runtime dependency
        log.info("pywebview is not installed - falling back to the browser")
        return False

    try:
        bridge = _NativeBridge(app)
        html = _build_standalone_html(app)
        webview.create_window(
            __app_name__,
            html=html,
            js_api=bridge,
            width=1280,
            height=860,
            min_size=(980, 640),
            text_select=True,
        )
        webview.start(debug=debug)
    except Exception as exc:  # missing GTK/Qt runtime, headless shell, ...
        log.warning("Native window could not start (%s) - falling back to the browser", exc)
        return False
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
    want_window = args.window or settings.native_window
    headless = args.no_browser or not settings.open_browser

    print(f"  Data folder : {user_data_dir()}")
    print(f"  Database    : {settings.safe_database_url}")
    if app.extensions.get("db_error"):
        print(f"  [!] Database problem: {app.extensions['db_error']}")
    print("\n  The app is running. Close the window (or press Ctrl+C) to stop it.\n")

    # The default native window is fully self-contained: no backend server,
    # no port, no browser tab - it is a desktop program, not a web service.
    if not headless and not args.browser and want_window:
        print("  Display     : native desktop window (no backend server)")
        if serve_native(app, debug=settings.debug):
            print("\n  App window closed. Bye!")
            return 0
        # pywebview is missing or its runtime is broken on this machine.
        print("  Display     : browser (pywebview runtime unavailable)")

    # --- only the server-backed modes (browser / headless) get a port ------ #
    def _local_url() -> str:
        return f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"

    port = find_free_port(host, port)
    url = _local_url()

    print(f"  Web address : {url}")

    if headless:
        # Server only (e.g. scripts, headless machines, CI).
        try:
            serve(app, host, port, debug=settings.debug)
        except KeyboardInterrupt:
            print("\n  Shutting down. Bye!")
        return 0

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
