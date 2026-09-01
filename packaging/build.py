#!/usr/bin/env python3
"""One-command installer builder for every desktop platform.

    python packaging/build.py            # native package(s) for this OS
    python packaging/build.py exe        # PyInstaller single-file binary
    python packaging/build.py msi        # Windows .msi (cx_Freeze)
    python packaging/build.py portable   # zip/tar.gz with the binary + docs
    python packaging/build.py dmg        # macOS .dmg
    python packaging/build.py deb        # Linux .deb (needs dpkg-deb)
    python packaging/build.py all        # everything this OS can produce

Artifacts land in  dist/  and are listed at the end of the run.

IMPORTANT: PyInstaller and cx_Freeze are **not** cross-compilers.  Build the
Windows artifacts on Windows, the macOS ones on macOS and the Linux ones on
Linux - or just push a tag and let .github/workflows/build.yml do all three.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

sys.path.insert(0, str(ROOT))
from timetable import __version__  # noqa: E402

APP_NAME = "TimetableGenerator"
PRETTY_NAME = "Automated Timetable Generator"

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def say(message: str) -> None:
    print(f"\n\033[1;36m==>\033[0m {message}", flush=True)


def run(cmd: list[str], **kwargs) -> None:
    print("   $", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=kwargs.pop("cwd", ROOT), **kwargs)


def ensure(module: str, pip_name: str | None = None) -> None:
    try:
        __import__(module)
    except ImportError:
        say(f"Installing build dependency: {pip_name or module}")
        run([sys.executable, "-m", "pip", "install", pip_name or module])


def clean() -> None:
    say("Cleaning previous build output")
    for path in (BUILD, DIST, ROOT / f"{APP_NAME}.spec"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    DIST.mkdir(parents=True, exist_ok=True)


def binary_path() -> Path:
    candidates = [DIST / f"{APP_NAME}{EXE_SUFFIX}", DIST / APP_NAME]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Run `python packaging/build.py exe` first.")


def write_version_info() -> None:
    """Windows file-properties resource so the .exe is not 'unknown publisher'."""
    parts = (__version__.split(".") + ["0", "0", "0"])[:4]
    quad = ", ".join(parts)
    (PACKAGING / "version_info.txt").write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad}), prodvers=({quad}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', '{PRETTY_NAME} contributors'),
        StringStruct('FileDescription', '{PRETTY_NAME}'),
        StringStruct('FileVersion', '{__version__}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('LegalCopyright', 'MIT licensed'),
        StringStruct('OriginalFilename', '{APP_NAME}{EXE_SUFFIX}'),
        StringStruct('ProductName', '{PRETTY_NAME}'),
        StringStruct('ProductVersion', '{__version__}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# targets
# --------------------------------------------------------------------------- #
def build_exe() -> Path:
    """Single-file executable via PyInstaller (all platforms)."""
    ensure("PyInstaller", "pyinstaller")
    write_version_info()
    say(f"Building the {platform.system()} executable with PyInstaller")
    run([sys.executable, "-m", "PyInstaller", str(PACKAGING / "timetable.spec"), "--noconfirm", "--clean"])
    binary = binary_path()
    if not IS_WINDOWS:
        binary.chmod(0o755)
    say(f"Executable ready: {binary}  ({binary.stat().st_size / 1_048_576:.1f} MB)")
    return binary


def smoke_test(binary: Path) -> None:
    """Prove the frozen binary actually starts before shipping it."""
    say("Smoke-testing the frozen binary")
    env = {**os.environ, "TTG_OPEN_BROWSER": "0"}
    out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, env=env, timeout=180)
    print((out.stdout or out.stderr).strip())
    if out.returncode != 0:
        raise SystemExit("The frozen binary failed to start - aborting.")


def build_msi() -> Path:
    """Windows installer (.msi) via cx_Freeze."""
    if not IS_WINDOWS:
        raise SystemExit("An .msi can only be produced on Windows.")
    ensure("cx_Freeze", "cx_Freeze")
    say("Building the Windows MSI installer")
    run([sys.executable, str(PACKAGING / "cx_setup.py"), "bdist_msi", "--dist-dir", str(DIST)])
    msi = sorted(DIST.glob("*.msi"))[-1]
    target = DIST / f"{PRETTY_NAME.replace(' ', '')}-{__version__}-win64.msi"
    if msi != target:
        shutil.move(str(msi), target)
    say(f"MSI ready: {target}")
    return target


def build_portable() -> Path:
    """A no-install archive: binary + README + sample .env."""
    binary = binary_path()
    say("Building the portable archive")
    staging = BUILD / f"{APP_NAME}-{__version__}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    shutil.copy2(binary, staging / binary.name)
    for extra in ("README.md", "LICENSE", "docs/USER_GUIDE.md", ".env.example"):
        source = ROOT / extra
        if source.exists():
            shutil.copy2(source, staging / Path(extra).name)

    if IS_WINDOWS:
        (staging / "Start Timetable Generator.bat").write_text(
            f'@echo off\r\nstart "" "%~dp0{binary.name}"\r\n', encoding="utf-8"
        )
        archive = DIST / f"{APP_NAME}-{__version__}-windows-x64.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in staging.rglob("*"):
                zf.write(item, item.relative_to(staging.parent))
    else:
        (staging / "start.sh").write_text(
            f'#!/bin/sh\ncd "$(dirname "$0")"\nexec ./{binary.name} "$@"\n', encoding="utf-8"
        )
        (staging / "start.sh").chmod(0o755)
        suffix = "macos" if IS_MAC else "linux"
        archive = DIST / f"{APP_NAME}-{__version__}-{suffix}-{platform.machine()}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(staging, arcname=staging.name)
    say(f"Portable archive ready: {archive}")
    return archive


def build_deb() -> Path:
    """Linux .deb built by hand (only dpkg-deb required)."""
    if not IS_LINUX:
        raise SystemExit("A .deb can only be produced on Linux.")
    if shutil.which("dpkg-deb") is None:
        raise SystemExit("dpkg-deb not found - install the 'dpkg' package.")
    binary = binary_path()
    say("Building the Debian package")

    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    stage = BUILD / "deb"
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "DEBIAN").mkdir(parents=True)
    (stage / "usr/bin").mkdir(parents=True)
    (stage / "usr/share/applications").mkdir(parents=True)
    (stage / "usr/share/icons/hicolor/512x512/apps").mkdir(parents=True)
    (stage / "usr/share/doc/timetable-generator").mkdir(parents=True)

    shutil.copy2(binary, stage / "usr/bin/timetable-generator")
    (stage / "usr/bin/timetable-generator").chmod(0o755)
    if (PACKAGING / "icon.png").exists():
        shutil.copy2(PACKAGING / "icon.png", stage / "usr/share/icons/hicolor/512x512/apps/timetable-generator.png")
    shutil.copy2(ROOT / "README.md", stage / "usr/share/doc/timetable-generator/README.md")
    shutil.copy2(PACKAGING / "timetable-generator.desktop", stage / "usr/share/applications/timetable-generator.desktop")

    size_kb = max(1, sum(f.stat().st_size for f in stage.rglob("*") if f.is_file()) // 1024)
    (stage / "DEBIAN/control").write_text(
        f"""Package: timetable-generator
