# Bug report & fix log

Every problem found in the original code, why it broke, and exactly what was
changed. Ordered by severity. **34 defects** in total.

Legend: 🔴 crash / data-loss / security · 🟠 feature does not work · 🟡 quality

---

## A. Backend — `app.py` (original 238 lines)

### 🔴 A1. `requirements.txt` was UTF‑16 encoded → `pip install -r` fails
`file requirements.txt` reported `Little-endian UTF-16 Unicode text`. pip reads
requirement files as UTF‑8, so the very first setup step failed for everyone
with:

```
ERROR: Invalid requirement: '\xff\xfeb\x00l\x00i\x00n\x00k\x00e\x00r...'
```

**Fix** — rewritten as UTF‑8 with LF endings, trimmed to what is actually
imported (the old list shipped pandas, numpy, pytz, six… none of which were
used), and `pyodbc` demoted to an optional extra.

### 🔴 A2. SQL injection in `/save-timetable`
```python
query = f"""INSERT INTO timeslots (course_name, ...)
            VALUES ('{course['name']}', '{course['start_time']}', ...)"""
cursor.execute(query)
```
Any course name containing an apostrophe broke the statement, and a crafted
POST body (`{"name": "x'); DROP TABLE courses;--"}`) could execute arbitrary
SQL. The endpoint required no authentication.

**Fix** — all SQL now goes through SQLAlchemy Core with bound parameters; input
is parsed and type-checked by `Assignment.from_payload()` before it ever
reaches the database. Regression test: `test_sql_injection_attempt_is_harmless`.

### 🔴 A3. Module-level connection = the app dies on the first hiccup
`connection`/`cursor` were created once at import time and shared by every
request thread. Consequences:
* if the DB was down at start-up, **every** route raised `NameError: name
  'cursor' is not defined` (a 500 with an HTML traceback, not a JSON error);
* `pyodbc` cursors are **not thread-safe**, and Flask serves requests on
  multiple threads → random `Function sequence error (0) (SQLFetch)` crashes;
* after any network blip the connection was never re-established.

**Fix** — a SQLAlchemy engine with a connection pool and `pool_pre_ping=True`
lives on `app.extensions`; every request borrows and returns a connection.
Failures return a clean `503 {"error": "database_unavailable", ...}` and the UI
shows a red banner instead of white-screening.

### 🔴 A4. `NameError: connection` inside `/save-timetable` and `/reset-timetable`
`get_students()` and `get_student_enrollments()` rebind the *local* names
`connection`/`cursor`, but `save_timetable()` calls the *global*
`connection.commit()`. If the global connect failed earlier (A3) the name never
existed at all → guaranteed 500 on save.

**Fix** — no globals; a `TimetableService` object owns the engine.

### 🔴 A5. Dead connection string / hard-coded machine name
```python
conn_str = (r'DRIVER={ODBC Driver 17 for SQL Server};SERVER=DESKTOP-99MP30B;...')
...
conn_str = os.getenv("DB_CONNECTION_STRING")     # silently overwrites it
```
The first assignment was pointless (immediately overwritten) and hard-coded a
personal PC name. The README told users to write `DB_SERVER`, `DB_NAME`, … in
`.env`, but the code only ever read `DB_CONNECTION_STRING` — **so following the
README produced a non-working app**.

**Fix** — `timetable/config.py::resolve_database_url()` accepts, in priority
order: `TTG_DATABASE_URL`/`DATABASE_URL` → `DB_CONNECTION_STRING` →
`DB_SERVER`+`DB_NAME`+… (the README variables) → **embedded SQLite** (default,
zero configuration). The app now runs out of the box with no database server.

### 🔴 A6. `load_dotenv` imported from the wrong place
`from flask.cli import load_dotenv` is a private Flask helper with a different
signature from `dotenv.load_dotenv`; in Flask 3 it does nothing unless the CLI
is running. The `.env` file was therefore never loaded when starting with
`python app.py`.

**Fix** — `python-dotenv` used directly, and the file is looked up next to the
executable *and* the CWD (important for a frozen app).

### 🟠 A7. `/save-timetable` wrote data no one could read back
It inserted `course_name`, `start_time`, `end_time`, `room_number` into
`timeslots` as `DATETIME` columns while the front-end sent strings like
`"08:30 AM-09:50 AM"` → `Conversion failed when converting date and/or time
from character string`. There was **no day-of-week column at all**, no course
id, no section — so a saved timetable could never be restored. There was also
no `GET` endpoint to load it.

