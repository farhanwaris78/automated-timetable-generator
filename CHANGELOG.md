# Changelog

## 2.0.3 — reports, per-day schedules, documents & full keyboard accessibility

The biggest change since 2.0.2: the app can now *tell you what to fix* rather
than just showing you a grid. Three printable reports, a dedicated Document
dialog, a per-day printed schedule, automatic backups and a full accessibility
pass round out the release.

### Reports you can review before you print  📊

A new **Reports** button (and <kbd>Alt+Shift+R</kbd>) opens all three reports
on screen, and the same data goes into the Excel workbook **and** a PDF page:

* **Room utilisation** — free vs. busy hours per room per week, flagging rooms
  below 50% used as **Under-used**, so you can see which classrooms are paying
  for themselves.
* **Teacher workload** — contact hours per teacher per week, flagging
  **Over-loaded** (> 20 h) and **Under-loaded** staff at a glance.
* **Clashes to fix** — every conflict sorted by **severity** (errors first,
  then warnings), deduplicated, each with a suggested fix: one printable
  "what to fix" page.

The Reports dialog lets you review the numbers on screen and then export them
as a PDF or back to Excel. The Excel workbook is now **guaranteed** to carry all
three report sheets whatever layout you pick in Publish.

### Document identity in its own dialog  📝

The institution, name of program, semester and commencement fields now live
under a dedicated toolbar **Document** button (and <kbd>Alt+D</kbd>) instead of
being buried inside *Publish*. The **term** is a season drop-down
(Spring / Summer / Fall / Winter) **+ year + free text**, and a live preview of
the document title block updates as you type.

### A printed schedule you can actually hand out  🗓️

* **Per-day list** — one landscape page **per weekday** with a big day header,
  the classic printed class schedule split day by day.
* **Class Schedule reference layout** — an exact-match printed layout for the
  reference CSV, with **AM/PM** times and a widened *C.Hrs* column so the
  `non-credited course` label always fits.

### Safety & niceties  🛡️

* **Never lose a few minutes again** — the app writes a timestamped backup of
  the current project into a `_backups` folder beside the project file every
  few minutes while there are unsaved edits (keeping the newest few).
* **“file is in use”** — if the export target is still open in Excel (or any
  program), the app now says so plainly instead of silently failing; nothing is
  overwritten or lost.
* **`non-credited` on screen** — a course with 0 credit hours wears a
  “non-credited” chip on its card and grid cell, not just in exports.
* **Warn before you lose typing** — leaving an edit dialog (teacher, room,
  course, building, section, document) with unsaved changes asks *“Discard your
  changes?”*.
