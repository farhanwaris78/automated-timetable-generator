#!/usr/bin/env python3
"""Frozen-application entry point (PyInstaller / cx_Freeze).

Kept deliberately tiny: it only fixes up multiprocessing on Windows and then
hands control to :func:`timetable.desktop.main`.  Any crash before the logger
exists is shown in a native error dialog (windowed builds) or printed on the
console (console builds) so the user always sees what happened.
"""

from __future__ import annotations

import multiprocessing
import sys


def _show_error(title: str, message: str) -> None:
    """Show a startup error the user can actually read.

    Windowed Windows builds have no console, so we use the native message
    box; everywhere else we print to stderr.
    """
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)  # MB_ICONERROR
            return
        except Exception:  # pragma: no cover - defensive
            pass
    print(f"\n[FATAL] {title}\n{message}\n", file=sys.stderr)


def _hold_console(code: int) -> None:
    """Stop a double-clicked console Windows .exe from vanishing on error."""
    if code != 0 and sys.platform.startswith("win") and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except Exception:
            pass


def main() -> int:
    multiprocessing.freeze_support()
    try:
        from timetable.desktop import main as run

        return run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # pragma: no cover - last-resort guard
        import traceback

        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        _show_error(
            "Automated Timetable Generator could not start",
            f"{exc}\n\n"
            "This is usually caused by a damaged installation or a missing "
            "system component. Reinstall the app, or check the log file in "
            "your data folder for details.",
        )
        print(f"\n[FATAL] {detail}\n", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    _hold_console(exit_code)
    raise SystemExit(exit_code)