**Fix** — new `timetable_entries` table (`day`, `start_time`, `end_time`,
`room_id`, `course_id`, `section`) with a uniqueness constraint on
`(day, start_time, room_id)`, plus `GET /api/timetable` and a working
**Load saved** button.

### 🟠 A8. Saving was not atomic
Rows were inserted one by one and `commit()` ran after the loop; a failure
half-way left a partially written timetable.

**Fix** — one transaction (`engine.begin()`); the whole grid is validated
first and rejected with `409` if anything clashes, so the DB never holds a
clashing schedule. Test: `test_save_is_rejected_when_the_grid_clashes`.

### 🟠 A9. `/api/students` and `/api/student-enrollments` were broken
* Both opened a **brand-new connection per request and never closed it** →
  file-handle/connection leak.
* `get_student_enrollments()` read `row.EnrollmentID`, but the SQL script
  explicitly comments that column out:
  `--EnrollmentID INT PRIMARY KEY IDENTITY(1,1)` → `AttributeError` on every
  call.
* Neither route had error handling, so both returned an HTML traceback.
* `row.CourseSection` was never returned, making the data useless for clash
  detection.

**Fix** — rewritten with the pooled engine, correct columns and JSON errors.

### 🟠 A10. `/api/course-details` returned only one instructor row, silently
The `GROUP BY` + `LEFT JOIN` combination returned the enrolment count for the
wrong grain (it counted rows of the join, not distinct students) and
`fetchone()` hid the fact that several instructors may teach one section.

**Fix** — explicit queries: instructor lookup, `COUNT` over enrolments, and the
full student roster (roll numbers are now shown in the UI, as the README
promised).

### 🟡 A11. No 404 for a missing course id (only for a missing section)
`/api/course-details/9999/A` returned `500` instead of `404`. Fixed and tested.

### 🟡 A12. `debug=True` hard-coded in production
`app.run(debug=True)` exposes the Werkzeug interactive debugger — remote code
execution if the port is reachable — and the dev server is single-process.

**Fix** — `waitress` (production WSGI server) by default; debug only via
`--debug`/`TTG_DEBUG=1`. Security headers (`X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`) added, and the request body is capped at
8 MB.

### 🟡 A13. README said `python main.py` — no `main.py` existed
Fixed: `python run.py`, `python -m timetable`, or the packaged binary.

### 🟡 A14. `print()` used as logging, `traceback.print_exc()` in two routes only
Replaced with the `logging` module writing to console **and** a rotating log
file in the user data folder (essential when debugging a double-clicked .exe).

---

## B. Front-end — `static/script.js` (original 432 lines)

### 🔴 B1. `html2pdf` loaded from `rawgit.com`, which was shut down in 2019
```html
<script src="https://rawgit.com/eKoopmans/html2pdf/master/dist/html2pdf.bundle.js"></script>
```
The domain no longer serves files, so **"Download Timetable" never worked**;
`html2pdf is not defined` was thrown on every click. jQuery and jQuery-UI also
came from CDNs — a desktop app with no internet would lose drag & drop
entirely.

**Fix** — the PDF library is vendored into `static/vendor/` (works offline) and
drag & drop was rewritten with the native HTML5 API, so jQuery and jQuery-UI
were removed completely (~350 KB less, no CDN, no version drift). A
`window.print()` fallback triggers if the PDF engine is unavailable.

### 🔴 B2. Two different handlers bound to the **same** `#saveTimetable` button
```js
$('#saveTimetable').click(...)          // exports a PDF
$('#saveTimetable').on('click', ...)    // POSTs to /save-timetable
```
One click did both. Meanwhile `#saveToDatabase` — which exists in the HTML —
had **no handler at all**.

**Fix** — one job per button: *Save to database*, *Load saved*, *Export PDF*,
*Export CSV*, *Print*, *Clear grid*, *Reset saved timetable*.

### 🔴 B3. `timetableData` was always empty
```js
var timetableData = [];        // never written to, anywhere
$.ajax({ data: JSON.stringify({ assigned_courses: timetableData }) ... })
```
"Save to Database" therefore always posted `[]` — **nothing was ever saved**.

**Fix** — the grid is kept in `state.placements` and serialised on save.

