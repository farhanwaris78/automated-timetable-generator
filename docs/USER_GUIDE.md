# User guide

## Installing

| Platform | File | How |
|---|---|---|
| Windows 10/11 | `AutomatedTimetableGenerator-2.0.0-win64.msi` | Double-click → Next → Install. Launch from the Start menu. |
| Windows (no admin rights) | `TimetableGenerator-2.0.0-windows-x64.zip` | Extract anywhere, double-click `TimetableGenerator.exe`. |
| macOS | `TimetableGenerator-2.0.0-macos-*.dmg` | Open the DMG, drag the app to *Applications*. First launch: right-click → **Open**. |
| Ubuntu/Debian | `timetable-generator_2.0.0_amd64.deb` | `sudo apt install ./timetable-generator_2.0.0_amd64.deb` |
| Any Linux | `TimetableGenerator-2.0.0-linux-x86_64.tar.gz` | Extract and run `./start.sh` |

Nothing else is required — no Python, no SQL Server, no ODBC driver, no
internet connection.

A console window appears with the address the app is serving on, and your
default browser opens automatically. **Closing that window stops the app.**

---

## The screen at a glance

```
┌──────────────────────────────────────────────────────────────────────┐
│ Automated Timetable Generator            [Local database · 18 …] Help│
├───────────┬──────────────────────────────────────────────────────────┤
│ Courses   │ Days | Start | End | Class | Break | Building | Rooms  ▶ │
│ [search]  ├──────────────────────────────────────────────────────────┤
│ ▣ MLOps A │ Save · Load · Check clashes · Auto-fill · Excel · Publish│
│ ▣ ML A LAB│ Semester [All ▾]   0 clashes · 12 not scheduled          │
│ ▣ ML A    │ Mon | Tue | Wed | Thu | Fri                              │
│ …         ├──────────────────────────────────────────────────────────┤
│           │ Room \ Time | 08:30-09:50 | 10:00-11:20 | …              │
│           │ A-108       | [ MLOps A ] |             |                │
└───────────┴──────────────────────────────────────────────────────────┘
```

---

## Managing your own data

The sample dataset is only a starting point. Everything is editable inside the
app — no SQL, no spreadsheets:

| What | How |
|---|---|
| **Teachers** | <kbd>Alt</kbd>+<kbd>T</kbd> or *+ Teacher*. Name, email, department and which shift they teach. |
| **Classrooms** | <kbd>Alt</kbd>+<kbd>R</kbd> or *+ Room*. Number, building, capacity and type (Classroom / Lab / Hall). Typing a new building name creates it. |
| **Buildings** | <kbd>Alt</kbd>+<kbd>B</kbd> |
| **Courses & course codes** | <kbd>Alt</kbd>+<kbd>C</kbd> or *+ Course*. Code (e.g. `CS3009`), title, department, credit hours, colour and a comma-separated list of sections with their teacher. |
| **Sections** | <kbd>Alt</kbd>+<kbd>S</kbd>, or from the course row in *Manage data*. |
| **Everything at once** | <kbd>Alt</kbd>+<kbd>M</kbd> opens *Manage data* with searchable Teachers / Classrooms / Courses / Buildings tables — edit or delete any row. |
| **Hundreds of rows at once** | <kbd>Ctrl</kbd>+<kbd>I</kbd> imports a spreadsheet — see *Importing from Excel* below. |

The app refuses destructive edits that would corrupt a schedule: you cannot
delete a teacher who still has sections, a room or course used by the saved
timetable, or a building that still contains rooms. It tells you exactly what
to fix first.

## Morning and evening shifts

Each shift keeps **its own hours** (default 08:30–13:00 and 13:30–19:00) but
shares the same rooms, teachers and courses. Switch with <kbd>Alt</kbd>+<kbd>1</kbd> /
<kbd>Alt</kbd>+<kbd>2</kbd> or the segmented control. Clash detection runs across
**both** shifts — a teacher scheduled at 12:30 in the morning shift cannot also
be at 12:30 in the evening shift — and one Save stores the complete day.

## Undo / redo