Version: {__version__}
Section: education
Priority: optional
Architecture: {arch}
Installed-Size: {size_kb}
Maintainer: {PRETTY_NAME} contributors <noreply@example.com>
Description: {PRETTY_NAME}
 Clash-free university timetable scheduling with drag & drop,
 automatic room/instructor/student conflict detection and PDF export.
 Ships with an embedded database - no server setup required.
""",
        encoding="utf-8",
    )
    package = DIST / f"timetable-generator_{__version__}_{arch}.deb"
    run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(package)])
    say(f"Debian package ready: {package}")
    return package


def build_dmg() -> Path:
    """macOS disk image containing the .app bundle."""
    if not IS_MAC:
        raise SystemExit("A .dmg can only be produced on macOS.")
    say("Building the macOS disk image")
    bundle = DIST / f"{APP_NAME}.app"
    if not bundle.exists():
        raise FileNotFoundError("Run `python packaging/build.py exe` first (it creates the .app).")

    # Ad-hoc signature: prevents the "damaged app" Gatekeeper error on arm64.
    run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)])

    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(bundle, staging / bundle.name, symlinks=True)
    os.symlink("/Applications", staging / "Applications")

    image = DIST / f"{APP_NAME}-{__version__}-macos-{platform.machine()}.dmg"
    if image.exists():
        image.unlink()
    run(["hdiutil", "create", "-volname", PRETTY_NAME, "-srcfolder", str(staging),
         "-ov", "-format", "UDZO", str(image)])
    say(f"Disk image ready: {image}")
    return image


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
TARGETS = {
    "exe": build_exe,
    "msi": build_msi,
    "portable": build_portable,
    "deb": build_deb,
    "dmg": build_dmg,
}


def native_targets() -> list[str]:
    if IS_WINDOWS:
        return ["exe", "portable", "msi"]
    if IS_MAC:
        return ["exe", "portable", "dmg"]
    return ["exe", "portable", "deb"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("targets", nargs="*", default=None,
                        help="exe | msi | portable | deb | dmg | all (default: native set)")
    parser.add_argument("--no-clean", action="store_true", help="keep previous build output")
    parser.add_argument("--no-test", action="store_true", help="skip the unit tests and the binary smoke test")
    args = parser.parse_args(argv)

    chosen = args.targets or native_targets()
    if "all" in chosen:
        chosen = native_targets()

    if not args.no_test:
        try:
            __import__("pytest")
        except ImportError:
            print("   (pytest not installed - skipping the test suite)")
        else:
            say("Running the test suite")
            run([sys.executable, "-m", "pytest", "-q"])

    if not args.no_clean:
        clean()

    built: list[Path] = []
    for target in chosen:
        if target not in TARGETS:
            raise SystemExit(f"Unknown target {target!r}. Valid: {', '.join(TARGETS)}")
        artifact = TARGETS[target]()
        if target == "exe" and not args.no_test:
            smoke_test(artifact)
        built.append(artifact)

    say("Build complete. Artifacts:")
    for artifact in built:
        size = artifact.stat().st_size / 1_048_576 if artifact.is_file() else 0
        print(f"   {artifact}  ({size:.1f} MB)" if size else f"   {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
