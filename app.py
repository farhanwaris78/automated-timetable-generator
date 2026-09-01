"""Backwards-compatible shim.

The original single-file ``app.py`` has been refactored into the
``timetable`` package (see BUGS_AND_FIXES.md).  This module is kept so that
existing commands such as ``python app.py`` and WSGI configs pointing at
``app:app`` keep working.
"""

from timetable.config import load_settings
from timetable.desktop import main
from timetable.web import create_app

settings = load_settings()
app = create_app(settings)          # WSGI entry point: `app:app`

if __name__ == "__main__":
    raise SystemExit(main())
