<div align="center">

<img src="packaging/icon.png" width="96" alt="">

# Automated Timetable Generator

**Clash-free university scheduling — one download, no setup.**

Drag & drop courses onto a room × time grid. The app blocks every room,
instructor and student conflict *as you place classes*, and tells you exactly
who clashes.

[Download](#-download) · [User guide](docs/USER_GUIDE.md) · [Build it yourself](docs/BUILD.md) · [What was fixed](docs/BUGS_AND_FIXES.md)

</div>

---

## ⬇ Download

Grab the file for your machine from the [Releases page](../../releases) — no
Python, no SQL Server, no ODBC driver, no internet connection required.

| Platform | File | Notes |
|---|---|---|
| **Windows 10/11** | `AutomatedTimetableGenerator-*-win64.msi` | Installer + Start-menu shortcut |
| Windows (portable) | `TimetableGenerator-*-windows-x64.zip` | No admin rights needed |
| **macOS** (Apple Silicon) | `TimetableGenerator-*-macos-arm64.dmg` | |
| macOS (Intel) | `TimetableGenerator-*-macos-x86_64.dmg` | |
| **Ubuntu / Debian** | `timetable-generator_*_amd64.deb` | `sudo apt install ./…deb` |
| Any Linux | `TimetableGenerator-*-linux-x86_64.tar.gz` | `./start.sh` |

Double-click → a console window shows the address → your browser opens on the
app. That's the whole installation.

---

## ✨ What it does

* **Manage everything in the app** — add/edit/delete **teachers**, **classrooms**
  (with capacity and type), **courses with course codes**, credit hours and
  **sections**, each with its own keyboard shortcut. No SQL, no spreadsheets.
* **Morning & evening shifts** with independent hours, sharing the same rooms
  and staff; clash detection spans both.
* **Full 1–7 day week.**
* **Drag & drop scheduling** on a room × time grid, one tab per day.
* **Undo / redo** (100 steps) for every action — <kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd>.
* **Auto-fill** places every remaining section in a conflict-free slot.
* **Excel export with one worksheet per day**, colour-coded, plus Summary and
  By-Teacher sheets.
* **Discoverable shortcuts** — <kbd>F1</kbd> shows a live list generated from the
  same registry that handles the keys, and every button's tooltip shows its key.
* **Real clash detection, server-side, on every drop:**
  * 🔴 **room** double-booking (overlapping, not just identical, slots)
  * 🔴 **instructor** teaching two sections at once
  * 🔴 **student** collisions — with the affected **roll numbers listed**
  * 🔴 duplicate placement of the same course-section
  * 🟠 **capacity** warning when enrolment exceeds the room's seats
* **Class details on click** — instructor, department, headcount, full roster.
* **Save & restore** the whole week atomically; nothing is written while a
  clash remains.
* **Export** to Excel (per-day sheets), PDF (one page per day), CSV, or print.
* **Search & filter** the catalogue, restrict to a building, cap the room count.
* **Zero configuration** — an embedded SQLite database is created on first run
  and seeded with a realistic sample dataset (18 courses · 45 sections ·
  27 instructors · 36 rooms · 20 students · 106 enrolments).
* **Optionally** point it at Microsoft SQL Server, PostgreSQL or MySQL with a
  one-line `.env` change.
* Keyboard shortcuts, responsive layout, print stylesheet, accessible markup.

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

Run the tests:

```bash
pip install pytest
python -m pytest -q                # 56 tests
```

---

## 📦 Build the installers

```bash
pip install -r requirements-dev.txt
python packaging/build.py          # native package(s) for the current OS
```

`exe` · `msi` · `dmg` · `deb` · `portable` are individual targets. Full
instructions, code-signing notes and the CI pipeline that builds Windows,
macOS and Linux together: **[docs/BUILD.md](docs/BUILD.md)**.

---

## 🏗 Architecture

```
launcher.py                 frozen-app entry point (PyInstaller / cx_Freeze)
run.py / app.py             developer + WSGI entry points
timetable/
├── config.py               env/.env handling, per-OS data dir, DB URL resolution
├── db.py                   SQLAlchemy schema, engine, first-run seeding
├── services.py             domain logic, clash-detection engine, auto-fill
├── catalog.py              CRUD for teachers, rooms, courses, sections
├── exporters.py            Excel workbook builder (one sheet per day)
├── web.py                  Flask app factory and JSON API
├── desktop.py              port picking, waitress server, browser launch
├── seed_data.json          sample dataset
├── templates/index.html
└── static/                 style.css · app.js · favicon.svg · vendor/html2pdf
packaging/                  build.py · timetable.spec · cx_setup.py · icons
tests/test_app.py           56 tests
docs/                       USER_GUIDE · BUILD · SCHEMA · BUGS_AND_FIXES
```

**Stack:** Python 3.10+ · Flask 3 · SQLAlchemy 2 · waitress · SQLite ·
openpyxl · vanilla ES2017 front-end (no jQuery, no CDN — it must work offline).

### Keyboard shortcuts

Press <kbd>F1</kbd> in the app. Add data: <kbd>Alt+T</kbd> teacher ·
<kbd>Alt+R</kbd> room · <kbd>Alt+C</kbd> course · <kbd>Alt+B</kbd> building ·
<kbd>Alt+S</kbd> section · <kbd>Alt+M</kbd> manage. Edit: <kbd>Ctrl+Z</kbd> /
<kbd>Ctrl+Y</kbd> · <kbd>Delete</kbd>. Timetable: <kbd>Ctrl+G</kbd> generate ·
<kbd>Ctrl+S</kbd> save · <kbd>Ctrl+O</kbd> load · <kbd>Ctrl+K</kbd> check ·
<kbd>Ctrl+Shift+A</kbd> auto-fill. Export: <kbd>Ctrl+E</kbd> Excel ·
<kbd>Alt+P</kbd> PDF · <kbd>Alt+V</kbd> CSV · <kbd>Ctrl+P</kbd> print.
View: <kbd>Alt+1</kbd>/<kbd>Alt+2</kbd> shift · <kbd>1</kbd>–<kbd>7</kbd> day ·
<kbd>Ctrl+F</kbd> search.

### API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | status + row counts |
| `GET` | `/api/courses` | catalogue (one row per course-section) |
| `GET` | `/api/course-details/<id>/<section>` | instructor, roster, scheduled slots |
| `GET` | `/api/rooms` · `/api/students` · `/api/student-enrollments` | reference data |
| `GET` | `/api/timetable` | the saved week |
| `POST` | `/api/timetable/validate` | check one placement or the whole grid |
| `POST` | `/api/timetable` | save (atomic, rejects clashes with `409`) |
| `POST` | `/api/timetable/reset` · `/api/database/reset` | clear / factory reset |
| `POST` | `/api/timetable/autofill` | fill the remaining sections automatically |
| `POST` | `/api/export/xlsx` | Excel workbook, one sheet per day |
| `GET`/`POST`/`PUT`/`DELETE` | `/api/instructors[/<id>]` | teachers |
| `GET`/`POST`/`DELETE` | `/api/buildings[/<id>]` | buildings |
| `POST`/`PUT`/`DELETE` | `/api/rooms[/<id>]` | classrooms |
| `GET` | `/api/admin/courses` | courses with their sections and teachers |
| `POST`/`PUT`/`DELETE` | `/api/courses[/<id>]` | courses and course codes |
| `POST`/`DELETE` | `/api/courses/<id>/sections[/<section>]` | sections |
| `GET`/`POST` | `/api/settings` | grid preferences |

---

## 🔧 Configuration

Everything is optional. Copy [`.env.example`](.env.example) to `.env` next to
the executable to change any of it.

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

## 📋 Status of the original project

This is version 2.0. Version 1 was a prototype that could not run outside its
author's PC: the requirements file was UTF-16 (so `pip install -r` failed), the
PDF library was loaded from a domain shut down in 2019, "Save to Database"
always posted an empty list, the SQL insert was string-interpolated (injectable),
the timetable grid mis-aligned its own time headers after day 1, and clash
detection compared a cell with itself so it never found anything.

**34 defects** are catalogued — with the exact cause and fix for each — in
**[docs/BUGS_AND_FIXES.md](docs/BUGS_AND_FIXES.md)**.

---

## 🗺 Roadmap

* Student enrolment editor + Excel/CSV **import** for bulk setup
* Teacher availability windows ("Dr. X cannot teach before 11:00")
* Lab sessions spanning several consecutive slots
* Per-teacher and per-section timetable views and printouts
* Optimising solver (minimise gaps, balance daily load) on top of auto-fill
* Multi-campus support, per-user logins and an audit trail
* Automatic backups of `timetable.db` with one-click restore

---

## 📄 Licence

MIT — see [LICENSE](LICENSE).
Original concept: FAST-NUCES Islamabad campus timetabling.