* **Full keyboard accessibility** — the Manage tables and the in-app file
  browser are now fully keyboard-driveable (arrow keys, <kbd>Home</kbd>/<kbd>End</kbd>,
  then <kbd>Tab</kbd> to each row's buttons).

### Works standalone, no server  💻

The desktop window still runs fully offline and serverless: the app serves its
own UI to an embedded webview and keeps everything in a local SQLite database —
no Python, no database server, no internet connection required.

**Tests:** backend **157 passing** (was 140); frontend jsdom suites (drag & drop,
project dialog, export dialog, document dialog) all green.

## 2.0.2 — drag & drop that works, save anywhere, blank new projects

This release fixes the three things that stopped 2.0.1 from being usable for
real work, and hardens everything around them.

### Drag & drop actually drops  🐛→✅

Courses could not be dropped onto the timetable at all. Three separate
spec-level defects had to line up for that to happen, and all three are fixed:

* **Mismatched drag effects.** The course cards advertised
  `effectAllowed = "copy"` while the grid cells answered
  `dropEffect = "move"`. The HTML5 drag-and-drop model **cancels a drop whose
  `dropEffect` is not permitted by `effectAllowed`**, so the browser silently
  threw the drop away and the card sprang back. Both sides now negotiate
  properly (`copyMove` + a matching effect per payload type).
* **Missing `dragenter` handler.** Only `dragover` called `preventDefault()`.
  Chromium decides whether an element is a drop target from the *first*
  `dragenter`, so the cell was rejected before `dragover` ever ran. Both
  events now accept the drag.
* **Unreadable payload in the desktop window.** The code read the dragged item
  back out of `dataTransfer.getData()`, which returns `""` while a drag is in
  progress (protected mode) and also on `drop` inside the WebView2 / WKWebView
  shells the desktop window uses. The payload is now held in memory, with
  `dataTransfer` kept only as a fallback for drags from outside the app.

On top of the fix:

* **You can see where a class may land.** Free slots are lightly hatched during
  a drag, the hovered cell is outlined, and a slot that is **already booked
  turns red with a “no drop” cursor before you release the mouse** instead of
  showing a “Slot taken” toast afterwards.
* **Highlights never get stuck.** Nested elements used to fire `dragleave` and
  strand the highlight; enter/leave are now depth-counted, and a cancelled
  drag (<kbd>Esc</kbd>, dropping outside the window, losing focus) always
  cleans up.
* **A stray drop can no longer blank the app** — dropping a card on a
  non-target used to let the browser navigate to the payload.
* **Keyboard and touch support.** Press <kbd>Enter</kbd> or <kbd>Space</kbd> on
  a course to pick it up, then <kbd>Enter</kbd> (or a tap) on a slot to place
  it; <kbd>Esc</kbd> cancels. Cards and cells are focusable and labelled for
  screen readers.
* **A regression test that fails on the old build.** `tests/frontend/`
  runs the real `app.js` against the real `index.html` in JSDOM, with a
  `DataTransfer` stub that reproduces the browser's protected mode. 22 checks
  including *“course was actually dropped into the timetable”*; the previous
  build fails 4 of them.

### Save your project **anywhere** — the whole computer is browsable  📁

The file browser was hard-locked to your home folder: `C:\Users\<name>` was a
wall you could not walk above, so a project could not be saved to `D:\`, a USB
stick or a shared drive.

* **Every drive and volume is reachable** — `C:\`, `D:\`, removable media,
  network shares, `/`, `/Volumes/…`, `/media/…`, `/mnt/…`.
* **A proper Save-as layout**: a sidebar of drives plus **Quick access**
  shortcuts (Home, Desktop, Documents, Downloads and their OneDrive-redirected
  equivalents), **clickable breadcrumbs**, and Up / Refresh / New folder.
  You can walk all the way up to the drive root.
* **Write permission is checked *before* you save.** A read-only folder is
  labelled as such and the Save button is disabled with an explanation,
  instead of the save failing after the fact.
* **The dialog shows the exact file it will create** (`Will be saved as: …`)
  and updates as you type.
* **Better path handling**: `~`, environment variables and relative paths are
  expanded; Windows-illegal characters and reserved device names (`CON`,
  `LPT1`, …) are rejected with a clear message; missing parent folders are
  created for you; creating a folder steps straight into it.
* **Strict mode is still available** for shared or kiosk machines:
  `TTG_SANDBOX_HOME=1`, or `TTG_SANDBOX_ROOT=/some/folder` for a custom root.

### Exports land next to your project  📊

Excel, PDF, CSV and iCalendar files used to go to the browser's Downloads
folder, scattered away from the project they belong to.

* **Every export is written into the folder your project was saved in.** Save
  `D:\Timetables\Spring 2026.ttproj` and the workbook, PDFs, CSV and calendar
  all appear in `D:\Timetables\`.
* **Nothing is silently overwritten** — a second export becomes
  `timetable (2).xlsx`, like Windows Explorer.
* **Writes are atomic** (temp file + rename), so a crash or a full disk can
  never leave a half-written spreadsheet behind.
* Exports still **download normally** when no project has been saved yet, so
  nothing breaks for people who never save.
* **CSV is now generated server-side**, so it has the same columns as the
  workbook (adding Building, Room type, Capacity, Kind and Semester), is
  correctly quoted, and carries a UTF-8 BOM so Excel on Windows renders
  accented names properly.

### A new project is genuinely new  🗒️

**New project** used to load the bundled sample university, so starting a real
institute meant deleting 18 courses, 27 teachers, 36 rooms and 20 students by
hand first.

* <kbd>Ctrl+N</kbd> now creates a **completely blank workspace** — no courses,
  teachers, buildings, rooms, students, enrolments or scheduled classes — and
  clears the previous project's grid preferences too.
* The sample university is a **tick-box** in the same dialog for anyone who
  wants to explore the app, and `POST /api/database/reset {"blank": true}`
  empties the database from the API.
* The empty grid is no longer a dead end: it shows a **guided checklist**
  (add a building → rooms → teachers → courses → generate) with working
  buttons and shortcuts, plus a pointer to the Excel importer.
* Having no rooms yet is treated as a normal starting state rather than an
  error.

### Under the hood

* New `timetable/filesystem.py`: drive enumeration, quick places, breadcrumbs,
  permission probing (a real write test, because `os.access` lies on Windows),
  name validation, non-clobbering unique names and the opt-in sandbox — all
  pure `pathlib`, no shell.
* New API: `GET /api/fs/roots`, `POST /api/fs/check`, `POST /api/export/csv`;
  `folder` accepted by every export route; `sample` by `/api/project/new`;
  `blank` by `/api/database/reset`. `/api/project` now returns the available
  drives, shortcuts and the current export folder.
* `FileSystemError` is handled as a first-class JSON error.
* Test suite grown from 110 to **121 Python tests** plus the 22 front-end
  drag-and-drop checks.

---

## 2.0.1 — standalone desktop window, portable projects

**Native desktop window (no browser tab)**
* The app now opens in its **own desktop window** through pywebview: WebView2
  on Windows, WKWebView on macOS and WebKitGTK on Linux. No address bar, no
  tabs, no browser chrome — it looks and feels like a normal installed
  program, and the packaged `.exe`/`.app`/binary no longer opens a console
  window either.
* If the webview runtime is missing the app **falls back to the browser**
  automatically — it never fails to start. `--browser` forces the old
  behaviour, `--no-browser` runs server-only, `TTG_WINDOW_NATIVE=0` disables
  the native window via `.env`.
* Startup crashes on Windows now show a native error dialog instead of a
  vanishing console window.

**Projects — save, open, new, save as** (`Ctrl+N/O/S`, `Ctrl+Shift+S`)
* A **project** is one portable `.ttproj` file containing *everything*:
  teachers, buildings, rooms, courses/sections, students, enrolments, the
  saved timetable and grid preferences.
* New project bar in the header: **New**, **Open**, **Save**, **Save as**
  with a live project name / file path.
* **Save** (or the in-app Save-as dialog) writes the file atomically (temp +
  rename — a crash never corrupts it) and automatically stores the grid on
  screen together with the reference data.
* **Open** restores the whole project. A safety backup of the current working
  database is written first, and the most recent 10 backups are kept in the
  data folder.
* **New** resets to the bundled sample dataset (with the same automatic
  backup) so you can start another institute without closing the app.
* **Recent projects** list, deduplicated, most-recent-first, removable, with
  modified dates; empty-name saves get a `.ttproj` suffix automatically.
* The project format is a versioned ZIP (`project.json` + `data.json`,
  backend-agnostic JSON) — a project saved while pointed at SQL Server opens
  fine on another PC using the default SQLite.

**In-app file browser — with proper logos**
* Open / Save-as use the app's own folder browser, not the OS dialog, so it
  works identically on Windows, macOS, Linux and in the dev browser.
* The **“Up to previous folder”** and **“New folder”** controls are now
  clean **icon buttons** (up-arrow and folder-plus logos) instead of plain
  text — exactly the shortcuts that were being used most.
* Folders and `.ttproj` files are listed with sizes and dates; browser is
  sandboxed to your home folder and every path is validated server-side.

**Under the hood**
* New `timetable/projects.py` module with atomic writes, JSON-safe dump /
  restore (dates round-trip correctly) and backup pruning.
* New API: `GET/POST /api/project`, `/api/project/new|save|open`,
  `GET /api/project/meta`, `DELETE /api/project/recent`, `GET /api/fs/list`,
  `POST /api/fs/mkdir` — plus a `ProjectError` JSON error handler.
* Desktop launcher runs waitress on a daemon thread with a clean shutdown and
  keeps the browser fallback path for headless machines.
* Test suite grown from 94 to **110 tests** (project round-trips, corrupt /
  future-format files, backups, recents, fs sandbox, launcher flags).

> Originally published as 3.0.0; renumbered to 2.0.1 so the desktop-window and
> projects work sits in the 2.x line alongside 2.0.0.

---

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
