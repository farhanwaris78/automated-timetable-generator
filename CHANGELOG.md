# Changelog

## 2.0.0 — first public release

A complete rewrite of the original prototype into a zero-configuration,
cross-platform desktop application, with **34 defects** from the prototype fixed
(cause, symptom and fix for each in `docs/BUGS_AND_FIXES.md`) and six more found
and fixed while building the features below.

### Labs, semesters, and a report of what is missing

**Labs are first-class classes**
* The course editor gained **“This course has a lab”** with its own
  **lab credit hours** (default 1, editable 1–6)
* Every section with a lab produces a **second draggable card** in the sidebar,
  marked with a `LAB` chip, so the lecture and the lab are scheduled separately
* Placed lab blocks carry the same `LAB` chip and a hatched pattern
* The class-details dialog has a **Theory ⇄ Lab switch** — flip a placement to
  the other half of the course and it is re-validated instantly
* New clash rules:
  * a lab may only be placed for a course that *has* a lab (**error**)
  * the lecture and the lab of one section may never overlap — the same students
    attend both (**error**)
  * a lab scheduled outside a `Lab` room is a **warning**, never a blocker
* Auto-fill schedules lectures *and* labs, and steers labs into `Lab` rooms
  first while keeping lectures out of them where possible

**Semester-wise timetabling**
* Courses now carry a **semester** (1–12, or unassigned)
* New **semester clash** rule: two classes of the same semester *and* the same
  section can never share a time slot — the batch cannot be in two places at
  once
* A **semester filter** in the toolbar narrows the sidebar and dims every
  placement that belongs to another semester
* Auto-fill accepts a semester so you can build one batch at a time
* **Excel export writes one sheet per semester** — rows are day × section,
  columns are the time slots — next to the existing per-day sheets
* The `Summary` sheet gained **Semester** and **Type** columns; `By Teacher`
  marks labs with `[LAB]`
* New PDF scope **“One page per semester”**, and `calendar.ics?semester=3`

**Report of unallocated classes**
* A new toolbar pill shows *“n not scheduled”* and turns green when nothing is
  missing; clicking it opens a report grouped by semester listing every lecture
  and lab that still needs a slot
* The workbook gains an **Unscheduled** sheet whenever something is missing
* New endpoint `POST /api/timetable/unscheduled` (checks the grid you send, or
  the saved timetable when you send nothing)

**Cleaner controls**
* The shortcut hints printed on the tabs and buttons (*Morning Alt+1*,
  *Generate grid Ctrl+G*, …) are gone; they now live in tooltips and in the
  <kbd>F1</kbd> shortcut reference only

**Data & compatibility**
* Additive migrations only: `courses.has_lab`, `courses.lab_credit_hours`,
  `courses.semester`, `timetable_entries.kind` — existing databases upgrade in
  place on first launch, with every old entry treated as `theory`
* The Excel import template carries the three new course columns
* Test suite: **94 tests**, all green

### Capacity warnings, Excel import, publishing (PDF & calendar)

**Room capacity vs enrolment**
* Placing a class in a room that seats fewer students than are enrolled now
  shows an amber `⚠ 58/40` badge on the class, outlines it, and counts it in a
  new toolbar pill ("*n* room(s) too small")
* Clicking the pill opens a **capacity report** listing every over-full class
  with the shortfall and **suggested rooms that would fit**
* Capacity stays a *warning*: it never blocks a placement or a save
* Checked client-side for instant feedback and re-checked server-side on every
  validation pass

**Bulk import from Excel** — <kbd>Ctrl+I</kbd>
* `GET /api/import/template` produces a workbook with a *Read me* sheet and one
  sheet each for **Teachers, Buildings, Rooms, Courses, Sections**
* `POST /api/import/xlsx` imports it through the same validation the GUI uses
* Records are matched by natural key (teacher name/email, building name,
  building + room number, course code, course + section) and **updated instead
  of duplicated** — re-importing the same file is safe
* Bad rows are reported with sheet name, row number and reason; the rest of the
  file still imports

**Publish & share** — <kbd>Ctrl+Shift+P</kbd>
* New `timetable/publishing.py`: a **dependency-free PDF writer** (no ReportLab,
  no headless browser) using the built-in PDF fonts, with real Helvetica metrics
  for centring and truncation