### 🔴 B4. `fetchCourses()` called recursively from `setupDroppables()`
`generateTimetable()` → `setupDroppables()` → `fetchCourses()` → appends the
whole catalogue to the sidebar **again**. Every regeneration duplicated all 45
course chips (45 → 90 → 135 …), each with duplicate drag handlers.

**Fix** — data is fetched once at boot; rendering is a pure function of state.

### 🔴 B5. The catalogue was rendered twice on page load
`fetchCourses()` appends the list, then the block at line ~91 loops over
`courses` (still empty because AJAX is asynchronous) and appends again with a
different markup shape. That second loop also read `course.name.split(" - ")`,
producing `undefined` sections for names without a dash.

**Fix** — removed; single render path.

### 🔴 B6. Race condition: the grid was built before the rooms arrived
`fetchRooms()` is asynchronous, but `generateTimetable()` iterates
`rooms_Permanent` immediately. Clicking *Generate* quickly produced a table
with a header row and **zero rooms**. `console.log(courses_Permanent)` right
after the call was documented in the code as a "debugging line" and always
printed `[]`.

**Fix** — `Promise.all([...])` boot sequence; the UI shows a *Loading…* state
until both fetches resolve.

### 🔴 B7. The time cursor was never reset between days
```js
let currentHour = parseInt(startTime.split(':')[0]);   // OUTSIDE the day loop
for (let day = 1; day <= totalDays; day++) { ... }
```
Only the header row used the outer cursor, so **Tuesday's header started where
Monday ended** (and by Friday the loop produced no columns at all, because the
cursor had passed `endTime`). The body rows used a correctly reset inner
cursor, so headers and cells were misaligned — the timetable literally lied
about the times.

**Fix** — slots are computed **once** into `state.slots` and reused for every
day, guaranteeing header/body alignment.

### 🔴 B8. `formatTime()` corrupts midnight and mutates 24-hour input
`formatTime(0, 30)` → `"00:30 AM"` (should be 12:30 AM) and `formatTime(12,0)`
→ `"12:00 PM"` ✓ but `formatTime(24,0)` → `"12:00 PM"` ✗. Worse, the *display*
string (`"08:30 AM-09:50 AM"`) was used as the cell's `data-time` **key** and
then sent to the server as if it were a machine-readable time.

**Fix** — 24-hour `HH:MM` strings everywhere internally (sortable, parseable,
DB-friendly); 12-hour text is generated only for display.

### 🔴 B9. Room identity was the **row index**, not the room id
```js
const room = $(this).closest('tr').index() + 1;   // 1,2,3...
```
Sorting or filtering the rooms silently re-mapped every booking, and the value
sent to the server had nothing to do with `rooms.id`.

**Fix** — each cell carries `data-room-id` from the database; the server
validates it exists.

