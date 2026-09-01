<div align="center">

<img src="packaging/icon.png" width="96" alt="Automated Timetable Generator app icon">

# Automated Timetable Generator

### Free, offline timetable software for universities, colleges and schools — Windows, macOS and Linux

**Automatic class scheduling with real-time clash detection, drag-and-drop
timetable editing, lab and semester support, portable projects, and
Excel / PDF / calendar export — in its own native desktop window.**

[![Latest release](https://img.shields.io/github/v/release/farhanwaris78/automated-timetable-generator?label=download&style=for-the-badge)](../../releases/latest)
[![Platforms](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-supported-2b3465?style=for-the-badge)](#-download-timetable-software-for-windows-macos-and-linux)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-green?style=for-the-badge)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-110%20passing-brightgreen?style=for-the-badge)](tests/)

[⬇ Download](#-download-timetable-software-for-windows-macos-and-linux) ·
[✨ Features](#-features) ·
[🚀 Quick start](#-quick-start-run-the-timetable-generator-from-source) ·
[📘 User guide](docs/USER_GUIDE.md) ·
[❓ FAQ](#-faq)

</div>

---

## What is the Automated Timetable Generator?

**Automated Timetable Generator** is a free, open-source **timetable maker** and
**class scheduling program** for universities, colleges, schools, academies and
training institutes. It builds a **clash-free weekly timetable** for every
teacher, classroom, lab, course section and student batch, and it runs
completely **offline** as a desktop application on **Windows, macOS and Linux** —
no Python, no database server, no subscription and no internet connection.

Use it to:

* create a **university timetable**, **college class schedule** or **school
  routine** in minutes instead of days;
* **automatically generate a timetable** with one click, then fine-tune it by
  **drag and drop**;
* **detect and prevent scheduling conflicts** — room double-bookings, teacher
  clashes, student clashes, semester/batch clashes, lecture-versus-lab overlaps
  and over-full rooms;
* schedule **theory lectures and laboratory sessions separately**, with their
  own credit hours;
* produce **semester-wise timetables** — one worksheet or one PDF page per
  semester;
* **export the timetable to Excel (.xlsx), PDF, CSV** or a **live iCalendar
  feed** for Google Calendar, Outlook and Apple Calendar.

<sub>Also known as: automatic timetable generator, class scheduler, lecture
timetable software, exam and course scheduling system, school routine maker,
university time table generator, faculty workload scheduler.</sub>

---

## ⬇ Download timetable software for Windows, macOS and Linux


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

Launch it → the app opens in its **own native desktop window** (no browser, no
address bar) — on Windows it uses WebView2, on macOS WKWebView and on Linux
WebKitGTK. If a webview runtime is missing it quietly falls back to the
browser, so it always starts. Everything (database, logs, settings, project
backups) lives in one per-user folder; uninstalling leaves nothing behind.

> **First run:** the app creates its own SQLite database and seeds a realistic
> sample university so you can try every feature immediately. Press
> <kbd>F1</kbd> for the shortcut list, or **Manage data → …** to replace the
> sample with your own.

---

## ✨ Features of this automatic timetable generator

### Projects — one file, everything inside
* **New** (<kbd>Ctrl+N</kbd>), **Open** (<kbd>Ctrl+O</kbd>), **Save**
  (<kbd>Ctrl+S</kbd>) and **Save as** (<kbd>Ctrl+Shift+S</kbd>) a **project**:
  one portable `.ttproj` file that carries the teachers, buildings, rooms,
  courses, sections, students, the saved timetable and the grid preferences.
* The in-app folder browser gives you **Up to the previous folder** and
  **New folder** as proper **icon buttons** (arrow-up and folder-plus logos)
  and lists projects with size and modified date.
* Opening or starting a new project keeps an **automatic safety backup** of
  your current database (last 10 kept); project files are written atomically.
* A **Recent** list remembers the last ten projects, deduplicated, and lets
  you remove entries you no longer need.

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

## 🚀 Quick start: run the timetable generator from source

```bash
git clone https://github.com/farhanwaris78/automated-timetable-generator.git
cd automated-timetable-generator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run.py                      # opens the app in its own native window
```

Useful flags: `--port 5000`, `--window` (native window, the default),
`--browser`, `--no-browser` (server only), `--debug`, `--reset-database`,
`--database-url …`, `--data-dir …`.

```bash
pip install pytest
python -m pytest -q                # 110 tests
```

---

## 📦 Build the Windows, macOS and Linux installers yourself

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

## 🏗 Architecture & tech stack

```
launcher.py                 frozen-app entry point (PyInstaller / cx_Freeze)
run.py / app.py             developer + WSGI entry points
timetable/
├── config.py               env/.env handling, per-OS data dir, DB URL resolution
├── db.py                   SQLAlchemy schema, engine, migrations, first-run seeding
├── services.py             domain logic, clash-detection engine, auto-fill
├── catalog.py              CRUD for teachers, buildings, rooms, courses, sections
├── projects.py             portable .ttproj files, recents, safety backups
├── exporters.py            Excel workbook builder (one worksheet per day)
├── importers.py            Excel template + bulk import with per-row reporting
├── publishing.py           dependency-free PDF writer + iCalendar feed builder
├── web.py                  Flask app factory and JSON API
├── desktop.py              port picking, waitress server, native window, browser
├── seed_data.json          sample dataset
├── templates/index.html
└── static/                 style.css · app.js · favicon.svg
packaging/                  build.py · timetable.spec · cx_setup.py · ci/ · icons
tests/                      110 tests (app + projects)
docs/                       USER_GUIDE · BUILD · SCHEMA · BUGS_AND_FIXES
```

**Stack:** Python 3.10+ · Flask 3 · SQLAlchemy 2 · waitress · SQLite · openpyxl ·
pywebview (native window, optional at runtime) · vanilla ES2017 front-end.
No jQuery, no CDN, no runtime JS dependencies.

### Keyboard shortcuts

Press <kbd>F1</kbd> in the app for the authoritative list.

| Group | Keys |
|---|---|
| Project | <kbd>Ctrl+N</kbd> new · <kbd>Ctrl+O</kbd> open · <kbd>Ctrl+S</kbd> save · <kbd>Ctrl+Shift+S</kbd> save as |
| Add data | <kbd>Alt+T</kbd> teacher · <kbd>Alt+R</kbd> room · <kbd>Alt+C</kbd> course · <kbd>Alt+B</kbd> building · <kbd>Alt+S</kbd> section · <kbd>Alt+M</kbd> manage · <kbd>Ctrl+I</kbd> import |
| Edit | <kbd>Ctrl+Z</kbd> undo · <kbd>Ctrl+Y</kbd> redo · <kbd>Delete</kbd> remove selected · <kbd>Ctrl+Backspace</kbd> clear grid |
| Timetable | <kbd>Ctrl+G</kbd> generate · <kbd>Ctrl+Alt+S</kbd> save grid to DB · <kbd>Ctrl+K</kbd> check clashes · <kbd>Ctrl+Shift+A</kbd> auto-fill |
| Export | <kbd>Ctrl+E</kbd> Excel · <kbd>Ctrl+Shift+P</kbd> publish (PDF/calendar) · <kbd>Alt+V</kbd> CSV · <kbd>Ctrl+P</kbd> print |
| View | <kbd>Alt+1</kbd>/<kbd>Alt+2</kbd> shift · <kbd>1</kbd>–<kbd>7</kbd> day · <kbd>Ctrl+F</kbd> search · <kbd>Alt+H</kbd> sidebar · <kbd>F1</kbd> help · <kbd>Esc</kbd> close |

### API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | status + row counts |
| `GET` | `/api/project` | current project + recent projects + home folder |
| `POST` | `/api/project/new` | fresh project (automatic safety backup) |
| `POST` | `/api/project/save` | save the whole database as a `.ttproj` file |
| `POST` | `/api/project/open` | load a `.ttproj` file (automatic safety backup) |
| `DELETE` | `/api/project/recent` | remove an entry from the recent list |
| `GET` | `/api/fs/list` | folders + `.ttproj` files inside the home folder |
| `POST` | `/api/fs/mkdir` | create a folder in the in-app browser |
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

## 🔧 Configuration options

Everything is optional. Copy [`.env.example`](.env.example) next to the
executable as `.env` to change any of it.

| Variable | Default | Meaning |
|---|---|---|
| `TTG_DATABASE_URL` | embedded SQLite | any SQLAlchemy URL |
| `DB_SERVER` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_DRIVER` | – | Microsoft SQL Server (needs `pip install pyodbc`) |
| `TTG_DATA_DIR` | per-OS app-data folder | where `timetable.db` and `timetable.log` live |
| `TTG_HOST` / `TTG_PORT` | `127.0.0.1` / free port | server binding |
| `TTG_OPEN_BROWSER` | `1` | show a window / open the browser; `0` = server only |
| `TTG_WINDOW_NATIVE` | `1` | own desktop window instead of the browser (`0` = browser) |
| `TTG_SEED_DEMO_DATA` | `1` | `0` = start with an empty database |
| `TTG_DEBUG` | `0` | verbose logging |

---

## 📋 Project history: from broken prototype to release

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
* One-click restore of the automatic safety backups
* Signed Windows installers and notarised macOS builds

---

---

## ❓ FAQ

<details open>
<summary><strong>Is this timetable generator really free?</strong></summary>

Yes. It is free and open source under the MIT licence — free for schools,
colleges, universities and commercial use. There is no account, no licence key,
no trial period and no paid tier.
</details>

<details>
<summary><strong>Does it work offline / without internet?</strong></summary>

Completely. Everything runs on your own machine: the interface, the scheduling
engine and the database. There is no cloud service, no CDN and no telemetry, so
it works on an air-gapped lab PC or an exam-hall laptop.
</details>

<details>
<summary><strong>Does it need a browser?</strong></summary>

No. By default the app opens in its **own native desktop window** (WebView2 on
Windows, WKWebView on macOS, WebKitGTK on Linux). If that runtime is not
installed it automatically falls back to your default browser, so the app
always starts. Use <code>--browser</code> or <code>TTG_WINDOW_NATIVE=0</code>
to force the browser mode.
</details>

<details>
<summary><strong>What is a project file?</strong></summary>

A <code>.ttproj</code> file is a self-contained snapshot of the whole app:
teachers, rooms, courses, students and the saved timetable. Use <kbd>Ctrl+S</kbd>
to save, <kbd>Ctrl+O</kbd> to open, <kbd>Ctrl+N</kbd> for a fresh project and
<kbd>Ctrl+Shift+S</kbd> to save under a new name. A safety backup of the
current database is taken automatically before Open/New.
</details>

<details>
<summary><strong>How does the automatic timetable generation work?</strong></summary>

Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd> (*Auto-fill remaining*) and
the scheduler walks every unscheduled class — largest enrolment first — and
drops it into the first day/slot/room where it causes no room, teacher, student,
semester or capacity conflict, preferring lab rooms for lab sessions. On the
bundled sample data it schedules 65 classes (45 lectures + 20 labs) in well
under a second. You can also fill one semester at a time and adjust anything by
hand afterwards.
</details>

<details>
<summary><strong>What kinds of scheduling conflicts does it detect?</strong></summary>

Room double-booking, teacher double-booking, student clashes (with the affected
roll numbers listed), duplicate placement of a course-section, lecture-vs-lab
overlap for the same section, semester/batch clashes, labs placed outside lab
rooms, and rooms with fewer seats than enrolled students. Errors block the
placement; warnings inform you without getting in the way.
</details>

<details>
<summary><strong>Can it handle labs, semesters and multiple sections?</strong></summary>

Yes. A course can carry a lab with its own credit hours, and the lab is
scheduled as a separate block from the lecture. Courses belong to a semester,
and a *semester + section* is treated as one student batch that can never be in
two rooms at once. Any number of sections per course is supported.
</details>

<details>
<summary><strong>Can I export the timetable to Excel or PDF?</strong></summary>

Yes — an `.xlsx` workbook with one colour-coded worksheet per day, one worksheet
per semester, a summary sheet, a per-teacher sheet and a list of anything still
unscheduled; PDFs for the master grid or per teacher, section, semester or room;
CSV; a print stylesheet; and `.ics` calendar files plus a live subscription link
for Google Calendar, Outlook and Apple Calendar.
</details>

<details>
<summary><strong>Which operating systems are supported?</strong></summary>

Windows 10/11 (installer `.msi` or portable `.zip`), macOS on Apple Silicon and
Intel (`.dmg`), and Linux (`.deb` package or portable `.tar.gz`). The same code
also runs from source on any OS with Python 3.10 or newer.
</details>

<details>
<summary><strong>Where is my data stored, and can I use my own database?</strong></summary>

By default in a single SQLite file in your user data folder, created and
migrated automatically. Set `TTG_DATABASE_URL` in a `.env` file to use
PostgreSQL, MySQL or Microsoft SQL Server instead.
</details>

<details>
<summary><strong>Can I import my existing data from a spreadsheet?</strong></summary>

Yes. Press <kbd>Ctrl</kbd>+<kbd>I</kbd>, download the template workbook, fill in
your teachers, buildings, rooms, courses and sections, and import it. Records
are matched by name or code and updated instead of duplicated, so the same file
can be re-imported safely.
</details>

---

## 🔍 Keywords

Automated timetable generator · automatic timetable software · university
timetable generator · college class scheduling software · school timetable maker
· class scheduler · lecture and lab scheduling · semester-wise timetable ·
timetable clash detection · conflict-free class scheduling · drag and drop
timetable editor · room and teacher allocation software · faculty workload
timetable · course scheduling system · academic scheduling app · free open
source timetable generator · offline timetable software · timetable to Excel
PDF iCalendar export · Windows macOS Linux desktop timetable app · Python Flask
SQLite scheduling application.

---

## 📄 Licence

MIT — see [LICENSE](LICENSE).
Original concept: university campus timetabling.