Every placement, move, deletion, auto-fill and grid clear can be undone with
<kbd>Ctrl</kbd>+<kbd>Z</kbd> and re-applied with <kbd>Ctrl</kbd>+<kbd>Y</kbd>
(100 steps of history). The ↶ / ↷ buttons on the toolbar do the same and grey
out when there is nothing to undo.

## Labs

A course can have a **lab** as well as a lecture. Open the course editor
(<kbd>Alt</kbd>+<kbd>C</kbd>, or *Manage data → Courses → Edit*) and tick
**“This course has a lab”**, then set its **lab credit hours** (1 by default).

From then on every section of that course shows **two cards** in the left panel:

| Card | Meaning |
|---|---|
| `CS3009 Artificial Intelligence - A` | the lecture (theory) |
| `CS3009 Artificial Intelligence - A` **LAB** | the lab session |

Drag them in separately. A placed lab keeps the `LAB` chip and a subtle hatched
pattern, and clicking it opens the details dialog where a **Theory / Lab**
switch lets you flip the block to the other half of the course.

Rules the app enforces for labs:

* the lecture and the lab of one section can never overlap (same students);
* a lab can only be placed for a course that actually has one;
* a lab in a room whose type is not **Lab** is a *warning* — it is placed, and
  you are told, but nothing is blocked.

## Semesters

Give each course a **semester** (1–12) in the course editor. The app then treats
a **semester + section** as one student batch and refuses to put two of its
classes in the same slot — even when the rooms, teachers and enrolments differ.
That is the *semester clash*.

* The **Semester** picker on the toolbar filters the course list and dims every
  class on the grid that belongs to a different semester.
* With a semester selected, *Auto-fill remaining* fills **only that semester**.
* **Excel export writes one worksheet per semester** (rows = day × section),
  and **Publish → One page per semester** does the same as a PDF.
* `http://localhost:PORT/calendar.ics?semester=3` is a live feed for one batch.

## What is still unscheduled

The toolbar shows a pill: **“*n* not scheduled”** (green *Everything scheduled*
when nothing is missing). Click it for a report grouped by semester, listing
every lecture and lab that has no slot yet, with its code, section, type and
teacher. The same list is written to an **Unscheduled** sheet in the Excel
export, so the gaps travel with the file.

## Auto-fill

*Auto-fill remaining* (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd>) places every
still-unscheduled class — lectures *and* labs — into the first slot where it
causes no room, teacher, student, semester or capacity conflict, largest classes
first, with labs preferring rooms of type **Lab**. On the bundled dataset it
schedules all 65 classes (45 lectures + 20 labs) in well under a second. Review
the result, adjust by hand, then save.

## Room capacity warnings

Every classroom has a number of seats, and every section has an enrolment. When
you place a class in a room that is too small the app:

* outlines the class in amber and adds a `⚠ 58/40` badge (enrolled / seats);
* raises a toast explaining the shortfall;
* counts it in the **“n room(s) too small”** pill on the toolbar.

Click that pill for a **capacity report**: every over-full class, by how much,
and a suggestion of the smallest rooms that *would* fit it.

Capacity is deliberately a **warning, not an error** — a lecture with 62
students in a 60-seat room is usually fine, and you may not have a bigger room.
It never stops you saving. Auto-fill, on the other hand, will not put a class in
a room that cannot hold it.

## Importing from Excel

Typing a whole department is slow. Instead press <kbd>Ctrl</kbd>+<kbd>I</kbd>
(*Import Excel*) and:

1. **Download template** — a workbook with a *Read me* sheet and one sheet each
   for **Teachers, Buildings, Rooms, Courses** and **Sections**.
2. Fill it in Excel, LibreOffice or Google Sheets (delete the example rows) and
   save as `.xlsx`.
3. Choose the file and press **Import file**.

Rules worth knowing:

* Sheets you leave empty are skipped, so you can import only teachers if you like.
* Existing records are **matched and updated, never duplicated** — by teacher
  name or email, building name, building + room number, course code, and
  course + section. Re-importing the same file is safe.
* Rows are validated exactly as if you had typed them into the dialogs. A bad
  row is listed with its sheet, row number and reason; every other row still
  imports.
* Import order is fixed (Teachers → Buildings → Rooms → Courses → Sections), so
  a section can reference a teacher and course created earlier in the same file.