### 🟠 B10. Clash detection only ever compared *the same cell*
`isCourseScheduled()` looks inside
`#{dayId} .time-slot[data-time="..."] .dropped-course`, then compares
`roomId === scheduledRoomId`, i.e. the same row and the same column — a cell
that jQuery had already told us was empty. It therefore detected **nothing**:
* no instructor clash (README feature #3),
* no student clash / roll-number list (README feature #2),
* no cross-room, no overlapping-time detection.

`drop` also popped `alert()` **twice** for one clash (once inside
`isCourseScheduled`, once in the caller).

**Fix** — real clash detection on the server (`TimetableService.check_assignment`)
covering **room**, **instructor**, **student** (with roll numbers), **duplicate
section** and a **capacity warning**, using proper half-open interval overlap
`a.start < b.end && b.start < a.end` so partial overlaps are caught. 13 unit
tests cover it.

### 🟠 B11. `revert:"invalid"` + `helper:'clone'` on placed classes = duplicates
Dragging an already-placed class cloned it instead of moving it, and the
original was never removed, so one class could exist in five cells at once.

**Fix** — explicit *move* semantics with the native drag API; the payload
carries the placement uid.

### 🟠 B12. The `break` column was computed but commented out
Both the header `<th class="break-time">` and the body `<td class="break-time-slot">`
lines were commented out, yet the cursor still advanced by `breakTime` — and
`.break-time { display:none }` in the CSS hid a column that no longer existed.
Break handling therefore silently shifted the grid.

**Fix** — breaks are gaps between slots, never columns; the value is honoured
exactly once, in `buildSlots()`.

### 🟠 B13. `switchDay()` / `toggleDrawer()` were global functions used in `onclick=`
Combined with `<script src="static/script.js" defer>` (see C1) they were often
undefined when the user clicked. Also `toggleDrawer()` compared
`drawer.style.left === "-250px"`, which is empty unless the inline style was
set — the first click did nothing.

**Fix** — all listeners attached in JS, no inline handlers, state-driven.

### 🟡 B14. `alert()` for every message, blocking the UI thread
Replaced with non-blocking toasts and a details dialog that lists **every**
conflict with the affected roll numbers.

### 🟡 B15. XSS via `innerHTML` with server data
`$('#coursePopup .course-details').html(...)` interpolated
`response.instructor` etc. directly. Course/instructor names come from the DB,
so a malicious record could inject script.

**Fix** — `escapeHtml()` on every interpolated value; most nodes are built with
`textContent`.

### 🟡 B16. `parseInt(...)||0` accepted nonsense
`classDuration = 0` produced an infinite `while(true)` loop candidate; only the
`break` on end-time saved it. `totalDays` allowed 0 (empty timetable) and the
`Math.min(...,7)` guard existed for days but not for anything else.

**Fix** — validated inputs with `min`/`max` attributes *and* a JS guard, plus a
loop guard of 100 iterations.

### 🟡 B17. No way to delete a placed class, no persistence of the layout
Added: ✕ button, drag-back-to-sidebar, <kbd>Delete</kbd> key, and the grid
configuration is stored in `app_settings` so the app reopens the way you left
it.

---

## C. Templates & CSS

### 🔴 C1. `<script src="static/script.js">` — relative URL, not `url_for`
Works on `/` but 404s on any nested route, and ignores Flask's static path.
Also loaded `defer` **before** jQuery finished, so `$` was sometimes undefined.

**Fix** — `{{ url_for('static', filename='app.js') }}` with a correct load order.

### 🟠 C2. `#saveTimetable` was labelled "Download Timetable" but saved to the DB
See B2. Buttons and labels now match their actions.

### 🟡 C3. Style rules duplicated and contradicting each other
`#totalRooms{width:120px}` at line 31 of `style.css` and `{width:350px}` at
line 116; the same button rules existed in both `style.css` and an inline
`<style>` block in `index.html`. `h1 { margin-left: 480px }` broke every screen
narrower than ~1400 px. `.timetable { display:flex }` on a `<table>` destroys
table layout — the reason the grid looked warped.

**Fix** — one stylesheet, CSS custom properties, sticky headers, responsive
down to phone width, print stylesheet.

### 🟡 C4. `#totalRooms` was collected but never used
The value was read into `totalRooms` and dropped. It is now the *Max rooms*
control, combined with a building filter.

### 🟡 C5. Zero accessibility
No labels, no focus styles, no keyboard path, `div` used as a button. Added
labels, `aria-*`, focus rings, skip link and keyboard shortcuts.

---

## D. Database script — `SQL_TimeTable.sql`

### 🔴 D1. `DROP TABLE` order violates the foreign keys
`courses` is dropped while `courseSections`, `CoursesTaughtBy` and `rooms`
still reference it, and `courseSections`/`buildings`/`rooms`/`CoursesTaughtBy`
are never dropped at all → re-running the script fails with
`Msg 3726: Could not drop object 'courses' because it is referenced by a
FOREIGN KEY constraint.`

### 🔴 D2. `timeslots` cannot store a timetable
No day column, no course/section id, `DATETIME` for what is a time of day.
See A7.

### 🟠 D3. `ALTER TABLE courses ADD instructor_id` contradicts `CoursesTaughtBy`
Two competing models of "who teaches this"; `instructor_id` is never populated
and never read.

### 🟠 D4. `rooms.room_number INT` + no uniqueness
Room "A-108" and "C-108" both store `108`; nothing prevents duplicates within a
building. Rooms also had no capacity, so over-booking could not be detected.

### 🟡 D5. `SELECT * FROM ...` statements scattered through a setup script
Harmless but noisy; they make `sqlcmd -b` output unusable in automation.

### 🟡 D6. T-SQL only (`IDENTITY`, `NVARCHAR`, `GETDATE`)
Locks the project to SQL Server, which is what forced the ODBC dependency that
makes packaging impossible on macOS/Linux.

**Fix for D1–D6** — the schema is now declared once in `timetable/db.py`
(SQLAlchemy) and created automatically on any backend. The original data was
extracted into `timetable/seed_data.json` (18 courses, 45 sections, 27
instructors, 36 rooms, 20 students, 106 enrolments) and loaded on first run.
`SQL_TimeTable.sql` is kept for reference only; `docs/SCHEMA.md` documents the
new model.

---

## E. Packaging & distribution (the reason it could not be an .exe)

### 🔴 E1. `pyodbc` + "ODBC Driver 17 for SQL Server" cannot be bundled
`pyodbc` links against the platform ODBC manager and needs a **separately
installed** Microsoft driver. On macOS/Linux that driver often isn't available
at all. Any .exe built from the original code would start and immediately fail
with `Data source name not found`.

**Fix** — SQLite (in the Python standard library, so it freezes perfectly) is
the default; `pyodbc` became an optional import used only when the user
explicitly configures SQL Server.

### 🔴 E2. Templates/static were loaded from `__file__`-relative paths
PyInstaller onefile unpacks to `sys._MEIPASS`; the frozen app would raise
`TemplateNotFound: index.html`.

**Fix** — `config.bundle_dir()` resolves `sys._MEIPASS` / the executable
directory / the source tree, and the spec file ships `templates/`, `static/`
and `seed_data.json` as data.

### 🔴 E3. The database would have been written inside `Program Files`
A SQLite file next to the executable is unwritable for a standard user on
Windows (and inside the read-only `.app` on macOS).

**Fix** — `config.user_data_dir()`: `%LOCALAPPDATA%`, `~/Library/Application
Support`, `$XDG_DATA_HOME`.

### 🟠 E4. SQLAlchemy dialects are imported dynamically → missing in the bundle
Declared as `hiddenimports` in the spec, with `collect_submodules`.

### 🟠 E5. Flask's dev server in a frozen app
Single-threaded, prints a scary warning, and dies on `multiprocessing` under
Windows. Now `waitress`, and `launcher.py` calls `multiprocessing.freeze_support()`.

### 🟠 E6. No port management
`app.run(debug=True)` hard-codes 5000; a second instance (or Skype/IIS) crashes
the app with `WinError 10048`.

**Fix** — `find_free_port()` picks a free port, prints the URL and opens the
browser once the socket accepts connections.

---

## F. What was added on top of the fixes

| Area | Addition |
|---|---|
| Reliability | 35 automated tests (`python -m pytest -q`), CI on Windows/macOS/Linux |
| Correctness | Server-side clash engine: room, instructor, student, duplicate, capacity |
| UX | Toasts, conflict dialog with roll numbers, search, building filter, day badges, dirty-state warning, keyboard shortcuts, responsive + print layout |
| Data | Save **and** load a timetable, CSV export, working PDF export, settings persistence |
| Ops | Rotating log file, `/api/health`, graceful degraded mode, `--reset-database` |
| Distribution | One-file .exe, Windows .msi, macOS .dmg (Intel + Apple Silicon), Linux .deb and .tar.gz, GitHub Actions release pipeline |


---

## Round 4 — defects found while adding labs and semesters

| # | Where | Problem | Fix |
|---|---|---|---|
| 35 | `services.list_courses` | The catalogue key was `course:section`, so a lab and its lecture would have collided in every "already placed" check. | The key is now `course:section:kind`; the whole front-end (`courseKey`, `placedKeys`, `findCourse`) was updated with it. |
| 36 | `services.check_assignment` | The duplicate rule compared only course + section, so switching a block to *Lab* would silently look like the same class. | Duplicate now compares course + section + kind, and additionally rejects a lecture overlapping its own lab with a specific message ("the same students attend both"). |
| 37 | `services.check_assignment` | Peer entries carried no semester, so a semester rule could not be evaluated for classes coming from an unsaved grid. | The peer lookup now resolves `courses.semester` alongside the name, for both saved rows and grid candidates. |
| 38 | `services.autofill` | Placing purely by roster overlap allowed two classes of the same batch when their enrolments happened not to intersect (small sample rosters). | Auto-fill now also tracks a `(semester, section)` group per placement and refuses to reuse a slot for the same group. |
| 39 | `exporters.build_workbook` | Nothing indicated a lab in the exported file. | `Summary` gained **Semester** and **Type** columns, day sheets and `By Teacher` mark labs `[LAB]`, and the column widths/alignment indices were re-derived (they were positional and would have shifted silently). |
| 40 | `web.api_publish_pdf` | `scope` was validated against a hard-coded four-value list. | Extended to include `semester`; the invalid-scope path is covered by a test. |

All six were found by tests written before the fix, and the suite grew from 83
to **94 tests**.
