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

The app opens in its **own native window** (no browser, no address bar). If
your machine happens to be missing the webview runtime the app quietly opens
your default browser instead — <code>--browser</code> forces that. Closing the
window stops the app.

The default window is a **true standalone program**: it does **not** start a
hidden web server, bind a port, or open a terminal — every feature (including
Excel/PDF/CSV exports and calendar files) runs entirely inside the one process
and works fully offline. It is software, not a service.

**Projects** in the bar above the toolbar: **New** (<kbd>Ctrl+N</kbd>) starts
a fresh dataset, **Open** (<kbd>Ctrl+O</kbd>) loads a `.ttproj` file, **Save**
(<kbd>Ctrl+S</kbd>) stores everything in the project file and **Save as**
(<kbd>Ctrl+Shift+S</kbd>) picks a new folder/name in the built-in browser —
which has *Up* and *New folder* icon buttons. A safety backup is made before
Open/New.

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
* **Excel export writes one Class Schedule worksheet per semester** — the
  printed layout, rows grouped by day with the day merged down the block —
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
| **Per-day list** | one landscape page **per weekday** with a big day header — the printed class schedule, split day by day |
| **One page per teacher** | each teacher's personal week, with their contact hours |
| **One page per course section** | what a class of students actually needs |
| **One page per room** | a booking sheet to stick on the door |
| **Room utilisation** | free vs. busy hours per room, flagging rooms under 50% used |
| **Teacher workload** | contact hours per teacher per week, flagging over/under-loaded staff |
| **Clashes to fix** | every clash sorted by severity, with a suggested fix — one printable page |

The **Reports** button on the toolbar opens the same three reports in the app
and lets you review them on screen before printing — the Excel workbook always
contains all three report sheets whatever layout you choose, and the **Reports**
dialog exports them in the semester-book layout so they arrive with the rest of
the document.

Then pick the **data**: the grid on screen (including unsaved changes) or the
saved timetable, optionally limited to a single teacher, section or room.

Every Excel, CSV and PDF export shares a **Formatting** panel so the output
matches your institution's style:

| Option | Effect |
|---|---|
| **Layout** | **Semester book** (default) is the whole document below; **Class Schedule** is the same printed list as a *single* page; **Grid** is the room × time facilities view. All three are available for Excel, and the printed look for PDF. |
| **Font** | the typeface applied to **every** cell and every PDF character — **Times New Roman** by default (also Arial, Calibri, Georgia, Courier New) |
| **Font size** | the body text size (9–12) |
| **Orientation** | landscape (default) or portrait for each printed page |
| **Document identity** | **Institution**, **Name of program**, **Semester** and **Commencement of classes**, plus the **term** as a season drop-down (Spring / Summer / Fall / Winter) **+ year + free text**. Set all of these under the dedicated **Document** button in the toolbar (or the link inside *Publish*), and a live preview of the title block updates as you type. |
| **Contents page** | a hyperlinked index of every sheet with its class count |
| **One sheet per semester** | the batch view, in the printed class-schedule arrangement |
| **Summary sheet** | the filterable class-by-class list |
| **By Teacher sheet** | each teacher's personal week, merged per teacher |
| **Free Slots** | the open-slot matrix per batch, plus free rooms per slot |
| **Load Balancing** | which classes to move, and to whom |
| **Credit Hour Audit** | planned credit hours vs. contact hours actually on the grid |
| **Dashboard with charts** | the week's headline numbers plus two Excel charts |
| **Master Data** | the courses, teachers and rooms behind the grid |
| **Unscheduled list** | the gaps that still need a slot |

The choices are remembered between sessions, so once you set the font to Times
New Roman it stays there for every later export.

### What the Excel export contains

The default **Semester book** layout writes one workbook that reads like a
document, in this order:

| Sheet | What is inside |
|---|---|
| **Contents** | a clickable index of every sheet, its class count and a one-line description |
| **Summary** | every class on one auto-filtered sheet — day, shift, semester, type, credit hours, times, code, course, section, teacher, room, students |
| **Semester 1 … Semester *n*** | **one sheet per semester**: the printed class schedule (*Days, Course Code, Course Title, C.Hrs, Total No.of Students, Teacher's Name, Time, Room No*), rows grouped by day with the day cell merged and banded, then a totals strip (classes, credit hours, contact hours, sections, teachers, non-credited) |
| **Monday … Sunday** | one sheet per weekday, the same eight columns, rows grouped by *semester · section* so a batch's whole day reads straight down |
| **By Teacher** | the same eight columns grouped by teacher, with the day instead of the teacher repeated |
| **Free Slots** | a green/amber matrix per batch — one row per weekday, one column per slot. Green **free**, amber = booked (showing the blocking course), red **no room** = the batch is free but every room is taken. Below it, **Free rooms at each slot** names the rooms and seats available |
| **Load Balancing** | concrete moves: *over-loaded teacher → which class → suggested teacher → hours after the move*. A move is only suggested when that teacher is free at exactly that time and ends up no busier than the giver |
| **Credit Hour Audit** | per course-section: planned credit hours vs. contact hours on the grid, the difference, and a status — `Complete`, `Short 1.5 h`, `Extra …`, `Not scheduled` or `Non-credited` |
| **Dashboard** | scheduled classes, contact hours, sections, teachers, rooms, non-credited classes, unscheduled count and clash count, plus two bar charts (room utilisation and teacher hours) |
| **Room Utilisation** | free vs. busy hours per room, flagging rooms under 50% used |
| **Teacher Workload** | contact hours per teacher, flagging over/under-loaded staff |
| **Conflict Report** | every clash, errors first, with the issue spelled out |
| **Master Data** | the courses, teachers and rooms behind the grid |
| **Unscheduled** | every class the catalogue expects that the grid does not have |
| **Revisions** | second sheet in the book when versioned names are on: the revision history plus what changed since the last export |

### Versioned exports

Tick **Versioned file names** and each export is numbered from what is already
in the folder — `Spring 2026-rev1.xlsx`, `-rev2`, `-rev3` — so nothing is ever
overwritten and the name says which copy is current. The stem comes from the
**Export file name** field under *Document*. Each file carries a **Revisions**
sheet with the history and a change list colour-coded by kind (green added, red
removed, amber moved / re-roomed / re-taught); the changes are worked out by
reading the previous revision's Summary sheet back out of the file.

### What the colours mean

| Colour | Meaning |
|---|---|
| A course's own colour | identity — the same colour it wears on the grid, lightened so the text stays readable. Used on the semester, weekday, teacher, Summary and Master Data sheets |
| Pastel per weekday | the day grouping on semester sheets and the Contents page |
| Green | free · balanced · complete · a suggested move · the current revision |
| Amber | needs a look: short on hours · under-used · evening shift · non-credited · moved or re-roomed |
| Red | stop: a clash · a slot with no free room · not scheduled · over-loaded |

Every sheet gets the same title block (institution, program, semester,
commencement), repeats its header row on each printed page, fits one page wide,
carries page numbers in the footer, and is colour-tabbed by kind — semester
sheets green, weekday sheets violet, reports red.

A **CSV bundle** button in the same dialog writes a `.zip` with one CSV per
sheet (`timetable.csv`, `semester-4.csv`, `monday.csv`, `by-teacher.csv`,
`credit-hour-audit.csv`, `unscheduled.csv`) for anyone without a spreadsheet
app.

A class whose credit hours are **0** is shown as **“non-credited course”** in
the C.Hrs column automatically, and is never flagged by the credit-hour audit.

* **Download PDF** writes the file straight from the app — no browser print
  dialog, real vector text (Times, matching the workbook), and it looks the
  same on every machine.
* **Download .ics** gives a calendar file you can open in any calendar app.
* **Copy subscription link** copies a live URL such as
  `http://localhost:5000/calendar.ics?teacher=Dr.%20Ayesha%20Khan&weeks=16`.
  Paste it into Google Calendar (*Other calendars → From URL*), Outlook
  (*Add calendar → Subscribe from web*) or Apple Calendar (*File → New Calendar
  Subscription*). Classes repeat weekly for the number of weeks you choose, and
  the feed reflects the saved timetable whenever the app is running.

## Step by step

0. **Create (or open) a project** — <kbd>Ctrl+N</kbd> creates a **completely
   blank** project (no courses, teachers, buildings, rooms or classes; tick
   *“Load the sample university”* if you want the demo data instead),
   <kbd>Ctrl+O</kbd> opens an existing `.ttproj`, and <kbd>Ctrl+Shift+S</kbd>
   saves it **anywhere on any drive** — the built-in browser lists every drive
   and volume with Desktop / Documents / Downloads shortcuts, clickable
   breadcrumbs and *Up* / *New folder* icon buttons. Use <kbd>Ctrl+S</kbd>
   whenever you want to save; it stores the grid on screen together with all
   your data.
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
   the left panel (or press ✕ / <kbd>Delete</kbd>) to unschedule it. While you
   drag, free slots are hatched and an **already-booked slot turns red** so you
   know before you let go. *Without a mouse:* press <kbd>Enter</kbd> on a
   course to pick it up, <kbd>Enter</kbd> on a slot to place it,
   <kbd>Esc</kbd> to cancel.
6. **Click a scheduled class** to see instructor, department, headcount, room
   and the complete list of enrolled roll numbers.
7. **Check all clashes** re-validates the entire week in one pass — do this
   before you publish.
8. **Save to database.** The whole week is written in a single transaction.
   If anything still clashes, nothing is saved and the offending cells turn red.
9. **Load saved** restores the stored week (grid settings included) next time
   you open the app.
10. **Export**:
    * **Export Excel** (also in *Publish* → **Export Excel**, or on the toolbar) —
      a **Contents** page, a filterable **Summary**, **one Class Schedule worksheet per
      semester**, one per weekday, **By Teacher**, a **Credit Hour Audit**, a charted
      **Dashboard**, the three report sheets, **Master Data** and an **Unscheduled** sheet when
      something is missing. Both shifts are included. All text is **Times New Roman** by default,
      chosen in the *Formatting* panel.
    * **Publish** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>) — the same *Formatting* options,
      PDF for the whole grid or per teacher / section / **semester** / room, plus `.ics` calendar
      files and a live subscription link.
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
| <kbd>Ctrl</kbd>+<kbd>E</kbd> | Export to Excel (one sheet per semester, plus roll-ups) |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd> (or <kbd>Alt</kbd>+<kbd>P</kbd>) | Publish: PDF per teacher / section / room + calendar |
| <kbd>Alt</kbd>+<kbd>D</kbd> | Document: institution, program, term, semester, commencement |
| <kbd>Alt</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> | Reports: room utilisation / workload / clashes |
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

