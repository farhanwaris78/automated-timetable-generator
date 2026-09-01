<div align="center">

<img src="packaging/icon.png" width="96" alt="">

# Automated Timetable Generator

**Clash-free university scheduling — one download, no setup.**

Add your teachers, rooms and courses inside the app, drag sections onto a
room × time grid, and let it block every room, instructor, student and capacity
conflict *as you place classes*. Then publish the result as Excel, PDF or a live
calendar feed.

[Download](#-download) · [User guide](docs/USER_GUIDE.md) · [Build it yourself](docs/BUILD.md) · [Changelog](CHANGELOG.md) · [What was fixed](docs/BUGS_AND_FIXES.md)

</div>

---

## ⬇ Download

Grab the file for your machine from the [Releases page](../../releases) — no
Python, no SQL Server, no ODBC driver, no internet connection required.

| Platform | File | How to install |
|---|---|---|
| **Windows 10/11** | `AutomatedTimetableGenerator-*-win64.msi` | Double-click → Start-menu shortcut |
| Windows (portable) | `TimetableGenerator-*-windows-x64.zip` | Unzip, run `TimetableGenerator.exe` — no admin rights |
| **macOS** (Apple Silicon) | `TimetableGenerator-*-macos-arm64.dmg` | Drag to Applications |
| macOS (Intel) | `TimetableGenerator-*-macos-x86_64.dmg` | Drag to Applications |
| **Ubuntu / Debian** | `timetable-generator_*_amd64.deb` | `sudo apt install ./timetable-generator_*_amd64.deb` |
| Any Linux | `TimetableGenerator-*-linux-x86_64.tar.gz` | `tar -xzf …` then `./start.sh` |

Launch it → a small console window prints the address → your browser opens on
the app. That is the whole installation. Everything (database, logs, settings)
lives in one per-user folder; uninstalling leaves nothing behind.

> **First run:** the app creates its own SQLite database and seeds a realistic
> sample university so you can try every feature immediately. Press
> <kbd>F1</kbd> for the shortcut list, or **Manage data → …** to replace the
> sample with your own.

---

## ✨ Features

### Your data, managed in the app
No SQL, no seed files. Every entity has a dialog, a keyboard shortcut and a row
in the searchable **Manage data** screen (<kbd>Alt+M</kbd>).

| Entity | Shortcut | What you can set |
|---|---|---|
| Teacher | <kbd>Alt+T</kbd> | name, email, department, morning/evening/both |
| Classroom | <kbd>Alt+R</kbd> | number, building, capacity, type (Classroom / Lab / Hall) |
| Course | <kbd>Alt+C</kbd> | **course code**, title, department, credit hours, **semester**, **lab + lab credit hours**, colour, sections |
| Building | <kbd>Alt+B</kbd> | name (rooms are grouped and filtered by it) |
| Section | <kbd>Alt+S</kbd> | section letter + the teacher who takes it |
| Manage all | <kbd>Alt+M</kbd> | tabbed, searchable, inline edit & delete |

Deletes are referentially safe: the app refuses to remove a teacher who still
teaches, a room or course used by the saved timetable, or a building that still
holds rooms — and tells you exactly what is blocking it.

### Bulk import from Excel  <kbd>Ctrl+I</kbd>
Download a template with one sheet each for Teachers, Buildings, Rooms, Courses
and Sections, fill it in any spreadsheet app, and import it. Records are matched
by name / code and **updated rather than duplicated**, so the same file can be
re-imported safely. Invalid rows are reported with their sheet and row number
instead of aborting the import.

### Labs & semesters
Tick **“This course has a lab”** in the course editor and give it its own lab
credit hours. Every section then shows **two cards** in the sidebar — the
lecture and a `LAB` card — so they are scheduled independently, and a placed
block can be flipped between Theory and Lab from its details dialog.

Give each course a **semester** and the app treats a *semester + section* as one
student batch: two of its classes can never share a slot. A semester picker in
the toolbar narrows the sidebar and dims the rest of the grid, auto-fill can
target a single semester, and both the Excel and PDF exports can be produced
**semester by semester**.

### Scheduling
* **Morning & evening shifts** with independent hours, sharing rooms and staff.
* **Full 1–7 day week**, one tab per day (<kbd>1</kbd>…<kbd>7</kbd>).
* **Drag & drop** onto a room × time grid; drag back to the list to unschedule.
* **Auto-fill** (<kbd>Ctrl+Shift+A</kbd>) places every remaining class in a
  conflict-free slot — 65/65 sample classes (45 lectures + 20 labs) in
  milliseconds — labs preferring `Lab` rooms, optionally one semester at a time.
* **“*n* not scheduled”** pill: a live report, grouped by semester, of every
  lecture and lab that still needs a slot.
* **Undo / redo**, 100 steps, covering every action
  (<kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd>).

### Clash detection — server-side, on every drop
* 🔴 **room** double-booking (any overlap, not just identical slots)
* 🔴 **instructor** teaching two sections at once
* 🔴 **student** collisions — the affected **roll numbers are listed**
* 🔴 duplicate placement of the same course-section — including its lecture
  against its own lab
* 🔴 **semester clash** — two classes of the same semester *and* section at once
* 🔴 a lab placed on a course that has no lab
* 🟠 a **lab outside a `Lab` room** — a warning, never a blocker
* 🟠 **room too small** — an amber `⚠ 58/40` badge on the class, a counter in the
  toolbar, and a click-through report that suggests rooms which would fit.
  Capacity is a *warning*: it never blocks you from saving.

### Publish & share  <kbd>Ctrl+Shift+P</kbd>
* **Excel** (<kbd>Ctrl+E</kbd>) — one colour-coded worksheet per day, **one
  worksheet per semester** (day × section), plus `Summary` (auto-filtered),
  `By Teacher` and an `Unscheduled` sheet when something is missing; landscape
  and fit-to-width.
* **PDF** — master grid (one page per day), or **one page per teacher**, per
  course section, **per semester**, or per room. Rendered by the app itself: vector text, real
  page boxes, no browser print dialog and no third-party PDF library.
* **iCalendar** — download a `.ics` file, or copy the live
  `http://localhost:PORT/calendar.ics?teacher=…` subscription link into Google
  Calendar, Outlook or Apple Calendar and the timetable keeps itself up to date.
* **CSV** and a print stylesheet as well.

### Everything else
* **Discoverable shortcuts** — <kbd>F1</kbd> lists all 29, generated from the
  same registry that handles the keys, so the docs cannot drift from the code.
  Every button's tooltip shows its shortcut too.
* **Zero configuration** — embedded SQLite, created and migrated automatically.
* Optionally point it at SQL Server, PostgreSQL or MySQL with a one-line `.env`.
* Offline by design: no CDN, no telemetry, no network calls at all.

---

## 🚀 Run from source

```bash
git clone https://github.com/farhanwaris78/automated-timetable-generator.git
cd automated-timetable-generator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run.py                      # opens http://127.0.0.1:<free-port>/
```

Useful flags: `--port 5000`, `--no-browser`, `--debug`, `--reset-database`,
`--database-url …`, `--data-dir …`.

```bash
pip install pytest
python -m pytest -q                # 83 tests
```

---

## 📦 Build the installers

```bash
pip install -r requirements-dev.txt
python packaging/build.py                      # native package(s) for this OS
python packaging/build.py exe portable         # individual targets
python packaging/build.py all --engine cxfreeze
```

Targets: `exe` · `msi` (Windows) · `dmg` (macOS) · `deb` · `portable` · `all`.
The builder drives **PyInstaller or cx_Freeze** and falls back automatically
when the interpreter has no shared `libpython`. Full instructions, code-signing
notes and the GitHub Actions pipeline that builds all three operating systems
together: **[docs/BUILD.md](docs/BUILD.md)**.

---

## 🏗 Architecture

```
launcher.py                 frozen-app entry point (PyInstaller / cx_Freeze)
run.py / app.py             developer + WSGI entry points
timetable/
├── config.py               env/.env handling, per-OS data dir, DB URL resolution
├── db.py                   SQLAlchemy schema, engine, migrations, first-run seeding
├── services.py             domain logic, clash-detection engine, auto-fill
├── catalog.py              CRUD for teachers, buildings, rooms, courses, sections
├── exporters.py            Excel workbook builder (one worksheet per day)
├── importers.py            Excel template + bulk import with per-row reporting
├── publishing.py           dependency-free PDF writer + iCalendar feed builder
├── web.py                  Flask app factory and JSON API
├── desktop.py              port picking, waitress server, browser launch
├── seed_data.json          sample dataset
├── templates/index.html
└── static/                 style.css · app.js · favicon.svg
packaging/                  build.py · timetable.spec · cx_setup.py · ci/ · icons
tests/test_app.py           83 tests
docs/                       USER_GUIDE · BUILD · SCHEMA · BUGS_AND_FIXES
```

**Stack:** Python 3.10+ · Flask 3 · SQLAlchemy 2 · waitress · SQLite · openpyxl ·
vanilla ES2017 front-end. No jQuery, no CDN, no runtime JS dependencies.

### Keyboard shortcuts

Press <kbd>F1</kbd> in the app for the authoritative list.

| Group | Keys |
|---|---|
| Add data | <kbd>Alt+T</kbd> teacher · <kbd>Alt+R</kbd> room · <kbd>Alt+C</kbd> course · <kbd>Alt+B</kbd> building · <kbd>Alt+S</kbd> section · <kbd>Alt+M</kbd> manage · <kbd>Ctrl+I</kbd> import |
| Edit | <kbd>Ctrl+Z</kbd> undo · <kbd>Ctrl+Y</kbd> redo · <kbd>Delete</kbd> remove selected · <kbd>Ctrl+Backspace</kbd> clear grid |
| Timetable | <kbd>Ctrl+G</kbd> generate · <kbd>Ctrl+S</kbd> save · <kbd>Ctrl+O</kbd> load · <kbd>Ctrl+K</kbd> check clashes · <kbd>Ctrl+Shift+A</kbd> auto-fill |
| Export | <kbd>Ctrl+E</kbd> Excel · <kbd>Ctrl+Shift+P</kbd> publish (PDF/calendar) · <kbd>Alt+V</kbd> CSV · <kbd>Ctrl+P</kbd> print |
| View | <kbd>Alt+1</kbd>/<kbd>Alt+2</kbd> shift · <kbd>1</kbd>–<kbd>7</kbd> day · <kbd>Ctrl+F</kbd> search · <kbd>Alt+H</kbd> sidebar · <kbd>F1</kbd> help · <kbd>Esc</kbd> close |

### API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | status + row counts |
| `GET` | `/api/courses` | catalogue (one row per course-section **and kind**) |
| `GET` | `/api/course-details/<id>/<section>` | instructor, roster, scheduled slots |
| `GET` | `/api/rooms` · `/api/students` · `/api/student-enrollments` | reference data |
| `GET` | `/api/timetable` | the saved week |
| `POST` | `/api/timetable/validate` | check one placement or the whole grid |
| `POST` | `/api/timetable` | save (atomic, rejects clashes with `409`) |
| `POST` | `/api/timetable/reset` · `/api/database/reset` | clear / factory reset |
| `POST` | `/api/timetable/autofill` | fill the remaining classes automatically (optional `semester`) |
| `POST` | `/api/timetable/unscheduled` | lectures and labs that are not on the grid |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/instructors[/<id>]` | teachers |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/buildings[/<id>]` | buildings |
| `POST`/`PUT`/`DELETE` | `/api/rooms[/<id>]` | classrooms |
| `GET` | `/api/admin/courses` | courses with their sections and teachers |
| `POST`/`PUT`/`DELETE` | `/api/courses[/<id>]` | courses and course codes |
| `POST`/`DELETE` | `/api/courses/<id>/sections[/<section>]` | sections |
| `POST` | `/api/export/xlsx` | Excel workbook: one sheet per day *and* per semester |
| `GET` | `/api/import/template` | blank import workbook |
| `POST` | `/api/import/xlsx` | bulk import (multipart `file`) → per-row report |
| `GET` | `/api/publish/targets` | teachers / sections / rooms that have classes |
| `POST` | `/api/publish/pdf` | PDF, `scope` = `all` \| `teacher` \| `section` \| `semester` \| `room` |
| `POST` | `/api/publish/ics` | downloadable `.ics` |
| `GET` | `/calendar.ics?teacher=…&weeks=…` | live calendar subscription feed |
| `GET`/`POST` | `/api/settings` | grid preferences |

---

## 🔧 Configuration

Everything is optional. Copy [`.env.example`](.env.example) next to the
executable as `.env` to change any of it.

| Variable | Default | Meaning |
|---|---|---|
| `TTG_DATABASE_URL` | embedded SQLite | any SQLAlchemy URL |
| `DB_SERVER` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_DRIVER` | – | Microsoft SQL Server (needs `pip install pyodbc`) |
| `TTG_DATA_DIR` | per-OS app-data folder | where `timetable.db` and `timetable.log` live |
| `TTG_HOST` / `TTG_PORT` | `127.0.0.1` / free port | server binding |
| `TTG_OPEN_BROWSER` | `1` | auto-open the browser |
| `TTG_SEED_DEMO_DATA` | `1` | `0` = start with an empty database |
| `TTG_DEBUG` | `0` | verbose logging |

---

## 📋 Where this came from

Version 1 was a prototype that could not run outside its author's PC: the
requirements file was UTF-16 (so `pip install -r` failed), the PDF library was
loaded from a domain shut down in 2019, "Save to Database" always posted an
empty list, the SQL insert was string-interpolated (injectable), the grid
mis-aligned its own time headers after day 1, and clash detection compared a
cell with itself so it never found anything.

**34 defects** are catalogued — cause, symptom and fix for each — in
**[docs/BUGS_AND_FIXES.md](docs/BUGS_AND_FIXES.md)**. Everything since is in the
**[changelog](CHANGELOG.md)**.

---

## 🗺 Roadmap

* Constraint-solver auto-fill (teacher availability windows, "no 3 lectures in a
  row", minimise gaps) that explains why a section could not be placed
* Student enrolment editor and per-student timetables
* Lab sessions spanning several consecutive slots in one block
* Multi-user mode: shared Postgres backend, logins, audit trail
* Automatic timestamped backups of `timetable.db` with one-click restore
* Signed Windows installers and notarised macOS builds

---

## 📄 Licence

MIT — see [LICENSE](LICENSE).
Original concept: FAST-NUCES Islamabad campus timetabling.
