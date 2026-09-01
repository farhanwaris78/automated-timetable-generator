"""cx_Freeze recipe - builds the Windows MSI installer (and Linux DEB/RPM).

Usage (from the project root, on Windows):
    python packaging/cx_setup.py bdist_msi

Produces ``dist/AutomatedTimetableGenerator-<version>-win64.msi`` which:
  * installs into "Program Files\\Automated Timetable Generator",
  * creates a Start-Menu shortcut and an optional desktop shortcut,
  * registers a proper uninstall entry in "Apps & features",
  * upgrades cleanly in place (fixed UpgradeCode).

On Linux the same file can build a DEB/RPM via `bdist_rpm`; on macOS use
`bdist_dmg`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cx_Freeze import Executable, setup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from timetable import __version__  # noqa: E402

PKG = PROJECT_ROOT / "timetable"
IS_WINDOWS = sys.platform.startswith("win")

build_exe_options = {
    "packages": ["timetable", "flask", "jinja2", "sqlalchemy", "waitress", "sqlite3", "dotenv"],
    "includes": ["sqlalchemy.dialects.sqlite"],
    "excludes": ["tkinter", "unittest", "test", "pydoc", "numpy", "pandas", "matplotlib", "PIL"],
    "include_files": [
        (str(PKG / "templates"), "templates"),
        (str(PKG / "static"), "static"),
        (str(PKG / "seed_data.json"), "seed_data.json"),
        (str(PROJECT_ROOT / "README.md"), "README.md"),
        (str(PROJECT_ROOT / "docs" / "USER_GUIDE.md"), "USER_GUIDE.md"),
    ],
    "include_msvcr": True,
    "optimize": 1,
}

# A stable GUID: never change it, otherwise upgrades turn into side-by-side
# installs.  Generated once for this product.
bdist_msi_options = {
    "upgrade_code": "{6C2F1E4A-6A7D-4C0B-9C4A-3F1B2D5E7A91}",
    "add_to_path": False,
    "initial_target_dir": r"[ProgramFiles64Folder]\Automated Timetable Generator",
    "all_users": True,
    "summary_data": {
        "author": "Automated Timetable Generator contributors",
        "comments": "Clash-free university timetable scheduling",
        "keywords": "timetable scheduling university",
    },
    "install_icon": str(PROJECT_ROOT / "packaging" / "icon.ico")
    if (PROJECT_ROOT / "packaging" / "icon.ico").exists()
    else None,
}

icon = PROJECT_ROOT / "packaging" / ("icon.ico" if IS_WINDOWS else "icon.png")

executables = [
    Executable(
        script=str(PROJECT_ROOT / "launcher.py"),
        target_name="TimetableGenerator.exe" if IS_WINDOWS else "timetable-generator",
        base="Console",                     # console build => errors stay visible
        icon=str(icon) if icon.exists() else None,
        shortcut_name="Automated Timetable Generator",
        shortcut_dir="ProgramMenuFolder",
        copyright="MIT licensed",
    )
]

setup(
    name="AutomatedTimetableGenerator",
    version=__version__,
    description="Automated Timetable Generator - clash-free university scheduling",
    long_description="A zero-configuration desktop app that builds clash-free university timetables.",
    author="Automated Timetable Generator contributors",
    options={"build_exe": build_exe_options, "bdist_msi": bdist_msi_options},
    executables=executables,
)