### Your projects and exports live wherever *you* put them

The folder above is only the app's own working data. Your **projects**
(`.ttproj`) go wherever you choose — any folder on any drive, including USB
sticks and network shares — and **every export (Excel, PDF, CSV, calendar) is
written into that same folder**, so a project and its outputs stay together:

```
D:\Timetables\
├── Spring 2026.ttproj      the project itself
├── timetable.xlsx          Ctrl+E
├── timetable-teacher.pdf   Publish -> PDF
├── timetable.csv           Alt+V
└── timetable.ics           Publish -> calendar
```

Exporting twice never overwrites: the second file becomes
`timetable (2).xlsx`. If the file you are exporting to is still open in
Excel (or another program), the app tells you *“file is in use”* instead of
failing quietly — nothing is overwritten or lost. If you have not saved a
project yet, exports simply download to your browser's Downloads folder as
before.

While you work, the app periodically writes a timestamped backup of the
current project into a `_backups` folder right next to the project file
(keeping the newest few), so a crash never costs you more than a few minutes
of changes.

On the screen, a course with **0 credit hours** wears a **“non-credited”**
chip on its card and grid cell as well as in the exports — so the label is
never a surprise.

> **Locked-down machines:** set `TTG_SANDBOX_HOME=1` (or
> `TTG_SANDBOX_ROOT=D:\Shared\Timetables`) in the `.env` file to confine the
> file browser to one folder — useful for shared lab or kiosk PCs.

---

## Command-line options

```
TimetableGenerator --help

  --host HOST            interface to bind (default 127.0.0.1)
  --port PORT            fixed port (default: first free port)
  --window               open the app in its own native window (default)
  --browser              force the browser mode instead
  --no-browser           start the server only; open nothing
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
