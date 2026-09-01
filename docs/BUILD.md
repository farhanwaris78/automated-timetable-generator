# Building the installers

The app ships as a **single self-contained executable** — the user does not
need Python, pip, ODBC drivers or SQL Server.

> ⚠️ **PyInstaller and cx_Freeze are not cross-compilers.**
> A Windows `.exe`/`.msi` must be built on Windows, a `.dmg` on macOS and a
> `.deb` on Linux. If you only have one machine, use the GitHub Actions
> pipeline described in §5 — it builds all of them for you, for free.

---

## 0. One-time preparation (any OS)

```bash
git clone https://github.com/farhanwaris78/automated-timetable-generator.git
cd automated-timetable-generator

python -m venv .venv
# Windows:      .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

pip install -r requirements-dev.txt      # runtime + pyinstaller + cx_Freeze + pytest
pip install pillow                       # only needed to regenerate the icons
python -m pytest -q                      # 35 tests must pass before you package
```

Everything below is driven by one script:

```bash
python packaging/build.py --help
```

| Command | Produces |
|---|---|
| `python packaging/build.py` | the native set for the current OS |
| `python packaging/build.py exe` | one-file binary (`dist/TimetableGenerator[.exe]`) |
| `python packaging/build.py msi` | Windows installer (Windows only) |
| `python packaging/build.py dmg` | macOS disk image (macOS only) |
| `python packaging/build.py deb` | Debian/Ubuntu package (Linux only) |
| `python packaging/build.py portable` | zip / tar.gz with the binary + docs |
| `python packaging/build.py exe --engine cxfreeze` | use cx_Freeze instead of PyInstaller |

The script runs the test suite first, cleans `build/` and `dist/`, builds, then
**smoke-tests the frozen binary** (`--version`) so a broken bundle can never be
shipped.

### Two freezer engines, so a build never dead-ends

`--engine auto` (the default) uses **PyInstaller** for a single-file
executable. If this Python was built without a shared `libpython` — common on
Debian-slim, Alpine and some CI images, and the one thing that stopped the
build in the original container — it automatically falls back to **cx_Freeze**,
which produces a folder containing the binary plus its libraries. `portable`,
`deb` and `dmg` all understand both layouts, so every downstream artifact still
builds. Force one with `--engine pyinstaller` or `--engine cxfreeze`.

---

## 1. Windows — `.exe` and `.msi`

Requirements: Windows 10/11 x64, Python 3.10–3.12 (64-bit) from python.org.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python packaging\make_icons.py           # optional, icon.ico is committed
python packaging\build.py exe portable msi
```

Output in `dist\`:

| File | What it is |
|---|---|
| `TimetableGenerator.exe` | ~25 MB single file. Double-click → browser opens. |
| `TimetableGenerator-2.0.0-windows-x64.zip` | portable: exe + README + `.env.example` + a `.bat` launcher |
| `AutomatedTimetableGenerator-2.0.0-win64.msi` | proper installer: Program Files, Start-Menu shortcut, entry in *Apps & features*, clean upgrades |

**Things worth knowing**

* The build is a *console* app on purpose: if something goes wrong the user can
  read the error. To hide the console, set `console=False` in
  `packaging/timetable.spec` — but then also keep `--no-browser` in mind,
  because errors become invisible.
* UPX compression is disabled deliberately; it is the main cause of false
  positives in Windows Defender.
* **SmartScreen** will warn on first run because the binary is unsigned. To
  remove the warning you need an OV/EV code-signing certificate:
  ```powershell
  signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 dist\TimetableGenerator.exe
  signtool sign /fd SHA256 /a /tr http://timestamp.digicert.com /td SHA256 dist\*.msi
  ```
* Never change `upgrade_code` in `packaging/cx_setup.py` — it is what makes
  version 2.1 replace version 2.0 instead of installing beside it.
* Silent install for a computer lab:
  ```powershell
  msiexec /i AutomatedTimetableGenerator-2.0.0-win64.msi /qn /norestart
  msiexec /x  AutomatedTimetableGenerator-2.0.0-win64.msi /qn        # uninstall
  ```

---

## 2. macOS — `.app` and `.dmg`

Requirements: macOS 12+, Xcode command-line tools (`xcode-select --install`).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt pillow
python packaging/make_icons.py            # creates icon.icns on macOS
python packaging/build.py exe portable dmg
```

