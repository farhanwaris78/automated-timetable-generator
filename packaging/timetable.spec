# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build recipe - produces a single-file executable.

Build with:
    pyinstaller packaging/timetable.spec --noconfirm --clean

Outputs:
    dist/TimetableGenerator.exe   (Windows)
    dist/TimetableGenerator       (Linux)
    dist/TimetableGenerator.app   (macOS bundle) + dist/TimetableGenerator
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH is injected by PyInstaller; fall back to CWD when linted standalone.
PROJECT_ROOT = Path(globals().get("SPECPATH", os.getcwd())).resolve().parent
PKG = PROJECT_ROOT / "timetable"

sys.path.insert(0, str(PROJECT_ROOT))
from timetable import __version__  # noqa: E402

APP_NAME = "TimetableGenerator"
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# Everything the app reads at runtime must be shipped next to the code.
datas = [
    (str(PKG / "templates"), "templates"),
    (str(PKG / "static"), "static"),
    (str(PKG / "seed_data.json"), "."),
]

hiddenimports = [
    "waitress",
    "sqlalchemy.dialects.sqlite",
    "sqlite3",
    "dotenv",
]
# SQLAlchemy loads dialects dynamically -> PyInstaller cannot see them.
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")
try:
    import pyodbc  # noqa: F401  (optional MSSQL support)
    hiddenimports += ["pyodbc"] + collect_submodules("sqlalchemy.dialects.mssql")
except ImportError:
    pass

excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "test",
    "numpy", "pandas", "matplotlib", "PIL", "PySide6", "PyQt5", "IPython",
]

icon_file = None
for candidate in (PROJECT_ROOT / "packaging" / "icon.ico", PROJECT_ROOT / "packaging" / "icon.icns"):
    if candidate.exists():
        if (IS_WINDOWS and candidate.suffix == ".ico") or (IS_MAC and candidate.suffix == ".icns"):
            icon_file = str(candidate)

version_file = PROJECT_ROOT / "packaging" / "version_info.txt"

a = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX trips Windows Defender heuristics
    runtime_tmpdir=None,
    console=True,                   # keep the log window: users can see errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
    version=str(version_file) if (IS_WINDOWS and version_file.exists()) else None,
)

if IS_MAC:
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        icon=icon_file,
        bundle_identifier="edu.timetable.generator",
        version=__version__,
        info_plist={
            "CFBundleName": "Timetable Generator",
            "CFBundleDisplayName": "Automated Timetable Generator",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
            "LSMinimumSystemVersion": "11.0",
        },
    )
