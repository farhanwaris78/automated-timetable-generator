#!/usr/bin/env python3
"""Frozen-application entry point (PyInstaller / cx_Freeze).

Kept deliberately tiny: it only fixes up multiprocessing on Windows and then
hands control to :func:`timetable.desktop.main`.  Any crash before the logger
exists is printed and the console is held open so the user can read it.
"""

from __future__ import annotations

import multiprocessing
import sys


def _hold_console(code: int) -> None:
    """Stop a double-clicked Windows .exe from vanishing on error."""
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

        print("\n[FATAL] The application could not start:\n", file=sys.stderr)
        traceback.print_exc()
        print(f"\n{exc}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    exit_code = main()
    _hold_console(exit_code)
    raise SystemExit(exit_code)