## Publishing: PDF and calendar feeds

*Publish…* (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>) turns the timetable
into something you can hand out.

| Choice | Result |
|---|---|
| **Master grid** | one landscape page per day, rooms down the side — the noticeboard copy |
| **One page per teacher** | each teacher's personal week, with their contact hours |
| **One page per course section** | what a class of students actually needs |
| **One page per room** | a booking sheet to stick on the door |

Then pick the **data**: the grid on screen (including unsaved changes) or the
saved timetable, optionally limited to a single teacher, section or room.

* **Download PDF** writes the file straight from the app — no browser print
  dialog, real vector text, and it looks the same on every machine.
* **Download .ics** gives a calendar file you can open in any calendar app.
* **Copy subscription link** copies a live URL such as
  `http://localhost:5000/calendar.ics?teacher=Dr.%20Ayesha%20Khan&weeks=16`.
  Paste it into Google Calendar (*Other calendars → From URL*), Outlook
  (*Add calendar → Subscribe from web*) or Apple Calendar (*File → New Calendar
  Subscription*). Classes repeat weekly for the number of weeks you choose, and
  the feed reflects the saved timetable whenever the app is running.

## Step by step

1. **Set the working week** — days per week, the start/end of the teaching day,
   class length and the break between classes. Optionally restrict the grid to
   one building and cap how many rooms are shown.
2. **Generate grid.** Slots are identical for every day, so headers and cells
   always line up.
3. **Drag a course** from the left panel into a `room × time` cell.
   Every drop is checked by the server *before* it is accepted.
4. **Read the clash report.** If the placement is impossible you get a dialog
   listing every reason:

   | Type | Meaning |
   |---|---|
   | **room** | that room is already booked in an overlapping slot |
   | **instructor** | the teacher of this section already teaches elsewhere then |
   | **student** | students enrolled in both classes would collide — their roll numbers are listed |
   | **duplicate** | the same course-section is already scheduled at that time — including its own lecture against its lab |
   | **semester** | another class of the same semester **and** section is already in that slot |
   | **roomtype** | *(warning only)* a lab placed in a room that is not a Lab |
   | **capacity** | *(warning only)* more students than seats; the class is still placed |

5. **Adjust.** Drag a placed class to another cell to move it, drag it back to
   the left panel (or press ✕ / <kbd>Delete</kbd>) to unschedule it.
6. **Click a scheduled class** to see instructor, department, headcount, room
   and the complete list of enrolled roll numbers.
7. **Check all clashes** re-validates the entire week in one pass — do this
   before you publish.
8. **Save to database.** The whole week is written in a single transaction.
   If anything still clashes, nothing is saved and the offending cells turn red.
9. **Load saved** restores the stored week (grid settings included) next time
   you open the app.
10. **Export**:
    * **Excel** (<kbd>Ctrl</kbd>+<kbd>E</kbd>) — **one worksheet per day** and **one per semester**,
      colour-coded exactly like the screen, plus a filterable **Summary** sheet, a **By Teacher** sheet
      and an **Unscheduled** sheet when something is missing. Both shifts are included.
    * **Publish** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>) — PDF for the whole grid or per
      teacher / section / **semester** / room, plus `.ics` calendar files and a live subscription link.
    * **CSV** (<kbd>Alt</kbd>+<kbd>V</kbd>) and **Print** (<kbd>Ctrl</kbd>+<kbd>P</kbd>).

### Keyboard shortcuts

Press <kbd>F1</kbd> in the app for this same list — it is generated from the
code, so it can never go out of date. Shortcuts are ignored while you type in
a text box.

**Add data**

| Key | Action |
|---|---|
| <kbd>Alt</kbd>+<kbd>T</kbd> | Add teacher |
| <kbd>Alt</kbd>+<kbd>R</kbd> | Add classroom |
| <kbd>Alt</kbd>+<kbd>C</kbd> | Add course (with its code) |
| <kbd>Alt</kbd>+<kbd>B</kbd> | Add building |
| <kbd>Alt</kbd>+<kbd>S</kbd> | Add a section to a course |
| <kbd>Alt</kbd>+<kbd>M</kbd> | Manage teachers / classrooms / courses / buildings |
| <kbd>Ctrl</kbd>+<kbd>I</kbd> | Import teachers / rooms / courses from Excel |