* PDF scopes: master grid (one page per day), **one page per teacher**, per
  course section, or per room — from the saved timetable *or* the unsaved grid
* **iCalendar**: `.ics` download plus a live subscription feed at
  `/calendar.ics?teacher=…&section=…&weeks=…`, RFC 5545 line-folded, one
  weekly-recurring VEVENT per class
* The publish dialog builds the subscription link and copies it to the clipboard

**GUI completeness**
* **Add building** and **Add section** are now proper dialogs (they were
  `window.prompt`, which some desktop webviews refuse to show); the section
  dialog has course and teacher pickers
* New **Buildings** tab in *Manage data* with room and seat totals, rename
  (`PUT /api/buildings/<id>`) and safe delete
* "+ section" button on every course row in *Manage data*
* Every destructive action uses a styled in-app confirmation dialog instead of
  `window.confirm`

**Removed**
* `html2pdf.bundle.min.js` (927 KB) — PDFs are now rendered by the app itself,
  which makes the installer smaller and the output vector-sharp

**Tests**: 56 → **83**, including front-end integrity checks that fail the build
if a button's `data-action`, a shortcut or a dialog id has no implementation.

### Data management, shifts, Excel, undo/redo

**Manage your own data (no SQL needed)**
* Add / edit / delete **teachers** (name, email, department, shift) — <kbd>Alt+T</kbd>
* Add / edit / delete **classrooms** (number, building, capacity, Classroom/Lab/Hall) — <kbd>Alt+R</kbd>;
  typing an unknown building name creates the building
* Add / edit / delete **courses with course codes**, credit hours, colour and
  sections with their teacher — <kbd>Alt+C</kbd>
* **Buildings** (<kbd>Alt+B</kbd>) and **sections** (<kbd>Alt+S</kbd>)
* **Manage data** screen (<kbd>Alt+M</kbd>): searchable Teachers / Classrooms / Courses tables
* Referential safety: the app refuses to delete a teacher who still teaches, a
  room or course used by the saved timetable, or a non-empty building

**Morning & evening shifts**
* Each shift keeps its own hours; both share rooms, teachers and courses
* Clash detection runs across shifts; one save stores both
* `shift` column added to `timetable_entries` (auto-migrated)

**Full week**
* 1–7 days; day tabs, `1`…`7` shortcuts, and per-day class counters

**Excel export**
* `POST /api/export/xlsx` → **one worksheet per day**, colour-coded, frozen
  panes, landscape fit-to-width, plus a filterable **Summary** sheet and a
  **By Teacher** sheet — <kbd>Ctrl+E</kbd>
* Works on the on-screen grid as well as the saved timetable

**Undo / redo**
* 100 steps covering placement, move, delete, clear, load and auto-fill
* Toolbar buttons + <kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd> / <kbd>Ctrl+Shift+Z</kbd>

**Discoverable shortcuts**
* One registry in `app.js` drives the key handler, every button tooltip **and**
  the <kbd>F1</kbd> shortcut dialog — the documentation cannot drift from the code

**Auto-fill**
* Greedy scheduler places every unscheduled section in a conflict-free slot
  (all 45 sample sections, verified clash-free by the independent validator)

**Packaging**
* `build.py --engine auto|pyinstaller|cxfreeze` with automatic fallback when the
  interpreter has no shared `libpython`; `portable`/`deb`/`dmg` handle both
  single-file and folder layouts
* openpyxl added to both freezer recipes

**Schema**
* Additive auto-migration on start-up: `courses.code`, `courses.credit_hours`,
  `instructors.email/department/shift`, `rooms.room_type`, `timetable_entries.shift`
* Course codes are back-filled for pre-existing databases

**Tests:** 35 → **56**.

### The rewrite itself

* Packaged as a real desktop app for **Windows, macOS and Linux** — no Python,
  no SQL Server, no ODBC driver and no internet connection required
* Embedded SQLite created, seeded and migrated automatically in a per-user data
  folder; optionally point it at SQL Server, PostgreSQL or MySQL with one line
  of `.env`
* Server-side clash engine, atomic saves, and a test suite of **94 tests**