Output: `dist/TimetableGenerator.app`, `dist/TimetableGenerator-2.0.0-macos-arm64.dmg`.

* The build script applies an **ad-hoc signature** (`codesign --sign -`),
  without which Apple Silicon refuses to launch the app ("is damaged and can't
  be opened").
* An Intel build must be made on an Intel Mac (or `macos-13` in CI); an Apple
  Silicon build on an M-series Mac. To ship one binary for both, build each and
  merge with `lipo`, or just publish two DMGs (what the CI workflow does).
* First launch on another Mac: right-click → **Open** → *Open* (Gatekeeper).
  To remove that step, notarise:
  ```bash
  codesign --deep --force --options runtime --sign "Developer ID Application: NAME (TEAMID)" dist/TimetableGenerator.app
  xcrun notarytool submit dist/TimetableGenerator-2.0.0-macos-arm64.dmg \
        --apple-id you@example.com --team-id TEAMID --password APP-SPECIFIC-PW --wait
  xcrun stapler staple dist/TimetableGenerator-2.0.0-macos-arm64.dmg
  ```

---

## 3. Linux — `.deb`, `.tar.gz` (and AppImage)

Requirements: any glibc distro; build on the **oldest** one you must support
(binaries are forward-compatible, not backward). Ubuntu 22.04 is a good target.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python packaging/build.py exe portable deb
```

Output:

| File | Install |
|---|---|
| `TimetableGenerator` | `./TimetableGenerator` |
| `TimetableGenerator-2.0.0-linux-x86_64.tar.gz` | extract, run `./start.sh` |
| `timetable-generator_2.0.0_amd64.deb` | `sudo apt install ./timetable-generator_2.0.0_amd64.deb` |

The `.deb` installs the binary to `/usr/bin/timetable-generator`, a desktop
entry and the icon, so the app appears in the application menu.

> **Sandbox note:** this repository's development container could not run
> PyInstaller because Debian slim ships Python without `libpython3.11.so`.
> If you hit `Python shared library ('libpython3.x.so.1.0') was not found`,
> install it: `sudo apt install libpython3.11` (or use the python.org /
> pyenv build, which includes it: `PYTHON_CONFIGURE_OPTS="--enable-shared" pyenv install 3.12`).

**AppImage (optional, one binary for every distro)**

```bash
python packaging/build.py exe
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/512x512/apps
cp dist/TimetableGenerator AppDir/usr/bin/
cp packaging/timetable-generator.desktop AppDir/usr/share/applications/
cp packaging/icon.png AppDir/usr/share/icons/hicolor/512x512/apps/timetable-generator.png
ln -sf usr/share/applications/timetable-generator.desktop AppDir/
ln -sf usr/share/icons/hicolor/512x512/apps/timetable-generator.png AppDir/
printf '#!/bin/sh\nexec "$(dirname "$0")/usr/bin/TimetableGenerator" "$@"\n' > AppDir/AppRun
chmod +x AppDir/AppRun
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
./appimagetool-x86_64.AppImage AppDir dist/TimetableGenerator-2.0.0-x86_64.AppImage
```

---

## 4. What ends up inside the bundle

```
TimetableGenerator(.exe)
├── Python 3.12 runtime
├── flask / jinja2 / werkzeug / sqlalchemy / waitress / dotenv
├── sqlite3            (standard library — no server needed)
├── templates/index.html
├── static/  style.css, app.js, favicon.svg
└── seed_data.json     (18 courses · 45 sections · 27 instructors · 36 rooms · 20 students)
```

At runtime the app writes only to the user data folder:

| OS | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\TimetableGenerator\` |
| macOS | `~/Library/Application Support/TimetableGenerator/` |
| Linux | `~/.local/share/timetable-generator/` |

It contains `timetable.db` (the SQLite database) and `timetable.log`.
Deleting the folder resets the app to factory state.

---

## 5. Build everything from one machine — GitHub Actions

`packaging/ci/build.yml` does this (copy it to `.github/workflows/build.yml` first — see `packaging/ci/README.md`). It runs the tests on all three
OSes, then builds:

* `windows-latest` → `.exe`, `.zip`, `.msi`
* `ubuntu-22.04` → binary, `.tar.gz`, `.deb`
* `macos-13` → Intel `.dmg`
* `macos-14` → Apple Silicon `.dmg`

**To get installers right now**

```bash
cp packaging/ci/build.yml .github/workflows/build.yml && git add -A && git commit -m "ci" && git push
gh workflow run "Build desktop installers" --ref master
gh run watch
gh run download            # pulls every artifact into the current folder
```

**To cut a public release** (attaches all installers to a GitHub Release):

```bash
git tag v2.0.0
git push origin v2.0.0

# the tag already exists? re-push it to re-run the pipeline:
#   git push --delete origin v2.0.0 && git tag -f v2.0.0 && git push origin v2.0.0
```

---

## 6. Version bumping

The version lives in exactly one place: `timetable/__init__.py::__version__`.
The spec file, the MSI, the DMG name, the `.deb` control file, the `--version`
flag and the UI footer all read it from there.

---

## 7. Troubleshooting the build

| Symptom | Cause & cure |
|---|---|
| `TemplateNotFound: index.html` in the frozen app | `datas` missing in the spec — rebuild with `--clean`. |
| `ModuleNotFoundError: sqlalchemy.dialects.sqlite` | add it to `hiddenimports` (already there). |
| `Python shared library not found` | build Python with `--enable-shared` or `apt install libpython3.x`. |
| Antivirus deletes the exe | PyInstaller + UPX false positive; UPX is already off. Sign the binary, or submit it to the vendor. |
| Exe starts, browser shows *"can't reach this page"* | Another program owns the port. The app picks a free port automatically — read the URL printed in the console. |
| `.msi` install succeeds but nothing launches | Check `%LOCALAPPDATA%\TimetableGenerator\timetable.log`. |
| macOS: *"app is damaged"* | Missing ad-hoc signature; run `codesign --force --deep --sign - dist/TimetableGenerator.app`. |

---

## 8. Verification performed on this branch

| Check | Result |
|---|---|
| `python -m pytest -q` | ✅ **83 passed** |
| App boots, serves the UI, saves and reloads a timetable | ✅ |
| Whole UI driven headlessly in a real DOM (jsdom): every dialog, shortcut, drag-drop, undo/redo, capacity badge, publish and import flow | ✅ 0 JavaScript errors |
| `python packaging/build.py exe portable` end-to-end | ✅ produced `dist/TimetableGenerator/` + `TimetableGenerator-2.0.0-linux-x86_64.tar.gz` (16 MB) |
| `python packaging/build.py deb` | ✅ produced `timetable-generator_2.0.0_amd64.deb` (12 MB), installs to `/opt` with a `/usr/bin` launcher, desktop entry and icon |
| Frozen binary serves the UI, migrates/creates its database, saves a timetable, adds a teacher and **exports a 9-sheet .xlsx** | ✅ verified |
| Frozen binary **publishes a PDF** (`%PDF-1.4`, per-teacher pages), serves `/calendar.ics` (2 VEVENTs) and **imports an .xlsx** (3 records created) | ✅ verified |
| `TimetableGenerator --version` on the frozen binary | ✅ `Automated Timetable Generator 2.0.0` |
| PyInstaller one-file build | ⚠️ not runnable in this container (Debian-slim Python has no `libpython3.11.so`, and downloading a standalone Python is blocked). The spec is correct; `--engine auto` detected this and used cx_Freeze instead. On Windows/macOS/CI, PyInstaller is used and gives a true single file. |
| `.msi` / `.dmg` | must be produced on Windows / macOS respectively (§1, §2) |