**Edit**

| Key | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Undo |
| <kbd>Ctrl</kbd>+<kbd>Y</kbd> (or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd>) | Redo |
| <kbd>Delete</kbd> | Remove the selected class |
| <kbd>Ctrl</kbd>+<kbd>Backspace</kbd> | Clear the whole grid |

**Timetable**

| Key | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>G</kbd> | Generate the grid |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save to database |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Load the saved timetable |
| <kbd>Ctrl</kbd>+<kbd>K</kbd> | Check every clash |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>A</kbd> | Auto-fill the remaining sections |

**Export**

| Key | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Export to Excel (one sheet per day) |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> (or <kbd>Alt</kbd>+<kbd>P</kbd>) | Publish: PDF per teacher / section / room + calendar |
| <kbd>Alt</kbd>+<kbd>V</kbd> | Export to CSV |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> | Print |

**View**

| Key | Action |
|---|---|
| <kbd>Alt</kbd>+<kbd>1</kbd> / <kbd>Alt</kbd>+<kbd>2</kbd> | Morning / Evening shift |
| <kbd>1</kbd> … <kbd>7</kbd> | Jump to Monday … Sunday |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Search the course list |
| <kbd>Alt</kbd>+<kbd>H</kbd> | Show / hide the course panel |
| <kbd>F1</kbd> | This shortcut list |
| <kbd>Esc</kbd> | Close a dialog |

---

## Buttons that delete things

| Button | Effect |
|---|---|
| **Clear grid** | empties the on-screen week; the saved timetable is untouched |
| **Reset saved timetable** | deletes the timetable stored in the database |
| `--reset-database` (command line) | wipes everything and reloads the sample data |

---

## Where your data lives

| OS | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\TimetableGenerator\` |
| macOS | `~/Library/Application Support/TimetableGenerator/` |
| Linux | `~/.local/share/timetable-generator/` |

* `timetable.db` — everything you have entered (SQLite; open it with *DB Browser
  for SQLite* if you want to bulk-edit courses or students).
* `timetable.log` — rotating log, the first place to look if something misbehaves.

Back up = copy `timetable.db`. Factory reset = delete the folder.

---

## Command-line options

```
TimetableGenerator --help

  --host HOST            interface to bind (default 127.0.0.1)
  --port PORT            fixed port (default: first free port)
  --no-browser           do not open a browser
  --debug                verbose logs + Flask debugger
  --database-url URL     any SQLAlchemy URL (overrides .env)
  --data-dir PATH        keep the database and logs somewhere else
  --reset-database       recreate the database from the sample data, then exit
  --version
```

Sharing one timetable with colleagues on the LAN:

```
TimetableGenerator --host 0.0.0.0 --port 8080 --no-browser
```
Then they open `http://<your-ip>:8080/`.
*(There is no login screen — only do this on a trusted network.)*

---

## Using a central database instead of SQLite

Put a `.env` file next to the executable (see `.env.example`):

```ini
# Microsoft SQL Server (requires: pip install pyodbc, plus the ODBC driver)
DB_SERVER=SQL01
DB_NAME=timetable
DB_USER=sa
DB_PASSWORD=secret
DB_DRIVER=ODBC Driver 17 for SQL Server

# ... or anything SQLAlchemy understands
# TTG_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/timetable
```

The schema is created automatically on first connect.

---

## FAQ

**Windows says "Windows protected your PC".**
The binary is not code-signed. Click *More info* → *Run anyway*, or install the
signed MSI if your institution provides one.

**macOS says the app is damaged.**
`xattr -dr com.apple.quarantine /Applications/TimetableGenerator.app`

**The browser did not open.**
Copy the URL printed in the console window into your browser.

**Nothing appears in the course list.**
The status pill in the header will say *Database offline*; check
`timetable.log`, or run `TimetableGenerator --reset-database`.

**Can I add my own courses/rooms/students?**
Yes — edit `timetable.db` with DB Browser for SQLite, or point the app at your
institution's database with `.env`. A built-in admin screen is on the roadmap.
